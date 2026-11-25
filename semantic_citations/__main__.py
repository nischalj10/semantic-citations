"""Command line.

    python -m semantic_citations run  https://arxiv.org/abs/2512.00601
    python -m semantic_citations eval arxiv-2512.00601
    python -m semantic_citations export-prompt     # refresh worker/src/prompt.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import arxiv, openalex
from .config import DATA
from .decisions import decide
from .evaluate import write_report
from .config import ROOT
from .taxonomy import cito_property, export, render_input
from .arxiv_html import Target, extract_contexts


def slug_for(work: dict) -> str:
    arxiv = openalex.arxiv_id_of(work)
    return f"arxiv-{arxiv}" if arxiv else openalex.short_id(work)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_citing_paper(arxiv_id: str, target: Target) -> tuple[str, list]:
    """Find the target's citations in one citing paper. ar5iv first, then arXiv's
    latest version, because ar5iv's copy can predate the citation."""
    saw_html = False
    for source in ("ar5iv", "arxiv"):
        html = arxiv.fetch_html(arxiv_id, source)
        if html is None:
            continue
        saw_html = True
        bib, found = extract_contexts(html, target)
        if bib:
            return ("ok" if found else "in reference list but no in-text citation found"), found
    return ("not in the reference list of the arXiv version" if saw_html else "no HTML version on arXiv"), []


