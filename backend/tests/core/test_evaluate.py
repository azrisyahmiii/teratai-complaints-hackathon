"""Offline tests for the eval harness: scoring parity with scoring/score.py, bootstrap, hold-out guard, fixtures."""

import csv
from datetime import datetime
from pathlib import Path

import pytest

from teratai import data, evaluate
from teratai.models import ComplaintRow

OFFICIAL = evaluate.official


def _gold(**kw: str) -> dict[str, str]:
    base = {
        "category": "DUPLICATE_CHARGE",
        "matched_txn_id": "TXN-1",
        "outcome": "REFUND",
        "refund_amount_myr": "46.66",
        "priority": "P2",
        "reply_language": "EN",
        "route": "AUTO_RESOLVE",
    }
    return base | kw


def _pairs() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    labels = {
        "A": _gold(),  # perfect
        "B": _gold(),  # wrong txn: outcome and refund are gated -> only category, priority, language score
        "C": _gold(outcome="DECLINE", refund_amount_myr="0.00"),  # critical: refund where gold is DECLINE
        "D": _gold(category="SCAM_TRANSFER", outcome="INVESTIGATE", refund_amount_myr="0.00"),  # critical: fraud missed
        "E": _gold(),  # missing prediction
    }
    preds = {
        "A": dict(_gold()),
        "B": dict(_gold(matched_txn_id="TXN-9")),
        "C": dict(_gold(outcome="REFUND", refund_amount_myr="10.00", matched_txn_id="TXN-1")),
        "D": dict(_gold(category="SCAM_TRANSFER", outcome="DECLINE", refund_amount_myr="0.00")),
    }
    return preds, labels


def test_scoring_matches_official_score_py(tmp_path: Path) -> None:
    preds, labels = _pairs()
    ours = evaluate.score_all(preds, labels)
    # the official scorer, run on the same files
    cols = ["complaint_id", "category", "matched_txn_id", "outcome", "refund_amount_myr", "priority", "reply_language", "route", "reply_text"]
    pf, lf = tmp_path / "p.csv", tmp_path / "l.csv"
    with pf.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({"complaint_id": k, "reply_text": "", **v} for k, v in preds.items())
    with lf.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols[:-1] + [], extrasaction="ignore")
        w.writeheader()
        w.writerows({"complaint_id": k, **v} for k, v in labels.items())
    p, _ = OFFICIAL.load(str(pf))
    t, _ = OFFICIAL.load(str(lf))
    points = []
    crit = 0
    for cid, gold in t.items():
        got = {f: OFFICIAL.field_ok(f, p[cid].get(f, ""), gold[f]) if cid in p else False for f in OFFICIAL.WEIGHTS}
        for f in OFFICIAL.GATED:
            got[f] = got[f] and got["matched_txn_id"]
        points.append(sum(OFFICIAL.WEIGHTS[f] for f, ok in got.items() if ok))
    crit = 2  # C wrongful refund, D missed fraud (documented in score.py)
    assert [r.points for r in ours.rows] == points
    assert ours.criticals == crit
    assert [r.critical for r in ours.rows] == [None, None, "wrongful refund", "missed fraud", None]
    expected = sum(points) / 5 * (1 - 2 * crit / 5)
    assert ours.final == pytest.approx(max(0.0, expected))
    # B: wrong transaction means outcome and refund get no credit even though they equal the gold
    assert ours.rows[1].points == 25 * 0 + 10 + 10 + 5
    assert ours.rows[1].first_wrong == "matched_txn_id"


def test_bootstrap_is_deterministic_and_brackets_the_mean() -> None:
    points = [100] * 40 + [75] * 8 + [0] * 2
    crit = [False] * 50
    a = evaluate.bootstrap_interval(points, crit)
    b = evaluate.bootstrap_interval(points, crit)
    assert a == b
    mean = sum(points) / len(points)
    assert a[0] <= mean <= a[1]
    assert evaluate.bootstrap_interval(points, crit, seed=1) != a


def test_holdout_guard_refuses_without_flag() -> None:
    with pytest.raises(SystemExit):
        evaluate.main(["--set", "messy_holdout"])
    with pytest.raises(SystemExit):
        evaluate.main(["--set", "x/holdout/anything.csv"])
    evaluate.check_holdout_guard("messy_dev", False)  # the dev set needs no flag
    evaluate.check_holdout_guard("messy_holdout", True)


def _fake(row: ComplaintRow, run_id: str, emit: object = None) -> object:
    raise RuntimeError("boom")


def test_run_rows_catches_errors_and_scores_zero() -> None:
    row = ComplaintRow(complaint_id="A", customer_id="CUS-00001", received_at=datetime(2026, 9, 1), channel="App chat", text="x")
    runs = evaluate.run_rows([row], _fake, "live", 2)  # type: ignore[arg-type]
    assert runs["A"].error == "RuntimeError: boom"
    scored = evaluate.score_all(evaluate.predictions(runs), {"A": _gold()})
    assert scored.rows[0].points == 0
    assert evaluate.bucket(scored.rows[0], runs["A"], _gold(), None) == "error: RuntimeError"


@pytest.mark.parametrize("name", ["messy_dev", "messy_holdout"])
def test_fixtures_parse_and_labels_follow_their_source(name: str) -> None:
    rows_path, labels_path = evaluate.SETS[name]
    rows = evaluate.load_rows(rows_path)
    labels = list(csv.DictReader(labels_path.open(encoding="utf-8")))
    assert len(rows) == len(labels) >= 40
    assert [r.complaint_id for r in rows] == [lab["complaint_id"] for lab in labels]
    assert len({r.complaint_id for r in rows}) == len(rows)
    src_labels = data.labels()
    for r, lab in zip(rows, labels, strict=True):
        assert data.has_customer(r.customer_id)
        if lab["source_id"] in src_labels:  # gold fields other than reply_language are the source row's
            s = src_labels[lab["source_id"]]
            assert lab["matched_txn_id"] == s.matched_txn_id
            assert lab["category"] == s.category
            assert lab["outcome"] == s.outcome
            assert lab["refund_amount_myr"] == f"{s.refund_amount:.2f}"
            assert lab["priority"] == s.priority
            assert lab["route"] == s.route
            assert data.complaint(lab["source_id"]).customer_id == r.customer_id
        assert lab["reply_language"] in ("EN", "MS")


def test_holdout_excludes_dev_sources() -> None:
    dev = {r["source_id"] for r in csv.DictReader(evaluate.SETS["messy_dev"][1].open(encoding="utf-8"))}
    hold = {r["source_id"] for r in csv.DictReader(evaluate.SETS["messy_holdout"][1].open(encoding="utf-8"))}
    assert not dev & hold


def test_template_groups_merge_same_template() -> None:
    texts = [
        "Hello I was charged twice at ShopLah for RM10.00 yesterday",
        "Hello I was charged twice at FoodKu for RM99.50 yesterday",
        "The cash deposit machine at the branch is out of order for a week",
    ]
    g = evaluate.template_groups(texts, 0.9)
    assert g[0] == g[1] != g[2]
