"""The target of every extraction in this lab: an `Invoice` with its `LineItem`s.

Why an invoice and not a job posting: an invoice has ARITHMETIC. Every line has
quantity x unit_price = amount, the lines sum to the subtotal, subtotal + tax = total. That
makes a second kind of correctness measurable, beyond "does it fit the shape":

    schema-valid    the JSON has the right keys and types       <- Pydantic checks this
    semantic-valid  the numbers agree with each other            <- validate.py checks this
    accurate        the values match what the document says      <- the golden set checks this

A job posting can be schema-valid and wrong in ways only a human can judge. An invoice can be
schema-valid and wrong in ways a 10-line function can catch. That gap is the lesson.

Three modelling decisions, each one visible in the JSON Schema the provider receives:

1. `X | None` for anything a document might not contain. Pydantic turns that into
   `anyOf: [{type: X}, {type: null}]` plus `default: null`. The prompt says "use null when a
   field is absent", so a non-null value where the golden answer has null is an INVENTED
   value, and it can be counted (validate.py). A required `str` would force the model to
   put *something* there - the schema itself would be asking it to make a value up.

2. `float` for money, which is wrong for production and right for this lab. Production
   money is `Decimal` or integer cents: 0.1 + 0.2 != 0.3 in float. But Pydantic emits
   `Decimal` as `anyOf: [{type: number}, {type: string, pattern: <regex>}]`, and a regex
   pattern inside an anyOf is exactly the kind of schema that strict modes reject or
   handle differently per provider. That would be a second schema experiment tangled into
   the first. So: float here, a 0.01 tolerance in every comparison, and a note.

3. No `ConfigDict(extra="forbid")`. With it, Pydantic emits `additionalProperties: false`
   by itself - which would quietly fix the most common strict-mode 400 (see section S in
   main.py) and hide the lesson. It is also a real trade-off, not a free win: "forbid" turns
   a harmless extra key (`"notes": "..."`) into a validation failure and a paid repair call.
   Pydantic's default is to IGNORE extra keys, so that is what this lab measures.

Every `description` below is prompt text. It travels inside the schema to the model, it is
billed as input tokens on every call (main.py section C), and it is the only place the
model learns what "amount" means. Write it for the model, not for a colleague.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

# A closed list, on purpose. With a strict schema the model CANNOT emit "JPY": constrained
# decoding only allows these four strings. If a document is in yen, strict mode forces a
# wrong-but-valid answer, while prompt mode would emit "JPY" and fail validation loudly.
# Which of those two failures you prefer is a product decision (see NOTES.md open questions).
Currency = Literal["USD", "EUR", "GBP", "PKR"]


class LineItem(BaseModel):
    description: str = Field(description="What was billed, as written on the invoice.")
    quantity: float = Field(description="Number of units. 1 if the line has no quantity.")
    unit_price: float = Field(description="Price of one unit, as a plain number.")
    amount: float = Field(
        description="The line total as written. If not written, quantity x unit_price."
    )


class Invoice(BaseModel):
    invoice_number: str | None = Field(
        default=None,
        description="The invoice's own number. null if the document does not state one. "
        "A purchase order or customer reference is NOT an invoice number.",
    )
    issue_date: date = Field(description="Date the invoice was issued, YYYY-MM-DD.")
    vendor_name: str = Field(description="The business that issued the invoice (the seller).")
    currency: Currency = Field(description="ISO 4217 code of the invoice currency.")
    line_items: list[LineItem] = Field(description="Every billed line, in document order.")
    # Deliberately silent on "as stated" vs "corrected": document 4 has a vendor's
    # arithmetic error in it, and the lab records what the model does BY DEFAULT. Writing
    # "as stated" here would be deciding the extraction contract inside the schema.
    subtotal: float = Field(description="Total before tax.")
    tax: float = Field(description="Tax amount. 0 if the document says no tax.")
    total: float = Field(description="Final amount due.")
    due_date: date | None = Field(
        default=None,
        description="Payment due date, YYYY-MM-DD, only if a date is written. null if the "
        "document gives only terms such as 'Net 30' or gives nothing.",
    )


# The fields scored one-by-one against the golden answer (validate.py). `line_items` is
# scored as one field with partial credit, so a document with 3 lines does not outweigh
# the other 8 fields combined.
SCORED_FIELDS: tuple[str, ...] = (
    "invoice_number",
    "issue_date",
    "vendor_name",
    "currency",
    "line_items",
    "subtotal",
    "tax",
    "total",
    "due_date",
)

# Fields whose golden value can be null - the only places an INVENTED value can occur.
NULLABLE_FIELDS: tuple[str, ...] = ("invoice_number", "due_date")
