import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teratai import db, export, pipeline
from teratai.models import CSV_COLUMNS, ComplaintRow

from .conftest import complaint

IDS = ["CMP-00165", "CMP-00244", "CMP-00387"]


def _store(cid: str, run: str = "exp") -> dict[str, str]:
    row = ComplaintRow(**complaint(cid))
    d = pipeline.process_complaint(row, run)
    pipeline.store(row, d)
    return d.to_csv_row()


def _parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def test_export_matches_decisions(client: TestClient) -> None:
    expected = {cid: _store(cid) for cid in IDS}
    _store("CMP-00289", "other")
    r = client.get("/api/export/predictions", params={"run_id": "exp"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-rows"] == "3"
    assert "predictions-exp.csv" in r.headers["content-disposition"]
    got = _parse(r.content.decode("utf-8"))
    assert list(got[0].keys()) == CSV_COLUMNS
    assert [g["complaint_id"] for g in got] == sorted(IDS)
    for g in got:
        assert g == expected[g["complaint_id"]]


def test_unchanged_after_human_action(client: TestClient) -> None:
    exp = _store("CMP-00244")
    with db.connect() as con:
        con.execute(
            "UPDATE cases SET human_action=?, case_state='approved' WHERE run_id='exp'",
            (json.dumps({"reply_text": "edited RM600.00"}),),
        )
    got = _parse(client.get("/api/export/predictions", params={"run_id": "exp"}).text)
    assert got == [exp]


def test_missing_run_id_and_empty(client: TestClient) -> None:
    assert client.get("/api/export/predictions").status_code == 422
    r = client.get("/api/export/predictions", params={"run_id": "nope"})
    assert r.status_code == 200 and r.headers["x-rows"] == "0"
    assert r.text.strip() == ",".join(CSV_COLUMNS)


def test_cli_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exp = {cid: _store(cid) for cid in IDS}
    out = tmp_path / "p.csv"
    assert export.main(["--run", "exp", "--out", str(out)]) == 0
    assert "wrote 3 rows" in capsys.readouterr().out
    with out.open(newline="", encoding="utf-8-sig") as fh:
        got = list(csv.DictReader(fh))
    assert len(got) == 3
    assert all(g == exp[g["complaint_id"]] for g in got)
    assert export.main(["--run", "none", "--out", str(out)]) == 1
