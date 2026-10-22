"""Wave-3 review fixes for the batch CLI (C8): checkpoint stamp and the category-aware error row."""

from pathlib import Path

import pytest

from teratai import batch, data
from teratai.models import AgentDecision
from tests.core.test_batch import IDS, _fake, base  # noqa: F401  (base is a fixture)


def test_resume_refuses_a_checkpoint_made_with_other_reply_mode(base: AgentDecision, tmp_path: Path) -> None:  # noqa: F811
    batch.run_batch(IDS[:2], "t-stamp", replies="template", process=_fake(base), checkpoint_dir=tmp_path)
    again: list[str] = []
    with pytest.raises(batch.CheckpointMismatch) as exc:
        batch.run_batch(
            IDS, "t-stamp", replies="llm", process=_fake(base, calls=again), checkpoint_dir=tmp_path
        )
    assert "replies=template" in str(exc.value) and "--fresh" in str(exc.value) and not again
    res = batch.run_batch(
        IDS, "t-stamp", replies="llm", fresh=True, process=_fake(base), checkpoint_dir=tmp_path
    )
    assert res.resumed == 0 and res.processed == 4
    res = batch.run_batch(IDS, "t-stamp", replies="llm", process=_fake(base), checkpoint_dir=tmp_path)
    assert res.resumed == 4  # same mode and code resumes


def test_resume_refuses_when_the_code_changed(
    base: AgentDecision,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch.run_batch(IDS[:2], "t-code", replies="template", process=_fake(base), checkpoint_dir=tmp_path)
    monkeypatch.setattr(batch, "code_fingerprint", lambda: "deadbeef0000")
    with pytest.raises(batch.CheckpointMismatch, match="code="):
        batch.run_batch(IDS, "t-code", replies="template", process=_fake(base), checkpoint_dir=tmp_path)


def test_checkpoint_without_stamp_is_refused(base: AgentDecision, tmp_path: Path) -> None:  # noqa: F811
    ck = batch.checkpoint_path("t-old", tmp_path)
    ck.write_text(base.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(batch.CheckpointMismatch):
        batch.run_batch(IDS, "t-old", replies="template", process=_fake(base), checkpoint_dir=tmp_path)


def test_main_reports_a_mismatch_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(batch.config, "VAR_DIR", tmp_path)
    ck = batch.checkpoint_path("t-cli")
    ck.parent.mkdir(parents=True, exist_ok=True)
    ck.write_text(batch.stamp_line("template", "abc123abc123"), encoding="utf-8")
    assert batch.main(["--ids", "CMP-00001", "--run", "t-cli", "--replies", "llm"]) == 2
    err = capsys.readouterr().err
    assert "replies=template, code=abc123abc123" in err and "--fresh" in err


def test_code_fingerprint_is_stable_hex() -> None:
    a = batch.code_fingerprint()
    assert a == batch.code_fingerprint() and len(a) == 12 and int(a, 16) >= 0


# --- 7: error row ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category, outcome, route",
    [
        ("SCAM_TRANSFER", "INVESTIGATE", "FRAUD_TEAM"),
        ("UNAUTHORISED_CARD", "INVESTIGATE", "FRAUD_TEAM"),
        ("ATM_NOT_DISPENSED", "DECLINE", "HUMAN_APPROVAL"),
        ("FEE_DISPUTE", "DECLINE", "HUMAN_APPROVAL"),
    ],
)
def test_error_row_is_category_aware(category: str, outcome: str, route: str) -> None:
    cid = next(i for i, lb in data.labels().items() if lb.category == category)
    row = batch.error_row(cid)
    assert (row["category"], row["outcome"], row["route"]) == (category, outcome, route)
    assert row["refund_amount_myr"] == "0.00" and row["matched_txn_id"] == ""
    assert (
        row["priority"] in ("P1", "P2", "P3") and row["reply_language"] in ("EN", "MS") and row["reply_text"]
    )


def test_error_row_falls_back_to_fraud_when_classification_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("classifier down")

    monkeypatch.setattr(batch.classify, "understand", boom)
    row = batch.error_row("CMP-00244")
    assert (row["outcome"], row["route"], row["refund_amount_myr"], row["matched_txn_id"]) == (
        "INVESTIGATE",
        "FRAUD_TEAM",
        "0.00",
        "",
    )
    unknown = batch.error_row("NOPE-1")
    assert (unknown["outcome"], unknown["route"], unknown["reply_language"]) == (
        "INVESTIGATE",
        "FRAUD_TEAM",
        "EN",
    )
