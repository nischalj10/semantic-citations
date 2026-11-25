# Decision model vs hand labels: arxiv-2512.00601

14 citation contexts from 7 citing papers.
6 hand labels are for citations that were not found this run (their papers are not on arXiv) and are excluded: W7224512487#1, W7224580160#1, W7163655861#1, W7163655861#2, W7163655861#3, W7163655861#4

## Agreement

| Question | All contexts | Clear-cut only | Top answer changed with option order |
|---|---|---|---|
| `function` | 11/14 (79%) | 10/11 (91%) | 3 of 14 |
| `stance` | 13/14 (93%) | 12/13 (92%) | 4 of 14 |
| `own_evidence` (threshold 0.5) | 14/14 (100%) | 13/13 (100%) | n/a |

Brier score for `own_evidence`: 0.000 (0 is perfect, 0.25 is a coin flip).

## Does confidence track correctness?

Confidence is the probability of the chosen option, averaged over option orders.

| Question | Confidence | Contexts | Agree with hand label |
|---|---|---|---|
| `function` | 0.90 - 1.00 | 8 | 7/8 (88%) |
| `function` | 0.70 - 0.90 | 2 | 2/2 (100%) |
| `function` | below 0.70 | 4 | 2/4 (50%) |
| `stance` | 0.90 - 1.00 | 8 | 8/8 (100%) |
| `stance` | 0.70 - 0.90 | 3 | 3/3 (100%) |
| `stance` | below 0.70 | 3 | 2/3 (67%) |

- `function`: mean confidence 0.88 when it agrees (11), 0.77 when it disagrees (3).
- `stance`: mean confidence 0.88 when it agrees (13), 0.64 when it disagrees (1).

## Review flag

A context is flagged when either choice is below the review threshold (default 0.90).

- Not flagged: 7 contexts, of which 6/7 (86%) match the hand label on both questions.
- Flagged: 7 contexts, of which 5/7 (71%) match on both.
- Contexts with any disagreement: 3, of which 2/3 (67%) were flagged.

## `function`: hand label (rows) vs model (columns)

| | background | compares | motivates |
|---|---|---|---|
| **background** | 5 | 0 | 0 |
| **compares** | 1 | 4 | 0 |
| **motivates** | 2 | 0 | 2 |

## `stance`: hand label (rows) vs model (columns)

| | critiques | neutral |
|---|---|---|
| **critiques** | 1 | 1 |
| **neutral** | 0 | 12 |

## Every context

Hand label / model label (confidence). **Bold** marks a disagreement; `~` marks a label the labeller flagged as borderline.

| Context | Citing paper | function | stance | own_evidence |
|---|---|---|---|---|
| `W7154719127#1` | RadAgent: A tool-using AI agent for stepwise int | background / background (0.92) | neutral / neutral (0.98) | no / 0.00 |
| `W7162563163#1` | MedGuideX: Internalizing Decision Logic from Exe | motivates~ / motivates (0.62) | neutral / neutral (0.55) | no / 0.00 |
| `W7162563163#2` | MedGuideX: Internalizing Decision Logic from Exe | compares / compares (0.88) | neutral / neutral (1.00) | yes / 0.99 |
| `W7162563163#3` | MedGuideX: Internalizing Decision Logic from Exe | background / background (0.93) | neutral / neutral (0.95) | no / 0.00 |
| `W7160921908#1` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | motivates / motivates (0.65) | critiques / critiques (0.56) | no / 0.00 |
| `W7160921908#2` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | **motivates / background (0.66)** | **critiques / neutral (0.64)** | no / 0.00 |
| `W7160921908#3` | CLR-voyance: Reinforcing Open-Ended Reasoning fo | **compares~ / background (0.97)** | neutral / neutral (1.00) | no / 0.00 |
| `W7168282280#1` | The Path to Self-Evolving Clinical Systems: Scal | background / background (0.88) | neutral / neutral (0.86) | no / 0.00 |
| `W7157260422#1` | Thinking Like a Clinician: A Cognitive AI Agent  | **motivates~ / background (0.68)** | neutral / neutral (0.76) | no / 0.00 |
| `W7212714462#1` | Reinforcement Learning over Patient Trajectories | background / background (0.99) | neutral~ / neutral (0.98) | no / 0.00 |
| `W7224777148#1` | Latent Decision Flow Rewards for Clinical Guidel | background / background (0.94) | neutral / neutral (0.76) | no / 0.00 |
| `W7224777148#2` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.94) | neutral / neutral (1.00) | no~ / 0.00 |
| `W7224777148#3` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.96) | neutral / neutral (1.00) | yes / 0.98 |
| `W7224777148#4` | Latent Decision Flow Rewards for Clinical Guidel | compares / compares (0.98) | neutral / neutral (1.00) | yes / 0.98 |

## Labeller's notes

- `W7154719127#1`: One of six works in a single bracket about training reasoning models. Perfunctory.
- `W7162563163#1`: Cited as a source for the claim that existing training data is weakly aligned with clinical decision procedures. Negative sentence, but the target is the witness, not the accused. Background is also defensible.
- `W7162563163#2`: Results table row reporting scores for Clinical-R1-3B as a baseline.
- `W7162563163#3`: Related work: listed as using guideline constraints as RL rewards.
- `W7160921908#1`: Says multi-objective rule-based clinical RL rewards, with the target first in the bracket, are grounded in static references rather than real care-team actions.
- `W7160921908#2`: Says most clinical LLM studies, target included, stop at benchmark numbers.
- `W7160921908#3`: A row of a table that compares prior work feature by feature; CRPO is one row. With arXiv HTML the row is visible, so this is a design comparison (it was labelled background when the old source flattened the table into a list of references). No results are reported.
- `W7168282280#1`: Survey sentence describing what Clinical-R1 introduces. The description (constrained RL, safety constraints) does not match the paper's abstract well, but that is accuracy, not stance.
- `W7157260422#1`: Cited as a source for the claim that linear reasoning leads to error propagation, the problem the citing paper addresses. The weakness is not the target's own, so stance is neutral. Background is also defensible.
- `W7212714462#1`: One of seven works listed as RL-based alignment for medical LLMs. The next sentence says these models perform strongly, which some would read as supports.
- `W7224777148#1`: Describes what CRPO rewards, alongside two other methods.
- `W7224777148#2`: Names Clinical-R1 (CRPO) as a primary baseline. No result in this passage, though it implies one exists.
- `W7224777148#3`: Results table row with CRPO scores. Outperforming is not criticism by rule 1.
- `W7224777148#4`: Results table row with CRPO scores.
