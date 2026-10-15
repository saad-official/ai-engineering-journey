"""Lab 06 - structured output: getting a typed object out of a model, and finding out when
"valid" still means "wrong".

The roadmap's interview question for this lab: what is the difference between JSON mode,
JSON schema (structured outputs) and tool calling, and when do you use each? This lab sends
the same 8 invoices through all three (plus a no-help baseline) and measures the answer
instead of reciting it. See extract.py for the four modes side by side.

Sections:
  S. shape     Pydantic's raw schema vs a strict-mode-safe one (schema_shape.py), sent for
               real. If a variant is rejected, leave-one-out finds which rule mattered. This
               is llm-kit's `to_provider_schema`, rediscovered - now you know WHY it exists.
  M. matrix    8 documents x 4 modes, each with at most ONE repair. Every output goes
               through three separate checks (validate.py): schema, semantic, accuracy.
  C. cost      what the schema adds to every call's input bill, per channel.

Run:
    uv run main.py                          # Groq, ~35-45 calls, several minutes (TPM)
    uv run main.py --dry-run                # the plan + schema transform; calls NOTHING
    uv run main.py --doc 7                  # one document, all modes, full detail
    uv run main.py --modes json_schema,tool --skip-schema-shape
    uv run main.py --provider both          # the portability question

NO CACHE. Outputs at temperature 0 still vary (lab 03), and the variation is data. What is
written to runs/ is provenance: every raw output, error, repair and usage block.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from common import (
    DEFAULT_CALL_TOKENS,
    MAX_TOKENS,
    MIN_SECONDS_BETWEEN_CALLS,
    TEMPERATURE,
    WORKSPACE_ENV,
    Provider,
    Settings,
    build_provider,
    call_cost,
)
from documents import DOCS, SCHEMA_PROBE_TEXT, Doc, get_doc
from extract import MODES, Outcome, Reply, build_request, extract, grade, send
from models import Invoice
from schema_shape import RULES, changes_per_rule, diff, to_strict_schema
from validate import check_schema

# Windows console is cp1252 by default; doc 6 is German and model output is anything.
# Lab 04's first run died on U+202F inside print() after the API work had succeeded.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNS_DIR = Path(__file__).parent / "runs"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)
GROQ_TEMPLATE_TOKENS = 71  # exp-002: Groq's constant chat-template overhead

RAW_SCHEMA: dict[str, Any] = Invoice.model_json_schema()
STRICT_SCHEMA: dict[str, Any] = to_strict_schema(RAW_SCHEMA)


def short(text: str | None, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


# ---------------------------------------------------------------- S. schema shape


@dataclass
class ShapeProbe:
    variant: str
    accepted: bool
    output_valid: bool | None  # None = nothing to validate (rejected or truncated)
    reply: Reply


def print_schema_changes() -> None:
    """Offline: also runs in --dry-run, because it needs no provider."""
    raw_n, strict_n = len(json.dumps(RAW_SCHEMA)), len(json.dumps(STRICT_SCHEMA))
    print(f"  raw    Invoice.model_json_schema()   {raw_n:>5} chars (~{raw_n // 4} tokens)")
    print(f"  strict to_strict_schema(raw)          {strict_n:>5} chars (~{strict_n // 4} tokens)")
    print("  changes, each attributed to the rule that made it:")
    for name, lines in changes_per_rule(RAW_SCHEMA):
        print(f"    {name:<15} {len(lines):>3} change(s)")
        for line in lines[:3]:
            print(f"        {short(line, 90)}")
        if len(lines) > 3:
            print(f"        ... {len(lines) - 3} more (full diff in the transcript)")


def shape_probe(client: OpenAI, p: Provider, variant: str, schema: dict) -> ShapeProbe:
    reply = send(client, p, build_request("json_schema", SCHEMA_PROBE_TEXT, schema))
    # A Groq `failed_generation` 400 means the schema WAS accepted and the model then
    # failed to follow it - a different finding from "schema rejected".
    accepted = reply.error is None or reply.failed_generation is not None
    valid = None
    if reply.error is None and reply.finish_reason != "length":
        valid = check_schema(reply.content)[1] is not None
    probe = ShapeProbe(variant, accepted, valid, reply)
    verdict = "accepted" if accepted else "REJECTED"
    tail = f"output valid: {valid}" if accepted else short(reply.error, 140)
    print(f"    {variant:<26} {verdict:<9} {tail}")
    return probe


def section_shape(client: OpenAI, p: Provider) -> list[ShapeProbe]:
    print("\n=== S. shape: Pydantic's raw schema vs the strict-safe one, sent for real ===")
    print_schema_changes()
    print("  json_schema mode, strict: true, on a tiny probe invoice:")
    raw = shape_probe(client, p, "raw pydantic", RAW_SCHEMA)
    full = shape_probe(client, p, "strict (all 5 rules)", STRICT_SCHEMA)
    probes = [raw, full]
    if raw.accepted and full.accepted:
        print(
            f"  {p.name} accepted Pydantic's raw schema as-is, so no rule was NEEDED here.\n"
            "  The transform still pays for itself in tokens (fewer titles) and portability:\n"
            "  run --provider both before concluding it is unnecessary."
        )
        return probes
    print("  leave-one-out: all rules except one. Which removal breaks (or fixes) it?")
    for name in RULES:
        drop = shape_probe(client, p, f"without {name}", to_strict_schema(RAW_SCHEMA, skip=name))
        probes.append(drop)
        if full.accepted and not drop.accepted:
            print(f"      -> {name} is REQUIRED on {p.name}")
        elif not full.accepted and drop.accepted:
            print(f"      -> {name} is HARMFUL on {p.name}: removing it fixed the request")
    if not full.accepted:
        print(
            "  The strict schema itself was rejected: read the error above - the five\n"
            "  rules are not the whole story for this provider."
        )
    return probes


# ---------------------------------------------------------------- M. the matrix


def section_matrix(client: OpenAI, p: Provider, docs: list[Doc], modes: list[str]) -> list[Outcome]:
    n = len(docs) * len(modes)
    print(f"\n=== M. matrix: {len(docs)} doc(s) x {len(modes)} mode(s) = {n} first tries ===")
    print("  documents outer, modes inner, so provider drift over the run is spread across")
    print("  all modes instead of landing on whichever ran last (same idea as lab 05's S,N,S,N)")
    outcomes: list[Outcome] = []
    for doc in docs:
        print(f"\n  doc {doc.id}: {doc.title}  [catches: {doc.catches}]")
        for mode in modes:
            out = grade(extract(client, p, mode, doc.id, doc.text, STRICT_SCHEMA), doc)
            outcomes.append(out)
            last = out.attempts[-1].reply
            u = out.attempts[0].reply.usage or {}
            line = f"    {mode:<12} {out.status:<10}"
            if out.schema_valid:
                sem = "ok" if not out.violations else f"{len(out.violations)} violation(s)"
                line += f" acc {out.accuracy:.2f}  semantic {sem}"
                if out.invented:
                    line += f"  INVENTED {','.join(out.invented)}"
                if out.reading:
                    line += f"  reading: {out.reading}"
                if out.injection_landed is not None:
                    line += f"  injection {'LANDED' if out.injection_landed else 'resisted'}"
            elif last.error and last.failed_generation is None:
                line += f" {short(last.error, 80)}"
            elif out.status == "invalid":
                line += f" {short(out.attempts[-1].schema_error, 80)}"
            if u:
                line += f"  (in {u.get('prompt_tokens')} out {u.get('completion_tokens')})"
            print(line)
    return outcomes


# ---------------------------------------------------------------- C. schema cost


def section_cost(
    client: OpenAI, p: Provider, doc: Doc, outcomes: list[Outcome], modes: list[str]
) -> dict[str, int | None]:
    """prompt_tokens is fixed before decoding starts, so it does not depend on max_tokens -
    which means the matrix's first tries ALREADY measured every mode's input on this doc.
    Re-sending them at max_tokens=1 (lab 04 section G) would buy the same numbers twice.
    Only the baseline the matrix never sends - no schema anywhere - needs its own call."""
    print(f"\n=== C. cost: what the schema adds to every call (doc {doc.id}) ===")
    bare = send(client, p, build_request("bare", doc.text, STRICT_SCHEMA, max_tokens=1))
    base = (bare.usage or {}).get("prompt_tokens")
    rows: dict[str, int | None] = {"bare": base}
    where = {
        "bare": "nowhere: json_schema's exact messages minus response_format",
        "prompt": "system message text",
        "json_object": "system message text (+ the json_object flag)",
        "json_schema": "response_format - billed only if the provider renders it in",
        "tool": "tools[0].parameters (+ the provider's tool framing, lab 04)",
    }
    for mode in modes:
        first = next((o for o in outcomes if o.doc_id == doc.id and o.mode == mode), None)
        usage = first.attempts[0].reply.usage if first else None
        rows[mode] = (usage or {}).get("prompt_tokens")
    print(f"  {'variant':<12} {'prompt_tokens':>13} {'vs bare':>8}  where the schema travelled")
    for name, tokens in rows.items():
        if tokens is None:
            err = bare.error if name == "bare" else "no usage (mode failed or not run)"
            print(f"  {name:<12} {'n/a':>13} {'':>8}  {short(err, 70)}")
            continue
        delta = "-" if name == "bare" or base is None else f"{tokens - base:+d}"
        print(f"  {name:<12} {tokens:>13} {delta:>8}  {where[name]}")
    print("  Paid on EVERY call, and again on a repair (the whole conversation is re-sent).")
    return rows


# ---------------------------------------------------------------- reports


def print_summary(outcomes: list[Outcome], providers: dict[str, Provider]) -> None:
    print("\n=== summary: per provider x mode (accuracy counts a failed doc as 0) ===")
    head = (
        f"  {'provider/mode':<20} {'N':>2} {'err':>3} {'json':>4} {'1st':>4} {'+rep':>4} "
        f"{'trunc':>5} {'sem':>4} {'acc':>5} {'inv':>4} {'inj':>5} {'in/out':>11} {'cost $':>9}"
    )
    print(head + "\n  " + "-" * (len(head) - 2))
    for prov, mode in dict.fromkeys((o.provider, o.mode) for o in outcomes):
        rows = [o for o in outcomes if o.provider == prov and o.mode == mode]
        errs = [o for o in rows if o.status == "api_error"]
        label = f"{prov}/{mode}"
        if len(errs) == len(rows):
            print(f"  {label:<20} unsupported: {short(errs[0].attempts[0].reply.error, 90)}")
            continue
        firsts = [o.attempts[0].reply.usage for o in rows if o.attempts[0].reply.usage]
        mean_in = statistics.mean(u["prompt_tokens"] or 0 for u in firsts) if firsts else 0
        mean_out = statistics.mean(u["completion_tokens"] or 0 for u in firsts) if firsts else 0
        cost = sum(call_cost(providers[prov], a.reply.usage) for o in rows for a in o.attempts)
        inj = [o.injection_landed for o in rows if o.injection_landed is not None]
        inj_s = "-" if not inj else ("LAND" if any(inj) else "no")
        print(
            f"  {label:<20} {len(rows):>2} {len(errs):>3} "
            f"{sum(o.attempts[0].is_json for o in rows):>4} "
            f"{sum(o.status == 'first_try' for o in rows):>4} "
            f"{sum(o.schema_valid for o in rows):>4} "
            f"{sum(o.status == 'truncated' for o in rows):>5} "
            f"{sum(o.schema_valid and not o.violations for o in rows):>4} "
            f"{statistics.mean(o.accuracy for o in rows):>5.2f} "
            f"{sum(len(o.invented) for o in rows):>4} {inj_s:>5} "
            f"{mean_in:>5.0f}/{mean_out:<5.0f} {cost:>9.6f}"
        )
    print(
        "  json = first try was valid JSON | 1st = schema-valid first try | +rep = after the\n"
        "  one repair | sem = schema-valid AND arithmetic agrees (doc 4 as stated CANNOT pass)\n"
        "  inv = invented values | inj = doc 7 injection | in/out = mean tokens, first tries"
    )


def print_grid(outcomes: list[Outcome], docs: list[Doc], modes: list[str]) -> None:
    for prov in dict.fromkeys(o.provider for o in outcomes):
        print(f"\n  per document ({prov}); * = semantic violation, ! = invented value")
        print(f"  {'doc':<5}" + "".join(f"{m:>13}" for m in modes))
        for doc in docs:
            cells = []
            for mode in modes:
                key = (prov, mode, doc.id)
                o = next(x for x in outcomes if (x.provider, x.mode, x.doc_id) == key)
                tag = {"first_try": "1st", "repaired": "rep"}.get(o.status, o.status[:5])
                cell = f"{tag} {o.accuracy:.2f}" if o.schema_valid else tag
                cells.append(cell + ("*" if o.violations else "") + ("!" if o.invented else ""))
            print(f"  {doc.id:<5}" + "".join(f"{c:>13}" for c in cells))
        for doc in (d for d in docs if d.readings or d.injected):
            picks = [o for o in outcomes if o.provider == prov and o.doc_id == doc.id]
            seen = ", ".join(f"{o.mode}={_probe_result(o)}" for o in picks)
            print(f"  doc {doc.id} ({doc.title}): {seen}")


def _probe_result(o: Outcome) -> str:
    """What docs 4, 7 and 8 exist to find out, in one word or two."""
    if not o.schema_valid:
        return o.status
    if o.injection_landed is not None:
        return "LANDED" if o.injection_landed else "resisted"
    return o.reading or "-"


def print_detail(outcomes: list[Outcome], doc: Doc) -> None:
    print(f"\n=== detail: doc {doc.id} - {doc.title} ===\n  catches: {doc.catches}")
    for o in (x for x in outcomes if x.doc_id == doc.id):
        print(f"\n  --- {o.provider}/{o.mode}: {o.status}")
        for a in o.attempts:
            r = a.reply
            print(f"    attempt {a.n}: finish={r.finish_reason} usage={r.usage} {r.seconds:.2f}s")
            if r.error:
                print(f"      error: {short(r.error, 300)}")
            if r.reasoning:
                print(f"      reasoning: {short(r.reasoning, 300)}")
            if a.raw:
                print(f"      raw: {short(a.raw, 600)}")
            if a.schema_error:
                print("      schema error (sent back in the repair turn):")
                print("        " + a.schema_error.replace("\n", "\n        "))
        if not o.schema_valid:
            continue
        got = Invoice.model_validate(o.invoice)
        for v in o.violations:
            print(f"    semantic: {v}")
        for f, score in o.scores.items():
            mark = "ok " if score == 1 else f"{score:.2f}"
            exp_v, got_v = getattr(doc.expected, f), getattr(got, f)
            if f == "line_items":
                exp_v, got_v = f"{len(exp_v)} lines", f"{len(got_v)} lines"
            exp_s, got_s = short(str(exp_v), 34), short(str(got_v), 34)
            print(f"    {mark} {f:<15} expected {exp_s:<36} got {got_s}")


# ---------------------------------------------------------------- transcript, dry run, main


def write_transcript(
    p: Provider,
    started: str,
    shape: list[ShapeProbe],
    outcomes: list[Outcome],
    cost: dict[str, int | None],
) -> Path:
    """Provenance, not a cache: never read back. Same contract as labs 03-05."""
    RUNS_DIR.mkdir(exist_ok=True)
    payload = {
        "lab": "06-structured",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "provider": p.name,
        "model": p.model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "raw_schema": RAW_SCHEMA,
        "strict_schema": STRICT_SCHEMA,
        "schema_diff": diff(RAW_SCHEMA, STRICT_SCHEMA),
        "shape_probes": [asdict(s) for s in shape],
        "schema_cost_prompt_tokens": cost,
        "outcomes": [asdict(o) for o in outcomes],
    }
    stamp = started.replace("-", "").replace(":", "").split(".")[0].replace("+0000", "")
    path = RUNS_DIR / f"{stamp}-{p.name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def dry_run(
    names: list[str], have: dict[str, bool], docs: list[Doc], modes: list[str], skip_shape: bool
) -> None:
    """The plan and the (offline) schema transform. No network call: MEASURES NOTHING."""
    print("\n=== --dry-run: the plan only. No network calls, no measurements. ===\n")
    first = len(docs) * len(modes)
    s_min, s_max = (0, 0) if skip_shape else (2, 2 + len(RULES))
    lo, hi = s_min + first + 1, s_max + 2 * first + 1
    keys = ", ".join(f"{n} (key in .env: {'yes' if have[n] else 'NO'})" for n in names)
    print(f"  providers    {keys}")
    print(f"  docs         {', '.join(str(d.id) for d in docs)}   modes  {', '.join(modes)}")
    if not skip_shape:
        print(f"  S shape      2 calls (raw, strict); up to {s_max} if one is rejected")
    print(f"  M matrix     {first} first tries + up to {first} repairs (only on a schema failure)")
    print("  C cost       1 call (bare, max_tokens=1); the other rows reuse the matrix's usage")
    print(f"  per provider {lo} calls minimum, {hi} maximum; x{len(names)} provider(s)")
    longest = max(len(json.dumps(build_request("prompt", d.text, STRICT_SCHEMA))) for d in docs)
    est_in = longest // 4 + GROQ_TEMPLATE_TOKENS
    print(f"  input/call   ~{est_in} tokens (longest doc, prompt mode, chars/4 + 71; a repair ~2x)")
    for n in names:
        p = build_provider(Settings(), n)
        if p is None:
            continue
        worst = hi * (2 * est_in * p.price_in_per_m + MAX_TOKENS * p.price_out_per_m) / 1e6
        pace = "paced by RPM only (TPM unknown)"
        if p.tpm:
            per_min = p.tpm / DEFAULT_CALL_TOKENS
            pace = f"TPM {p.tpm} -> ~{per_min:.0f} calls/min, ~{lo / per_min:.0f}+ min"
        print(f"  {n:<12} upper-bound cost ${worst:.4f} at paid rates (free tier: $0); {pace}")
    print(f"  pacing       >= {MIN_SECONDS_BETWEEN_CALLS}s between starts; max_tokens={MAX_TOKENS}")
    print("\n  The schema transform is offline, so it can be shown without a call:")
    print_schema_changes()


def run_provider(p: Provider, docs: list[Doc], modes: list[str], skip_shape: bool) -> list[Outcome]:
    started = datetime.now(UTC).isoformat()
    print(f"\n######## {p.name}  model={p.model}  started {started}")
    print(f"  max_tokens={MAX_TOKENS}  temperature={TEMPERATURE}  no cache: every number is live")
    # max_retries=0, same as labs 03-05: an SDK retry is a call nobody sees, and its cost
    # and latency would be folded silently into this one. send() handles 429 once, visibly.
    client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=HTTP_TIMEOUT, max_retries=0)
    shape = [] if skip_shape else section_shape(client, p)
    outcomes = section_matrix(client, p, docs, modes)
    cost = section_cost(client, p, docs[0], outcomes, modes)
    path = write_transcript(p, started, shape, outcomes, cost)
    print(f"\n  transcript -> {path}")
    return outcomes


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab 06: structured output, measured.")
    ap.add_argument("--provider", choices=("groq", "gemini", "both"), default="groq")
    ap.add_argument("--modes", default=",".join(MODES), help=f"comma list of {', '.join(MODES)}")
    ap.add_argument("--doc", type=int, help="one document (1-8), with full detail")
    ap.add_argument("--skip-schema-shape", action="store_true", help="skip section S")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; measure nothing")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not modes or any(m not in MODES for m in modes):
        ap.error(f"--modes must be a comma list drawn from {', '.join(MODES)}")
    try:
        docs = [get_doc(args.doc)] if args.doc is not None else DOCS
    except KeyError as exc:
        ap.error(exc.args[0])

    names = ["groq", "gemini"] if args.provider == "both" else [args.provider]
    settings = Settings()
    providers = {n: p for n in names if (p := build_provider(settings, n)) is not None}
    if args.dry_run:
        dry_run(names, {n: n in providers for n in names}, docs, modes, args.skip_schema_shape)
        return
    if not providers:
        print(f"No API key for {', '.join(names)} in {WORKSPACE_ENV}. Nothing to run.")
        return

    print("Lab 06 - structured output: prompt vs json_object vs json_schema vs tool")
    outcomes: list[Outcome] = []
    for p in providers.values():
        outcomes += run_provider(p, docs, modes, args.skip_schema_shape)
    print_summary(outcomes, providers)
    print_grid(outcomes, docs, modes)
    if args.doc is not None:
        print_detail(outcomes, docs[0])
    print(
        "\n  Explain it back (CLAUDE.md rule 2):\n"
        "   1. Pick one output that was schema-valid but semantically invalid. Which layer\n"
        "      caught it, and why could the layer before it never have caught it?\n"
        "   2. Section S: which rule did this provider actually need, and what does the\n"
        "      provider DO with the schema that makes that rule necessary?\n"
        "   3. Doc 4: the model either copied or corrected the vendor's total. Who should\n"
        "      decide which is right, and where in this code would that decision live?"
    )


if __name__ == "__main__":
    main()
