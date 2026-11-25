"""Compare the decision model with hand labels.

gold.jsonl has one row per context:
    {"id": "...", "function": "...", "stance": "...", "own_evidence": true,
     "borderline": ["stance"], "note": "why"}

`borderline` lists the questions where the labeller thought a second reasonable
person could answer differently. Agreement is reported with and without them.
"""

from __future__ import annotations

from pathlib import Path

CHOICE_QUESTIONS = ("function", "stance")
BINS = ((0.9, 1.01, "0.90 - 1.00"), (0.7, 0.9, "0.70 - 0.90"), (0.0, 0.7, "below 0.70"))


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d else "")


def write_report(out: Path, contexts: list[dict], predictions: list[dict], gold: list[dict]) -> str:
    ctx = {c["id"]: c for c in contexts}
    pred = {p["id"]: p for p in predictions}
    gold_by_id = {g["id"]: g for g in gold}
    ids = [i for i in ctx if i in pred and i in gold_by_id]
    missing = [i for i in ctx if i not in gold_by_id]

    lines = [f"# Decision model vs hand labels: {out.name}", ""]
    lines.append(f"{len(ids)} citation contexts from {len({ctx[i]['citing_work'] for i in ids})} citing papers.")
    if missing:
        lines.append(f"**{len(missing)} contexts have no hand label and are excluded:** {', '.join(missing)}")
    lines.append("")

    # --- agreement ----------------------------------------------------------
    lines += ["## Agreement", "", "| Question | All contexts | Clear-cut only | Top answer changed with option order |", "|---|---|---|---|"]
    for q in CHOICE_QUESTIONS:
        hits = [pred[i][q]["label"] == gold_by_id[i][q] for i in ids]
        clear = [i for i in ids if q not in gold_by_id[i].get("borderline", [])]
        clear_hits = [pred[i][q]["label"] == gold_by_id[i][q] for i in clear]
        flips = sum(1 for i in ids if pred[i][q]["order_sensitive"])
        lines.append(f"| `{q}` | {_pct(sum(hits), len(ids))} | {_pct(sum(clear_hits), len(clear))} | {flips} of {len(ids)} |")
    ev_hits = [(pred[i]["own_evidence"]["probability"] >= 0.5) == gold_by_id[i]["own_evidence"] for i in ids]
    clear = [i for i in ids if "own_evidence" not in gold_by_id[i].get("borderline", [])]
    ev_clear = [(pred[i]["own_evidence"]["probability"] >= 0.5) == gold_by_id[i]["own_evidence"] for i in clear]
    brier = sum((pred[i]["own_evidence"]["probability"] - float(gold_by_id[i]["own_evidence"])) ** 2 for i in ids) / max(1, len(ids))
    lines.append(f"| `own_evidence` (threshold 0.5) | {_pct(sum(ev_hits), len(ids))} | {_pct(sum(ev_clear), len(clear))} | n/a |")
    lines += ["", f"Brier score for `own_evidence`: {brier:.3f} (0 is perfect, 0.25 is a coin flip).", ""]

    # --- confidence ---------------------------------------------------------
    lines += [
        "## Does confidence track correctness?",
        "",
        "Confidence is the probability of the chosen option, averaged over option orders.",
        "",
        "| Question | Confidence | Contexts | Agree with hand label |",
        "|---|---|---|---|",
    ]
    for q in CHOICE_QUESTIONS:
        for lo, hi, name in BINS:
            members = [i for i in ids if lo <= pred[i][q]["confidence"] < hi]
            right = sum(1 for i in members if pred[i][q]["label"] == gold_by_id[i][q])
            lines.append(f"| `{q}` | {name} | {len(members)} | {_pct(right, len(members)) if members else '-'} |")
    lines.append("")
    for q in CHOICE_QUESTIONS:
        right = [pred[i][q]["confidence"] for i in ids if pred[i][q]["label"] == gold_by_id[i][q]]
        wrong = [pred[i][q]["confidence"] for i in ids if pred[i][q]["label"] != gold_by_id[i][q]]
        mean = lambda xs: f"{sum(xs) / len(xs):.2f}" if xs else "n/a"
        lines.append(f"- `{q}`: mean confidence {mean(right)} when it agrees ({len(right)}), {mean(wrong)} when it disagrees ({len(wrong)}).")
    lines.append("")

    # --- review flag --------------------------------------------------------
    flagged = [i for i in ids if pred[i].get("needs_review")]
    kept = [i for i in ids if not pred[i].get("needs_review")]
    both_right = lambda i: all(pred[i][q]["label"] == gold_by_id[i][q] for q in CHOICE_QUESTIONS)
    wrong = [i for i in ids if not both_right(i)]
    lines += [
        "## Review flag",
        "",
        "A context is flagged when either choice is below the review threshold (default 0.90).",
        "",
        f"- Not flagged: {len(kept)} contexts, of which {_pct(sum(both_right(i) for i in kept), len(kept))} match the hand label on both questions.",
        f"- Flagged: {len(flagged)} contexts, of which {_pct(sum(both_right(i) for i in flagged), len(flagged))} match on both.",
        f"- Contexts with any disagreement: {len(wrong)}, of which {_pct(sum(1 for i in wrong if i in flagged), len(wrong))} were flagged.",
        "",
    ]

    # --- confusion ----------------------------------------------------------
    for q in CHOICE_QUESTIONS:
        labels = sorted({gold_by_id[i][q] for i in ids} | {pred[i][q]["label"] for i in ids})
        lines += [f"## `{q}`: hand label (rows) vs model (columns)", "", "| | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
        for g in labels:
            row = [str(sum(1 for i in ids if gold_by_id[i][q] == g and pred[i][q]["label"] == p)) for p in labels]
            lines.append(f"| **{g}** | " + " | ".join(row) + " |")
        lines.append("")

    # --- every context ------------------------------------------------------
    lines += [
        "## Every context",
        "",
        "Hand label / model label (confidence). **Bold** marks a disagreement; `~` marks a label the labeller flagged as borderline.",
        "",
        "| Context | Citing paper | function | stance | own_evidence |",
        "|---|---|---|---|---|",
    ]
    for i in ids:
        g, p = gold_by_id[i], pred[i]
        cells = []
        for q in CHOICE_QUESTIONS:
            flag = "~" if q in g.get("borderline", []) else ""
            cell = f"{g[q]}{flag} / {p[q]['label']} ({p[q]['confidence']:.2f})"
            cells.append(f"**{cell}**" if g[q] != p[q]["label"] else cell)
        flag = "~" if "own_evidence" in g.get("borderline", []) else ""
        prob = p["own_evidence"]["probability"]
        cell = f"{'yes' if g['own_evidence'] else 'no'}{flag} / {prob:.2f}"
        cells.append(f"**{cell}**" if (prob >= 0.5) != g["own_evidence"] else cell)
        lines.append(f"| `{i}` | {ctx[i]['citing_title'][:48]} | " + " | ".join(cells) + " |")
    lines.append("")

    notes = [(i, gold_by_id[i]["note"]) for i in ids if gold_by_id[i].get("note")]
    if notes:
        lines += ["## Labeller's notes", ""] + [f"- `{i}`: {note}" for i, note in notes] + [""]

    report = "\n".join(lines)
    (out / "report.md").write_text(report)
    return report
