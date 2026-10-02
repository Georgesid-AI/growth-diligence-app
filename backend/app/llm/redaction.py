"""Pseudonymisation of customer / company identifiers and segment names.

Nothing that identifies a real customer may reach the provider. Before a payload
leaves the server every identifier is swapped for a stable per-run pseudonym
(`Customer_01`, `Customer_02`, ...) and every segment name for a stable label
(`Segment A`, `Segment B`, ...). The mapping lives in Mongo (`pseudonym_map`,
keyed by run_id) and is never included in an outbound payload.

Matching is whole-token: an identifier is replaced only where it stands as its
own word, never inside a longer word, a date or a number ("12" leaves "2026-12"
alone). Engine field-name keys are never rewritten; the only dict keys that are
data, the children of a segment container, are relabelled by exact match.

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

# Containers whose dict keys are segment names rather than field names.
SEGMENT_CONTAINERS = {"by_segment", "segments"}

_CUSTOMER_PREFIX = "Customer_"
_SEGMENT_PREFIX = "Segment "


def _pseudonym(index: int) -> str:
    return f"{_CUSTOMER_PREFIX}{index:02d}"


def _segment_label(index: int) -> str:
    """1 -> "Segment A", 26 -> "Segment Z", 27 -> "Segment AA"."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return f"{_SEGMENT_PREFIX}{letters}"


# Dates, numbers, percentages and ranges. Never rewritten, whatever the mapping says.
_NUMERIC_LIKE = re.compile(r"[\d\s.,:/%+\-]+")


def _is_numeric_like(text: str) -> bool:
    return bool(_NUMERIC_LIKE.fullmatch(text))


def _token_pattern(tokens: Iterable[str]) -> "re.Pattern | None":
    """One regex matching any token as a whole word, longest first.

    A token is not matched inside a longer word, nor where it would be glued to a
    neighbouring number by a date or range separator ("2026-12", "1.12", "12-3").
    """
    usable = sorted({t for t in tokens if t and not _is_numeric_like(t)}, key=len, reverse=True)
    if not usable:
        return None
    body = "|".join(re.escape(t) for t in usable)
    return re.compile(rf"(?<!\w)(?<!\d[-./:,])(?:{body})(?!\w)(?![-./:,]\d)")


def substitute(text: str, replacements: Dict[str, str]) -> str:
    """Replace whole-token occurrences of each key of `replacements` in `text`."""
    pattern = _token_pattern(replacements)
    if pattern is None:
        return text
    return pattern.sub(lambda m: replacements[m.group(0)], text)


def collect_segment_names(payload: Any) -> List[str]:
    """Every dict key under a segment container, in a stable order."""
    found = set()

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, dict):
            if key in SEGMENT_CONTAINERS:
                found.update(k for k in node if isinstance(k, str) and k.strip())
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)

    walk(payload)
    return sorted(found)


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

    new = [i for i in collect_identifiers(payload) if i not in mapping]
    new_segments = [s for s in collect_segment_names(payload) if s not in mapping and s not in new]
    if new or new_segments:
        customers = sum(1 for v in mapping.values() if v.startswith(_CUSTOMER_PREFIX))
        for offset, real in enumerate(new, start=customers + 1):
            mapping[real] = _pseudonym(offset)
        segments = sum(1 for v in mapping.values() if v.startswith(_SEGMENT_PREFIX))
        for offset, real in enumerate(new_segments, start=segments + 1):
            mapping[real] = _segment_label(offset)
        await db[PSEUDONYM_COLLECTION].update_one(
            {"run_id": run_id},
            {"$set": {"run_id": run_id, "mapping": mapping}},
            upsert=True,
        )
    return mapping


def redact(payload: Any, mapping: Dict[str, str]) -> Any:
    """Deep-copy `payload` with every real identifier replaced by its pseudonym.

    String values are matched whole-token, so an identifier embedded in a
    sentence ("Acme Corp churned") is caught, but one inside a longer word, a
    date or a number is not. Dict keys are field names and are left alone,
    except the children of a segment container, which are relabelled by exact
    match.
    """
    if not mapping:
        return payload
    pattern = _token_pattern(mapping)

    def scrub(text: str) -> str:
        return pattern.sub(lambda m: mapping[m.group(0)], text) if pattern else text

    def walk(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            relabel = key in SEGMENT_CONTAINERS
            return {(mapping.get(k, k) if relabel else k): walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, key) for item in node]
        if isinstance(node, str):
            return scrub(node)
        return node

    return walk(payload)


def restore(text: str, mapping: Dict[str, str]) -> str:
    """Put real identifiers back into model output, server-side."""
    if not mapping:
        return text
    return substitute(text, {v: k for k, v in mapping.items()})


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
    Matched the same way `redact` replaces, so anything `redact` would have
    caught is reported. A numeric-like identifier is never rewritten and is not
    checked: it cannot be told apart from a figure.
    """
    if not mapping:
        return []
    blob = _flatten(outbound)
    return [real for real in mapping
            if real and (p := _token_pattern([real])) is not None and p.search(blob)]


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


# A hyphen is only a minus sign when nothing word-like precedes it. Inside a
# word or a date it is a separator: "sub-1%" is 1, "non-12-month" is 12, and
# "2027-12-31" is 2027, 12, 31 - not -1, -12 and -31. A genuine negative still
# reads as one ("-5", "a drop of -5"), because a space or start-of-string is
# not word-like.
#
# Two alternatives rather than an optional sign: the signed form carries the
# stricter lookbehind, while the unsigned form only has to avoid starting in
# the middle of a number, so digits after an underscore ("..._12m") still count.
_NUMBER_RE = re.compile(r"(?<![\w.])-\d[\d,]*\.?\d*|(?<![\d.])\d[\d,]*\.?\d*")


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
