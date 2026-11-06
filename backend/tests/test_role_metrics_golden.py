"""Golden output of the engine on the map: `role_metrics` for the synthetic yearly P&L and the synthetic monthly report of test_role_engine.py.

Stored results carry the contract version they were computed under. If the engine's output changes (a value, a reason string, a cell, a note, a
flag) and CONTRACT_VERSION is not bumped, stored results silently disagree with a re-run. This test fails then, so the change is either undone
or the contract is bumped (schemas/metrics.py, test_interface_contracts.py, docs/specs/interface-contracts.md; CLAUDE.md rule 23).

Regenerate the golden file for the current contract (after bumping it), from backend/:

    GOLDEN_REGENERATE=1 .venv/bin/python -m pytest tests/test_role_metrics_golden.py

Review the diff of tests/golden/role_metrics_<contract>.json before committing. Synthetic fixtures only; no client data."""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from schemas.metrics import CONTRACT_VERSION  # noqa: E402
from test_column_classes import board_pack, files_of, smap_of, sheet_of  # noqa: E402
from test_role_engine import monthly_report, run, yearly_pnl  # noqa: E402
from app import series  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / f"role_metrics_{CONTRACT_VERSION}.json"
REGENERATE = "regenerate with: GOLDEN_REGENERATE=1 .venv/bin/python -m pytest tests/test_role_metrics_golden.py (from backend/)"


def board_pack_files() -> list:
    """The board-pack layout (tests/test_column_classes.py): TOTAL year columns, months with a Qn subtotal after every third, datetime headers."""
    grid, layout, months, quarters, years, last = board_pack()
    text, _ = sheet_of(grid)
    fmap = series.attach({"map_version": 1, "kind": "sheet", "figures": [], "sheets": [smap_of(last)]}, text)
    return files_of({"fmap": fmap})


def produce() -> dict:
    """role_metrics of the fixtures, round-tripped through JSON so what is compared is what is stored."""
    out = {"yearly": run(yearly_pnl())["role_metrics"], "monthly": run(monthly_report())["role_metrics"],
           "board_pack": run(board_pack_files(), as_of="2023-12")["role_metrics"]}
    return json.loads(json.dumps(out, sort_keys=True, default=str))


def test_role_metrics_match_the_golden_file_of_this_contract():
    got = produce()
    if os.environ.get("GOLDEN_REGENERATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
        return
    assert GOLDEN.exists(), f"no golden file for contract {CONTRACT_VERSION}; {REGENERATE}"
    assert got == json.loads(GOLDEN.read_text()), (
        f"stored results changed; bump the contract and regenerate the golden file (ENGINE_CONTRACT_VERSION is CONTRACT_VERSION = {CONTRACT_VERSION} "
        f"in schemas/metrics.py); {REGENERATE}")
