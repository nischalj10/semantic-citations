"""Command line.

    python -m semantic_citations run  https://arxiv.org/abs/2512.00601
    python -m semantic_citations eval arxiv-2512.00601
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import openalex
from .config import DATA
from .decisions import decide
from .evaluate import write_report
from .taxonomy import cito_property, render_input
from .tei import Target, extract_contexts


def slug_for(work: dict) -> str:
    arxiv = openalex.arxiv_id_of(work)
    return f"arxiv-{arxiv}" if arxiv else openalex.short_id(work)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collect(identifier: str, max_fulltext_usd: float) -> tuple[Path, dict, list[dict]]:
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
    to_buy = openalex.uncached_fulltext_count(citing)
    cost = to_buy * openalex.FULLTEXT_COST_USD
    print(f"{len(citing)} citing works; {to_buy} full texts to download (${cost:.2f} of OpenAlex budget)")
    if cost > max_fulltext_usd:
        raise SystemExit(f"That exceeds --max-fulltext-usd {max_fulltext_usd}. Raise the limit to proceed.")

    contexts, summary = [], []
    for w in citing:
        wid = openalex.short_id(w)
        row = {"openalex_id": wid, "title": w["title"], "doi": w.get("doi"), "published": w.get("publication_date")}
        tei = openalex.fulltext_tei(w)
        if tei is None:
            row["status"] = "no full text available from OpenAlex"
        else:
            bib, found = extract_contexts(tei, target)
            if bib is None:
                row["status"] = "target not found in reference list"
            else:
                row["status"] = "ok" if found else "in reference list but no in-text citation found"
            for n, ctx in enumerate(found, 1):
                contexts.append({"id": f"{wid}#{n}", "citing_work": wid, "citing_title": w["title"], **ctx.to_dict()})
            row["contexts"] = len(found)
        summary.append(row)
        print(f"  {wid}  {row.get('contexts', 0)} context(s)  {row['status']:<45.45}  {w['title'][:60]}")

    (out / "cited.json").write_text(json.dumps({k: v for k, v in cited.items() if k != "abstract"}, indent=2) + "\n")
    (out / "citing_works.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    write_jsonl(out / "contexts.jsonl", contexts)
    return out, cited, contexts


def classify(out: Path, cited: dict, contexts: list[dict], rotations: int) -> list[dict]:
    """Step 4: ask the decision model about every context."""
    predictions, tokens = [], 0
    for ctx in contexts:
        result = decide(render_input(cited, ctx["citing_title"], ctx), rotations=rotations)
        tokens += result.pop("input_tokens")
        evidence = result["own_evidence"]["probability"] >= 0.5
        result["cito"] = cito_property(result["function"]["label"], result["stance"]["label"], evidence)
        predictions.append({"id": ctx["id"], **result})
        print(
            f"  {ctx['id']:<15} function={result['function']['label']:<10} ({result['function']['confidence']:.2f})"
            f"  stance={result['stance']['label']:<9} ({result['stance']['confidence']:.2f})"
            f"  own_evidence={result['own_evidence']['probability']:.2f}"
        )
    write_jsonl(out / "predictions.jsonl", predictions)
    print(f"{len(predictions)} contexts, {tokens:,} input tokens (about ${tokens / 1e6 * 0.10:.4f} at $0.10 per 1M)")
    return predictions


def write_turtle(out: Path, cited: dict, contexts: list[dict], predictions: list[dict], citing: list[dict]) -> None:
    """Step 5: one CiTO triple per distinct relation between a citing paper and the cited one."""
    iri = lambda w: f"<{w['doi']}>" if w.get("doi") else f"<https://openalex.org/{w['openalex_id']}>"
    by_work: dict[str, set[str]] = {}
    for ctx, pred in zip(contexts, predictions):
        by_work.setdefault(ctx["citing_work"], set()).add(pred["cito"])
    works = {w["openalex_id"]: w for w in citing}
    lines = ["@prefix cito: <http://purl.org/spar/cito/> .", ""]
    for wid, props in by_work.items():
        title = re.sub(r"\s+", " ", works[wid]["title"])
        lines.append(f"# {title}")
        for prop in sorted(props):
            lines.append(f"{iri(works[wid])} cito:{prop} {iri(cited)} .")
        lines.append("")
    (out / "citations.ttl").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(prog="semantic_citations", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="collect citations of a paper and classify them")
    run.add_argument("paper", help="arXiv URL or ID, DOI, or OpenAlex work ID")
    run.add_argument("--rotations", type=int, default=4, help="option orders to average over (default 4)")
    run.add_argument("--max-fulltext-usd", type=float, default=0.50, help="OpenAlex full-text spend allowed for this run")
    run.add_argument("--no-classify", action="store_true", help="stop after extracting contexts (e.g. to hand-label first)")

    ev = sub.add_parser("eval", help="compare predictions with hand labels in gold.jsonl")
    ev.add_argument("slug", help="folder name under data/, e.g. arxiv-2512.00601")

    args = parser.parse_args()
    if args.command == "run":
        out, cited, contexts = collect(args.paper, args.max_fulltext_usd)
        print(f"{len(contexts)} citation contexts -> {out / 'contexts.jsonl'}")
        if args.no_classify:
            return
        predictions = classify(out, cited, contexts, args.rotations)
        write_turtle(out, cited, contexts, predictions, json.loads((out / "citing_works.json").read_text()))
        print(f"Wrote {out / 'predictions.jsonl'} and {out / 'citations.ttl'}")
    else:
        out = DATA / args.slug
        report = write_report(out, read_jsonl(out / "contexts.jsonl"), read_jsonl(out / "predictions.jsonl"), read_jsonl(out / "gold.jsonl"))
        print(report)


if __name__ == "__main__":
    main()
