"""LLM layer tests: fully offline (temp cache, fake Anthropic client, no network)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock
from anthropic.types import Usage as ApiUsage

from teratai.llm import CacheMiss, LLMError, compute_cost, settings
from teratai.llm.anthropic_provider import AnthropicProvider
from teratai.llm.base import BaseProvider
from teratai.llm.cache import LLMCache, cache_key
from teratai.llm.factory import MissingApiKey, get_provider
from teratai.llm.replay_provider import ReplayProvider
from teratai.models import StageEvent

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
SCHEMA = {"type": "object", "properties": {"amount": {"type": "number"}}, "required": ["amount"]}


def _msg(content: list[Any], stop: str, tin: int = 100, tout: int = 20, **usage: int) -> Message:
    return Message(
        id="msg_1",
        content=content,
        model=HAIKU,
        role="assistant",
        stop_reason=stop,  # type: ignore[arg-type]
        type="message",
        usage=ApiUsage(input_tokens=tin, output_tokens=tout, **usage),
    )


class FakeClient:
    """Stands in for anthropic.Anthropic: returns queued responses and records requests."""

    def __init__(self, responses: list[Message]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Message:
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _provider(tmp_path: Path, responses: list[Message]) -> tuple[AnthropicProvider, FakeClient]:
    client = FakeClient(responses)
    return AnthropicProvider(LLMCache(tmp_path / "c.sqlite"), client=client), client  # type: ignore[arg-type]


def _tool_use(i: str = "toolu_1", **inp: Any) -> ToolUseBlock:
    return ToolUseBlock(id=i, name="lookup", input=inp, type="tool_use")


def test_cache_key_stable_and_sensitive() -> None:
    req = {"model": HAIKU, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
    reordered = {"max_tokens": 5, "messages": [{"content": "hi", "role": "user"}], "model": HAIKU}
    assert cache_key(HAIKU, "v1", req) == cache_key(HAIKU, "v1", reordered)
    assert cache_key(HAIKU, "v1", req) != cache_key(HAIKU, "v2", req)
    assert cache_key(HAIKU, "v1", req) != cache_key(SONNET, "v1", req)
    assert cache_key(HAIKU, "v1", req) != cache_key(HAIKU, "v1", {**req, "max_tokens": 6})


def test_cost_is_decimal_and_exact() -> None:
    # Haiku 5.5: $0.10 in / $0.50 out per MTok, cache read $0.01, cache write $0.125.
    cost = compute_cost(HAIKU, 20_000, 20_000, 20_000, 20_000)  # 60K prompt: base rate card
    assert isinstance(cost, Decimal)
    assert cost == (Decimal("0.10") + Decimal("0.50") + Decimal("0.01") + Decimal("0.125")) * 20_000 / 1_000_000
    assert compute_cost(HAIKU, 1_000_000, 1_000_000, 1_000_000, 1_000_000) == Decimal("3.675")  # long rate card
    assert compute_cost(SONNET, 1000, 500) == Decimal("0.002") + Decimal("0.005")
    # prompts over 100K tokens use the Haiku long-prompt rate card
    assert compute_cost(HAIKU, 200_000, 0) == Decimal("0.10")
    assert compute_cost("unknown-model", 10, 10) == Decimal(0)


def test_extract_forces_tool_and_caches(tmp_path: Path) -> None:
    prov, client = _provider(tmp_path, [_msg([_tool_use(amount=46.66)], "tool_use")])
    events: list[StageEvent] = []
    kwargs: dict[str, Any] = {
        "schema": SCHEMA,
        "tool_name": "lookup",
        "messages": [{"role": "user", "content": "charged RM46.66"}],
        "model": HAIKU,
        "system": "static prefix",
        "emit": events.append,
    }
    first = prov.extract(**kwargs)
    assert first.data == {"amount": 46.66}
    assert not first.usage.cache_hit and first.usage.tokens_in == 100
    req = client.requests[0]
    assert req["tool_choice"] == {"type": "tool", "name": "lookup"}
    assert "temperature" not in req
    assert req["system"][-1]["cache_control"] == {"type": "ephemeral"}
    second = prov.extract(**kwargs)  # the fake has no more responses: must come from disk
    assert second.data == first.data and second.usage.cache_hit
    assert len(client.requests) == 1
    assert [e.stage for e in events] == ["extract", "extract"] and events[1].payload["cache_hit"] is True
    assert events[0].model == HAIKU and events[0].cost_usd == first.usage.cost_usd > 0


def test_extract_on_model_without_forced_tool_uses_auto(tmp_path: Path) -> None:
    prov, client = _provider(tmp_path, [_msg([_tool_use(amount=1)], "tool_use")])
    prov.extract(schema=SCHEMA, tool_name="lookup", messages=[{"role": "user", "content": "x"}], model=SONNET)
    assert client.requests[0]["tool_choice"] == {"type": "auto"}
    assert "lookup" in client.requests[0]["system"][-1]["text"]


def test_extract_without_tool_output_raises(tmp_path: Path) -> None:
    prov, _ = _provider(tmp_path, [_msg([TextBlock(text="sorry", type="text")], "end_turn")])
    with pytest.raises(LLMError):
        prov.extract(schema=SCHEMA, tool_name="lookup", messages=[{"role": "user", "content": "x"}], model=HAIKU)


def test_generate_text_effort_and_cache_usage(tmp_path: Path) -> None:
    resp = _msg(
        [TextBlock(text="Dear Puan, ...", type="text")], "end_turn", tin=10, tout=30, cache_read_input_tokens=500
    )
    prov, client = _provider(tmp_path, [resp])
    out = prov.generate(messages=[{"role": "user", "content": "draft"}], model=SONNET, system="sys", effort="low")
    assert out.text == "Dear Puan, ..."
    assert client.requests[0]["output_config"] == {"effort": "low"}
    assert out.usage.tokens_in == 510 and out.usage.cache_read_tokens == 500
    assert out.usage.cost_usd == compute_cost(SONNET, 10, 30, 500, 0)


def test_replay_returns_recorded_response_and_miss_raises(tmp_path: Path) -> None:
    live, _ = _provider(tmp_path, [_msg([TextBlock(text="recorded", type="text")], "end_turn")])
    msgs = [{"role": "user", "content": "hello"}]
    recorded = live.generate(messages=msgs, model=HAIKU)

    replay = ReplayProvider(LLMCache(tmp_path / "c.sqlite"))
    out = replay.generate(messages=msgs, model=HAIKU)
    assert out.text == recorded.text == "recorded" and out.usage.cache_hit
    with pytest.raises(CacheMiss):
        replay.generate(messages=[{"role": "user", "content": "never seen"}], model=HAIKU)
    with pytest.raises(CacheMiss):  # a new prompt_version is a different key
        replay.generate(messages=msgs, model=HAIKU, prompt_version="v2")


def test_tool_loop_executes_handlers_and_replays(tmp_path: Path) -> None:
    prov, client = _provider(
        tmp_path,
        [
            _msg([_tool_use(cid="CUS-1")], "tool_use"),
            _msg([TextBlock(text="Her name is Aisyah.", type="text")], "end_turn"),
        ],
    )
    seen: list[dict[str, Any]] = []

    def lookup(args: dict[str, Any]) -> dict[str, Any]:
        seen.append(args)
        return {"name": "Aisyah"}

    events: list[StageEvent] = []
    kwargs: dict[str, Any] = {
        "tools": [{"name": "lookup", "description": "d", "input_schema": SCHEMA}],
        "handlers": {"lookup": lookup},
        "messages": [{"role": "user", "content": "who is CUS-1?"}],
        "model": HAIKU,
        "emit": events.append,
    }
    res = prov.tool_loop(**kwargs)
    assert seen == [{"cid": "CUS-1"}]
    assert res.text == "Her name is Aisyah." and not res.truncated
    assert res.tool_calls[0].name == "lookup" and res.tool_calls[0].output == {"name": "Aisyah"}
    assert res.usage.calls == 2 and res.usage.tokens_in == 200
    # second request carries assistant tool_use and the user tool_result
    second_msgs = client.requests[1]["messages"]
    assert second_msgs[-1]["content"][0]["type"] == "tool_result"
    assert second_msgs[-1]["content"][0]["tool_use_id"] == "toolu_1"
    assert [e.tool_name for e in events if e.tool_name] == ["lookup"]
    assert len(events) == 3  # two model calls + one tool execution

    # Whole loop replays from the cache, handler runs again, no API call.
    replay = ReplayProvider(LLMCache(tmp_path / "c.sqlite"))
    again = replay.tool_loop(**{**kwargs, "emit": None})
    assert again.text == res.text and again.usage.cache_hit and len(client.requests) == 2
    assert len(seen) == 2


def test_tool_loop_stops_at_max_calls(tmp_path: Path) -> None:
    prov, client = _provider(tmp_path, [_msg([_tool_use(f"t{i}", cid=str(i))], "tool_use") for i in range(5)])
    runs = 0

    def lookup(args: dict[str, Any]) -> dict[str, Any]:
        nonlocal runs
        runs += 1
        return {"ok": True}

    res = prov.tool_loop(
        tools=[{"name": "lookup", "description": "d", "input_schema": SCHEMA}],
        handlers={"lookup": lookup},
        messages=[{"role": "user", "content": "loop forever"}],
        model=HAIKU,
        max_calls=2,
    )
    assert res.truncated and runs == 2 and len(res.tool_calls) == 2
    assert len(client.requests) == 3


def test_tool_loop_handler_error_is_reported_to_model(tmp_path: Path) -> None:
    prov, client = _provider(
        tmp_path,
        [_msg([_tool_use(cid="x")], "tool_use"), _msg([TextBlock(text="done", type="text")], "end_turn")],
    )

    def boom(args: dict[str, Any]) -> Any:
        raise KeyError("CUS-X")

    res = prov.tool_loop(
        tools=[{"name": "lookup", "description": "d", "input_schema": SCHEMA}],
        handlers={"lookup": boom},
        messages=[{"role": "user", "content": "q"}],
        model=HAIKU,
    )
    assert not res.tool_calls[0].ok
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_factory_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CACHE_PATH", str(tmp_path / "f.sqlite"))
    monkeypatch.setenv("DEMO_MODE", "cached")
    assert isinstance(get_provider(), ReplayProvider)
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setattr(settings, "api_key", lambda: None)
    with pytest.raises(MissingApiKey, match="ANTHROPIC_API_KEY missing"):
        get_provider()
    monkeypatch.setattr(settings, "api_key", lambda: "sk-ant-test")
    prov = get_provider()
    assert isinstance(prov, AnthropicProvider) and isinstance(prov, BaseProvider)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("EXTRACT_MODEL", "REPLY_MODEL", "DEMO_MODE", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    assert settings.extract_model() == "claude-haiku-5-5"
    assert settings.reply_model() == "claude-sonnet-5-5"
    assert settings.demo_mode() == "live" and settings.llm_provider() == "anthropic"
