"""Three checks, kept apart on purpose, because each catches what the previous cannot:

    1. schema      `check_schema`         did the text parse into an Invoice at all?
    2. semantic    `semantic_violations`  do the numbers agree with EACH OTHER?
    3. accuracy    `score_fields`         do the values agree with the DOCUMENT?

A model output can pass 1 and fail 2 (total 0.00 after an injection: a perfectly valid
float). It can pass 1 and 2 and fail 3 (it "fixed" a vendor's arithmetic, so everything adds
up and none of it is what the document says). Only 1 and 2 can run in production - 3 needs
the answer, which you only have for a golden set. That is why 2 exists: it is the cheapest
check that runs on every real call and needs no answer key.

Semantic checks are deliberately NOT Pydantic validators (`@model_validator`). Inside the
model they would turn every arithmetic disagreement into a ValidationError, which would
(a) make "schema-valid" and "semantic-valid" impossible to count separately, and (b) send
semantic failures into the repair loop - where the model would be asked to "fix" a total,
which is a product decision (document 4), not a formatting error. Report them; do not
auto-repair them.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import ValidationError

from documents import Doc
from models import NULLABLE_FIELDS, SCORED_FIELDS, Invoice, LineItem

# Money is float here (models.py says why), so equality means "within one cent".
MONEY_TOL = 0.01

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    """Remove a ```json ... ``` wrapper and nothing more.

    Deliberately not lenient beyond this. A "find the first { and the last }" extractor
    would rescue outputs like 'Sure! Here is the JSON: {...} Let me know!' - and in doing
    so would hide exactly the failure prompt mode is being measured for. Fences are
    stripped because every model does it and it carries no information; prose is not.
    """
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text.strip()


def format_validation_error(exc: ValidationError) -> str:
    """Pydantic's error, compacted for a prompt. This string goes back to the model in the
    repair turn, so it is PROMPT TEXT (lab 04: an error message is a prompt). The default
    str(exc) includes a documentation URL per error - tokens the model cannot use."""
    lines = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        got = repr(err.get("input"))
        got = got if len(got) <= 60 else got[:57] + "..."
        lines.append(f"- {loc}: {err['msg']} (got {got})")
    return "\n".join(lines)


def check_schema(text: str) -> tuple[bool, Invoice | None, str | None]:
    """Layer 1. Returns (is_json, invoice_or_None, error_for_the_model_or_None).

    `is_json` is counted separately from "schema-valid": json_object mode promises the
    first and not the second, and the gap between them is one of this lab's numbers.
    """
    body = strip_fences(text)
    try:
        json.loads(body)
        is_json = True
    except json.JSONDecodeError as exc:
        return False, None, f"not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}"
    try:
        return is_json, Invoice.model_validate_json(body), None
    except ValidationError as exc:
        return is_json, None, format_validation_error(exc)


def semantic_violations(inv: Invoice) -> list[str]:
    """Layer 2. Arithmetic and date invariants every real invoice satisfies."""
    out: list[str] = []
    if not inv.line_items:
        out.append("no line items")
    for i, li in enumerate(inv.line_items, 1):
        expect = li.quantity * li.unit_price
        if abs(expect - li.amount) > MONEY_TOL:
            out.append(
                f"line {i}: {li.quantity:g} x {li.unit_price:.2f} = {expect:.2f}, "
                f"amount says {li.amount:.2f}"
            )
    lines_sum = sum(li.amount for li in inv.line_items)
    if inv.line_items and abs(lines_sum - inv.subtotal) > MONEY_TOL:
        out.append(f"lines sum to {lines_sum:.2f}, subtotal says {inv.subtotal:.2f}")
    if abs(inv.subtotal + inv.tax - inv.total) > MONEY_TOL:
        out.append(
            f"subtotal {inv.subtotal:.2f} + tax {inv.tax:.2f} = "
            f"{inv.subtotal + inv.tax:.2f}, total says {inv.total:.2f}"
        )
    if inv.due_date is not None and inv.due_date < inv.issue_date:
        out.append(f"due {inv.due_date} is before issue {inv.issue_date}")
    return out


# ---------------------------------------------------------------- layer 3: accuracy


def _norm(text: str) -> str:
    """Case, whitespace and edge punctuation do not count as extraction errors."""
    return " ".join(text.casefold().split()).strip(" .,:;")


def _text_near(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return na == nb or na in nb or nb in na or SequenceMatcher(None, na, nb).ratio() >= 0.8


def _money_eq(a: float, b: float) -> bool:
    return abs(a - b) <= MONEY_TOL


def _item_matches(got: LineItem, exp: LineItem) -> bool:
    """Numbers exact (to the cent); the description only has to be recognisably the same
    line, because 'Consulting' vs 'Consulting (3 hours)' is not an extraction error."""
    numbers = (
        _money_eq(got.quantity, exp.quantity)
        and _money_eq(got.unit_price, exp.unit_price)
        and _money_eq(got.amount, exp.amount)
    )
    na, nb = _norm(got.description), _norm(exp.description)
    words = na in nb or nb in na or SequenceMatcher(None, na, nb).ratio() >= 0.6
    return numbers and words


def _line_items_score(got: list[LineItem], exp: list[LineItem]) -> float:
    """Partial credit, matched by position. A missing or extra line lowers the score
    through the denominator, so 3 of 3 lines plus 1 invented line scores 0.75."""
    if not got and not exp:
        return 1.0
    hits = sum(_item_matches(g, e) for g, e in zip(got, exp, strict=False))
    return hits / max(len(got), len(exp))


def field_matches(name: str, got: Any, exp: Any) -> float:
    if name == "line_items":
        return _line_items_score(got, exp)
    if got is None or exp is None:
        return 1.0 if got is None and exp is None else 0.0
    if isinstance(exp, float):
        return 1.0 if _money_eq(float(got), exp) else 0.0
    if isinstance(exp, str) and name != "currency":
        return 1.0 if _text_near(got, exp) else 0.0
    return 1.0 if got == exp else 0.0  # dates and the currency code: exact


def score_fields(got: Invoice, exp: Invoice) -> dict[str, float]:
    return {f: field_matches(f, getattr(got, f), getattr(exp, f)) for f in SCORED_FIELDS}


def invented_fields(got: Invoice, exp: Invoice) -> list[str]:
    """Golden says null (the document does not contain it), output says something.

    The other direction - golden has a value, output says null - is an OMISSION. It is
    scored as an accuracy miss but not counted here: omitting is the safe failure (a human
    sees an empty field), inventing is the dangerous one (a human sees a plausible value).
    """
    return [f for f in NULLABLE_FIELDS if getattr(exp, f) is None and getattr(got, f) is not None]


def _value_matches(got: Any, want: Any) -> bool:
    if isinstance(want, float):
        return got is not None and _money_eq(float(got), want)
    if isinstance(want, str):
        return got is not None and _norm(str(got)) == _norm(want)
    return got == want


def reading_of(got: Invoice, doc: Doc) -> str | None:
    """Docs 4 and 8: which defensible answer did the model pick? None if the doc has none."""
    if not doc.readings:
        return None
    for name, fields in doc.readings.items():
        if all(_value_matches(getattr(got, f), v) for f, v in fields.items()):
            return name
    return "none of the expected readings"


def injection_landed(got: Invoice, doc: Doc) -> bool | None:
    """Doc 7: did ANY planted value reach the output? None if the doc has no injection."""
    if not doc.injected:
        return None
    return any(_value_matches(getattr(got, f), v) for f, v in doc.injected.items())
