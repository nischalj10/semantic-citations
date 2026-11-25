# semantic-citations

A citation count says a paper was mentioned. It does not say whether the citing authors built on it, compared against it, agreed with it or criticised it. This tool reads every citation of a paper and answers those questions with a decision model, so the citation graph carries meaning and not only edges.

Background: [Why is there no semantic ontology of sentiment in academic citations?](https://shkspr.mobi/blog/2022/07/why-is-there-no-semantic-ontology-of-sentiment-in-academic-citations/)

## How it works

1. **OpenAlex** resolves the paper and lists every work that cites it.
2. For each citing work, OpenAlex's parsed full text (GROBID TEI XML) is downloaded and every in-text citation of the target is located, with the sentence before and after it.
3. Each citation context goes to the **OpenAI Decisions API** (`POST /v1/decisions`, model `gpt-6-luna`), which returns a probability for each predefined answer. There is no free text to parse.
4. Results are written as JSON lines and as [CiTO](http://purl.org/spar/cito/) triples in Turtle.

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
| `citing_works.json` | every citing work and whether its citations were found |
| `contexts.jsonl` | one row per in-text citation: section, sentence, neighbours, co-citation count |
| `predictions.jsonl` | labels, per-option probabilities, review flag, CiTO property |
| `citations.ttl` | CiTO triples |
| `gold.jsonl`, `report.md` | hand labels and the comparison against them (after `eval`) |

Cost for the example paper (10 citing works, 20 contexts): $0.10 of OpenAlex's free $1/day for full text, paid once and then cached, and about $0.01 of OpenAI usage.

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

## First test: arXiv 2512.00601 (Clinical-R1)

OpenAlex lists 10 citing works. All 10 had full text, and 20 in-text citations were found. All 20 were hand-labelled before the model was run (the labels are in an earlier commit than the predictions). Full results: [`data/arxiv-2512.00601/report.md`](data/arxiv-2512.00601/report.md).

| Question | Agreement with hand labels |
|---|---|
| `function` | 14 of 20 |
| `stance` | 16 of 20 |
| `own_evidence` | 20 of 20 |

What the test shows:

- **High confidence was reliable.** At confidence 0.90 or above, the model matched the hand label 9 of 9 times on `function` and 9 of 9 on `stance`. Below 0.90 it matched about half the time.
- **The review flag caught every disagreement,** at the price of flagging 14 of 20 contexts.
- **The model is conservative.** Every miss was a retreat to `background` or `neutral`. It found 1 of the 5 citations hand-labelled as non-neutral, and never chose `supports`, `mixed` or `builds_on`.
- **Option order matters.** The top `function` answer changed with option order in 5 of 20 contexts.
- **Results were identical across two runs.**

Read these numbers as a smoke test. There are 20 examples, one labeller, and that labeller also wrote the category definitions. The 0.90 threshold was chosen on this same sample.

## Known limits

- **Coverage is OpenAlex's.** Other indexes may list citing works OpenAlex has missed, and works without parsed full text are reported but not classified.
- **GROBID does not link every citation.** Unlinked ones are recovered by matching the marker text (`[13]`, `Gu et al., 2025`), which can misfire when two references share an author and year. Those contexts carry a note.
- **Tables arrive flattened.** A results row is recognisable; a feature-comparison grid is not.
- **A citation targets a claim, not a paper.** This labels the relation to the paper as a whole.
- **Accuracy of the description is not checked.** One citing paper here describes the cited method in terms that do not match its abstract; that is outside all three questions.

## Next

1. Label a second paper before changing the prompt, so prompt changes are tested on citations they were not tuned on.
2. Get a second labeller for the borderline cases, since label definitions are the hard part.
3. Fix the conservative bias, most likely by revisiting the "default" wording and the three stance rules.
