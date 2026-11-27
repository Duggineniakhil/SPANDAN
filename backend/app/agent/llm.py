"""Provider-neutral chat-with-tools wrapper for Groq and Gemini (order set by AGENT_PROVIDERS).

The planner only sees `ToolCall` / `Turn` / `ToolResult`; each provider keeps its own message
history in its native format. Any API/network failure is raised as `ProviderError` so the
planner can switch to the next provider.
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import get_settings


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict | None  # None when the model produced invalid JSON


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    refused: bool = False


@dataclass
class ToolResult:
    call: ToolCall
    content: dict
    is_error: bool = False


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    schema: dict


class ProviderError(Exception):
    pass


class Session(Protocol):
    def next(self, results: list[ToolResult] | None, user_text: str | None = None) -> Turn: ...


class Provider(Protocol):
    name: str

    def start(self, system: str, tools: list[ToolDef], user: str) -> Session: ...


# ---------------- Gemini ----------------

class GeminiProvider:
    def __init__(self, api_key: str, model: str, timeout_s: float = 30):
        from google import genai
        from google.genai import types

        self.name = f"gemini:{model}"
        self.model = model
        # Without a timeout an overloaded model can hang and block the fallback.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    def start(self, system: str, tools: list[ToolDef], user: str) -> "GeminiSession":
        return GeminiSession(self, system, tools, user)


class GeminiSession:
    def __init__(self, provider: GeminiProvider, system: str, tools: list[ToolDef], user: str):
        from google.genai import types

        self.types = types
        self.p = provider
        self.config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.schema)
                for t in tools
            ])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        self.contents: list[Any] = [types.Content(role="user", parts=[types.Part.from_text(text=user)])]

    def next(self, results: list[ToolResult] | None, user_text: str | None = None) -> Turn:
        from google.genai import errors

        types = self.types
        if results:
            self.contents.append(types.Content(role="user", parts=[
                types.Part(function_response=types.FunctionResponse(
                    id=r.call.id, name=r.call.name,
                    response={"error": r.content} if r.is_error else {"output": r.content},
                )) for r in results
            ]))
        if user_text:
            self.contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
        try:
            resp = self.p.client.models.generate_content(model=self.p.model, contents=self.contents, config=self.config)
        except errors.APIError as e:
            raise ProviderError(f"Gemini API error: {e}") from e
        except Exception as e:  # network errors etc.
            raise ProviderError(f"Gemini request failed: {e}") from e

        if not resp.candidates:
            reason = getattr(resp.prompt_feedback, "block_reason", None)
            return Turn(refused=True, text=f"blocked: {reason}")
        cand = resp.candidates[0]
        if cand.content is not None:
            self.contents.append(cand.content)  # keeps thought signatures for the next turn
        finish = str(cand.finish_reason or "")
        if any(k in finish for k in ("SAFETY", "PROHIBITED", "BLOCKLIST", "SPII")):
            return Turn(refused=True, text=finish)
        calls = [ToolCall(id=fc.id or f"call_{uuid.uuid4().hex[:8]}", name=fc.name, args=dict(fc.args or {}))
                 for fc in (resp.function_calls or [])]
        text = "".join(p.text for p in (cand.content.parts if cand.content and cand.content.parts else []) if getattr(p, "text", None))
        return Turn(text=text, tool_calls=calls)


# ---------------- Groq (OpenAI-style chat completions) ----------------

class GroqProvider:
    def __init__(self, api_key: str, model: str, timeout_s: float = 30):
        from groq import Groq

        self.name = f"groq:{model}"
        self.model = model
        self.client = Groq(api_key=api_key, timeout=timeout_s, max_retries=1)

    def start(self, system: str, tools: list[ToolDef], user: str) -> "GroqSession":
        return GroqSession(self, system, tools, user)


class GroqSession:
    def __init__(self, provider: GroqProvider, system: str, tools: list[ToolDef], user: str):
        self.p = provider
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
                      for t in tools]
        self.messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def next(self, results: list[ToolResult] | None, user_text: str | None = None) -> Turn:
        import groq

        for r in results or []:
            self.messages.append({"role": "tool", "tool_call_id": r.call.id,
                                  "content": json.dumps({"error": r.content} if r.is_error else r.content, ensure_ascii=False)})
        if user_text:
            self.messages.append({"role": "user", "content": user_text})
        try:
            resp = self.p.client.chat.completions.create(
                model=self.p.model, messages=self.messages, tools=self.tools, tool_choice="auto", temperature=0.2,
            )
        except groq.APIError as e:
            raise ProviderError(f"Groq API error: {e}") from e
        except Exception as e:
            raise ProviderError(f"Groq request failed: {e}") from e

        msg = resp.choices[0].message
        assistant: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        calls: list[ToolCall] = []
        if msg.tool_calls:
            assistant["tool_calls"] = [{"id": tc.id, "type": "function",
                                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                       for tc in msg.tool_calls]
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args if isinstance(args, dict) else None))
        self.messages.append(assistant)
        return Turn(text=msg.content or "", tool_calls=calls, refused=resp.choices[0].finish_reason == "content_filter")


def default_providers() -> list[Provider]:
    """Providers in the order set by AGENT_PROVIDERS (e.g. "groq,gemini"); those without a key are skipped."""
    s = get_settings()
    available: dict[str, Provider] = {}
    if s.gemini_api_key:
        available["gemini"] = GeminiProvider(s.gemini_api_key, s.gemini_model, s.llm_request_timeout_s)
    if s.groq_api_key:
        available["groq"] = GroqProvider(s.groq_api_key, s.groq_model, s.llm_request_timeout_s)
    order = [p.strip().lower() for p in s.agent_providers.split(",") if p.strip()]
    return [available[p] for p in order if p in available]
