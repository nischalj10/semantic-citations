# semantic-citations

A citation count says a paper was mentioned. It does not say whether the citing authors built on it, compared against it, agreed with it or criticised it. This tool reads every citation of a paper and answers those questions with a decision model, so the citation graph carries meaning and not only edges.

Background: [Why is there no semantic ontology of sentiment in academic citations?](https://shkspr.mobi/blog/2022/07/why-is-there-no-semantic-ontology-of-sentiment-in-academic-citations/)

There is a web app too (see [Web app](#web-app)). Its hosted copy is switched off for now; `npm run build && node test/local.mjs` in `worker/` runs it locally.

## How it works

1. **OpenAlex** resolves the paper and lists every work that cites it. This costs a fraction of a cent per paper.
2. The text of each citing work comes from **arXiv's HTML version**, which is free. arXiv renders papers with LaTeXML, so every in-text citation is a real link into the reference list. Each link to the target is located, with the sentence before and after it.
3. Each citation context goes to the **OpenAI Decisions API** (`POST /v1/decisions`, model `gpt-6-luna`), which returns a probability for each predefined answer. There is no free text to parse.
4. Results are written as JSON lines and as [CiTO](http://purl.org/spar/cito/) triples in Turtle.

### Where the text comes from

Two hosts serve the same HTML. `ar5iv.labs.arxiv.org` (arXiv Labs) is tried first and fetched once every 3 seconds. `arxiv.org/html` is the fallback, fetched once every 15 seconds because its robots.txt asks for that. The fallback matters because ar5iv keeps the version it converted, which can predate the citation being looked for. Every page is fetched once and then cached.

On the 30 most-cited papers citing τ-bench, all 30 were on arXiv, 27 had a usable HTML version, and 26 of those listed τ-bench in their references.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY and OPENALEX_API_KEY

python -m semantic_citations run https://arxiv.org/abs/2512.00601
python -m semantic_citations eval arxiv-2512.00601     # needs data/<slug>/gold.jsonl
python -m unittest                                     # offline tests
```

`run` accepts an arXiv URL or ID, a DOI, or an OpenAlex work ID. Output goes to `data/<slug>/`:

| File | Contents |
|---|---|
| `citing_works.json` | every citing work, its arXiv ID, and whether its citations were found |
| `contexts.jsonl` | one row per in-text citation: section, sentence, neighbours, co-citation count |
| `predictions.jsonl` | labels, per-option probabilities, review flag, CiTO property |
| `citations.ttl` | CiTO triples |
| `gold.jsonl`, `report.md` | hand labels and the comparison against them (after `eval`) |

Cost for the example paper (10 citing works, 14 contexts): under a cent of OpenAI usage, and effectively nothing for OpenAlex.

## Web app

`worker/` is the same pipeline as a Cloudflare Worker with a single page in front of it.

- `GET /api/paper?id=<arxiv link>` resolves the paper and returns the first 100 works citing it.
- `GET /api/citing?target=<id>&page=<n>` returns further pages of citing works.
- `GET /api/results?target=<id>` returns every citing work already read, in bulk.
- `GET /api/citations?target=<id>&work=<id>&page=<n>` reads one citing work and labels each citation in it.

The browser reads the 30 most-cited citing papers on its own, then offers "Read 100 more" and "Read all remaining". Papers are read one at a time, because arXiv is fetched one page every few seconds; the queue is shared by all visitors. Results are stored in D1, so each citing paper is fetched and labelled once, for everyone.

The prompt is not duplicated: `python -m semantic_citations export-prompt` writes `worker/src/prompt.json` from `taxonomy.py`. The context extractor exists twice, `worker/src/arxiv.js` and `semantic_citations/arxiv_html.py`, written as line-for-line ports of each other. `node worker/test/parity.mjs` checks they agree. On the test paper the live site returns the same 14 contexts, labels and confidences as the Python run.

Limits, set in `worker/wrangler.jsonc`:

| Setting | Default | Why |
|---|---|---|
| `MAX_CITING` | 2000 | citing works listed per paper, most-cited first |
| `MAX_CONTEXTS_PER_WORK` | 8 | keeps one request under the Workers free plan's 50 outbound calls |
| `DAILY_NEW_PAPERS_CAP` | 1500 | new citing papers labelled per day across all visitors; caps OpenAI spend at roughly $2 a day |

The citations endpoint takes IDs, never text, and only reads works that OpenAlex lists as citing the target, so it cannot be used as an open proxy to the OpenAI key.

```bash
cd worker
npm install
npm test                       # offline unit tests
npx wrangler login
npx wrangler d1 execute semantic-citations --remote --file schema.sql   # first deploy only
npx wrangler secret put OPENAI_API_KEY                                  # first deploy only
npx wrangler secret put OPENALEX_API_KEY                                # first deploy only
npx wrangler deploy

npm run build && node test/local.mjs        # or run it in Node, no Cloudflare login needed
```

## Categories

Each citation context gets three independent answers.

**`function`: why is the paper cited here?** (choice)

| Label | Meaning |
|---|---|
| `background` | Context: related work, an example of a trend, a description, or a source for a general claim. The default. |
| `builds_on` | The citing work adopts, adapts or extends the cited method, model, data, metric or idea. |
| `compares` | A baseline or explicit point of comparison, including rows of a results table. |
| `motivates` | Cited to expose a gap, limitation or open problem the citing work addresses. |

**`stance`: what do the citing authors think of it?** (choice)

| Label | Meaning |
|---|---|
| `supports` | Explicitly agrees with, corroborates or praises the cited paper. |
| `neutral` | Describes, lists, uses or compares against it without evaluating it. The default. |
| `critiques` | States a weakness, limitation, gap, failure or disagreement that applies to it, including as one of a group. |
| `mixed` | Credits a strength and states a limitation in the same passage. |

**`own_evidence`: does the passage report the citing paper's own result for the cited paper's method or model?** (yes/no probability)

The split is deliberate. "Supporting" has meant both "the authors agree" and "the authors ran something that confirms it". Here the first is `stance` and the second is `own_evidence`, so either definition can be recovered.

`co_cited` (how many other works share the bracket) is counted from the text, not asked of the model.

## The prompt

The Decisions API has no system prompt. The model sees an `input` string and, per question, an `instructions` string plus a `description` for each option. The source of truth is [`semantic_citations/taxonomy.py`](semantic_citations/taxonomy.py).

**Input**

```
CITED PAPER
Title: <title>
Abstract: <abstract, up to 1,200 characters>

CITING PAPER
Title: <title>
Section: <section heading>

PASSAGE
<sentence before>
>>> <citing sentence, with the citation wrapped in <TARGET>...</TARGET>>
<sentence after>
```

**Shared preamble, prefixed to every question**

> You are labelling a single citation. The PASSAGE is taken from the CITING PAPER. The place where it cites the CITED PAPER is wrapped in `<TARGET>...</TARGET>`. Judge only what the citing authors do with the CITED PAPER at this spot. Use the sentence marked `>>>` first, and the sentences around it only to resolve ambiguity. Other works cited in the same bracket are not being labelled.

**`function`** adds: *Why is the CITED PAPER cited here?*

**`stance`** adds:

> What attitude do the citing authors express toward the CITED PAPER itself, meaning its method, findings or quality? Three rules. (1) Beating it in an experiment is not criticism unless the authors also state a weakness. (2) If the cited paper is only the source for a claim about something else, the attitude toward the cited paper is neutral, even when that claim is negative. (3) Generic field-level phrases such as 'recent advances' or 'recent work' are not praise on their own.

**`own_evidence`** adds:

> Statement to judge: the passage reports the citing paper's own experimental result or measurement for the CITED PAPER's method or model, such as a score in a results table or a head-to-head number. Merely describing it, or naming it as a baseline without a result, does not count.

Option descriptions are the "Meaning" columns above, in slightly longer form.

**Confidence.** Each context is asked four times with the options rotated, and the probabilities are averaged. A context is flagged `needs_review` when either choice has confidence below 0.90.

## Test: arXiv 2512.00601 (Clinical-R1)

OpenAlex lists 10 citing works. Seven are on arXiv, and 14 in-text citations were found in them. Full results: [`data/arxiv-2512.00601/report.md`](data/arxiv-2512.00601/report.md).

| Question | Agreement with hand labels |
|---|---|
| `function` | 11 of 14 |
| `stance` | 13 of 14 |
| `own_evidence` | 14 of 14 |

What the test shows:

- **The model is conservative.** All four misses were a retreat to `background` or `neutral`.
- **High confidence is a good sign, not a guarantee.** At confidence 0.90 or above, `stance` matched 8 of 8 and `function` 7 of 8. The one miss is a row of a feature-comparison table, which the hand label itself marks as borderline.
- **Option order matters.** The top answer changed with option order in 3 of 14 contexts for `function` and 4 of 14 for `stance`.

Read these numbers as a smoke test. There are 14 examples, one labeller, and that labeller also wrote the category definitions. The three citing papers that are not on arXiv held the only `supports`, `mixed` and `builds_on` examples, so those labels are untested here.

### Earlier run on OpenAlex full text

The first version read OpenAlex's parsed full text (GROBID), at $0.01 per citing paper. That reached all 10 citing works and 20 citations, with agreement of 14 of 20 on `function` and 16 of 20 on `stance`. It was replaced because of the cost at scale: a paper with 1,500 citing works would have cost about $15 to read. The hand labels for all 20 are still in `gold.jsonl`; the six from papers not on arXiv are reported as excluded. One label was changed for the new source, before the model was run on it: a citation that GROBID had flattened into a list of references is, in arXiv's HTML, visibly a row of a comparison table.

The arXiv route is also more exact. GROBID did not link every citation, and recovering the unlinked ones by matching "Yao et al., 2024" in the text produced false matches when two references shared an author and year. arXiv's links come straight from the paper's LaTeX.

## Known limits

- **Only citing papers on arXiv are read**, and only those with an HTML version. For τ-bench that was 26 of the 30 most-cited citing papers.
- **The arXiv version is what gets read.** A journal version can cite the target when the arXiv version does not, and the other way round.
- **Coverage of the citing list is OpenAlex's.** Other indexes may list citing works OpenAlex has missed.
- **Reading is slow by design.** About 3.5 seconds per citing paper, so 1,500 citing papers take roughly an hour and a half the first time.
- **Sentence splitting is rule-based** and occasionally joins two sentences.
- **A citation targets a claim, not a paper.** This labels the relation to the paper as a whole.
- **Accuracy of the description is not checked.** One citing paper here describes the cited method in terms that do not match its abstract; that is outside all three questions.

## Next

1. Label a second paper before changing the prompt, so prompt changes are tested on citations they were not tuned on.
2. Get a second labeller for the borderline cases, since label definitions are the hard part.
3. Fix the conservative bias, most likely by revisiting the "default" wording and the three stance rules.
