"""Provider interface (SPEC §12) and the logic shared by every provider.

Providers differ only in `_call_api` (what happens on a cache miss): the Anthropic provider calls the SDK,
the replay provider raises `CacheMiss`. Everything else (request building, disk cache, tool loop, usage,
cost, StageEvent emission) lives here once.

The LLM only produces language and clues. It never sets outcome, refund, route or priority.
Calls are synchronous; async callers use `asyncio.to_thread`.
No `temperature`/`top_p`/`top_k` is ever sent: Sonnet 5.5 and Haiku 5.5 reject non-default values and the
API rejects them on every model from API version 2026-10-21.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from teratai.llm.cache import LLMCache, cache_key
from teratai.llm.pricing import compute_cost
from teratai.models import Emit, StageEvent

Message = dict[str, Any]
ToolHandler = Callable[[dict[str, Any]], Any]

# Models that return 400 on a forced tool_choice (any / tool). Use tool_choice=auto + a prompt instruction.
NO_FORCED_TOOL_PREFIXES = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable", "claude-mythos")


class LLMError(RuntimeError):
    """The model answered but not usably (no tool output, refusal, ...)."""


class CacheMiss(LLMError):
    """Replay provider: the request is not in the disk cache. Callers fall back to templates and flag `degraded`."""

    def __init__(self, key: str, model: str) -> None:
        super().__init__(f"LLM cache miss for model {model} (key {key[:12]}...): not recorded, cannot replay")
        self.key = key
        self.model = model


@dataclass(frozen=True)
class Usage:
    model: str
    tokens_in: int = 0  # all input tokens: uncached + cache read + cache write
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal(0)  # cost of the call as recorded; a cache hit costs nothing real now
    latency_ms: int = 0  # wall time of this call (a cache hit is a lookup)
    recorded_latency_ms: int = 0  # latency of the original live call
    cache_hit: bool = False
    calls: int = 1

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            model=self.model,
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=self.latency_ms + other.latency_ms,
            recorded_latency_ms=self.recorded_latency_ms + other.recorded_latency_ms,
            cache_hit=self.cache_hit and other.cache_hit,
            calls=self.calls + other.calls,
        )


@dataclass(frozen=True)
class ExtractResult:
    data: dict[str, Any]  # the forced tool's input: validate with pydantic in the caller
    usage: Usage


@dataclass(frozen=True)
class GenerateResult:
    text: str
    usage: Usage
    stop_reason: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    output: Any
    ok: bool
    latency_ms: int


@dataclass(frozen=True)
class ToolLoopResult:
    text: str  # final assistant text ("" if stopped at max_calls)
    tool_calls: list[ToolCall]
    usage: Usage  # summed over every model turn
    truncated: bool  # True when max_calls was hit and the model still wanted more tools
    messages: list[Message] = field(default_factory=list)  # full transcript, for the trace


class LLMProvider(Protocol):
    def extract(
        self,
        *,
        schema: dict[str, Any],
        messages: Sequence[Message],
        model: str,
        tool_name: str = "extract",
        tool_description: str = "Record the extracted fields.",
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "extract",
    ) -> ExtractResult: ...

    def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        effort: str | None = None,
        cache_system: bool = True,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "reply",
    ) -> GenerateResult: ...

    def tool_loop(
        self,
        *,
        tools: Sequence[dict[str, Any]],
        handlers: dict[str, ToolHandler],
        messages: Sequence[Message],
        model: str,
        max_calls: int = 5,
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        effort: str | None = None,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "investigate",
    ) -> ToolLoopResult: ...


def _system_blocks(system: str | Sequence[str] | None, cache_last: bool) -> list[dict[str, Any]] | None:
    """System prompt as text blocks. `cache_control` goes on the last block, so everything before it
    (tools + system) is the cached static prefix. Keep volatile content in `messages`."""
    if system is None:
        return None
    parts = [system] if isinstance(system, str) else list(system)
    if not parts:
        return None
    blocks: list[dict[str, Any]] = [{"type": "text", "text": p} for p in parts]
    if cache_last:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _text_of(content: Sequence[dict[str, Any]]) -> str:
    return "".join(str(b.get("text", "")) for b in content if b.get("type") == "text").strip()


class BaseProvider:
    def __init__(self, cache: LLMCache) -> None:
        self.cache = cache

    # -- the only provider-specific part ---------------------------------------------------------------
    def _call_api(self, request: dict[str, Any], key: str) -> dict[str, Any]:
        """Return a cache record for `request`:
        {"content": [block dicts], "stop_reason": str, "model": str, "latency_ms": int,
         "usage": {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"}}"""
        raise NotImplementedError

    # -- shared plumbing ---------------------------------------------------------------------------------
    def _complete(self, request: dict[str, Any], prompt_version: str) -> tuple[dict[str, Any], Usage]:
        model = str(request["model"])
        key = cache_key(model, prompt_version, request)
        start = time.perf_counter()
        record = self.cache.get(key)
        hit = record is not None
        if record is None:
            record = self._call_api(request, key)
            self.cache.put(key, record)
        elapsed = int((time.perf_counter() - start) * 1000)
        u = record["usage"]
        cost = compute_cost(model, u["input_tokens"], u["output_tokens"], u["cache_read_tokens"], u["cache_write_tokens"])
        usage = Usage(
            model=model,
            tokens_in=u["input_tokens"] + u["cache_read_tokens"] + u["cache_write_tokens"],
            tokens_out=u["output_tokens"],
            cache_read_tokens=u["cache_read_tokens"],
            cache_write_tokens=u["cache_write_tokens"],
            cost_usd=cost,
            latency_ms=elapsed if hit else int(record.get("latency_ms", elapsed)),
            recorded_latency_ms=int(record.get("latency_ms", 0)),
            cache_hit=hit,
        )
        return record, usage

    @staticmethod
    def _emit_model_call(
        emit: Emit | None, stage: str, usage: Usage, ok: bool, payload: dict[str, Any]
    ) -> None:
        if emit is None:
            return
        emit(
            StageEvent(
                stage=stage,
                ok=ok,
                latency_ms=usage.latency_ms,
                model=usage.model,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=usage.cost_usd,
                payload={"cache_hit": usage.cache_hit, "calls": usage.calls, **payload},
            )
        )

    @staticmethod
    def _base_request(
        model: str,
        messages: Sequence[Message],
        system: list[dict[str, Any]] | None,
        max_tokens: int,
        effort: str | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": list(messages)}
        if system:
            request["system"] = system
        if effort:
            request["output_config"] = {"effort": effort}
        return request

    # -- public API --------------------------------------------------------------------------------------
    def extract(
        self,
        *,
        schema: dict[str, Any],
        messages: Sequence[Message],
        model: str,
        tool_name: str = "extract",
        tool_description: str = "Record the extracted fields.",
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "extract",
    ) -> ExtractResult:
        """Structured output via a forced tool call (the tool input is the JSON). Models that reject a forced
        `tool_choice` get `auto` plus an instruction to call the tool."""
        forced = not model.startswith(NO_FORCED_TOOL_PREFIXES)
        sys_parts = [system] if isinstance(system, str) else list(system or [])
        if not forced:
            sys_parts.append(f"Respond only by calling the `{tool_name}` tool exactly once.")
        request = self._base_request(model, messages, _system_blocks(sys_parts, cache_last=True), max_tokens, None)
        request["tools"] = [{"name": tool_name, "description": tool_description, "input_schema": schema}]
        request["tool_choice"] = {"type": "tool", "name": tool_name} if forced else {"type": "auto"}
        record, usage = self._complete(request, prompt_version)
        for block in record["content"]:
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                data = dict(block["input"])
                self._emit_model_call(emit, stage, usage, True, {"stop_reason": record["stop_reason"]})
                return ExtractResult(data=data, usage=usage)
        self._emit_model_call(emit, stage, usage, False, {"stop_reason": record["stop_reason"]})
        raise LLMError(f"model did not call the `{tool_name}` tool (stop_reason={record['stop_reason']})")

    def generate(
        self,
        *,
        messages: Sequence[Message],
        model: str,
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        effort: str | None = None,
        cache_system: bool = True,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "reply",
    ) -> GenerateResult:
        request = self._base_request(model, messages, _system_blocks(system, cache_system), max_tokens, effort)
        record, usage = self._complete(request, prompt_version)
        text = _text_of(record["content"])
        ok = bool(text) and record["stop_reason"] in ("end_turn", "stop_sequence")
        self._emit_model_call(emit, stage, usage, ok, {"stop_reason": record["stop_reason"]})
        if record["stop_reason"] == "refusal":
            raise LLMError("model refused the request (stop_reason=refusal)")
        return GenerateResult(text=text, usage=usage, stop_reason=record["stop_reason"])

    def tool_loop(
        self,
        *,
        tools: Sequence[dict[str, Any]],
        handlers: dict[str, ToolHandler],
        messages: Sequence[Message],
        model: str,
        max_calls: int = 5,
        system: str | Sequence[str] | None = None,
        max_tokens: int = 1024,
        effort: str | None = None,
        prompt_version: str = "v1",
        emit: Emit | None = None,
        stage: str = "investigate",
    ) -> ToolLoopResult:
        """Bounded tool loop. Python `handlers` execute the tools (errors become `is_error` results);
        every model turn is cached on its own, so a rerun replays the whole loop. Stops after `max_calls`
        executed tool calls; if the model still wants more, `truncated=True`."""
        convo: list[Message] = [dict(m) for m in messages]
        sys_blocks = _system_blocks(system, cache_last=True)
        calls: list[ToolCall] = []
        total: Usage | None = None
        while True:
            request = self._base_request(model, convo, sys_blocks, max_tokens, effort)
            request["tools"] = list(tools)
            request["tool_choice"] = {"type": "auto"}
            record, usage = self._complete(request, prompt_version)
            total = usage if total is None else total + usage
            content: list[dict[str, Any]] = record["content"]
            convo.append({"role": "assistant", "content": content})
            uses = [b for b in content if b.get("type") == "tool_use"]
            self._emit_model_call(
                emit, stage, usage, True, {"stop_reason": record["stop_reason"], "tool_uses": [u["name"] for u in uses]}
            )
            if record["stop_reason"] != "tool_use" or not uses:
                return ToolLoopResult(_text_of(content), calls, total, False, convo)
            if len(calls) + len(uses) > max_calls:
                return ToolLoopResult(_text_of(content), calls, total, True, convo)
            results: list[dict[str, Any]] = []
            for use in uses:
                call = self._run_tool(use, handlers)
                calls.append(call)
                if emit is not None:
                    emit(
                        StageEvent(
                            stage=stage,
                            ok=call.ok,
                            latency_ms=call.latency_ms,
                            tool_name=call.name,
                            payload={"input": call.input, "output": call.output},
                        )
                    )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": json.dumps(call.output, ensure_ascii=False, default=str),
                        **({} if call.ok else {"is_error": True}),
                    }
                )
            convo.append({"role": "user", "content": results})

    @staticmethod
    def _run_tool(use: dict[str, Any], handlers: dict[str, ToolHandler]) -> ToolCall:
        name = str(use["name"])
        args = dict(use.get("input") or {})
        handler = handlers.get(name)
        start = time.perf_counter()
        if handler is None:
            return ToolCall(name, args, {"error": f"unknown tool {name}"}, False, 0)
        try:
            output = handler(args)
            ok = True
        except Exception as exc:  # noqa: BLE001  tool errors go back to the model, not up the stack
            output, ok = {"error": f"{type(exc).__name__}: {exc}"}, False
        return ToolCall(name, args, output, ok, int((time.perf_counter() - start) * 1000))
