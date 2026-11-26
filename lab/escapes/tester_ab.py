"""Tester-template A/B lab over the escape corpus (HX-44).

Subcommands:
  gen <out> <label> --template <path> [--model M] [--ids a,b] [--jobs 4]
  run <out> <label>
  score <out> <label> [<label> ...]
  clean <out>
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # `python3 -I` drops the script directory from sys.path
    sys.path.insert(0, str(HERE))
try:
    from . import corpus
except ImportError:
    import corpus

DEFAULT_MODEL = "opencode-go/qwen3.7-plus#high"
MODEL_TIMEOUT = 1200
JOBS = 4
ABORT = threading.Event()  # set on the first stray write: no further model call starts


# --- paths -------------------------------------------------------------------
def tester_dir(out, label, case_id):
    return Path(out) / "tester" / label / case_id


def hidden_dir(out, label, case_id):
    return tester_dir(out, label, case_id) / "hidden"


def tbase_path(out, case_id):
    return Path(out) / "tbase" / case_id


def result_path(out, label, case_id):
    return tester_dir(out, label, case_id) / "result.json"


def test_files(directory):
    """Regular files in the hidden directory whose path has a test shape."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return [path for path in sorted(directory.rglob("*"))
            if path.is_file() and corpus.is_test_path(path.relative_to(directory).as_posix())]


# --- model calls -------------------------------------------------------------
def run_model(prompt, cwd, model, profile=None):
    """Run opencode once (standalone, PWD = cwd, 1200 s); returns (raw, rc, timeout, seconds)."""
    command = [corpus.opencode_bin(), "run", "--standalone", "-m", model, "--format", "json", prompt]
    if profile is not None:
        command = [corpus.SANDBOX_EXEC, "-f", str(profile), *command]
    started = time.time()
    try:
        proc = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace",
                                env=dict(os.environ, PWD=str(cwd)), start_new_session=True)
    except OSError:
        return "", None, False, round(time.time() - started, 3)
    try:
        out, _ = proc.communicate(timeout=MODEL_TIMEOUT)
    except subprocess.TimeoutExpired:
        corpus._kill_group(proc)
        out, _ = proc.communicate()
        return out or "", None, True, round(time.time() - started, 3)
    return out or "", proc.returncode, False, round(time.time() - started, 3)


def ensure_tbase(root, case):
    """Create out/tbase/<id> from the case base when it does not exist yet (shared by labels)."""
    path = tbase_path(root, case["id"])
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    corpus.git(case["repo"], "worktree", "add", "--detach", str(path), case["base"])
    return path


def gen_case(root, label, template, case, model):
    if ABORT.is_set():
        return "skipped"
    directory = tester_dir(root, label, case["id"])
    meta = directory / "meta.json"
    if meta.exists():
        return "skipped"
    hidden = hidden_dir(root, label, case["id"])
    hidden.mkdir(parents=True, exist_ok=True)
    tbase = ensure_tbase(root, case)
    prompt = corpus.fill(template, {
        "{SPEC}": Path(corpus.spec_path(case)).read_text(encoding="utf-8"),
        "{WORKTREE}": str(tbase),
        "{TBASE}": str(tbase),
        "{HIDDEN}": str(hidden),
    })
    profile = None
    if sys.platform == "darwin":
        profile = corpus.sandbox_profile(Path(root) / "tester" / label, case["id"], hidden)
    before = corpus.repo_statuses(root)
    raw, rc, timeout, seconds = run_model(prompt, hidden, model, profile)
    (directory / "raw.jsonl").write_text(raw, encoding="utf-8")
    after = corpus.repo_statuses(root)
    stray = next((repo for repo in after if before.get(repo) != after[repo]), None)
    if stray:
        ABORT.set()
        raise SystemExit(f"tester_ab: stray_write: {stray}")
    if ABORT.is_set():  # another job already aborted the run: keep no meta for this case
        return "skipped"
    corpus.write_json(meta, {"model": model, "seconds": seconds, "rc": rc, "timeout": timeout})
    return "generated"


def cmd_gen(out, label, template, model=DEFAULT_MODEL, ids=None, jobs=JOBS):
    root = Path(os.path.abspath(str(out)))
    if sys.platform == "darwin":
        corpus.require_sandbox()
    text = Path(template).read_text(encoding="utf-8")
    cases = corpus.select_cases(root, ids, ("valid",))
    done = skipped = 0
    ABORT.clear()
    pool = ThreadPoolExecutor(max_workers=max(1, int(jobs)))
    try:
        futures = [pool.submit(gen_case, root, label, text, case, model) for case in cases]
        for future in as_completed(futures):
            if future.result() == "generated":
                done += 1
            else:
                skipped += 1
    except BaseException:
        ABORT.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    print(f"gen: {done} generated, {skipped} skipped -> {root}")


# --- run ---------------------------------------------------------------------
def run_hidden(command, wt, hidden):
    command = corpus.subst(command, wt, hidden).strip()
    if not command:
        return "fail", ""
    out, err, code, error = corpus._run(command, wt, shell=True)
    text = out + err
    if error == "timeout":
        return "timeout", text
    if error:
        return "fail", error
    return ("pass" if code == 0 else "fail"), text


