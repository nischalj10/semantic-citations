# Decision model vs hand labels: arxiv-2512.00601

20 citation contexts from 10 citing papers.

## Agreement

| Question | All contexts | Clear-cut only | Top answer changed with option order |
|---|---|---|---|
| `function` | 14/20 (70%) | 11/15 (73%) | 5 of 20 |
| `stance` | 16/20 (80%) | 12/16 (75%) | 2 of 20 |
| `own_evidence` (threshold 0.5) | 20/20 (100%) | 19/19 (100%) | n/a |

Brier score for `own_evidence`: 0.000 (0 is perfect, 0.25 is a coin flip).

## Does confidence track correctness?

Confidence is the probability of the chosen option, averaged over option orders.

| Question | Confidence | Contexts | Agree with hand label |
|---|---|---|---|
| `function` | 0.90 - 1.00 | 9 | 9/9 (100%) |
| `function` | 0.70 - 0.90 | 7 | 4/7 (57%) |
| `function` | below 0.70 | 4 | 1/4 (25%) |
| `stance` | 0.90 - 1.00 | 9 | 9/9 (100%) |
| `stance` | 0.70 - 0.90 | 8 | 5/8 (62%) |
| `stance` | below 0.70 | 3 | 2/3 (67%) |

- `function`: mean confidence 0.88 when it agrees (14), 0.69 when it disagrees (6).
- `stance`: mean confidence 0.88 when it agrees (16), 0.76 when it disagrees (4).

## Review flag

A context is flagged when either choice is below the review threshold (default 0.90).

- Not flagged: 6 contexts, of which 6/6 (100%) match the hand label on both questions.
- Flagged: 14 contexts, of which 7/14 (50%) match on both.
- Contexts with any disagreement: 7, of which 7/7 (100%) were flagged.

## `function`: hand label (rows) vs model (columns)

| | background | builds_on | compares | motivates |
|---|---|---|---|---|
| **background** | 8 | 0 | 0 | 0 |
| **builds_on** | 2 | 0 | 0 | 0 |
| **compares** | 1 | 0 | 4 | 0 |
| **motivates** | 3 | 0 | 0 | 2 |

## `stance`: hand label (rows) vs model (columns)

| | critiques | mixed | neutral | supports |
|---|---|---|---|---|
| **critiques** | 1 | 0 | 1 | 0 |
| **mixed** | 0 | 0 | 1 | 0 |
| **neutral** | 0 | 0 | 15 | 0 |
| **supports** | 0 | 0 | 2 | 0 |

## Every context

Hand label / model label (confidence). **Bold** marks a disagreement; `~` marks a label the labeller flagged as borderline.

| Context | Citing paper | function | stance | own_evidence |
|---|---|---|---|---|
| `W7224512487#1` | Trustworthy Medical LLMs via Bayesian Belief Upd | background / background (0.90) | neutral~ / neutral (0.93) | no / 0.00 |
| `W7224580160#1` | Unlocking Latent Medical Reasoning in LLMs via I | **motivates / background (0.79)** | **mixed / neutral (0.83)** | no / 0.00 |
| `W7154719127#1` | RadAgent: A tool-using AI agent for stepwise int | background / background (0.98) | neutral / neutral (0.98) | no / 0.00 |
| `W7157260422#1` | Thinking Like a Clinician: A Cognitive AI Agent  | **motivates~ / background (0.62)** | neutral / neutral (0.79) | no / 0.00 |
| `W7160921908#1` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | motivates / motivates (0.74) | critiques / critiques (0.64) | no / 0.00 |
| `W7160921908#2` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | **motivates / background (0.53)** | **critiques / neutral (0.64)** | no / 0.00 |
| `W7160921908#3` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | background~ / background (0.72) | neutral / neutral (0.65) | no / 0.00 |
| `W7162563163#1` | MedGuideX: Internalizing Decision Logic from Exe | motivates~ / motivates (0.55) | neutral / neutral (0.75) | no / 0.00 |
| `W7162563163#2` | MedGuideX: Internalizing Decision Logic from Exe | compares / compares (0.98) | neutral / neutral (1.00) | yes / 1.00 |
| `W7162563163#3` | MedGuideX: Internalizing Decision Logic from Exe | background / background (0.86) | neutral / neutral (0.95) | no / 0.00 |
| `W7163655861#1` | Auxiliary diagnosis and risk assessment of cardi | **builds_on / background (0.67)** | neutral~ / neutral (0.99) | no / 0.00 |
| `W7163655861#2` | Auxiliary diagnosis and risk assessment of cardi | **compares~ / background (0.83)** | **supports / neutral (0.70)** | no / 0.00 |
| `W7163655861#3` | Auxiliary diagnosis and risk assessment of cardi | background~ / background (0.92) | **supports / neutral (0.85)** | no / 0.00 |
| `W7163655861#4` | Auxiliary diagnosis and risk assessment of cardi | **builds_on / background (0.73)** | neutral~ / neutral (0.82) | no / 0.00 |
| `W7168282280#1` | The Path to Self-Evolving Clinical Systems: Scal | background / background (0.93) | neutral / neutral (0.82) | no / 0.00 |
| `W7212714462#1` | Reinforcement Learning over Patient Trajectories | background / background (0.99) | neutral~ / neutral (0.98) | no / 0.00 |
| `W7224777148#1` | Latent Decision Flow Rewards for Clinical Guidel | background / background (0.94) | neutral / neutral (0.84) | no / 0.00 |
| `W7224777148#2` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.96) | neutral / neutral (1.00) | no~ / 0.00 |
| `W7224777148#3` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.95) | neutral / neutral (0.99) | yes / 0.93 |
| `W7224777148#4` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.97) | neutral / neutral (1.00) | yes / 0.99 |

