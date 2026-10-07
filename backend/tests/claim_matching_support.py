"""Shared set-up of the claim-matching tests: the synthetic TestCo fixture and a real engine run over
sample_data/ (docs/specs/claim-matching.md section 9). Nothing here touches a network or a database."""
import json
import sys
from functools import lru_cache
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

FIXTURE = BACKEND / "tests" / "fixtures" / "claim_matching" / "testco_claims.json"
SAMPLE = BACKEND.parent / "sample_data"
FILES = {"revenue": "revenue.csv", "pnl": "pnl.csv", "crm": "crm.csv"}


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def engine_results(files: tuple = ("revenue", "pnl", "crm"), as_of_month=None) -> dict:
    """compute_all over the chosen sample files, EUR, no other currency, the as-of month as given."""
    import growth_engine as ge
    import server

    uploads = {}
    for dtype in files:
        df, sheet = server.parse_file((SAMPLE / FILES[dtype]).read_bytes(), FILES[dtype])
        uploads[dtype] = {"file": FILES[dtype], "sheet": sheet, "columns": list(df.columns),
                          "rows": server.df_to_records(df), "mapping": server.suggest_mapping(dtype, list(df.columns))}
    norm = {d: server.normalize(u["rows"], d, u["mapping"]) for d, u in uploads.items()}
    empty = server.pd.DataFrame()
    config = {"reporting_currency": "EUR", "target_arr": 1_000_000, "target_date": "2026-12-31", "fx": {"EUR": 1.0},
              "billing_terms": {}, "default_l": 1, "as_of_month": as_of_month}
    sources = {d: {"file": u["file"], "sheet": u["sheet"]} for d, u in uploads.items()}
    return server.sanitize(ge.compute_all(norm["revenue"], norm.get("crm", empty), norm.get("pnl", empty), config, sources,
                                          files=server.candidate_views(uploads)))
