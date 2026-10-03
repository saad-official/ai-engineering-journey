"""Break-it: is Gemini's thought_signature enforced on the CURRENT turn's tool call?

Step 1 gets a tool call. Step 2 sends the tool result back in the same turn, once with the
signature echoed (what server_v5 does, FIX-8) and once without (what the original would do if
it ever got that far). captures/K showed a stripped signature on a PREVIOUS turn is tolerated.
Run:  uv run python probe_signature.py
"""

import json

from server_v5 import TOOL_SCHEMAS as TOOLS  # no import-time side effects
from run_original import GEMINI_MODEL, gemini

user = {"role": "user", "content": "What is the weather in Lahore in celsius?"}
first = gemini.chat.completions.create(model=GEMINI_MODEL, messages=[user], tools=TOOLS)
call = first.choices[0].message.tool_calls[0]
raw = call.model_dump(exclude_none=True)
print("signature present on call:", "extra_content" in raw)

for label, keep in (("with signature", True), ("signature stripped", False)):
    c = dict(raw)
    if not keep:
        c.pop("extra_content", None)
    msgs = [
        user,
        {"role": "assistant", "content": None, "tool_calls": [c]},
        {"role": "tool", "tool_call_id": call.id,
         "content": json.dumps({"temperature": 31, "unit": "celsius", "location": "Lahore"})},
    ]
    try:
        r = gemini.chat.completions.create(model=GEMINI_MODEL, messages=msgs, tools=TOOLS)
        print(f"{label}: OK -> {r.choices[0].message.content!r}")
    except Exception as e:  # noqa: BLE001
        print(f"{label}: {type(e).__name__} -> {str(e)[:300]}")
