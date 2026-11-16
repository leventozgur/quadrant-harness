# Worker lab v4: candidate Go models as worker and as tester (2026-11-16)

Correction to earlier notes: the OpenCode Go budget is a **single shared pool** (5-hour, weekly, monthly),
not a per-model budget (user correction 2026-11-16). Per-token price therefore costs the whole pool.

## Worker role (base 19 runs + hard 7x2, same checkers as v3)
Effort-variant runs (#low/#max) removed where the model rejects variants ("Variant unavailable").

| Model | Base (valid) | Hard | Hard s | Tokens in/out | Notable failure |
|---|---|---|---|---|---|
| DeepSeek V4.1 Flash | 17/18 | 14/14 | 619 | 2.0M/82k | README limit |
| GLM-5.3-Flash | 16/18 | 14/14 | 418 | 1.2M/51k | line drift, README limit |
| Kimi K2.7 Code | 14/14 | 13/14 | 622 | 1.5M/58k | one edge case; expensive per token |
| LongCat-2.0 | 13/14 | 14/14 | 1276 | 1.5M/99k | line drift; slowest |
| MiMo-V2.6-Pro | 14/14 | 13/14 | 923 | 1.2M/66k | one 20-min stall (timeout) |
| Qwen3.7 Plus | 15/16 | 11/14 | 796 | 1.0M/72k | wrote a tool call as plain text and stopped; README 24 lines |

## Tester role (harness tester template, hidden tests from spec; 28 validated mutants)
"Ref pass" = the generated suite passes on the reference solution (a failing suite would reject correct worker code).
Kill rate counts only suites that pass on the reference. Cost = upper bound (cache reads at input price).

| Model | Ref pass | Mutants killed | Seconds | Tokens in/out | ≈$/run |
|---|---|---|---|---|---|
| **Qwen3.7 Plus** | **7/8** | 25/28 | 1035 | 0.52M/59k | **0.04** |
| LongCat-2.0 | 7/7 | 27/28 | 2753 | 1.97M/178k | 0.11 |
| MiMo-V2.6-Pro | 8/10 | 32/32 | 4129 | 2.84M/234k | 0.14 |
| GLM-5.3-Flash (previous tester) | 4/8 | 16/16 | 908 | 0.75M/64k | 0.02 |
| Kimi K2.7 Code | 3/8 | 12/12 | 958 | 0.97M/66k | 0.15 |

## Decision
- Worker stays DeepSeek V4.1 Flash #low; escalation stays GLM-5.3-Flash.
- Tester changes from GLM-5.3-Flash to Qwen3.7 Plus (harness config updated).
- LongCat-2.0 is the high-assurance tester option (7/7, 27/28) at ~3x cost and ~3x time.
- Not used: Kimi K2.7 Code (wrong expectations as tester, expensive), MiMo-V2.6-Pro (slow, expensive), MiniMax M3.1 Flash.

## Lab issues found and fixed
- Scorer ran tests away from the path the tester saw; testers that hardcoded the project path failed unfairly → scorer now places each solution at that path.
- Two mutants were not real behaviour changes (rounding mode not distinguished; TypeError already raised) → checker case added / mutant replaced; all 28 verified.
- Nine parallel runs filled the disk and hit rate limits; tester runs crashed on uncaught timeouts → sequential queue, timeout handling, resume.
- Limits: 7–10 tester runs per model, 1 repetition per task for most; synthetic tasks.