def collect(identifier: str) -> tuple[Path, dict, list[dict]]:
    """Steps 1-3: resolve the paper, list citing works, extract citation contexts."""
    work = openalex.resolve(identifier)
    out = DATA / slug_for(work)
    out.mkdir(parents=True, exist_ok=True)
    cited = {
        "openalex_id": openalex.short_id(work),
        "title": work["title"],
        "doi": work.get("doi"),
        "abstract": openalex.abstract_of(work),
    }
    target = Target(title=work["title"], arxiv_id=openalex.arxiv_id_of(work), doi=(work.get("doi") or "").split("doi.org/")[-1] or None)
    print(f"Cited paper: {work['title']}")

    citing = openalex.citing_works(work)
    ids = {openalex.short_id(w): arxiv.arxiv_id_of(w) for w in citing}
    to_fetch = sum(1 for a in ids.values() if a and not arxiv.is_cached(a))
    print(f"{len(citing)} citing works, {sum(1 for a in ids.values() if a)} on arXiv" + (f"; {to_fetch} pages to fetch, about {to_fetch * 3 // 60 + 1} min" if to_fetch else ""))

    contexts, summary = [], []
    for w in citing:
        wid = openalex.short_id(w)
        row = {"openalex_id": wid, "arxiv_id": ids[wid], "title": w["title"], "doi": w.get("doi"), "published": w.get("publication_date")}
        if not ids[wid]:
            row["status"], found = "not on arXiv", []
        else:
            row["status"], found = read_citing_paper(ids[wid], target)
        for n, ctx in enumerate(found, 1):
            contexts.append({"id": f"{wid}#{n}", "citing_work": wid, "citing_title": w["title"], **ctx.to_dict()})
        row["contexts"] = len(found)
        summary.append(row)
        print(f"  {wid}  {row['contexts']} context(s)  {row['status']:<48.48}  {w['title'][:56]}")

    (out / "cited.json").write_text(json.dumps({k: v for k, v in cited.items() if k != "abstract"}, indent=2) + "\n")
    (out / "citing_works.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    write_jsonl(out / "contexts.jsonl", contexts)
    return out, cited, contexts


def classify(out: Path, cited: dict, contexts: list[dict], rotations: int, review_below: float) -> list[dict]:
    """Step 4: ask the decision model about every context."""
    predictions, tokens = [], 0
    for ctx in contexts:
        result = decide(render_input(cited, ctx["citing_title"], ctx), rotations=rotations)
        tokens += result.pop("input_tokens")
        evidence = result["own_evidence"]["probability"] >= 0.5
        result["cito"] = cito_property(result["function"]["label"], result["stance"]["label"], evidence)
        result["needs_review"] = min(result["function"]["confidence"], result["stance"]["confidence"]) < review_below
        predictions.append({"id": ctx["id"], **result})
        print(
            f"  {ctx['id']:<15} function={result['function']['label']:<10} ({result['function']['confidence']:.2f})"
            f"  stance={result['stance']['label']:<9} ({result['stance']['confidence']:.2f})"
            f"  own_evidence={result['own_evidence']['probability']:.2f}"
            f"{'  REVIEW' if result['needs_review'] else ''}"
        )
    write_jsonl(out / "predictions.jsonl", predictions)
    flagged = sum(p["needs_review"] for p in predictions)
    print(f"{len(predictions)} contexts, {flagged} flagged for review (confidence below {review_below})")
    print(f"{tokens:,} input tokens (about ${tokens / 1e6 * 0.10:.4f} at $0.10 per 1M)")
    return predictions


def write_turtle(out: Path, cited: dict, contexts: list[dict], predictions: list[dict], citing: list[dict]) -> None:
    """Step 5: one CiTO triple per distinct relation between a citing paper and the cited one."""
    iri = lambda w: f"<{w['doi']}>" if w.get("doi") else f"<https://openalex.org/{w['openalex_id']}>"
    # property -> True if every context behind it was flagged for review
    by_work: dict[str, dict[str, bool]] = {}
    for ctx, pred in zip(contexts, predictions):
        props = by_work.setdefault(ctx["citing_work"], {})
        props[pred["cito"]] = props.get(pred["cito"], True) and pred["needs_review"]
    works = {w["openalex_id"]: w for w in citing}
    lines = ["@prefix cito: <http://purl.org/spar/cito/> .", ""]
    for wid, props in by_work.items():
        title = re.sub(r"\s+", " ", works[wid]["title"])
        lines.append(f"# {title}")
        for prop in sorted(props):
            note = "  # low confidence, review before use" if props[prop] else ""
            lines.append(f"{iri(works[wid])} cito:{prop} {iri(cited)} .{note}")
        lines.append("")
    (out / "citations.ttl").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(prog="semantic_citations", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="collect citations of a paper and classify them")
    run.add_argument("paper", help="arXiv URL or ID, DOI, or OpenAlex work ID")
    run.add_argument("--rotations", type=int, default=4, help="option orders to average over (default 4)")
    run.add_argument("--review-below", type=float, default=0.90, help="flag a context when either choice is less confident than this")
    run.add_argument("--no-classify", action="store_true", help="stop after extracting contexts (e.g. to hand-label first)")

    ev = sub.add_parser("eval", help="compare predictions with hand labels in gold.jsonl")
    ev.add_argument("slug", help="folder name under data/, e.g. arxiv-2512.00601")

    sub.add_parser("export-prompt", help="write the prompt to worker/src/prompt.json for the web app")

    args = parser.parse_args()
    if args.command == "export-prompt":
        path = ROOT / "worker" / "src" / "prompt.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(export(), indent=2) + "\n")
        print(f"Wrote {path}")
    elif args.command == "run":
        out, cited, contexts = collect(args.paper)
        print(f"{len(contexts)} citation contexts -> {out / 'contexts.jsonl'}")
        if args.no_classify:
            return
        predictions = classify(out, cited, contexts, args.rotations, args.review_below)
        write_turtle(out, cited, contexts, predictions, json.loads((out / "citing_works.json").read_text()))
        print(f"Wrote {out / 'predictions.jsonl'} and {out / 'citations.ttl'}")
    else:
        out = DATA / args.slug
        report = write_report(out, read_jsonl(out / "contexts.jsonl"), read_jsonl(out / "predictions.jsonl"), read_jsonl(out / "gold.jsonl"))
        print(report)


if __name__ == "__main__":
    main()
