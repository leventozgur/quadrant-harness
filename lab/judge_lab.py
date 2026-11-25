"""Judge-role lab: measure whether a referee model blames the code or the tests correctly.

Tester runs (`tester_lab`) give hidden test suites; this lab turns each run into cases with a known
label: the reference fails some test -> TEST mistake, a mutant that the reference passes -> KOD
mistake. The judge sees only the spec, the hidden tests and the gate output (never the label).

  python3 -I judge_lab.py build <out> <label> [<label> ...]
  python3 -I judge_lab.py judge <out> <model> [reps] [--jobs N]
  python3 -I judge_lab.py score <out>
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import hard as H  # noqa: E402
import run_oc  # noqa: E402
import tester_lab as T  # noqa: E402

GATE_CMD = "python3 -m unittest"
TEST_TIMEOUT_S = 300
JUDGE_TIMEOUT_S = 600
TAGS = {"KOD": "KOD_HATASI", "TEST": "TEST_HATASI", "BELIRSIZ": "BELIRSIZ"}
_FAILING = ("fail", "error")

_RESULT = re.compile(r"\.\.\.\s+(ok|FAIL|ERROR|skipped(?:\s.*)?|expected failure|unexpected success)\s*$")
_BARE = re.compile(r"^(ok|FAIL|ERROR|skipped(?:\s.*)?|expected failure|unexpected success)\s*$")
_ID_LINE = re.compile(r"^(\S+)\s+\(([^()\s]+)\)")
_STATUS = {"ok": "pass", "FAIL": "fail", "ERROR": "error",
           "expected failure": "pass", "unexpected success": "fail"}
_VERDICT = {k: re.compile(re.escape(v) + r"\s*[—–-]\s+\S") for k, v in TAGS.items()}


# ------------------------------------------------------------------ run hidden tests
def _discover_ids(hidden_dir):
    """Best-effort test ids for a timeout during discovery (the tests themselves never import)."""
    ids = []
    for f in sorted(Path(hidden_dir).glob("**/test*.py")):
        rel = f.relative_to(hidden_dir).with_suffix("")
        mod = ".".join(rel.parts)
        if mod.endswith(".__init__"):
            mod = mod[:-len(".__init__")]
        cls = None
        for line in f.read_text(errors="replace").splitlines():
            m = re.match(r"class\s+(\w+)\s*[(:]", line)
            if m:
                cls = m.group(1)
                continue
            m = re.match(r"\s+def\s+(test\w*)\s*\(", line)
            if m:
                ids.append(f"{mod}.{cls}.{m.group(1)}" if cls else f"{mod}.{m.group(1)}")
            elif line and not line[0].isspace():
                cls = None
    return ids


def _parse_verbose(output):
    """`test_name (id) ... ok|...`; a docstring or stderr text can split the result.

    An id is bound only to a header line that itself contains `...`, or to a docstring-style
    header (`name (id)` followed by a line ending in ` ... <status>`). Arbitrary test stdout such
    as `name (a word)` therefore cannot steal the pending identity.
    """
    outcomes = {}
    pending = candidate = None
    for raw in output.splitlines():
        line = raw.strip()
        hm = _ID_LINE.match(line)
        if hm:
            ident, body = hm.group(2), line[hm.end():]
            if "..." in body:
                pending, candidate = ident, None  # a new real header wins over a stale pending id
            else:
                if pending is None and candidate is None:
                    candidate = ident  # docstring header: commit only on a `... status` line
                continue  # test stdout (`name (word)`) must not steal the pending identity
        elif pending is not None or candidate is not None:
            body = line
        else:
            continue
        sm = _RESULT.search(body)
        if sm is None and pending is not None:
            sm = _BARE.match(body)  # a lone ok/FAIL/ERROR belongs to the pending test
        if not sm:
            continue
        ident = pending if pending is not None else candidate
        if ident is None:
            continue
        status = sm.group(1)
        outcomes[ident] = "skip" if status.startswith("skipped") else _STATUS[status]
        pending = candidate = None
    return outcomes


def test_outcomes(hidden_dir, sol_dir, ids=None):
    """Run the hidden suite against a solution; return ({test id: pass|fail|error|skip}, rc, output)."""
    hidden_dir, sol_dir = Path(hidden_dir), Path(sol_dir)
    ids = None if ids is None else list(ids)
    if ids is not None and not ids:
        return {}, 0, ""
    if ids is None:
        args = [sys.executable, "-m", "unittest", "discover", "-s", str(hidden_dir),
                "-t", str(hidden_dir), "-v"]
    else:
        args = [sys.executable, "-m", "unittest", "-v", *ids]
    env = dict(os.environ, PYTHONPATH=str(sol_dir) + os.pathsep + str(hidden_dir))
    try:
        r = subprocess.run(args, cwd=str(hidden_dir), env=env, capture_output=True, text=True,
                           timeout=TEST_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        text = "".join(x if isinstance(x, str) else (x or b"").decode("utf-8", "replace")
                       for x in (e.stdout, e.stderr))
        targets = ids if ids is not None else _discover_ids(hidden_dir)
        return {t: "error" for t in targets}, -1, text
    output = (r.stdout or "") + (r.stderr or "")
    outcomes = _parse_verbose(output)
    if ids is not None:
        # An import error/crash reports unittest.loader._FailedTest instead of the requested id;
        # a requested id that never appears is an error even when the process still exits 0.
        outcomes = {t: outcomes.get(t, "error") for t in ids}
    return outcomes, r.returncode, output


def gate_text(cmd, rc, output):
    """The hx gate shape: one header line plus the last 60 lines of the run."""
    return f"--- hidden ({cmd}) exit {rc}\n" + "\n".join((output or "").splitlines()[-60:])


# ------------------------------------------------------------------ verdict parsing
def parse_verdicts(text):
    counts = {"KOD": 0, "TEST": 0, "BELIRSIZ": 0}
    for line in (text or "").splitlines():
        line = line.strip()
        for key, pat in _VERDICT.items():
            if pat.match(line):
                counts[key] += 1
                break
    return counts


def category(counts):
    kod, test = counts.get("KOD", 0), counts.get("TEST", 0)
    if kod and test:
        return "MIXED"
    if kod:
        return "KOD"
    if test:
        return "TEST"
    if counts.get("BELIRSIZ", 0):
        return "BELIRSIZ"
    return "NONE"


# ------------------------------------------------------------------ cases
def _runs_root():
    return Path(os.environ.get("TESTER_LAB_ROOT") or T.ROOT)


def _at_project(proj, sol):
    """Put a solution variant exactly where the tester saw the project (tests may hardcode it)."""
    if proj.exists():
        shutil.rmtree(proj)
    shutil.copytree(sol, proj)


def _write_case(out, run, task, variant, label, failing, rc, output, sol):
    case_id = f"{run.parent.name}__{run.name}__{variant}"
    dest = out / "cases" / case_id
    if (dest / "case.json").exists():
        return case_id  # idempotent: an existing complete case dir is never rewritten
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    if dest.exists():
        shutil.rmtree(dest)  # an interrupted earlier build left no case.json
    tmp.mkdir(parents=True)
    try:
        shutil.copytree(run / "hidden", tmp / "hidden", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(sol, tmp / "project")
        (tmp / "gate.txt").write_text(gate_text(GATE_CMD, rc, output))
        meta = {"case_id": case_id, "task": task, "suite": f"{run.parent.name}/{run.name}",
                "variant": variant, "label": label, "failing": failing}
        (tmp / "case.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        os.replace(tmp, dest)  # only a fully written case becomes visible
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return case_id


def _failing(outcomes):
    return sorted(t for t, o in outcomes.items() if o in _FAILING)


def _case_files(out):
    """Every complete case.json, never a half-written `<case>.tmp` directory."""
    return [p for p in sorted((Path(out) / "cases").glob("*/case.json"))
            if not p.parent.name.endswith(".tmp")]


def build_cases(out, labels):
    """Turn tester runs into labelled cases (TEST = reference fails, KOD = a passing test is killed)."""
    out = Path(out)
    root = _runs_root()
    cases_dir = out / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for stale in cases_dir.glob("*.tmp"):
        shutil.rmtree(stale, ignore_errors=True)  # an interrupted earlier build left a half case
    started = time.time()
    cache, created = {}, []

    def sol_for(task, m):
        key = (task, m)
        if key not in cache:
            d = Path(T.solution_dir(task, m))
            cache[key] = d
            try:
                if d.stat().st_ctime >= started:  # created by this build, so it is ours to delete
                    created.append(d)
            except OSError:
                pass
        return cache[key]

    try:
        for label in labels:
            for task in H.HARD:
                for run in sorted((root / label).glob(f"{task}_r*")):
                    if not (run / "_meta.json").exists():
                        continue
                    hidden, proj = run / "hidden", run / "project"
                    ref_sol = sol_for(task, None)
                    try:
                        _at_project(proj, ref_sol)
                        outcomes, rc, output = test_outcomes(hidden, proj)
                        if _failing(outcomes):
                            _write_case(out, run, task, "ref", "TEST", _failing(outcomes), rc, output, ref_sol)
                        passing = sorted(t for t, o in outcomes.items() if o == "pass")
                        for m in range(len(T.MUT[task])):
                            if not passing:
                                break
                            sol = sol_for(task, m)
                            _at_project(proj, sol)
                            got, rc_m, out_m = test_outcomes(hidden, proj, ids=passing)
                            if _failing(got):
                                _write_case(out, run, task, f"m{m}", "KOD", _failing(got), rc_m, out_m, sol)
                    finally:
                        _at_project(proj, ref_sol)  # leave the run dir as the tester produced it
    finally:
        for d in created:
            shutil.rmtree(d, ignore_errors=True)
    cases = [json.loads(p.read_text()) for p in _case_files(out)]
    cases.sort(key=lambda c: c["case_id"])
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1))
    return cases


# ------------------------------------------------------------------ judge
def _fill(template, mapping):
    return re.sub(r"\{(SPEC|HIDDEN|WORKTREE|FEEDBACK)\}", lambda m: mapping[m.group(1)], template)


def _judge_prompt(template, case, hidden, project, feedback):
    return _fill(template, {"SPEC": H.P[case["task"]], "HIDDEN": str(hidden),
                            "WORKTREE": str(project), "FEEDBACK": feedback})


def _blind_dir(out, case_id, rep):
    """Neutral name: no case id, ref/m<i>, TEST or KOD can leak through the path."""
    return Path(out) / "blind" / hashlib.sha1((case_id + str(rep)).encode("utf-8")).hexdigest()[:12]


def _neutral_gate(case, case_dir, blind):
    """Rewrite every case/run path in the gate text to the blind copy's paths."""
    text = (case_dir / "gate.txt").read_text()
    targets = {"hidden": (blind / "hidden").resolve(), "project": (blind / "project").resolve(),
               "": blind.resolve()}
    bases = [Path(case_dir)]
    if case.get("suite"):
        bases.append(_runs_root() / case["suite"])
    pairs = set()
    for base in bases:
        for sub, target in targets.items():
            old = base / sub if sub else base
            pairs.add((str(old), str(target)))
            pairs.add((str(old.resolve()), str(target)))
    for old, new in sorted(pairs, key=lambda p: -len(p[0])):
        text = text.replace(old, new)
    suite = case.get("suite")
    if suite:  # the tester root can differ between build and judge; match the suite tail anyway
        tail = re.compile(r"[^\s'\"()]*?" + re.escape(suite) + r"/(hidden|project)")
        text = tail.sub(lambda m: str(targets[m.group(1)]), text)
    return text