def write_log(path, text):
    lines = text.splitlines()[-corpus.LOG_LINES:]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def cmd_run(out, label):
    root = Path(os.path.abspath(str(out)))
    ran = no_tests = 0
    for case in corpus.select_cases(root, None, ("valid",)):
        case_id = case["id"]
        hidden = hidden_dir(root, label, case_id)
        target = result_path(root, label, case_id)
        if not test_files(hidden):
            corpus.write_json(target, {"valid": False, "caught": False,
                                       "clean": "no_tests", "defect": "no_tests"})
            no_tests += 1
            continue
        results = {}
        for variant in ("clean", "defect"):
            wt = corpus.wt_path(root, corpus.item_of(case_id, variant))
            status, text = run_hidden(case.get("hidden_cmd", ""), wt, hidden)
            results[variant] = status
            write_log(tester_dir(root, label, case_id) / f"{variant}.log", text)
        valid = results["clean"] == "pass"
        caught = valid and results["defect"] != "pass"
        corpus.write_json(target, {"clean": results["clean"], "defect": results["defect"],
                                   "valid": valid, "caught": caught})
        ran += 1
    print(f"run: {ran} run, {no_tests} without tests -> {root}")


# --- score -------------------------------------------------------------------
def case_stats(root, label, cases):
    suites = []
    for case in cases:
        path = result_path(root, label, case["id"])
        if path.exists():
            suites.append(corpus.read_json(path))
    valid = sum(1 for result in suites if result.get("valid") is True)
    caught = sum(1 for result in suites if result.get("caught") is True)
    return {"n": len(cases), "suites": len(suites), "valid": valid, "caught": caught,
            "catch_rate": corpus.rate(caught, len(cases)), "invalid": len(suites) - valid}


def caught_ids(root, label, cases):
    caught = set()
    for case in cases:
        path = result_path(root, label, case["id"])
        if path.exists() and corpus.read_json(path).get("caught") is True:
            caught.add(case["id"])
    return caught


def cmd_score(out, labels):
    root = Path(os.path.abspath(str(out)))
    split = corpus.load_split(root)
    cases = [case for case in corpus.all_cases(root) if case.get("status") == "valid"]
    report = {"labels": {}}
    rows = []
    for label in labels:
        by_split = {}
        for name in ("tuning", "holdout", "all"):
            members = [case for case in cases
                       if name == "all" or corpus.split_of(split, case["id"]) == name]
            by_split[name] = case_stats(root, label, members)
        entry = dict(by_split)
        report["labels"][label] = entry
        report[label] = entry
        rows.extend((label, name, by_split[name]) for name in ("tuning", "holdout", "all"))
    if len(labels) == 2:
        first, second = labels
        only_first = caught_ids(root, first, cases) - caught_ids(root, second, cases)
        only_second = caught_ids(root, second, cases) - caught_ids(root, first, cases)
        report["only_A"] = sorted(only_first)
        report["only_B"] = sorted(only_second)
    corpus.write_json(root / "tester_score.json", report)
    print(f"{'label':<12} {'split':<8} {'n':>4} {'suites':>6} {'valid':>5} {'caught':>6} "
          f"{'catch_rate':>10} {'invalid':>7}")
    for label, name, stats in rows:
        print(f"{label:<12} {name:<8} {stats['n']:>4} {stats['suites']:>6} {stats['valid']:>5} "
              f"{stats['caught']:>6} {corpus.show(stats['catch_rate']):>10} {stats['invalid']:>7}")
    if "only_A" in report:
        print(f"only_{labels[0]}: {', '.join(report['only_A']) or '-'}")
        print(f"only_{labels[1]}: {', '.join(report['only_B']) or '-'}")
    print(f"score: {len(labels)} label(s) -> {root / 'tester_score.json'}")


# --- clean -------------------------------------------------------------------
def cmd_clean(out):
    root = Path(os.path.abspath(str(out)))
    tbase = root / "tbase"
    removed = 0
    if tbase.is_dir():
        for path in sorted(tbase.iterdir()):
            if not path.is_dir():
                continue
            repo = corpus.worktree_repo(path)
            if not repo:
                continue
            corpus.git(repo, "worktree", "remove", "--force", str(path), check=False)
            if not path.exists():
                removed += 1
    print(f"clean: {removed} worktrees removed")


# --- CLI ---------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(prog="tester_ab.py", description="Tester-template A/B lab (HX-44).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("gen", help="write hidden tests with a tester template")
    gen.add_argument("out")
    gen.add_argument("label")
    gen.add_argument("--template", required=True)
    gen.add_argument("--model", default=DEFAULT_MODEL)
    gen.add_argument("--ids", default=None)
    gen.add_argument("--jobs", type=int, default=JOBS)
    run = sub.add_parser("run", help="run hidden tests on the clean and defect worktrees")
    run.add_argument("out")
    run.add_argument("label")
    score = sub.add_parser("score", help="score labels per split")
    score.add_argument("out")
    score.add_argument("labels", nargs="+")
    clean = sub.add_parser("clean", help="remove out/tbase worktrees")
    clean.add_argument("out")
    args = parser.parse_args(argv)
    if args.cmd == "gen":
        ids = [part.strip() for part in (args.ids or "").split(",") if part.strip()]
        cmd_gen(args.out, args.label, args.template, model=args.model, ids=ids, jobs=args.jobs)
    elif args.cmd == "run":
        cmd_run(args.out, args.label)
    elif args.cmd == "score":
        cmd_score(args.out, args.labels)
    elif args.cmd == "clean":
        cmd_clean(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
