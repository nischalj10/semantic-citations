"""The categories and the prompt.

One citation context gets three independent answers:

  function      why the paper is cited here        (choice, 4 options)
  stance        what the authors think of it       (choice, 4 options)
  own_evidence  do they report their own result    (yes/no probability)
                about the cited paper

Keeping these apart is deliberate. "Supporting" has meant two different
things in earlier work: "the authors agree" and "the authors ran something
that confirms it". Here the first is `stance`, the second is `own_evidence`,
and anyone can recombine them (scite-style supporting = supports + evidence).

The Decisions API has no system prompt. Everything the model is told lives in
the per-question `instructions` and the per-option `description` below, plus
the `input` built by `render_input`.
"""

from __future__ import annotations

PREAMBLE = (
    "You are labelling a single citation. The PASSAGE is taken from the CITING PAPER. "
    "The place where it cites the CITED PAPER is wrapped in <TARGET>...</TARGET>. "
    "Judge only what the citing authors do with the CITED PAPER at this spot. "
    "Use the sentence marked >>> first, and the sentences around it only to resolve ambiguity. "
    "Other works cited in the same bracket are not being labelled. "
)

FUNCTION = {
    "name": "function",
    "instructions": PREAMBLE + "Why is the CITED PAPER cited here?",
    "choices": [
        {
            "value": "background",
            "description": (
                "Mentioned as context: related work, an example of a trend, a description of what "
                "it did, or a source for a general claim. The citing work does not use, extend or "
                "evaluate it here. Choose this when nothing more specific applies."
            ),
        },
        {
            "value": "builds_on",
            "description": (
                "The citing work adopts, adapts or extends the cited paper's method, model, data, "
                "metric or idea as part of its own approach."
            ),
        },
        {
            "value": "compares",
            "description": (
                "The cited paper is a baseline or an explicit point of comparison: its results, "
                "numbers or design are set against the citing work's, whether to show a "
                "difference or a similarity. Includes rows of a results table."
            ),
        },
        {
            "value": "motivates",
            "description": (
                "The cited paper is cited to expose a gap, limitation or open problem that the "
                "citing work sets out to address."
            ),
        },
    ],
}

STANCE = {
    "name": "stance",
    "instructions": PREAMBLE
    + (
        "What attitude do the citing authors express toward the CITED PAPER itself, meaning its "
        "method, findings or quality? Three rules. (1) Beating it in an experiment is not "
        "criticism unless the authors also state a weakness. (2) If the cited paper is only the "
        "source for a claim about something else, the attitude toward the cited paper is neutral, "
        "even when that claim is negative. (3) Generic field-level phrases such as 'recent "
        "advances' or 'recent work' are not praise on their own."
    ),
    "choices": [
        {
            "value": "supports",
            "description": (
                "Explicitly agrees with, corroborates or praises the cited paper, for example "
                "'consistent with', 'aligns with', 'confirms', 'as convincingly shown by'."
            ),
        },
        {
            "value": "neutral",
            "description": (
                "Describes, lists, uses or compares against the cited paper without evaluating "
                "it. Choose this when no evaluation of the cited paper is stated."
            ),
        },
        {
            "value": "critiques",
            "description": (
                "States a weakness, limitation, gap, failure or disagreement that applies to the "
                "cited paper, including when it is criticised as one of a group."
            ),
        },
        {
            "value": "mixed",
            "description": (
                "Credits a strength of the cited paper and states a limitation of it in the same "
                "passage, for example 'although X improves accuracy, it requires ...'."
            ),
        },
    ],
}

OWN_EVIDENCE = {
    "name": "own_evidence",
    "instructions": PREAMBLE
    + (
        "Statement to judge: the passage reports the citing paper's own experimental result or "
        "measurement for the CITED PAPER's method or model, such as a score in a results table "
        "or a head-to-head number. Merely describing it, or naming it as a baseline without a "
        "result, does not count."
    ),
}

# Nearest properties in CiTO, the Citation Typing Ontology (http://purl.org/spar/cito/).
# Stance wins when it is not neutral; otherwise the function decides.
CITO_STANCE = {
    ("supports", False): "agreesWith",
    ("supports", True): "confirms",
    ("critiques", False): "critiques",
    ("critiques", True): "disputes",
    ("mixed", False): "qualifies",
    ("mixed", True): "qualifies",
}
CITO_FUNCTION = {
    "background": "obtainsBackgroundFrom",
    "builds_on": "extends",
    "compares": "discusses",  # CiTO has no dedicated "compares with"
    "motivates": "citesAsRelated",  # nor a neutral "cites as motivation"
}


def cito_property(function: str, stance: str, own_evidence: bool) -> str:
    if stance != "neutral":
        return CITO_STANCE[(stance, own_evidence)]
    return CITO_FUNCTION[function]


def _rotate(items: list, k: int) -> list:
    k %= len(items)
    return items[k:] + items[:k]


def build_questions(rotation: int = 0) -> list[dict]:
    """The `questions` array for one request. `rotation` shifts option order,
    which lets the caller average out the API's sensitivity to it."""
    return [
        {"type": "choice", **FUNCTION, "choices": _rotate(FUNCTION["choices"], rotation)},
        {"type": "choice", **STANCE, "choices": _rotate(STANCE["choices"], rotation)},
        {"type": "predicate", **OWN_EVIDENCE},
    ]


def render_input(cited: dict, citing_title: str, context: dict) -> str:
    """The `input` string for one citation context."""
    abstract = (cited.get("abstract") or "").strip()
    if len(abstract) > 1200:
        abstract = abstract[:1200].rsplit(" ", 1)[0] + " ..."
    lines = [
        "CITED PAPER",
        f"Title: {cited['title']}",
    ]
    if abstract:
        lines.append(f"Abstract: {abstract}")
    lines += [
        "",
        "CITING PAPER",
        f"Title: {citing_title}",
        f"Section: {context.get('section') or 'unknown'}",
        "",
        "PASSAGE",
    ]
    if context.get("before"):
        lines.append(context["before"])
    lines.append(">>> " + context["sentence"])
    if context.get("after"):
        lines.append(context["after"])
    return "\n".join(lines)
