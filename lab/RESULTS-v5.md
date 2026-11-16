# Lab v5: model-specific prompts and effort (2026-11-16)

Research: Qwen3.7 Plus#high with web tools wrote `research/result-{deepseek,qwen,glm}.md` (sources and confidence
marked per finding; some sources are community/third-party). Common findings: no "think step by step" with thinking
models; role and task first, hard limits repeated at the end; English prompts safer for coding, ask for the output
language explicitly; DeepSeek default effort is high (harness used #low); GLM forced thinking, low for classification.

Effort variants available on Go (probed): DeepSeek default/low/high/max; Qwen3.7 Plus default/high/max;
GLM-5.3-Flash default/low/high/max; LongCat-2.0 default only.

## Worker (DeepSeek V4.1 Flash; 19 base + 7 hard, 1 rep; prompts wrapped in the worker template as hx does)
| Arm | Base | Hard | Seconds base/hard | Cost upper bound |
|---|---|---|---|---|
| v1: Turkish template + #low (harness until now) | 17/18 | 7/7 | 356 / 220 | $0.49 |
| v2: English template + default (high) | 18/18 | 7/7 | 420 / 309 | $0.57 |
v1 failure: t02 (text task) — the report text leaked into the answer and broke the "no 've'" rule.

## Tester (Qwen3.7 Plus; 7 hard tasks, 28 validated mutants, 1 rep)
| Arm | Ref pass | Mutants killed (valid suites) | Seconds | Tokens in/out |
|---|---|---|---|---|
| v1: Turkish template with calculation rules, default | 6/7 | 21/28 | 1202 | 0.53M / 66k |
| v2: English template + example, #high | 6/7 | 22/28 | 1148 | 0.61M / 63k |
| (lab v4: old template without rules, default) | 7/8 | 25/28 | 1035 | 0.52M / 59k |
Failures: v1 h07 (CSV quote rule), v2 h06 (exact float equality) → float-tolerance rule added to the template.

## Judge (GLM-5.3-Flash#low), real case
BA-31 original hidden tests (2 contradicted the spec): both classified TEST_HATASI with the calculation, 139 s, ~$0.03.

## Decision
Worker → English template, default effort. Tester → English template, #high. Judge → #low. Escalate → GLM #high.
Differences are within noise at n=7–18 (one task each way); the lab is saturated. Prompts and effort do not make
these models equal to Opus; the gate, hidden tests, judge and blind review are what hold the quality line.

## Correction 2026-11-16 (cost)
The cost column above priced cache reads at the full input rate and DeepSeek at $0.30/$1.20 instead of the Go rates (models.dev: $0.15 in / $0.60 out / $0.003 cache read). Absolute dollars are 10–25x too high; the v1 vs v2 ratio is not comparable either, because the two arms have different cache shares. Quality results are unaffected. `lab/score_all.py` now uses `hx.est_cost`.
