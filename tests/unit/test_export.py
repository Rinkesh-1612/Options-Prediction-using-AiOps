"""Unit tests for the export stage (no ClickHouse needed)."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from optpred.data import export


class FakeCH:
    """Stands in for ClickHouse: canned TSV counts, writes a real Parquet file."""

    def __init__(self, tsv: str = "", rows: int = 0) -> None:
        self.tsv, self.rows = tsv, rows

    def text(self, sql: str) -> str:
        return self.tsv

    def to_file(self, sql: str, path) -> None:
        assert "readonly" not in sql  # readonly is a URL setting, not SQL
        pq.write_table(pa.table({"ts_ns": list(range(self.rows))}), path)


def test_day_counts_parses_tsv():
    ch = FakeCH("2026-10-14\t1820116\n2026-10-15\t1904073\n")
    assert export.day_counts(ch, "opt_tape", "2026-10-14", "2026-10-15") == {
        "2026-10-14": 1820116,
        "2026-10-15": 1904073,
    }


def test_export_day_verifies_row_count(tmp_path):
    assert export.export_day(FakeCH(rows=5), "opt_tape", "2026-10-15", 5, tmp_path) == 5
    assert (tmp_path / "opt_tape" / "2026-10-15.parquet").exists()


def test_export_day_rejects_short_file(tmp_path):
    with pytest.raises(export.ExportError):
        export.export_day(FakeCH(rows=4), "opt_tape", "2026-10-15", 5, tmp_path)
    assert not list((tmp_path / "opt_tape").iterdir())  # nothing half-written left behind


def test_runlog_journals_success_and_failure(tmp_path, monkeypatch):
    import json

    from optpred.common import runlog

    monkeypatch.chdir(tmp_path)

    def ok(argv, summary):
        summary["rows"] = 7
        return 0

    assert runlog.run("demo", ok, []) == 0
    assert runlog.run("demo", lambda a, s: 1, []) == 1
    recs = [json.loads(x) for x in (tmp_path / "runs" / "runs.jsonl").read_text().splitlines()]
    assert [r["status"] for r in recs] == ["ok", "failed"]
    assert recs[0]["summary"] == {"rows": 7}
    assert all((tmp_path / r["log"]).exists() for r in recs)
