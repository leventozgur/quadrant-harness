# hx forensics: real failure data (BrainAtlas BA-*, CodartERP P1-P7), 2026-11-17

Method: parsed all judge-N.jsonl "text" parts (56 TEST_HATASI lines, all accounted for), test_issues.txt, worker/tester jsonl, metrics.jsonl, review/PM feedback files, specs. Unit = one judge verdict LINE (a line can cover several tests: BA-32 line 1 = 3 tests, P2 R12 = 6 tests; by test count the P2/Codart share is larger). Classification is mine (reading judge reason + spec + hidden test); estimates are marked "est".
Data caveats: BA-38 gate 1 and BA-31 gate 1 had no judge run (BA-31 only via replay BA-31J); BA-38's failing tests are unknown. Old metrics.jsonl rows count prose such as "KOD_HATASI yok"/"(yok)" as code errors (BA-36, BA-43 judge-2, P1, P2-r2); hx.py now filters it. Real KOD_HATASI = 5 lines / 4 root causes, not 6-8.

## Q1. Root-cause taxonomy of the 56 TEST_HATASI

| Cat | Meaning | BA (Qwen) | Codart (Haiku) | Total | Share |
|---|---|---|---|---|---|
| G | Source-grep coupling: static text/regex test demands a literal, variable name, syntax form, helper placement or window that the spec does not fix | 0 | 32 | 32 | 57% |
| B | Broken test code / wrong self-derived expectation although spec fixes the answer (missing await, wrong HOME-derived path, bad substring detector, wrong loop) | 14 | 0 | 14 | 25% |
| C | Interface/import/fixture shape assumed (SDK import path, MCP `isError` field) | 5 | 0 | 5 | 9% |
| A | Tester computed/derived wrong expected value that the spec defines | 2 | 0 | 2 | 4% |
| E | Depends on unspecified internals (real search scores) | 1 | 0 | 1 | 2% |
| D | Environment/fixture state (doctor `release` check needs installed release; pre-existing behaviour) | 2 | 0 | 2 | 4% |
| S | Spec silent/ambiguous and tester guessed | 0 | 0 | 0 | 0% |

(S=0 is a judge-view; the judge has a "never guess TEST_HATASI" rule, but testers also listed silent points as untested, see Q5. One BELIRSIZ, BA-43 vault scope, was a real spec premise error.)

