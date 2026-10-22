"""Batch CLI (C8): CSV round-trip, resume, error isolation, --dist, and the four regression IDs end to end."""

import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from teratai import batch, data, pipeline
from teratai.models import CSV_COLUMNS, AgentDecision, ComplaintRow, Emit

REGRESSION_IDS = ["CMP-00165", "CMP-00244", "CMP-00387", "CMP-00289"]
NASTY_REPLY = 'Dear "Puan", RM46.66, refunded.\nSecond line, with a comma;\nthird\tline é'
IDS = ["CMP-00001", "CMP-00002", "CMP-00003", "CMP-00005"]


@pytest.fixture(scope="module")
def base() -> AgentDecision:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("REPLY_MODE", "template")
        return pipeline.process_complaint(data.complaint("CMP-00165"), "dev")


def _fake(
    base: AgentDecision, fail: set[str] | None = None, calls: list[str] | None = None
) -> Callable[[ComplaintRow, str, Emit | None], AgentDecision]:
    def process(row: ComplaintRow, run_id: str, emit: Emit | None = None) -> AgentDecision:
        assert row.complaint_id is not None
        if calls is not None:
            calls.append(row.complaint_id)
        if fail and row.complaint_id in fail:
            raise RuntimeError("boom")
        return base.model_copy(
            update={"complaint_id": row.complaint_id, "run_id": run_id, "reply_text": NASTY_REPLY}
        )

    return process


def test_csv_round_trip(base: AgentDecision, tmp_path: Path) -> None:
    res = batch.run_batch(IDS, "t-csv", process=_fake(base), checkpoint_dir=tmp_path)
    out = tmp_path / "out.csv"
    batch.write_csv(out, res.rows)
    with out.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == CSV_COLUMNS
        rows = list(reader)
    assert [r["complaint_id"] for r in rows] == IDS  # input order
    assert all(r["reply_text"] == NASTY_REPLY for r in rows)
    assert rows[0]["refund_amount_myr"] == "46.66"


def test_resume_skips_done_ids(base: AgentDecision, tmp_path: Path) -> None:
    first: list[str] = []
    batch.run_batch(IDS[:2], "t-res", process=_fake(base, calls=first), checkpoint_dir=tmp_path)
    assert sorted(first) == IDS[:2]
    second: list[str] = []
    res = batch.run_batch(IDS, "t-res", process=_fake(base, calls=second), checkpoint_dir=tmp_path)
    assert sorted(second) == IDS[2:]
    assert res.resumed == 2 and res.processed == 2
    assert [r["complaint_id"] for r in res.rows] == IDS
    third: list[str] = []
    batch.run_batch(IDS, "t-res", fresh=True, process=_fake(base, calls=third), checkpoint_dir=tmp_path)
    assert sorted(third) == IDS  # --fresh restarts


def test_raising_row_does_not_kill_run(base: AgentDecision, tmp_path: Path) -> None:
    res = batch.run_batch(IDS, "t-err", process=_fake(base, fail={"CMP-00002"}), checkpoint_dir=tmp_path)
    assert list(res.errors) == ["CMP-00002"] and "boom" in res.errors["CMP-00002"]
    assert len(res.rows) == 4
    bad = res.rows[1]
    assert (bad["complaint_id"], bad["outcome"], bad["refund_amount_myr"], bad["matched_txn_id"]) == (
        "CMP-00002",
        "INVESTIGATE",
        "0.00",
        "",
    )
    assert res.rows[0]["outcome"] == "REFUND"
    # errors are not checkpointed, so a rerun retries only the failed row
    again: list[str] = []
    res2 = batch.run_batch(IDS, "t-err", process=_fake(base, calls=again), checkpoint_dir=tmp_path)
    assert again == ["CMP-00002"] and not res2.errors


def test_unknown_id_is_an_error_not_a_crash(base: AgentDecision, tmp_path: Path) -> None:
    res = batch.run_batch(["CMP-00001", "NOPE-1"], "t-unk", process=_fake(base), checkpoint_dir=tmp_path)
    assert "NOPE-1" in res.errors and len(res.rows) == 2


def test_live_run_id_refused(base: AgentDecision, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        batch.run_batch(IDS, "live", process=_fake(base), checkpoint_dir=tmp_path)


def test_persist_calls_store_for_each_row(base: AgentDecision, tmp_path: Path) -> None:
    stored: list[str] = []

    def store(row: ComplaintRow, d: AgentDecision) -> int:
        stored.append(d.complaint_id)
        return 1

    batch.run_batch(IDS, "t-store", persist=True, process=_fake(base), store=store, checkpoint_dir=tmp_path)
    assert sorted(stored) == IDS


def test_dist_flags_more_than_5pp_shift() -> None:
    train = [{f: "A" for f in batch.DIST_FIELDS} for _ in range(100)]
    assert batch.dist_shifts([dict(r) for r in train], train) == []
    shifted = [dict(r) for r in train]
    for r in shifted[:6]:
        r["route"] = "B"  # 6 pp
    flagged = {(s.field, s.value) for s in batch.dist_shifts(shifted, train)}
    assert flagged == {("route", "A"), ("route", "B")}
    within = [dict(r) for r in train]
    for r in within[:5]:
        r["route"] = "B"  # exactly 5 pp is not flagged
    assert batch.dist_shifts(within, train) == []


def test_read_ids_csv_and_comma_list(tmp_path: Path) -> None:
    p = tmp_path / "ids.csv"
    p.write_text("complaint_id,x\nCMP-00001,a\nCMP-00002,b\nCMP-00001,c\n", encoding="utf-8")
    assert batch.read_ids(str(p)) == ["CMP-00001", "CMP-00002"]
    assert batch.read_ids("CMP-00003, CMP-00004") == ["CMP-00003", "CMP-00004"]


def test_four_regression_ids_match_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLY_MODE", "template")
    res = batch.run_batch(REGRESSION_IDS, "t-four", fresh=True, concurrency=4, checkpoint_dir=tmp_path)
    assert not res.errors and len(res.rows) == 4
    for r in res.rows:
        lab = data.labels()[r["complaint_id"]]
        got = {k: r[k] for k in CSV_COLUMNS if k not in ("complaint_id", "reply_language", "reply_text")}
        want = {
            "category": lab.category,
            "matched_txn_id": lab.matched_txn_id,
            "outcome": lab.outcome,
            "refund_amount_myr": f"{lab.refund_amount:.2f}",
            "priority": lab.priority,
            "route": lab.route,
        }
        assert got == want, r["complaint_id"]
