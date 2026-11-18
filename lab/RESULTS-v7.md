# Tester lab v7: GPT-6 Luna vs Haiku 5.5 / Qwen3.7 Plus#high (2026-11-16)
Same tester template, 1 rep, Luna at default effort. Question: is GPT-6 Luna (OpenAI family) a better tester than Haiku?

## Synthetic (7 hard tasks, 28 validated mutants)
| Model | Ref pass | Mutants killed | Tests | Seconds | Tokens in(cache)/out | ≈$ |
|---|---|---|---|---|---|---|
| GPT-6 Luna | 6/7 (h04 test wrong) | 22/28 | 66 | 258 | 232k/24k | ~0.02 |
| Haiku 5.5 | 7/7 | 28/28 | 164 | 222 | 367k/53k | ~0.03 |
| Qwen3.7 Plus#high | 7/7 | 25/28 | 278 | 1195 | 673k/69k | ~0.14 |

## Real specs (BA-38, BA-32b; ref = main 7e41e58, only version bumps since 1b1a82a; base = pre-merge 503bcba)
Every failure on ref is a TEST_HATASI (ref is the reviewed, merged implementation).
| Model | Task | Tests | Fail on ref | Fail on base | Seconds | ≈$ |
|---|---|---|---|---|---|---|
| GPT-6 Luna | BA-38 | 21 | 4 (selection count 52≠46, older-than, title fallback, 40-section order) | 21/21 | 372 | 0.040 |
| GPT-6 Luna | BA-32b | 6 | 0 | 4/6 | 87 | 0.009 |
| Haiku 5.5 | BA-38 | 26 | 2 | 26/26 | 198 | 0.011 |
| Haiku 5.5 | BA-32b | 10 | 0 | 6/10 | 123 | 0.007 |
| Qwen3.7 Plus#high | BA-38 | 48 | 3 | 48/48 | 631 | 0.097 |
| Qwen3.7 Plus#high | BA-32b | 8 | 1 | 5/8 | 912 | 0.165 |
(Haiku/Qwen rows re-scored on the same ref/base: identical to v6.)

Conclusion: Luna is worse than Haiku on every quality measure (ref-pass, mutation score, TEST_HATASI 4 vs 2, fewer
tests) and not cheaper on real specs. Keep Haiku as tester, Qwen as fallback; Luna not adopted. Limit: n=1 rep.
Data: lab tester run luna6 (tester_luna6.log); real-task runs in the session scratchpad (tcmp/luna6).
