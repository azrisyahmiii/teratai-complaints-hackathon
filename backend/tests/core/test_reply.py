"""C10: LLM reply writer (SPEC §4.6-4.7). Offline: real Sonnet responses are replayed from a committed fixture
(`fixtures/reply_llm_cache.json`, exported from the llm cache) through DEMO_MODE=cached; failure paths use a fake provider."""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from teratai import data, reply
from teratai.llm import LLMError
from teratai.llm.base import GenerateResult, Usage
from teratai.llm.cache import LLMCache
from teratai.models import ComplaintRow, Emit, FactSheet, StageEvent
from teratai.pipeline import process_complaint

FIXTURE = Path(__file__).parent / "fixtures" / "reply_llm_cache.json"
DEMO_IDS = ["CMP-00165", "CMP-00244", "CMP-00387", "CMP-00289"]


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DEMO_MODE=cached with the recorded Sonnet responses loaded into a tmp cache."""
    cache = LLMCache(tmp_path / "llm_cache.sqlite")
    for key, record in json.loads(FIXTURE.read_text(encoding="utf-8")).items():
        cache.put(key, record)
    monkeypatch.setenv("LLM_CACHE_PATH", str(cache.path))
    monkeypatch.setenv("DEMO_MODE", "cached")
    monkeypatch.setenv("REPLY_MODE", "llm")


def _facts(complaint_id: str, **update: Any) -> FactSheet:
    d = process_complaint(data.complaint(complaint_id), run_id="test")
    return d.facts.model_copy(update=update)


def _needs_info_facts() -> FactSheet:
    return FactSheet(
        customer_name="Aisyah binti Kassim",
        honorific="Puan",
        language="MS",
        category="FAILED_TRANSFER",
        outcome="DECLINE",
        refund_myr=Decimal("0.00"),
        ids={"state": "needs_info"},
        amounts={},
        dates={},
        sla_days=3,
    )


class FakeProvider:
    """Returns scripted drafts (or raises) and records every call."""

    def __init__(self, texts: Sequence[str | Exception]) -> None:
        self.texts = list(texts)
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls.append(kwargs)
        item = self.texts[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        emit: Emit | None = kwargs.get("emit")
        if emit is not None:
            emit(StageEvent(stage=kwargs["stage"], ok=True, latency_ms=1, payload={}))
        return GenerateResult(text=item, usage=Usage(model=kwargs["model"]), stop_reason="end_turn")


def _fake(monkeypatch: pytest.MonkeyPatch, texts: Sequence[str | Exception]) -> FakeProvider:
    monkeypatch.setenv("REPLY_MODE", "llm")
    fake = FakeProvider(texts)
    monkeypatch.setattr(reply, "_provider", lambda: fake)
    return fake


def _final(events: list[StageEvent]) -> StageEvent:
    return next(e for e in reversed(events) if e.stage == "reply")


# --- recorded Sonnet replies -------------------------------------------------------------------------------------------
@pytest.mark.usefixtures("replay")
@pytest.mark.parametrize("complaint_id", DEMO_IDS)
def test_demo_ids_get_a_checked_llm_reply(complaint_id: str) -> None:
    events: list[StageEvent] = []
    d = process_complaint(data.complaint(complaint_id), run_id="test", emit=events.append)

    assert d.reply.source == "llm"  # a cache miss would have fallen back to the template
    assert d.reply.check.ok
    assert d.check_ok
    assert len(d.reply.drafts) == 1
    final = _final(events).payload
    assert final["degraded"] is False
    assert final["check_flagged"] is False
    assert any(e.stage == "reply_draft" and e.model == "claude-sonnet-5-5" for e in events)


@pytest.mark.usefixtures("replay")
def test_cmp_00165_reply_is_malay_and_cites_the_refund() -> None:
    d = process_complaint(data.complaint("CMP-00165"), run_id="test")

    assert d.reply_language == "MS"
    assert "TXN-0115572" in d.reply_text
    assert "RM46.66" in d.reply_text
    assert "Sekian, terima kasih" in d.reply_text


@pytest.mark.usefixtures("replay")
def test_needs_info_reply_from_recorded_response() -> None:
    r = reply.write_reply(_needs_info_facts(), "batch", lambda _: None)

    assert r.source == "llm"
    assert r.check.ok


# --- fallback chain ----------------------------------------------------------------------------------------------------
def test_failed_draft_gets_exactly_one_redraft_then_the_template(monkeypatch: pytest.MonkeyPatch) -> None:
    bad1 = "Dear Ms Aisyah, we will refund RM600.00 for TXN-0088299 within 7 working days. Yours sincerely, Teratai Bank"
    bad2 = "Dear Ms Aisyah, we have refunded RM800.00 for TXN-0088211. Yours sincerely, Teratai Bank"
    facts = _facts("CMP-00244")
    fake = _fake(monkeypatch, [bad1, bad2, "must never be requested"])
    events: list[StageEvent] = []

    r = reply.write_reply(facts, "batch", events.append)

    assert len(fake.calls) == 2  # draft + one redraft, never a third
    assert r.source == "template"
    assert r.check.ok
    assert r.drafts[:2] == [bad1, bad2]  # failed drafts are kept
    assert r.drafts[-1] == r.text
    redraft_prompt = fake.calls[1]["messages"][-1]["content"]
    assert "RM600.00" in redraft_prompt  # the redraft is told what failed
    assert fake.calls[1]["messages"][1] == {"role": "assistant", "content": bad1}
    final = _final(events).payload
    assert final["source"] == "template"
    assert final["check_flagged"] is True
    assert final["degraded"] is False
    assert final["drafts"] == 3


def test_redraft_that_passes_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts("CMP-00244")
    good = reply.render(facts)
    fake = _fake(monkeypatch, ["Dear Ms Aisyah, we will refund RM600.00 for TXN-0088211.", good])

    r = reply.write_reply(facts, "batch", lambda _: None)

    assert len(fake.calls) == 2
    assert r.source == "redraft"
    assert r.check.ok
    assert r.text == good
    assert len(r.drafts) == 2


def test_cache_miss_in_cached_mode_falls_back_to_template_and_is_degraded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LLM_CACHE_PATH", str(tmp_path / "empty.sqlite"))
    monkeypatch.setenv("DEMO_MODE", "cached")
    monkeypatch.setenv("REPLY_MODE", "llm")
    events: list[StageEvent] = []

    r = reply.write_reply(_facts("CMP-00244"), "live", events.append)

    assert r.source == "template"
    assert r.check.ok
    final = _final(events).payload
    assert final["degraded"] is True
    assert final["check_flagged"] is False  # no LLM draft failed; the LLM was simply unavailable
    assert "CacheMiss" in final["error"]


def test_llm_error_falls_back_to_template_and_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts("CMP-00244")
    fake = _fake(monkeypatch, [TimeoutError("timed out")])
    events: list[StageEvent] = []

    r = reply.write_reply(facts, "batch", events.append)

    assert len(fake.calls) == 1
    assert r.source == "template"
    assert r.check.ok
    assert _final(events).payload["degraded"] is True


def test_error_on_the_redraft_is_degraded_and_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts("CMP-00244")
    _fake(monkeypatch, ["Dear Ms Aisyah, we will refund RM600.00 for TXN-0088211.", LLMError("boom")])
    events: list[StageEvent] = []

    r = reply.write_reply(facts, "batch", events.append)

    assert r.source == "template"
    assert len(r.drafts) == 2  # the failed draft + the template
    final = _final(events).payload
    assert final["degraded"] is True
    assert final["check_flagged"] is True


# --- unchanged paths -----------------------------------------------------------------------------------------------------
def test_reply_mode_template_never_calls_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    facts = _facts("CMP-00244")
    fake = _fake(monkeypatch, [])
    monkeypatch.setenv("REPLY_MODE", "template")

    r = reply.write_reply(facts, "batch", lambda _: None)

    assert fake.calls == []
    assert r.source == "template"
    assert r.text == reply.render(facts)
    assert r.drafts == [r.text]


def test_wrong_customer_gets_an_empty_reply_and_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _facts("CMP-00244")
    fake = _fake(monkeypatch, [])
    facts = base.model_copy(update={"ids": {**base.ids, "state": "wrong_customer"}})
    events: list[StageEvent] = []

    r = reply.write_reply(facts, "live", events.append)

    assert fake.calls == []
    assert r.text == ""
    assert r.source == "template"
    assert [e.stage for e in events] == ["reply"]


# --- prompt hygiene ------------------------------------------------------------------------------------------------------
def test_the_model_never_sees_the_complaint_text(monkeypatch: pytest.MonkeyPatch) -> None:
    row: ComplaintRow = data.complaint("CMP-00244")
    facts = _facts("CMP-00244")
    fake = _fake(monkeypatch, [reply.render(facts)])

    reply.write_reply(facts, "batch", lambda _: None)

    sent = json.dumps(fake.calls[0]["messages"], ensure_ascii=False) + "\n".join(fake.calls[0]["system"])
    assert row.text not in sent
    assert "withdrew" not in sent.lower()
    assert fake.calls[0]["prompt_version"] == reply.PROMPT_VERSION
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"


def test_fact_sheet_carries_the_decision_and_the_verified_contacts() -> None:
    declined = _facts("CMP-00056")
    sheet = reply.fact_sheet_text(declined)
    assert "outcome: DECLINE" in sheet
    assert "refund_amount" not in sheet  # a non-refund sheet has no refund figure to leak
    assert "FMOS" in sheet and "1-300-88-5465" in sheet

    scam = reply.fact_sheet_text(_facts("CMP-00005"))
    assert "997" in scam
    assert "working_days_between_updates: 10" in scam

    refund = reply.fact_sheet_text(_facts("CMP-00244"))
    assert "refund_amount: RM550.00" in refund
    assert "atm_amount_dispensed: RM950.00" in refund


def test_system_prompt_is_static_and_has_both_languages() -> None:
    first, second = reply.system_prompt()
    assert reply.system_prompt() == (first, second)
    assert "EXAMPLE (EN)" in second and "EXAMPLE (MS)" in second
    assert "Sekian, terima kasih" in second
