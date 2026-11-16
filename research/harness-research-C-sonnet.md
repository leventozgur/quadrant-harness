# hx research round 2 (Sonnet 5.5, 2026-11-17) - quality-first

Legend: [O]=opened page this session, [S]=only seen in search-result snippet (lower trust). Trust: official / paper / community.

## 1. FINDINGS
1. Spec ambiguity: ClarifyGPT (consistency check on sampled code/tests decides if a requirement is ambiguous, then asks questions) lifts GPT-4 pass@1 68.02 -> 75.75 avg over 4 benchmarks; human eval 70.96 -> 80.80 - https://arxiv.org/abs/2310.10996 [O] - paper
2. TiCoder: tests as partial formalization of intent, <=5 interactions, avg +45.97 abs pass@1 (idealized user proxy) - https://arxiv.org/abs/2404.10100 [O] - paper
3. Ask or Assume (decouple underspecification detection from coding): SWE-bench Verified underspecified, OpenHands+Sonnet 4.5 69.40% vs 61.20% single agent - https://arxiv.org/abs/2603.26233 [O: 69.40; 61.20 from search snippet] - paper
4. Ambig-SWE: models cannot tell well- from under-specified instructions on their own; interaction gives up to +74% - https://arxiv.org/abs/2502.13069 [S] - paper
5. Test flaws dominate benchmark noise: OpenAI audit of hard Verified subset found >=59.4% had tests rejecting correct solutions (the page itself returned 403; figure from search summary) - https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ [S] - official
6. Anthropic evals guidance: 0% pass over many trials usually = broken task/grader; every task needs a reference solution passing all graders; good task = two experts reach same verdict; CORE-Bench Opus 4.5 42% -> 95% after fixing rigid grading/ambiguous specs (96.12 vs 96.1249..) - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents [O] - official
7. Weak tests accept wrong patches: UTBoost found 15.7% (Verified) / 28.4% (Lite) of originally passing patches wrong after LLM-augmented tests; 5.2% of Verified instances had insufficient tests - https://arxiv.org/abs/2506.09289 [S] - paper
8. PatchDiff: 29.6% of plausible patches diverge in behaviour from ground truth, 28.6% of those confirmed wrong; SWE-bench resolution inflated 6.2 pts; causes: similar-but-divergent implementation 46.8%, adapts extra behaviour 27.3% - https://arxiv.org/abs/2503.15223 [O] - paper
9. Test overfitting with generated tests (IBM): patches overfit generated tests in 21.8% (Claude 3.7) / 33.0% (GPT-4o) of instances; test-driven refinement raised overfit to 25.5%/35.9%; of 22 refinement "fixes", 14 failed golden tests; coverage of overfit patches lower (median <0.8 vs 1) - https://arxiv.org/html/2511.16858v3 [O] - paper. Implication: visible generated tests are a weak signal; coverage is a cheap overfit alarm.
10. SWT-Bench: generated reproduction tests used as a filter double SWE-Agent precision - https://arxiv.org/abs/2406.12952 [O]; AssertFlip: write tests that PASS on current behaviour then invert; 43.6% fail-to-pass on SWT-Bench-Verified - https://arxiv.org/abs/2507.17542 [O] - papers
11. Property-Generated Solver: property-based tests + minimal counterexample as feedback; up to +13.4% pass@1 over TDD baselines, >64% fix rate on initially failed problems, 1.4-1.6x bug-fix rate vs debugging baselines; claim: models write properties more reliably than exact outputs - https://arxiv.org/abs/2506.18315 [O] - paper
12. Meta ACH: mutation-guided test generation, 571 tests from 9,095 mutants over 10,795 classes; equivalent-mutant detector precision 0.79/recall 0.47 -> 0.95/0.96 with preprocessing; engineers accepted 73% of tests - https://arxiv.org/abs/2501.12862 [O] - paper (industry)
13. Agentic Rubrics (Scale): repo-grounded checklist (File Change, Spec Alignment, Integrity, Runtime) graded without execution; ROC-AUC 0.886 vs ground-truth tests; Best@16 54.2% (Qwen3-Coder-30B); rubric flags disagreeing with tests were substantive in 54% of cases (missed root causes, uncovered edges); removing repo access from rubric generation -1.4 to -4.0 pts - https://labs.scale.com/blog/agentic-rubrics [O] - paper/vendor blog
14. Anthropic long-running harness: JSON feature list with `passes` flag (agent may only flip it, not edit/remove tests; JSON chosen because models overwrite Markdown more), init.sh, progress file + git log read at each session start, run a basic e2e test BEFORE new work, one feature per session; browser-automation e2e testing beat unit/curl for catching bugs; open question whether specialist QA agents help - https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents [O] - official
15. Claude Code best practices: "give Claude a check to run", missing self-verification is the main cause of "said done but wasn't" (only intro read; page is 51KB, details not verified) - https://code.claude.com/docs/en/best-practices [O partially] - official
16. Verifiers: R4P patch verifier 72.2% accuracy on Verified patches; SWE-World generative verifier holds up as candidate set grows - https://arxiv.org/pdf/2510.22775, https://arxiv.org/pdf/2602.03419 [S] - papers
17. Carried from previous round (DeepSeek-reported, hand-verified only for model card): mini-SWE 74.2 vs OpenCode 65.5 on DeepSWE v1.1 at max effort.

