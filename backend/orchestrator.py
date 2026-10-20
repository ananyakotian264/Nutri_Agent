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
import re
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from gateway import gateway

MAX_AGENT_STEPS = 4

SYSTEM_PROMPT = """You estimate nutrition for a food or meal and save one combined entry.
If the user supplied exact nutrition numbers, use them and source="manual".
Otherwise, use search_usda_food at most once. Use its candidate with a medium or
high match strength only when it describes the food; low-strength matches are
not suitable references. For a suitable USDA match, use a listed standard
portion weight when available, set portion_grams to the edible portion weight,
and set source="usda". The server calculates serving nutrients from the source.
For composite dishes or missing portions, use a reasonable clearly named serving
estimate and source="estimated". Use source="usda" only when the lookup supports
the food and a usable portion weight is available. Do not call profile or summary
tools. The API updates today's totals after saving. Keep the final reply short
and state the meal and nutrition values.
"""

PREDICTION_PROMPT = """You estimate the nutrition in foods described by the user.
Use search_usda_food at most once when a close match is useful, then call
log_meal exactly once with the combined nutrition prediction. This is preview
only and does not save anything. For a USDA match, use its standard portion
weights when available, set portion_grams to the edible portion weight, and
scale each nutrient from per-100g values. For composite dishes or unknown
portions, use source="estimated" and omit portion_grams. Use source="usda"
only when the lookup supports both the food and its portion weight. Do not say
that anything was logged.
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
    def _apply_usda_values(args: dict, reference: dict | None, user_message: str = "") -> dict:
        """Use USDA nutrient values directly when match and portion evidence suffice."""
        args = dict(args)
        if args.get("source") != "usda":
            return args
        reference_keys = {
            "calories": "calories_per_100g",
            "protein_g": "protein_g_per_100g",
            "carbs_g": "carbs_g_per_100g",
            "fat_g": "fat_g_per_100g",
            "fiber_g": "fiber_g_per_100g",
        }
        reference = reference or {}
        reference_values = reference.get("found") and all(
            isinstance(reference.get(key), (int, float)) for key in reference_keys.values()
        )
        try:
            proposed_portion = float(args.get("portion_grams"))
            valid_portion = math.isfinite(proposed_portion) and 0 < proposed_portion <= 100000
        except (TypeError, ValueError, OverflowError):
            valid_portion = False
            proposed_portion = 0
        explicit_grams = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:g|grams?)\b", user_message, re.IGNORECASE)
        number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a": 1, "an": 1}
        fraction_match = re.search(r"\b(\d+)\s*/\s*(\d+)\s+(?=[a-z])", user_message)
        quantity_match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|a|an|\d+(?:\.\d+)?)\s+(?=[a-z])", user_message, re.IGNORECASE)
        quantity = (
            float(fraction_match.group(1)) / float(fraction_match.group(2)) if fraction_match
            else number_words[quantity_match.group(1).casefold()] if quantity_match and quantity_match.group(1).casefold() in number_words
            else float(quantity_match.group(1)) if quantity_match else 1.0
        )
        lowered_message = user_message.casefold()
        if not fraction_match and any(word in lowered_message for word in ("half", "1/2")):
            quantity *= 0.5
        elif not fraction_match and any(word in lowered_message for word in ("quarter", "1/4")):
            quantity *= 0.25
        standard_weights = []
        for item in reference.get("portions", []) if isinstance(reference.get("portions"), list) else []:
            try:
                weight = float(item.get("gram_weight")) * quantity
            except (AttributeError, TypeError, ValueError):
                continue
            if math.isfinite(weight) and 0 < weight <= 100000:
                standard_weights.append(weight)
        if explicit_grams:
            portion = float(explicit_grams.group(1))
            valid_portion = 0 < portion <= 100000
        else:
            portion = next((weight for weight in standard_weights if abs(weight - proposed_portion) <= max(1.0, weight * 0.01)), 0)
            valid_portion = bool(portion)
        trusted_match = reference.get("match_strength") in {"high", "medium"}
        if not (reference_values and valid_portion and trusted_match):
            args["source"] = "estimated"
            return args
        args["portion_grams"] = portion
        for field, reference_key in reference_keys.items():
            args[field] = round(float(reference[reference_key]) * portion / 100, 1)
        return args

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
        portion = args.get("portion_grams")
        if portion is not None:
            portion = float(portion)
            if not math.isfinite(portion) or portion <= 0 or portion > 100000:
                raise ValueError("The model returned an invalid portion weight.")
        prediction["portion_grams"] = portion
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
        usda_reference = None
        usda_lookup_result = None
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
            lookup_in_this_round = any(call.function.name == "search_usda_food" for call in calls)
            for call in calls:
                model_args = json.loads(call.function.arguments or "{}")
                args = dict(model_args)
                # The model is never authoritative for ownership. Force the
                # authenticated account id into every account-scoped tool call.
                if persist and call.function.name in {"log_meal", "get_daily_summary", "get_saved_profile"}:
                    args["user_id"] = user_id
                if call.function.name == "log_meal":
                    # A parallel tool batch was generated before the model saw
                    # the USDA response. Do not let that stale log call be
                    # treated as source-grounded; the next round is forced to
                    # create the meal after the lookup observation is visible.
                    if lookup_in_this_round:
                        observation = {
                            "status": "deferred",
                            "reason": "USDA lookup results must be reviewed before saving the meal.",
                        }
                        trace.append({"type": "observation", "tool": call.function.name, "result": observation})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(observation),
                        })
                        continue
                    # Do not trust the model to transcribe retrieved nutrient values.
                    args = self._apply_usda_values(
                        args, usda_reference if has_grounded_usda_record else None, user_message
                    )
                trace_args = {key: value for key, value in args.items() if key != "user_id"}
                trace.append({"type": "plan", "tool": call.function.name, "args": trace_args})

                if call.function.name == "log_meal":
                    try:
                        prediction = self._prediction_from_args(args)
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        observation = {"status": "rejected", "reason": str(exc)}
                    else:
                        if usda_reference:
                            prediction["reference"] = usda_reference
                        if isinstance(usda_lookup_result, dict) and usda_lookup_result.get("error"):
                            prediction["lookup_error"] = usda_lookup_result["error"]
                        if persist:
                            observation = await self.bridge.call_tool(call.function.name, args)
                            if observation.get("status") == "logged":
                                prediction["meal_id"] = observation.get("meal_id")
                                predictions.append(prediction)
                        else:
                            predictions.append(prediction)
                            observation = {"status": "predicted", "saved": False}
                else:
                    observation = await self.bridge.call_tool(call.function.name, args)

                if call.function.name == "search_usda_food":
                    usda_lookup_result = observation
                    if observation.get("found"):
                        has_grounded_usda_record = True
                        usda_reference = observation
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
