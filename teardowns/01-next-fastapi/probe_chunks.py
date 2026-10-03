"""Print the RAW provider chunks for the exact request the original backend makes.

When a backend translates stream A (provider chunks) into stream B (the AI SDK protocol) and B
comes out wrong, look at A before reading the translator. This is that look.

Run:  uv run python probe_chunks.py ["prompt"] [--include-usage]
"""

from __future__ import annotations

import sys

from run_original import GEMINI_MODEL, gemini  # gemini.create already forces our model

TOOLS = [  # copied verbatim from api/index.py so the request is identical
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    },
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location", "unit"],
            },
        },
    }
]

args = [a for a in sys.argv[1:] if not a.startswith("--")]
prompt = args[0] if args else "What is the weather in Lahore in celsius?"
extra = {"stream_options": {"include_usage": True}} if "--include-usage" in sys.argv else {}

stream = gemini.chat.completions.create(
    model=GEMINI_MODEL,
    messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    stream=True,
    tools=TOOLS,
    **extra,
)
for i, chunk in enumerate(stream):
    print(f"--- chunk {i}")
    print(chunk.model_dump_json(exclude_none=True, indent=1))