## 2. CRITIQUE of HX-01..HX-11
Strong (keep, user-approved): HX-02 oracle table (matches Anthropic "experts reach same verdict" + CORE-Bench arithmetic lesson; add the formula, not just the value), HX-04 check.sh, HX-11 context map (but keep it as a pointer map, see risk below).
- HX-01 two-reference quarantine: strong idea but QUALITY-RISKY as written. Two cheap refs agreeing on a wrong interpretation will quarantine a correct test (and refs fail on both = "suspect" is also what a hard-but-correct test looks like). Fix: quarantine only routes to judge, never deletes; and the reference must be built from the oracle table (see N2). Also quarantined tests must still be re-run against the final worker code.
- HX-03 judge recompute: sound; keep an Opus spot check of a sample, since the judge is the same weak family.
- HX-05 minimal scaffold: strong evidence but model-card gap is at max effort and different harness; risk of losing opencode tools (lint/LSP) - must be A/B'd, not assumed.
- HX-06 max effort for hard tasks: low risk; keep.
- HX-07 skip 3rd worker turn: QUALITY-RISKY (it is a "fewer retries" variant). Drop or reframe as "change the retry prompt", never remove a retry.
- HX-08 nudge instead of kill: fine, but a nudge could lengthen runaway sessions; keep wall-clock hard kill as backstop.
- HX-09 cheap reviewer for low-risk diffs: VIOLATES the hard rule (cheaper reviewer). Remove.
- HX-10 narrow reviewer context: VIOLATES hard rule (UTBoost/PatchDiff: wrong patches are mostly "similar but divergent" and "extra behaviour" - exactly what needs wider context: callers, siblings). Remove; Agentic Rubrics shows repo access matters (-1.4..-4.0).
- HX-11: ok as hint map, but a locator map from a weak model can anchor Opus on wrong files; mark it "unverified hints".
- Elimination note: "worker writes own tests - dropped" is right for hidden-test leakage but see N6 (worker may write non-binding self-checks from the oracle table, not tests).

## 3. NEW HYPOTHESES (quality-raising only)

N1 Spec ambiguity gate (pre-spec clarification, ClarifyGPT/Ask-or-Assume style)
- Mechanism: after Opus drafts SPEC, two different-family cheap models (GLM, Qwen) each independently restate the task as 5 concrete input->output examples without seeing each other. Disagreement on any example = ambiguity candidate; Opus resolves it in the SPEC (adds a rule/oracle row) before worker and tester start. Same-spec disagreement is the ClarifyGPT consistency signal, with Opus as the "user".
- Targets: TEST_ERROR (tester and worker each guessing a different reading) and CODE_ERROR from ambiguous rules.
- Expected: ClarifyGPT +7.7 avg pass@1 (GPT-4); Ask-or-Assume 61.2 -> 69.4 resolve. Our 90% TEST_ERROR share suggests the largest lever is here.
- Measure: replay R specs (BA-38, BA-32b, Codart P1-P6): count disagreement items; check whether disagreements predict the tests that fell on ref (precision/recall). Then re-run tester on patched specs, 3 reps: ref-failing tests/task vs baseline.
- Quality risk: none because it only adds clarifications to the spec; it changes no gate and spends cheap-model tokens plus a bit of Opus time.

N2 Executable oracle: reference implementation derived from the oracle table, tests must pass on it (tester self-validation done safely)
- Mechanism: from the oracle table (HX-02) generate a trivial table-driven stub (`lookup` of exact rows). Every hidden test whose inputs are IN the table must pass on the stub; tests whose expectation comes from outside the table are flagged "uncovered by oracle" and shown to Opus/judge. Do NOT use an LLM-written full reference for pass/fail filtering (shared errors; tests that fail on wrong refs get deleted = weaker suite).
- Targets: TEST_ERROR of the "wrong expected value" kind.
- Expected: Anthropic evals guidance (reference solution must pass all graders; CORE-Bench 42 -> 95); IBM paper shows generated tests alone are unreliable signal (14/22 false fixes).
- Measure: R specs with seeded wrong oracle rows (inject 3 wrong rows per spec): does the mechanism flag them (recall) and how many correct tests are flagged (precision)? 3 reps. Also count mutants killed on S before/after (must not drop).
- Quality risk: none because no test is removed or weakened; flagged tests go to judge/Opus, and uncovered ones remain in the suite.

