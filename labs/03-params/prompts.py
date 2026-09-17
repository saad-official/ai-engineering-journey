"""Prompts for lab 03.

Two prompts, picked for opposite reasons. The pair is the experiment: temperature is a
knob on the *distribution*, so how much it changes the output depends entirely on how
peaked that distribution already is. One prompt is chosen to have a flat distribution,
the other a spiky one.

All text here is synthetic and public. Free-tier prompts are used to improve the
provider's products (see TECHNOLOGY_STACK.md), so nothing private or company-related
ever goes through these labs.

CREATIVE - naming plus a tagline. There is no single right answer, so at every position
    the model has many plausible next tokens with similar probabilities. That is a flat
    distribution, and a flat distribution is exactly what temperature reshapes. The
    output is also long enough (a handful of words) for a similarity score to mean
    something, and short enough to stay cheap over 30+ samples.

FACTUAL - a closed question with a three-digit answer. The distribution collapses onto
    one token almost immediately. Flattening a spike that tall still leaves a spike, so
    this prompt should look deterministic at *every* temperature. If it does, that is
    the real lesson: "temperature 1.2 is risky" is not a property of the temperature, it
    is a property of the temperature *and the prompt*.

Both prompts end with an explicit output-format instruction. That is not decoration: an
unconstrained prompt varies in length and shape as well as in wording, and length
variance would swamp the word-level similarity metric with noise that has nothing to do
with sampling.
"""

from __future__ import annotations

CREATIVE = (
    "Invent a name for a command-line tool that turns merged pull requests into a "
    "release changelog, and write a tagline of at most six words for it. "
    "Reply with exactly one line in the form: Name - tagline. Nothing else."
)

FACTUAL = (
    "Which HTTP status code means the resource is gone permanently and is not coming "
    "back? Reply with the three-digit number only. Nothing else."
)

# (label, prompt). The label is what shows up in the printed tables, so keep it short.
PROMPTS: list[tuple[str, str]] = [
    ("creative", CREATIVE),
    ("factual", FACTUAL),
]
