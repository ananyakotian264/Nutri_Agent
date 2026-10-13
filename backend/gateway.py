"""
gateway.py — The AI MODEL GATEWAY.

Every other file in this project talks to "the model" only through the
ModelGateway class below — never directly to the `groq` package. That
single choke point is the whole idea of a model gateway:

  * Swap providers (Groq -> OpenAI -> Anthropic -> a local model) by
    rewriting ONE file, not every call site.
  * Add cross-cutting concerns once — retries, logging, cost tracking,
    rate limiting, a fallback model — and every caller gets them for free.
  * Keep provider-specific request/response shapes out of the orchestrator,
    which should only think in terms of "messages in, message out".

In a bigger system this gateway might sit in front of several models and
route between them (a cheap/fast model for simple lookups, a stronger model
for planning). Here it's intentionally simple: one provider, one model,
clear seams for you to extend later.
"""

import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-20b"


class ModelGateway:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.client = None
        self.model = os.getenv("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.active_model = self.model

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_key != "your_groq_key_here")

    def chat(self, messages: list, tools: list | None = None, tool_choice="auto"):
        """
        Single entry point used by the orchestrator. Returns the raw
        `message` object from the completion so the orchestrator can inspect
        both `.content` and `.tool_calls`.
        """
        if not self.configured:
            raise RuntimeError("AI food logging is unavailable because GROQ_API_KEY is not configured")
        if self.client is None:
            self.client = Groq(api_key=self.api_key, timeout=25.0, max_retries=1)

        kwargs = {
            "model": self.active_model,
            "messages": messages,
            "temperature": 0.2,  # low temperature: this is a data task, not creative writing
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            completion = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Fall back when an old or account-restricted model ID is configured.
            # Other provider errors should remain visible to the API error mapper.
            if type(exc).__name__ != "NotFoundError" or self.active_model == DEFAULT_MODEL:
                raise
            self.active_model = DEFAULT_MODEL
            kwargs["model"] = self.active_model
            completion = self.client.chat.completions.create(**kwargs)
        return completion.choices[0].message


gateway = ModelGateway()