N3 Property/invariant tests from spec in addition to example tests
- Mechanism: tester writes, per spec rule, a property (idempotence, monotonicity, round-trip, conservation, ordering, "output subset of input") using hypothesis/fast-check with seeded runs, plus the example tests. Properties avoid computing exact expected values, the main source of TEST_ERROR, and kill more mutants. On failure the harness feeds back the shrunk minimal counterexample (PGS finding).
- Targets: TEST_ERROR (fewer hand-computed values) and escaped defects (weak suites).
- Expected: PGS +13.4% pass@1 vs TDD baselines, 1.4-1.6x fix rate; UTBoost/PatchDiff show example suites miss 15.7%/28.6%-of-divergent wrong patches.
- Measure: S lab (28 mutants): mutant kill rate with vs without properties, 3 reps; on R: ref-failing property tests/task (must be <= example tests). Judge-confirmed TEST_ERROR rate per test type.
- Quality risk: none because properties are additive; a bad property is caught by the ref run and the judge, as is any test.

N4 Test-spec traceability matrix with coverage audit by a second model
- Mechanism: tester must emit `trace.json` mapping each SPEC rule/boundary ID (Opus numbers them R1..Rn) to test names and the derivation line. A different-family auditor (not the judge) checks (a) every ID covered, (b) the derivation really follows the rule, (c) ID with no test. Gaps trigger tester re-run for those IDs only.
- Targets: both TEST_ERROR (derivation audited) and escaped defects (uncovered rules), with a deterministic coverage check on top (mapped IDs missing = automatic fail).
- Expected: Agentic Rubrics: rubric-vs-test disagreements were substantive in 54% of cases (uncovered edges, missed root causes) - i.e. tests miss what a spec-derived checklist catches.
- Measure: R specs: share of rules without any test in current hidden suites (baseline gap); after matrix, mutants killed on S and number of spec rules with zero tests.
- Quality risk: none because it only adds coverage and an audit; nothing is removed.

N5 Mutation testing of the hidden suite on the final code (post-gate defect hunt)
- Mechanism: after gate PASS, run mutmut/cosmic-ray/Stryker restricted to the diff, using the hidden+visible suite. Surviving mutants (after LLM equivalent-mutant filter, ACH-style) go to a tester round that writes tests to kill each; new tests run on the final code, any failures go back to the worker/judge. Survivors also go to the Sonnet reviewer as "untested behaviour in this diff".
- Targets: escaped defects, weak suites (the 50% FAIL rate says tests are strict about wrong things but possibly loose about right ones).
- Expected: Meta ACH 73% of generated tests accepted by engineers; equivalent-mutant filter 0.95/0.96; UTBoost shows ~16-28% of "passing" patches are wrong.
- Measure: seed S lab with 28 verified mutants applied to worker output; compare escaped-defect counts at gate vs after mutation round; on R, count surviving mutants per diff and how many correspond to a real defect found by hand. 3 reps.
- Quality risk: none because it runs after the gate and only adds tests/information; added tests cannot lower pass quality (a wrong new test goes through the judge).

N6 Self-check from the oracle table (non-binding) plus coverage guard for the worker
- Mechanism: the worker gets the oracle table as `oracle.json` + a tiny runner script (visible, not the hidden tests) and must run it; harness runs a coverage report on the diff and flags changed lines not executed by any visible/oracle check (overfit signal from IBM paper: overfit patches had lower coverage). Spec's "Bitirme" command includes both.
- Targets: CODE_ERROR and timeouts of the "declared done early" type (Anthropic harness: premature done; Claude Code docs: no check to run).
- Expected: IBM paper: coverage lower for overfit patches (<0.8 median); Anthropic: self-verification against explicit steps is the main fix for premature completion.
- Measure: worker hard set (lab/hard.py) 3 reps: first-turn gate PASS rate, escaped defects, visible-run compliance. Check the worker does not edit the oracle (glob guard in gate).
- Quality risk: none because the oracle file comes from Opus's spec and is protected by the glob gate; the gate still runs the full hidden suite.