Per task (lines): BA-31J 2 (A1,E1) | BA-32 3 (C1,B2) | BA-32b 4 (B3,A1) | BA-36 4 (C4, one shared bad import) | BA-43 11 (B9, D2; rounds of 4+7, the same shared-fixture bug survived the tester-3 rewrite) | P1 1 | P2 11 (5+6; same G classes recurred after tester feedback) | P3 6 | P4 6 | P5 4 | P6 4 (all G).
Per tester: Qwen3.7 Plus(#high) 24 lines over 5 of its ~9 BA tasks (BA-21, BA-28, BA-37 gave 0 TEST_HATASI; BA-38 unknown) and P7 = 0. Haiku 5.5 32 lines, 6/6 Codart tasks failed the first hidden gate (avg 5.3 lines/task) but Haiku on BA-43 phase 1 = 0 and in lab v6/v7 on BA-38/BA-32b = 2 (Node). Confound: the Codart format (".NET not run, only text/regex") and Haiku coincide; the only Qwen Codart run (P7, 0 TH) had the strictest spec wording (brace counting, "prefer presence checks"). Inference: the test STYLE, not the model, is the dominant lever (est; n=1 for Qwen on Codart).

Examples (task / test / why):
- G: P1 CR-004 projection: `body.slice(d, indexOf(';', d))` stops at first `;` inside the block lambda. P2 R5/R9/R13: demands inline `52_428_800`, `Contains("(Hata kodu: ")`, 3 literal `LogWarning("Upload rejected:` calls; code used a const and one `LogRejected` helper (values identical). P3 sort `7 => izlenebilirlikKodu` compact form; P4 literal "Program Files" while code uses `%ProgramFiles%`, `zip\s` marker matches an early error message; P6 expects `Status === 1`, code uses `!== 1`.
- B: BA-32b three tests `JSON.parse(run(...).stdout)` without `await`. BA-43 nine tests compute expected shim path from module-level `home` while each test installs under its own HOME (`home-r4-payload`). BA-32 `ctx.includes('- p')` vs titles `Page01`. BA-32 900+ snippet test appends the blank separator (901 vs 900).
- C: BA-36 imports `node_modules/@modelcontextprotocol/sdk/client/index.js` (real: `dist/esm/client/`); the spec only said `join(WT,'node_modules/…')`. BA-32 reads `result.isError` (SDK omits it on success).
- A: BA-31J expects 0.5*1.5=0.75 item to outrank 0.9 (contradicts the spec's own boundary; this exact case is now the tester.md example). BA-32b expects progressive output byte-identical to full though spec says progressive adds `#anchor`.
- E: BA-31J hook integration asserts order from real search scores (0.28*1.5<0.65).
- D: BA-43 "doctor in cli channel exits 0" with no release installed; pre-existing `checks.release` fails.

Also: 27 hidden tests were SKIPPED by the PM after triage (P2 6, P3 6, P4 7, P5 4, P6 4). That is lost rule coverage, not a fix. P2 says behaviour is covered by the worker-written visible test (not independent).

## Q2. Which spec-side fix prevents which category (est. over 56)

| Fix | G (32) | B (14) | C (5) | A (2) | E (1) | D (2) | Est. prevented / 56 |
|---|---|---|---|---|---|---|---|
| Input->expected oracle table | 0 | 0-1 | 0 | 1-2 | 0 | 0 | 2-3 (5%) |
| Interface contract (exact import specifiers, fixture helper pasted verbatim, signatures, "expected paths derive from the HOME you pass in") | 8-12 (anchors: helper names/signature) | 9 (if contract names `paths(home)` helper) | 5 | 0 | 0 | 0 | 22-26 (40-45%) |
| Machine-readable check script / shared extractor lib (brace-body, resolve consts/helpers, pwsh/C# AST) given to tester | 24-30 | 2-3 (windows/loops) | 0 | 0 | 0 | 0 | 26-33 (46-59%) |
| Pre-spec context map (routes, exports, ctx fields, existing checks, tests pinning old behaviour) | 0 | 0 | 4-5 | 0 | 0-1 | 2 | 6-8 (11-14%), plus 3 spec gaps outside the 56 (Q3) |
| Executable behavioural tests (xUnit/pwsh/node vm) instead of grep | 28-32 | 0 | 0 | 0 | 0 | 0 | 28-32 (50-57%) |
| Base-worktree preflight (not spec-side, tester-side) | 0 | 4-6 | 4 | 0 | 0 | 0-1 | 8-11 (14-20%) |
Overlaps are large; the union of {executable/extractor, contract, preflight} covers est. 50-54 of 56 (about 90%).

## Q3. KOD_HATASI, Sonnet reviewer findings, escapes

KOD_HATASI (5 lines): BA-32 x2 (one root cause: pointer-like `- ... (known.md)` lines after a blank line still parsed as blocks; the spec was clarified afterwards, "Rule 7, clarified in the SPEC" in fb-r2, so ambiguity + code), BA-37 (Turkish inflection: `\btoken\b` misses "tokeni" while other secret nouns used prefixes), BA-43 (uninstall ran init-time conflict check, so E_MANAGED_BLOCK_EDITED never reached), P4 (`Sort-Object Name` is culture-aware but spec says ordinal order). All five were genuine rule violations caught by hidden tests; none is a numeric/format rule. Types: boundary/edge handling, flow-ordering, locale/culture.

Sonnet findings (34 numbered, 5 of 15 accepted tasks needed review rounds: BA-21 2, BA-28 3, BA-38 6+2, BA-43 8+5, P4 8; BA-32b, P1, P3, P5, P6, P7 ONAY). NONE of them was found by a hidden test. Rough split (est):
- Edge cases the spec never listed, ~12: macOS case-insensitive reserved paths, `\r`/trailing-space back-link mismatch, empty kept body throws E_INTERNAL, partial-failure idempotence (BA-38); BOM, CRLF, malformed JSON tolerance (BA-43); `--days` with `feedback` (BA-28).
- Security/pattern parity not stated: BA-28 `recordFeedback` lacks the hook's lstat/uid/O_NOFOLLOW/0600; BA-43 fb3 PM caught the worker widening managed write roots to the vault (scope creep inside allowed files, gate cannot see).
- Worker quality defects, ~14: tautological self-check + dead code, swallowed `catch {}`, top-level await breaking every CLI command, duplicated constant, test named "writes nothing" that asserts nothing (BA-21), and P4 platform-API errors a text regex cannot see (`$connection.ConnectionTimeout` is read-only so DB check always FAILs; `Get-Content` without `-Encoding UTF8`; OK printed before delete verified; Ghostscript folder = bin; double WARN; leaf-only identity match; blocking probe 15 s; non-parallel xUnit collection).
- Regressions: BA-43 w2 broke 31 existing tests (`isCli` throws without ctx), caught by visible tests; Rule 7 byte identity needed 2 more review rounds.
PM-side escapes (not Sonnet): BA-28 hook p95 +48 ms with shadow (spec budget +10 ms measured only post-gate; two PM rounds with the algorithm dictated by the PM); P2 spec said health route `/Health`, real `/api/Health` (spec factual gap) plus test run leaves `logs/*.log` in repo (gate out_of_scope FAIL). Spec premise errors: BA-43 vault scope via CLI does not exist (judge BELIRSIZ, fb3 removed tests); BA-21 spec did not list the existing pinned acceptance test, so the full suite failed 3 gates.
Reviewer findings revealing spec gaps: yes, ~15 of 34 (edge cases, parity, byte-identity of default channel). Also 4 BA tasks passed the gate but failed product holdout (BA-31 0.733<0.85, BA-37 0.815<0.90, BA-36 hypothesis_fail, BA-32 primary fail), i.e. spec-intent gaps the gate cannot see.

## Q4. Worker problems

| Event | Task | Cause (evidence) |
|---|---|---|
| TIMEOUT 1200 s | BA-21 w1 | 6 full `npm test` runs (2365 tests), 1034 s of 1143 s in shell; despite "narrowest tests" rule |
| TIMEOUT 1200 s | BA-32 w2 | 80 steps/92 tool calls, only 394 s in shell: model latency + hook rework; limit since raised to 2400 |
| STALLED | BA-43 w1 | silent after step 45 (a grep), active 356 s but wall 1260 s: 15 min stall limit wasted ~900 s |
| near-miss | BA-37 w1 1188 s, BA-38 w1 1516 s | 99 / 90 tool calls |
Steps (calls): 17-82; >55 steps: P6 82, BA-32 80, BA-37 76, P2 66, BA-43 66/66, BA-38 58, BA-36 57. High step counts correlate with large specs/full-suite loops, not with failure.
Numeric-limit violations: none found in metrics, gate files or reviewer text (no "line count"/length limit appears in any BA/P spec; only "report at most 12 lines" and hx never checks it).
Hidden-dir access: 1 of 30 worker calls: BA-28 w1 ran `ls .../hidden` and the hidden tests at step 114 (BA-28 gate-1 PASS is therefore not blind evidence). Cause: the spec's hidden-test section (paths, run command) was visible to the worker; hx now strips it (`strip_hidden_section`) and `hidden_access` is logged. The BA-43 w1 flag is false (no `.git/hx` string in the jsonl).
Scope violations: 2 gate out_of_scope, both artifacts generated by running tests (BA-21 `tests/acceptance/BA-26/.work/*`, P2 `Web/logs/codart-*.log`), not worker edits; protected_touched = 0. Visible-test-only failures: BA-21 x4 (pinned existing test + unlisted file), BA-32 cold-start timing under load.

## Q5. Other quality signals

1. Testers disclosed fragility in their own reports and nobody acted: P2 ("message assigned to a variable fails"), P4 ("multi-line New-Item gives false failure"), P5 ("equivalent spelling gives false failure"), P6 ("helper method gives false failure"). These warnings predicted the G failures. Also BA-43 tester-1: "runWikiCommand signature not specified".
2. The Codart hidden format ("no build, DB, network; regex only") makes behaviour untestable independently; testers said so: P5 sequence-number rule ("C2026-AB-0000009" cases), P6 0-7 status table, P4 `UploadFoldersOk`, P2 runtime config. These rules are covered only by worker-written tests. dotnet runs on this machine (workers ran `dotnet test` 5-11 times), so executable hidden tests look feasible (est).
3. Telling the tester to be robust did not stick for Haiku: P2 tester_feedback rewrite still produced 6 G lines (3 repeats); P6 had a binding "Robustness" paragraph and still failed 4. BA-43 tester-3 rewrite kept the shared-`home` bug. Feedback prose is weak; a mechanical check is needed.
4. Judge reasons were verified by PM spot checks and by reproduction (BA-32b, BA-43), so triage accuracy looks good; the cost of a wrong TEST_HATASI is a skipped test, which is a quality loss (27 skipped).
5. BA-43 shows the same bug surviving across tester rounds, and the BELIRSIZ vault case exposed a false spec premise: facts should be verified against the repo before the spec is sent.
6. Tester.md rule 7 says "you do not have to run the tests"; base-run would have caught 8 crash-type failures (BA-36 x4, BA-32b x3, BA-32 isError) before any worker time was spent.
7. Gate runs tests that dirty the tree (BA-21, P2): gate should clean/ignore generated dirs to avoid false scope FAILs.

## Hypothesis candidates (max 8)

H1. Base-worktree preflight of hidden tests: run hidden suite on the base commit; any test that errors with non-assertion errors (ERR_MODULE_NOT_FOUND, TypeError, JSON.parse(undefined)) or any "unchanged behaviour" test that fails on base is bounced back to the tester before the worker result is used. Targets B+C. Would have flagged est 8-11 of 56: BA-36 (4), BA-32b (3), BA-32 (1), BA-43 (1-2 unchanged-behaviour hook test). Measure: replay saved hidden dirs for BA-36, BA-32, BA-32b, BA-43 against task_base (task.json); count flagged tests that the judge called TEST_HATASI (recall) and flagged tests among the other hidden tests judged valid (false positives, must be 0).
H2. Executable or AST-based hidden tests for Codart (xUnit hidden project run against the worktree, pwsh AST parse, node vm for JS) instead of regex on source; pair with public-symbol contract. Targets G (32) and the untested-behaviour gap. Would have prevented est 28-32 of 32 (P1-P6) and restores P5/P6/P4 behaviour coverage. Measure: have Haiku and Qwen rewrite P1-P6 hidden suites in the new format from the same specs; run on the merged commits (509f216, 627bf8a, 08ec1f6, 1965134, 31af173, c75ea3f): count false failures (target 0, was 32) and kill rate when the reviewer-found P4 defects and reverted P5/P6 logic are injected.
H3. Interface contract section in every spec (verbatim fixture/import snippet from an existing test, exact signatures, CLI args, file paths, and the tester.md rule "derive expected paths from the same variable passed to the SUT"). Targets C+B (+part of G). Est 14-22 of 56: BA-36 (4), BA-32 (1), BA-43 (9), P2/P3 helper-shape lines (partial). Measure: add the section to BA-36, BA-32, BA-43b and P2-P6 specs, re-run only the tester (about 2-15 min each), run on the saved implementations, compare TEST_HATASI counts.
H4. Shared extractor library handed to the tester (brace-matched method body, constant/helper resolution across the file, window-free ordering, pwsh/C# comment stripping) plus a rule "no raw regex over whole files". Cheaper than H2. Est 10-16 of 32 G lines (P1, P3-body, P5 x2, P4 x3, P6 order, P2 R2/R5/R9). Measure: same P1-P6 replay as H2 with the library; compare to H2.
H5. Pre-spec context map: a script greps routes, exports, ctx fields, existing checks and the existing tests that pin behaviour touched by the spec, and the spec cites it. Targets spec gaps: BA-36 import (4), BA-43 doctor (2), BA-43 vault premise (BELIRSIZ + fb3), BA-21 unlisted pinned test (3 gate FAILs), P2 `/api/Health`. Est 6-8 of 56 plus 3 non-TEST events. Measure: generate maps for these 5 tasks at their base commits and check recall of the facts that later became fixes (target 5/5).
H6. Tester fragility manifest: each test tagged behavioural/source-shape with a fragile flag and reason; fragile or source-shape tests must be rewritten (H2/H4) before the gate, not skipped after it. Targets G and the 27 skipped tests. Est predicts 8-14 of 32. Measure offline: parse tester-N.jsonl reports of P1-P6 and compute overlap between disclosed-fragile tests and the 32 TEST_HATASI.
H7. Spec edge-case battery for robustness classes Sonnet found (case-insensitive FS, CRLF/BOM, empty/zero kept, partial-failure idempotence, symlink/uid parity with sibling writer, option validation order, default-channel byte identity, perf budget as a gate metric). Targets reviewer findings; est 12-15 of 34 findings and the BA-28 perf escape. Measure: label the 34 findings against the battery (recall), then rerun BA-38 with the battery added and count Sonnet findings.
H8. Static-analysis/perf gate: PSScriptAnalyzer or pwsh smoke run for scripts, dotnet analyzers, and hx-measured latency budgets for hook specs. Targets P4 findings 1-6 (read-only property etc.) and BA-28 +48 ms. Est 5-7 of 34 findings plus 2 PM rounds. Measure: run the analyzer on P4 `review.diff`/pre-fix commit and the BA-28 pre-fix diff, count how many of the 8 + 2 are flagged.
