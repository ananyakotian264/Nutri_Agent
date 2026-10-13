"""
orchestrator.py — The ORCHESTRATION LAYER + the PLANNING/EXECUTING AGENT.

This file is the busiest one in the project, so here's the map:

  MCPToolBridge   -> holds the MCP CLIENT connection to mcp_server.py and
                      translates between "MCP tool schema" and "Groq tool
                      schema" so the two protocols never leak into each
                      other.

  Agent.run()     -> the actual agentic loop. This is the classic
                      "Reason + Act" (ReAct) pattern:

                          THOUGHT   the model decides what to do next
                          ACTION    it calls a tool (executed via MCP)
                          OBSERVATION  the tool's result is appended back
                                    into the conversation
                          ... repeat until the model is confident enough
                          to answer without another tool call ...
                          FINAL ANSWER

                      "Planning" here is implicit in the loop rather than a
                      separate upfront step: the model re-plans after every
                      observation, which is more robust than committing to a
                      rigid plan up front (e.g. if USDA has no match, it can
                      pivot to an estimate instead of getting stuck).

Everything above this file (main.py / the FastAPI routes) does not know
Groq or MCP exist — it just calls `orchestrator.handle_message(text)` and
gets a plain-English reply plus a trace. That's what makes this the
orchestration layer: it's the only place that coordinates the model gateway
and the tool layer together.
"""
import asyncio
import math
import sys
import json
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gateway import gateway

MAX_AGENT_STEPS = 4

SYSTEM_PROMPT = """You estimate nutrition for a food or meal and save one combined entry.
If the user supplied exact nutrition numbers, use them and source="manual".
Otherwise, use search_usda_food at most once when a close match is useful, then
call log_meal exactly once. Scale reference values to the described portion.
For composite dishes or missing portions, use a reasonable clearly named serving
estimate and source="estimated". Use source="usda" only when the lookup supports
the food. Do not call profile or summary tools. The API updates today's totals
after saving. Keep the final reply short and state the meal and nutrition values.
"""

PREDICTION_PROMPT = """You estimate the nutrition in foods described by the user.
Use search_usda_food at most once when a close match is useful, then call
log_meal exactly once with the combined nutrition prediction. This is preview
only and does not save anything. Scale reference values to the described
portion; estimate composite dishes with a reasonable named serving. Use
source="usda" only when the lookup supports the food; otherwise use
source="estimated". Do not say that anything was logged.
"""


class MCPToolBridge:
    """Owns the MCP CLIENT session and speaks both protocol dialects."""

    def __init__(self):
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self, server_script: str):
        params = StdioServerParameters(command=sys.executable, args=[server_script])
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def close(self):
        await self._stack.aclose()

    async def list_tools_for_groq(self, prediction_only: bool = False) -> list:
        result = await self.session.list_tools()
        groq_tools = []
        for tool in result.tools:
            # Food logging does not need profile/summary tools. Keeping the
            # schema small saves prompt tokens and avoids unnecessary model turns.
            if tool.name not in {"search_usda_food", "log_meal"}:
                continue
            schema = json.loads(json.dumps(tool.inputSchema))
            if tool.name == "log_meal":
                # Account ownership is supplied by the API after model output.
                schema.get("properties", {}).pop("user_id", None)
                schema["required"] = [key for key in schema.get("required", []) if key != "user_id"]
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (
                        "Return one structured nutrition prediction for the described food. "
                        "This is a preview and does not write to the food log."
                        if prediction_only and tool.name == "log_meal"
                        else tool.description
                    ),
                    "parameters": schema,
                },
            })
        return groq_tools

    async def call_tool(self, name: str, args: dict) -> dict:
        result = await self.session.call_tool(name, args)
        # FastMCP serializes tool return values as JSON text content blocks.
        for block in result.content:
            if hasattr(block, "text"):
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    return {"raw": block.text}
        return {"raw": None}