def _run_rep(case, case_dir, dest, out, rep, model, template, opencode):
    t0 = time.time()
    answer, infra, error = "", False, ""
    blind = _blind_dir(out, case["case_id"], rep)
    try:
        try:
            shutil.rmtree(blind, ignore_errors=True)
            blind.mkdir(parents=True, exist_ok=True)
            shutil.copytree(case_dir / "hidden", blind / "hidden")
            shutil.copytree(case_dir / "project", blind / "project")
            prompt = _judge_prompt(template, case, (blind / "hidden").resolve(),
                                   (blind / "project").resolve(),
                                   _neutral_gate(case, case_dir, blind))
            p = subprocess.run([opencode, "run", "-m", model, "--format", "json", prompt],
                               cwd=str(blind / "project"), capture_output=True, text=True,
                               timeout=JUDGE_TIMEOUT_S)
            answer, _meta = run_oc.parse(p.stdout or "")
            if p.returncode != 0:
                infra = True
                error = "\n".join((p.stderr or "").splitlines()[-20:])
        except Exception as e:
            # Any rep error (copy, timeout, decode) is infra and must not abort the whole run.
            infra = True
            error = repr(e)
    finally:
        shutil.rmtree(blind, ignore_errors=True)  # the blind copy never outlives its rep
    if not answer.strip():
        infra = True
    counts = parse_verdicts(answer)
    rec = {"answer": answer, "counts": counts, "category": "INFRA" if infra else category(counts),
           "seconds": round(time.time() - t0, 1), "model": model, "infra": infra, "error": error}
    dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


