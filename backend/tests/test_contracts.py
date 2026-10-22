"""Joint contract test: must stay green on every branch, with the stubs and with the real code."""

import csv
from pathlib import Path

import pytest
from pydantic import ValidationError

from teratai.models import ComplaintRow, StageEvent
from teratai.pipeline import process_complaint

DATA = Path(__file__).resolve().parents[2] / "data"


def _row(path: Path, complaint_id: str) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as f:
        return next(r for r in csv.DictReader(f) if r["complaint_id"] == complaint_id)


def test_cmp_00165_matches_gold_label() -> None:
    raw = _row(DATA / "complaints.csv", "CMP-00165")
    gold = _row(DATA / "labels_train.csv", "CMP-00165")
    events: list[StageEvent] = []

    decision = process_complaint(ComplaintRow.model_validate(raw), run_id="test", emit=events.append)
    row = decision.to_csv_row()

    assert {k: row[k] for k in gold} == gold
    assert row["reply_text"]
    assert decision.check_ok
    assert events, "stages must emit StageEvents"


def test_agent_decision_is_immutable_and_money_is_a_string() -> None:
    raw = _row(DATA / "complaints.csv", "CMP-00165")
    decision = process_complaint(ComplaintRow.model_validate(raw), run_id="test")

    assert decision.model_dump(mode="json")["refund_amount_myr"] == "46.66"
    with pytest.raises(ValidationError):
        decision.outcome = "DECLINE"  # type: ignore[misc]