class Agent:
    def __init__(self, bridge: MCPToolBridge):
        self.bridge = bridge

    @staticmethod
    def _prediction_from_args(args: dict) -> dict:
        food_name = args.get("food_name")
        if not isinstance(food_name, str) or not food_name.strip():
            raise ValueError("The model did not provide a food name.")
        prediction = {"food_name": food_name.strip()[:120]}
        for field, maximum in (
            ("calories", 100000),
            ("protein_g", 10000),
            ("carbs_g", 10000),
            ("fat_g", 10000),
            ("fiber_g", 10000),
        ):
            value = float(args[field])
            if not math.isfinite(value) or value < 0 or value > maximum:
                raise ValueError("The model returned an invalid nutrition value.")
            prediction[field] = round(value, 1)
        source = args.get("source", "estimated")
        prediction["source"] = source if source in {"usda", "estimated", "manual"} else "estimated"
        return prediction

    async def run(self, user_message: str, user_id: int, persist: bool = True) -> dict:
        """Runs the plan -> act -> observe loop, optionally without writing meals."""
        tools = await self.bridge.list_tools_for_groq(prediction_only=not persist)
        meal_tool = next(tool for tool in tools if tool["function"]["name"] == "log_meal")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT if persist else PREDICTION_PROMPT},
            {"role": "user", "content": user_message},
        ]
        trace = []
        predictions = []
        has_grounded_usda_record = False
        require_meal_output = False

        for step in range(MAX_AGENT_STEPS):
            force_meal_tool = require_meal_output and not predictions
            current_tools = [meal_tool] if force_meal_tool else tools
            tool_choice = (
                {"type": "function", "function": {"name": "log_meal"}}
                if force_meal_tool
                else "auto"
            )
            msg = await asyncio.to_thread(gateway.chat, messages, current_tools, tool_choice)

            if not msg.tool_calls:
                if not predictions and not require_meal_output:
                    # Some model replies ignore the structured-output instruction.
                    # Ask once more with a forced nutrition tool call so the UI
                    # receives real numbers instead of prose it cannot render.
                    messages.extend([
                        {"role": "assistant", "content": msg.content or ""},
                        {"role": "user", "content": "Return the food and its nutrition values now by calling the log_meal tool. Do not answer in prose alone."},
                    ])
                    require_meal_output = True
                    continue
                trace.append({"type": "final_answer", "content": msg.content})
                return {"reply": msg.content, "trace": trace, "predictions": predictions}

            # The model chose one or more tool calls this step — execute all of them.
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})
            calls = sorted(msg.tool_calls, key=lambda call: call.function.name != "search_usda_food")
            for call in calls:
                model_args = json.loads(call.function.arguments or "{}")
                args = dict(model_args)
                # The model is never authoritative for ownership. Force the
                # authenticated account id into every account-scoped tool call.
                if persist and call.function.name in {"log_meal", "get_daily_summary", "get_saved_profile"}:
                    args["user_id"] = user_id
                if call.function.name == "log_meal":
                    # An LLM cannot mark an estimate as database-grounded by
                    # merely choosing the source field in its tool arguments.
                    if args.get("source") == "usda" and not has_grounded_usda_record:
                        args["source"] = "estimated"
                trace.append({"type": "plan", "tool": call.function.name, "args": model_args})

                if call.function.name == "log_meal":
                    try:
                        prediction = self._prediction_from_args(args)
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        observation = {"status": "rejected", "reason": str(exc)}
                    else:
                        if persist:
                            observation = await self.bridge.call_tool(call.function.name, args)
                            if observation.get("status") == "logged":
                                predictions.append(prediction)
                        else:
                            predictions.append(prediction)
                            observation = {"status": "predicted", "saved": False}
                else:
                    observation = await self.bridge.call_tool(call.function.name, args)

                if call.function.name == "search_usda_food" and observation.get("found"):
                    has_grounded_usda_record = True
                if call.function.name == "search_usda_food" and not predictions:
                    require_meal_output = True
                trace.append({"type": "observation", "tool": call.function.name, "result": observation})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(observation),
                    }
                )

            if predictions:
                details = "; ".join(
                    f"{item['food_name']}: {item['calories']:g} kcal, "
                    f"{item['protein_g']:g} g protein, {item['carbs_g']:g} g carbs, "
                    f"{item['fat_g']:g} g fat, {item['fiber_g']:g} g fiber"
                    for item in predictions
                )
                reply = f"Logged {details}." if persist else f"Estimated nutrition: {details}."
                trace.append({"type": "final_answer", "content": reply})
                return {"reply": reply, "trace": trace, "predictions": predictions}

        trace.append({"type": "final_answer", "content": "Hit the step limit before finishing — try rephrasing."})
        return {
            "reply": "I got stuck reasoning about that — could you rephrase or give me exact numbers?",
            "trace": trace,
            "predictions": predictions,
        }