def judge(out, model, reps=3, jobs=4):
    out = Path(out)
    cases = [json.loads(p.read_text()) for p in _case_files(out)]
    cases.sort(key=lambda c: c["case_id"])
    template = (HERE.parent / "templates/judge.md").read_text()
    opencode = os.environ.get("JUDGE_LAB_OPENCODE", "opencode")
    todo = []
    for case in cases:
        case_dir = out / "cases" / case["case_id"]
        for k in range(1, reps + 1):
            dest = case_dir / f"rep_{k}.json"
            if not dest.exists():
                todo.append((case, case_dir, dest, k))
    if not todo:
        return []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        return list(ex.map(
            lambda a: _run_rep(a[0], a[1], a[2], out, a[3], model, template, opencode), todo))


# ------------------------------------------------------------------ score
def _ratio(num, den):
    return num / den if den else None


def _majority(cats):
    counts = {}
    for c in cats:
        counts[c] = counts.get(c, 0) + 1
    top = max(counts.values())
    winners = [c for c, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else "TIE"


def _kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n)
             for c in ("KOD", "TEST", "OTHER"))
    if abs(1 - pe) < 1e-12:
        return None
    return (po - pe) / (1 - pe)


def score(out):
    out = Path(out)
    (out / "cases").mkdir(parents=True, exist_ok=True)
    cases = []
    for p in _case_files(out):
        try:
            cases.append(json.loads(p.read_text()))
        except Exception:
            continue  # a half-written case cannot be scored
    cases.sort(key=lambda c: c["case_id"])
    valid, infra_reps = {}, 0
    for case in cases:
        reps = []
        for p in sorted((out / "cases" / case["case_id"]).glob("rep_*.json")):
            try:
                rec = json.loads(p.read_text())
            except Exception:
                infra_reps += 1  # unreadable rep is infra, never fatal
                continue
            if not isinstance(rec, dict) or rec.get("infra"):
                infra_reps += 1
            else:
                reps.append(rec)
        valid[case["case_id"]] = reps

    n_cases = {"KOD": 0, "TEST": 0}
    for case in cases:
        n_cases[case["label"]] = n_cases.get(case["label"], 0) + 1

    rep_accuracy = {}
    for label in ("KOD", "TEST"):
        rs = [r for c in cases if c["label"] == label for r in valid[c["case_id"]]]
        rep_accuracy[label] = _ratio(sum(1 for r in rs if r.get("category") == label), len(rs))

    correct, majorities = 0, {}
    for case in cases:
        reps = valid[case["case_id"]]
        if not reps:
            majorities[case["case_id"]] = None
            continue
        maj = _majority([r.get("category") for r in reps])
        majorities[case["case_id"]] = maj
        correct += maj == case["label"]

    flips = flipped = 0
    for case in cases:
        cats = [r.get("category") for r in valid[case["case_id"]]]
        if len(cats) >= 2:
            flips += 1
            flipped += len(set(cats)) > 1

    def judged(label, cats):
        rs = [r for c in cases if c["label"] == label for r in valid[c["case_id"]]]
        return _ratio(sum(1 for r in rs if r.get("category") in cats), len(rs))

    all_reps = [r for case in cases for r in valid[case["case_id"]]]
    pairs = [(c["label"], majorities[c["case_id"]] if majorities[c["case_id"]] in ("KOD", "TEST")
              else "OTHER") for c in cases if majorities[c["case_id"]] is not None]
    ties = sum(1 for c in cases if majorities[c["case_id"]] == "TIE")

    result = {
        "cases": n_cases,
        "infra_reps": infra_reps,
        "rep_accuracy": rep_accuracy,
        "majority_accuracy": _ratio(correct, len(pairs)),
        "majority_denominator": len(pairs),
        "ties": ties,
        "flip_rate": _ratio(flipped, flips),
        "kod_judged_test": judged("KOD", ("TEST", "MIXED")),
        "test_judged_kod": judged("TEST", ("KOD", "MIXED")),
        "belirsiz_rate": _ratio(sum(1 for r in all_reps if r.get("category") == "BELIRSIZ"),
                                 len(all_reps)),
        "kappa": _kappa(pairs),
    }
    (out / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"cases KOD={n_cases['KOD']} TEST={n_cases['TEST']}  infra_reps={infra_reps}")
    print(f"rep_accuracy KOD={rep_accuracy['KOD']} TEST={rep_accuracy['TEST']}  "
          f"majority={result['majority_accuracy']} (n={result['majority_denominator']}, "
          f"ties={result['ties']})  flip={result['flip_rate']}")
    print(f"kod_judged_test={result['kod_judged_test']}  test_judged_kod={result['test_judged_kod']}  "
          f"belirsiz={result['belirsiz_rate']}  kappa={result['kappa']}")
    return result


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="judge_lab")
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("out")
    b.add_argument("labels", nargs="+")
    j = sp.add_parser("judge")
    j.add_argument("out")
    j.add_argument("model")
    j.add_argument("reps", nargs="?", type=int, default=3)
    j.add_argument("--jobs", type=int, default=4)
    s = sp.add_parser("score")
    s.add_argument("out")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build_cases(a.out, a.labels)
    elif a.cmd == "judge":
        judge(a.out, a.model, reps=a.reps, jobs=a.jobs)
    else:
        score(a.out)


if __name__ == "__main__":
    main()
