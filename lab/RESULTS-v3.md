# Worker lab v3: DeepSeek V4.1 Flash vs GLM-5.3-Flash vs MiniMax M3.1 Flash (2026-11-15)

All three via the paid OpenCode Go endpoint (`opencode-go/...`), opencode v2.3.0, same machine, same
fixtures and model-independent checkers. Base tier = the 19 rebuilt runs from lab v2 (18 scored).
Hard tier = 7 new agentic repo tasks (`hard.py`), 2 runs each; checkers validated on reference
solutions (all pass) and pristine fixtures (all fail); the thread-safety check was confirmed to catch
an unlocked implementation.

| | DeepSeek V4.1 Flash | GLM-5.3-Flash | MiniMax M3.1 Flash |
|---|---|---|---|
| Base tier | **17/18** | 16/18 | 14/18 |
| Hard tier (full pass) | 14/14 | 14/14 | 14/14 |
| Base seconds / hard seconds | 194 / 619 | 247 / **418** | 169 / 931 |
| Input tokens (incl. cache reads) / output+reasoning | 2.02M / 82k | **1.20M / 51k** | 3.45M / 159k |
| Cost upper bound (cache reads at input price, DeepSeek at peak) | $0.70 | **$0.21** | $0.61 |
| Go monthly budget | $100 | $60 | $20 |

Failures
- DeepSeek: t08 README 20 lines (limit 15). Same model passed t08 in lab v2 (free tier) → variance.
- GLM-5.3-Flash: t06 wrong line number on pasted 396-line file (229, true 184) — the original lab's
  line-drift weakness; t08 README 18 lines.
- MiniMax: dropped newline characters inside its own output twice (t01 bullets merged; t11_low2 code
  `best_point = coord    return best_point` → SyntaxError) — confirmed in the raw event stream, not a
  parser artefact; t06 off by one (185); t08 16 lines; t05 built an 8-file Node app for a vague request.

Conclusions
- With a detailed six-block spec, all three solve these mid-size repo tasks; the hard tier did not
  discriminate either. Differences are reliability and cost, not capability on this set.
- All three ignored a numeric length limit at least once → such limits must be checked mechanically.
- MiniMax is unsuitable as a code writer (newline corruption) and has the smallest budget.
- Role choice: worker DeepSeek (most reliable, largest budget), tester GLM-5.3-Flash (different family,
  cheapest, fastest), escalation GLM-5.3-Flash. MiniMax not used.
- Limits: n=1 per base run, n=2 per hard task; tasks are synthetic; harder/repo-scale differences unknown.
