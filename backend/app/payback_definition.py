"""The definition of a CAC payback claim, read from its own words (docs/specs/forecast-and-payback.md section 4.3).

Pure Python, read in the register as the growth basis is: the denominator (net new ARR, revenue growth or gross new ARR), whether the figure is
gross-margin adjusted and the cost basis (sales and marketing, marketing only, sales only). A part the claim does not state is None and is never
assumed equal to the annual calculation's (docs/design/claim-review-simplified-design.md sections 1 and 5). Nothing here reaches a model.
"""
import re
from typing import Dict, Optional

NET_NEW_ARR, REVENUE_GROWTH, GROSS_NEW_ARR = "net new ARR", "revenue growth", "gross new ARR"
GROSS_MARGIN, NO_MARGIN = "gross margin", "none"
TOTAL_SM, MARKETING_ONLY, SALES_ONLY = "sales and marketing", "marketing only", "sales only"
NOT_COMPARED = "definition not compared: "
OFFERED = f"{NET_NEW_ARR} and {REVENUE_GROWTH}"

_DENOMINATORS = (
    (NET_NEW_ARR, re.compile(r"(?i)\bnet[- ]new\s+(?:arr|annual recurring revenue)\b")),
    (REVENUE_GROWTH, re.compile(r"(?i)\b(?:revenue growth|incremental revenue|new revenue|revenue increase|growth in revenue)\b")),
    (GROSS_NEW_ARR, re.compile(r"(?i)\b(?:gross[- ]new|new)\s+(?:arr|annual recurring revenue)\b")),
)
_MARGIN_NONE = re.compile(r"(?i)\b(?:unadjusted|not (?:gross[- ])?margin[- ]adjusted|revenue[- ]based|before (?:gross )?margin|without (?:gross )?margin)\b")
_MARGIN = re.compile(r"(?i)\bgross[- ]margin\b|\bmargin[- ]adjusted\b|\bgross profit\b")
_COSTS = (
    (TOTAL_SM, re.compile(r"(?i)\bsales\s*(?:and|&|/)\s*marketing\b|\bs\s*&\s*m\b")),
    (MARKETING_ONLY, re.compile(r"(?i)\bmarketing[- ](?:spend|only|expenses?|costs?)\b|\bpaid (?:marketing|acquisition)\b|\bad(?:vertising)? spend\b")),
    (SALES_ONLY, re.compile(r"(?i)\bsales (?:only|costs?|expenses?|spend)\b")),
)


def claimed_definition(text: Optional[str]) -> Dict[str, Optional[str]]:
    """{"denominator", "margin", "cost"} of a payback claim's words; None for a part it does not state."""
    text = text or ""
    first = lambda table: next((name for name, rx in table if rx.search(text)), None)  # noqa: E731
    margin = NO_MARGIN if _MARGIN_NONE.search(text) else GROSS_MARGIN if _MARGIN.search(text) else None
    return {"denominator": first(_DENOMINATORS), "margin": margin, "cost": first(_COSTS)}


def compare(claimed: Dict[str, Optional[str]], offered: Dict) -> Optional[str]:
    """None when the claim's definition matches the annual calculation (`offered`: {"denominators", "margin", "cost"}); else the closed reason it
    is not compared. A part the claim does not state comes first; a scope the S&M line does not name is never taken for total S&M."""
    unstated = [name for name, key in (("denominator", "denominator"), ("gross margin treatment", "margin"), ("cost basis", "cost"))
                if claimed[key] is None]
    if unstated:
        return f"{NOT_COMPARED}the claim does not state its {', '.join(unstated)}"
    if offered["cost"] not in (TOTAL_SM, MARKETING_ONLY, SALES_ONLY):
        return f"{NOT_COMPARED}the scope of the S&M line is not known"
    if claimed["denominator"] not in offered["denominators"]:
        return f"{NOT_COMPARED}the claim uses {claimed['denominator']}; the annual calculation offers {OFFERED}"
    if claimed["margin"] != offered["margin"]:
        return f"{NOT_COMPARED}the claim is not gross margin adjusted; the annual calculation is"
    if claimed["cost"] != offered["cost"]:
        return f"{NOT_COMPARED}the claim states {claimed['cost']}; the S&M line holds {offered['cost']}"
    return None
