"""Pseudonymisation of customer / company identifiers.

Nothing that identifies a real customer may reach the provider. Before a payload
leaves the server every identifier is swapped for a stable per-run pseudonym
(`Customer_01`, `Customer_02`, ...). The mapping lives in Mongo (`pseudonym_map`,
keyed by run_id) and is never included in an outbound payload.

The model's returned text is re-substituted server-side before it is stored or
shown, so the dashboard still reads in real names.
"""
import re
from typing import Any, Dict, Iterable, List

PSEUDONYM_COLLECTION = "pseudonym_map"

# Keys whose values are treated as identifiers wherever they appear in the
# computed-results payload.
IDENTIFIER_KEYS = {
    "customer", "customer_id", "customers", "company", "company_name",
    "account", "account_name", "client", "name",
}


def _pseudonym(index: int) -> str:
    return f"Customer_{index:02d}"


def collect_identifiers(payload: Any) -> List[str]:
    """Walk the payload and return every distinct identifier value, in a stable
    order so the same run always yields the same pseudonym assignment."""
    found: List[str] = []
    seen = set()

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        elif isinstance(node, str):
            if key in IDENTIFIER_KEYS and node.strip() and node not in seen:
                seen.add(node)
                found.append(node)

    walk(payload)
    return sorted(found)


async def get_or_create_map(db, run_id: str, payload: Any) -> Dict[str, str]:
    """Return {real_name: pseudonym} for this run, creating it on first use.

    Stored server-side only. Callers must never place this dict, its keys, or
    any value derived from its keys into an outbound payload.
    """
    doc = await db[PSEUDONYM_COLLECTION].find_one({"run_id": run_id}, {"_id": 0})
    mapping: Dict[str, str] = dict(doc["mapping"]) if doc else {}

    identifiers = collect_identifiers(payload)
    new = [i for i in identifiers if i not in mapping]
    if new:
        start = len(mapping) + 1
        for offset, real in enumerate(new):
            mapping[real] = _pseudonym(start + offset)
        await db[PSEUDONYM_COLLECTION].update_one(
            {"run_id": run_id},
            {"$set": {"run_id": run_id, "mapping": mapping}},
            upsert=True,
        )
    return mapping


def redact(payload: Any, mapping: Dict[str, str]) -> Any:
    """Deep-copy `payload` with every real identifier replaced by its pseudonym.

    Replacement is applied to whole strings and to substrings, so an identifier
    embedded in a sentence ("Acme Corp churned") is caught too.
    """
    if not mapping:
        return payload
    # Longest first, so "Acme Corporation" is not half-replaced by "Acme".
    ordered = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)

    def scrub(text: str) -> str:
        for real, pseudo in ordered:
            if real in text:
                text = text.replace(real, pseudo)
        return text

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {scrub(k) if isinstance(k, str) else k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return scrub(node)
        return node

    return walk(payload)


def restore(text: str, mapping: Dict[str, str]) -> str:
    """Put real identifiers back into model output, server-side."""
    if not mapping:
        return text
    reverse = sorted(((v, k) for k, v in mapping.items()), key=lambda kv: len(kv[0]), reverse=True)
    for pseudo, real in reverse:
        text = text.replace(pseudo, real)
    return text


def restore_deep(node: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {k: restore_deep(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [restore_deep(i, mapping) for i in node]
    if isinstance(node, str):
        return restore(node, mapping)
    return node


def find_leaks(outbound: Any, mapping: Dict[str, str]) -> List[str]:
    """Return any real identifier still present in an outbound payload.

    Used as a last-line assertion before the provider call, and by the leak test.
    """
    if not mapping:
        return []
    blob = _flatten(outbound)
    return [real for real in mapping if real and real in blob]


def _flatten(node: Any) -> str:
    out: List[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(k, str):
                    out.append(k)
                walk(v)
        elif isinstance(n, (list, tuple)):
            for i in n:
                walk(i)
        elif isinstance(n, str):
            out.append(n)
        else:
            out.append(str(n))

    walk(node)
    return "\n".join(out)


def iter_pseudonyms(mapping: Dict[str, str]) -> Iterable[str]:
    return mapping.values()


# A hyphen only counts as a minus sign when it does not follow a digit or a
# dot, so "2027-12-31" yields 2027, 12, 31 rather than 2027, -12, -31.
_NUMBER_RE = re.compile(r"(?<![\d.])-?\d[\d,]*\.?\d*")


def numbers_in(node: Any) -> set:
    """Every numeric token reachable in `node`, normalised for comparison.

    Used by the gateway's numeric guard. Digits inside strings count, so a
    payload containing "2026-Q2" contributes 2026 and 2.
    """
    found = set()

    def add(text: str) -> None:
        for match in _NUMBER_RE.findall(text):
            cleaned = match.replace(",", "").rstrip(".")
            if not cleaned or cleaned in {"-", "."}:
                continue
            try:
                value = float(cleaned)
            except ValueError:
                continue
            found.add(_norm(value))

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(k, str):
                    add(k)
                walk(v)
        elif isinstance(n, (list, tuple)):
            for i in n:
                walk(i)
        elif isinstance(n, bool):
            return
        elif isinstance(n, (int, float)):
            found.add(_norm(float(n)))
        elif isinstance(n, str):
            add(n)

    walk(node)
    return found


def _norm(value: float) -> str:
    """Collapse 3.0 and 3 to one token; keep 2 decimals of precision."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