## Labeller's notes

- `W7224512487#1`: Listed among related approaches (multi-objective rewards). The next sentence says current slow-thinking medical LLMs lack uncertainty assessment, which arguably covers the target, so a reader could call this critiques.
- `W7224580160#1`: Says RL post-training can improve medical reasoning but needs heavy compute and high-quality rationales. Credit and limitation in one sentence.
- `W7154719127#1`: One of six works in a single bracket about training reasoning models. Perfunctory.
- `W7157260422#1`: Cited as a source for the claim that linear reasoning leads to error propagation, the problem the citing paper addresses. The weakness is not the target's own, so stance is neutral. Background is also defensible.
- `W7160921908#1`: Says multi-objective rule-based clinical RL rewards, with the target first in the bracket, are grounded in static references rather than real care-team actions.
- `W7160921908#2`: Says most clinical LLM studies, target included, stop at benchmark numbers.
- `W7160921908#3`: A literature comparison table flattened into a list of references. From the text alone it is a listing; the original table may be a design comparison.
- `W7162563163#1`: Cited as a source for the claim that existing training data is weakly aligned with clinical decision procedures. Negative sentence, but the target is the witness, not the accused. Background is also defensible.
- `W7162563163#2`: Results table row reporting scores for Clinical-R1-3B as a baseline.
- `W7162563163#3`: Related work: listed as using guideline constraints as RL rewards.
- `W7163655861#1`: Says the implementation draws on recent advances. 'Recent advances' is generic, so neutral by rule 3, but some would read it as supportive.
- `W7163655861#2`: Says the reward design aligns with the target's emphasis on comprehensive reward signals. A similarity statement; background is also defensible.
- `W7163655861#3`: Cites the target as part of a growing body of evidence for a claim the authors endorse. The wording 'builds on' could pull this to builds_on.
- `W7163655861#4`: Building on PPO and recent advances, reports its own method's gain. The number is for the citing paper's method, not the target, so own_evidence is no.
- `W7168282280#1`: Survey sentence describing what Clinical-R1 introduces. The description (constrained RL, safety constraints) does not match the paper's abstract well, but that is accuracy, not stance.
- `W7212714462#1`: One of seven works listed as RL-based alignment for medical LLMs. The next sentence says these models perform strongly, which some would read as supports.
- `W7224777148#1`: Describes what CRPO rewards, alongside two other methods.
- `W7224777148#2`: Names Clinical-R1 (CRPO) as a primary baseline. No result in this passage, though it implies one exists.
- `W7224777148#3`: Results text and table row with CRPO scores; the citing method scores higher. Outperforming is not criticism by rule 1.
- `W7224777148#4`: Results table row with CRPO scores.