N7 Rubric review in addition to the blind Sonnet review (spec-derived checklist, execution-grounded)
- Mechanism: Opus's SPEC already has numbered rules; before review, a cheap model turns them into a repo-grounded checklist across 4 axes (File Change, Spec Alignment, Integrity: hardcoding/skips/test edits, Runtime) and runs targeted commands (grep for hardcoded expected values, `git diff --stat` vs scope, run touched module under the oracle runner). Sonnet gets SPEC + diff + gate result + checklist verdicts + execution transcript. Sonnet remains and keeps full repo access.
- Targets: escaped defects ("similar but divergent", "extra behaviour", hardcoding to pass tests).
- Expected: PatchDiff: 46.8% of divergent patches are similar-but-divergent, 27.3% adapt extra behaviour (both catchable by a scope/rule checklist); Agentic Rubrics ROC-AUC 0.886 and 54% substantive disagreements with tests.
- Measure: replay past reviews/diffs (BA, Codart): count genuine findings Sonnet-alone vs Sonnet+checklist; seed 10 defects of PatchDiff types (extra behaviour, near-miss logic) into correct diffs, 3 reps, measure catch rate.
- Quality risk: none because Sonnet's input is a strict superset (no context removed); extra Sonnet tokens are small. Reviewer still blind to worker rationale.

N8 Different-family second reviewer in parallel on high-impact diffs (additive, not replacement)
- Mechanism: add one Qwen3.7/GLM reviewer with an adversarial prompt ("write the failing input for the weakest rule") run in parallel; findings are executed as a concrete counterexample (a test) before reaching Sonnet/Opus; non-reproducing findings are dropped as noise.
- Targets: escaped defects, shared-family blind spots between worker (DeepSeek) and Sonnet.
- Expected: no direct benchmark number found; supported indirectly by verifier literature (R4P 72.2% patch verification, Agentic Rubrics Best@16 gains) and by execution-validated tests as filter (SWT-Bench: 2x precision). Treat as an experiment.
- Measure: seeded-mutant lab, catch rate of (Sonnet) vs (Sonnet + adversarial counterexample generator), false-positive count per diff after execution filter, 3 reps.
- Quality risk: none because it only adds findings; only reproduced counterexamples are forwarded, so reviewer attention is not diluted.

N9 Reproduce-first / plan-then-code worker prompt with plan checkpoint against the spec
- Mechanism: worker turn 1 writes `plan.md` (per rule ID: file + function it will change, per boundary: how it handles it) and a failing repro of the oracle runner on the unchanged tree; cheap deterministic check that every rule ID appears in the plan; then implement. Failing-first run proves the oracle runner actually exercises the change (a check that cannot fail is useless, per Anthropic eval advice).
- Targets: worker CODE_ERROR (missed rules), timeouts (less thrashing), scope creep ("extra behaviour" 27.3% in PatchDiff).
- Expected: Ask-or-Assume style decoupling raised resolve 61.2 -> 69.4 for a related reason (separating uncertainty handling from coding); no direct number for plan-then-code on V4.1 Flash, so this is an experiment, A/B only.
- Measure: lab/hard.py + base set, 3 reps: first-turn gate PASS, scope violations, steps; stop if timeouts increase.
- Quality risk: none because the worker still must pass the same gate; plan.md is a harness artifact outside the diff, and a plan step cannot lower the checks.

N10 Cross-run progress file + gate-state JSON for phased tasks (Anthropic harness pattern)
- Mechanism: for phased tasks, harness writes `progress.json` (phase id, rule IDs `passes: true/false` flipped only by the harness from gate results, last gate diff, open judge verdicts) and the worker reads it at start; each new worker session first reruns previous-phase checks (test-before-work) so a phase-N regression is caught before phase N+1 builds on it.
- Targets: stalls/timeouts recovery, regressions across phases, premature "done".
- Expected: Anthropic: structured JSON passes-flag list, one feature per session, e2e check before new work; they note it caught bugs left by the previous session. No numbers published.
- Measure: Codart P1-P6 replay, 3 reps: regressions introduced in later phases, rerun time cost, phase-level first-pass gate rate.
- Quality risk: none because the harness, not the worker, owns the flags and every earlier check is rerun.

## Notes and caveats
- Items 4, 5, 7, 16 are search-snippet only; open the primary pages before betting engineering effort. OpenAI page returned 403.
- No source found for DeepSeek V4.1 Flash-specific plan-then-code effect; N9 and N8 are experiments, not evidence-backed bets.
- Ordering by expected leverage on our 90% TEST_ERROR problem: N1, N2, N3, N4 (tests), then N5/N7 (escaped defects), N6/N9 (worker), N8, N10.
