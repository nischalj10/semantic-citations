"""OpenAI Decisions API client.

    POST https://api.openai.com/v1/decisions
    {"model": "gpt-6-luna", "input": "...", "questions": [...]}

The response carries, per question, either a `probability` (predicate) or a
`choice` with `probabilities` over the options. There is no system prompt and
no free-text output, so there is nothing to parse.

Choice probabilities from this API tend to be near 0 or 1, and reports say
they move with option order. So each context is asked `rotations` times with
the options rotated, and the probabilities are averaged. The averaged number
is the confidence we evaluate; `order_sensitive` records whether the top
answer changed between rotations.
"""

from __future__ import annotations

import time

import requests

from .config import require
from .taxonomy import build_questions

URL = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"


def _post(payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {require('OPENAI_API_KEY')}"}
    for attempt in range(5):
        r = requests.post(URL, json=payload, headers=headers, timeout=60)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(2**attempt)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Decisions API {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError("Decisions API: retries exhausted")


def decide(input_text: str, rotations: int = 4, model: str = MODEL) -> dict:
    """Classify one citation context. Returns averaged probabilities per question."""
    choice_sums: dict[str, dict[str, float]] = {}
    choice_tops: dict[str, list[str]] = {}
    predicate_sums: dict[str, float] = {}
    refusals: list[str] = []
    tokens = 0

    for k in range(rotations):
        resp = _post({"model": model, "input": input_text, "questions": build_questions(k)})
        tokens += resp.get("usage", {}).get("input_tokens", 0)
        for ans in resp["answers"]:
            name = ans["name"]
            if ans["type"] == "choice":
                sums = choice_sums.setdefault(name, {})
                for p in ans["probabilities"]:
                    sums[p["value"]] = sums.get(p["value"], 0.0) + p["probability"]
                choice_tops.setdefault(name, []).append(ans["choice"])
            elif ans["type"] == "predicate":
                predicate_sums[name] = predicate_sums.get(name, 0.0) + ans["probability"]
            else:  # "refusal"
                refusals.append(name)

    out: dict = {"model": model, "rotations": rotations, "input_tokens": tokens}
    for name, sums in choice_sums.items():
        n = len(choice_tops[name])
        probs = {value: round(total / n, 4) for value, total in sums.items()}
        label = max(probs, key=probs.get)
        out[name] = {
            "label": label,
            "confidence": probs[label],
            "probabilities": probs,
            "order_sensitive": len(set(choice_tops[name])) > 1,
        }
    for name, total in predicate_sums.items():
        out[name] = {"probability": round(total / rotations, 4)}
    if refusals:
        out["refusals"] = sorted(set(refusals))
    return out
