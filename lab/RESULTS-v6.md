# Tester lab v6: Claude Haiku 5.5 vs Qwen3.7 Plus#high (2026-11-16)
Same current tester template (with the float-tolerance rule), 1 rep. Haiku at default effort.

## Synthetic (7 hard tasks, 28 validated mutants)
| Model | Ref pass | Mutants killed | Seconds | Tokens in(cache)/out | ≈$ |
|---|---|---|---|---|---|
| Haiku 5.5 | 7/7 | 28/28 | 222 | 367k/53k | ~0.03 |
| Qwen3.7 Plus#high | 7/7 | 25/28 | 1195 | 673k/69k | ~0.14 |

## Real specs (BA-38, BA-32b; tests run on main 1b1a82a = ref and pre-merge 503bcba = base)
| Model | Task | Tests | Fail on ref (all TEST_HATASI) | Fail on base | Seconds | ≈$ |
|---|---|---|---|---|---|---|
| Haiku 5.5 | BA-38 | 26 | 2 (trailing empty line not counted) | 26/26 | 198 | 0.011 |
| Haiku 5.5 | BA-32b | 10 | 0 | 6/10 | 123 | 0.007 |
| Qwen3.7 Plus#high | BA-38 | 48 | 3 (undated section expected moved; text format; wordsAfter ignores back-link) | 48/48 | 631 | 0.097 |
| Qwen3.7 Plus#high | BA-32b | 8 | 1 (byte-identical full vs progressive, same as original run) | 5/8 | 912 | 0.165 |

Conclusion: Haiku 5.5 is better or equal on every measure, ~5x faster, ~10x cheaper. Limit: n=1 rep.
Data: lab tester runs hk55 / qw_v3high; real-task runs in the session scratchpad (tcmp).
