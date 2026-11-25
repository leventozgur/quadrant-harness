"""Tester-role lab: a model writes hidden acceptance tests from a spec (harness tester template).
Quality = tests pass on the reference solution AND fail on hand-written mutants (mutation score).

  python3 -I tester_lab.py run <label> <model> [reps=2]     # generate tests
  python3 -I tester_lab.py score <label> [<label> ...]      # evaluate
  python3 -I tester_lab.py selftest                          # mutants differ from ref per hidden checker
"""
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import hard as H  # noqa: E402
from run_oc import parse  # noqa: E402

ROOT = Path(os.environ.get("TESTER_LAB_ROOT", "/private/tmp/claude-501/lab-runs/tester"))
TEMPLATE = Path(os.environ.get("TESTER_TEMPLATE", HERE.parent / "templates/tester.md")).read_text()


def sub(path, old, new):
    def f(d):
        p = d / path
        s = p.read_text()
        assert old in s, f"mutant anchor missing in {path}: {old!r}"
        p.write_text(s.replace(old, new, 1))
    return f


MUT = {
    "h01": [sub("shop/discounts.py", "item.qty >= BULK", "item.qty > BULK"),
            sub("shop/pricing.py", "gross - disc", "gross - disc - disc"),
            sub("shop/pricing.py", 'total >= Decimal("100")', 'total > Decimal("100")'),
            sub("shop/pricing.py", "quantize(CENT, rounding=ROUND_HALF_UP)\n\n\ndef order", "quantize(CENT)\n\n\ndef order")],
    "h02": [sub("report/formatters.py", "any(ch in s for ch in ',\"\\n')", "any(ch in s for ch in ',\"')"),
            sub("report/formatters.py", "s.replace('\"', '\"\"')", "s"),
            sub("report/formatters.py", 's = "" if v is None else str(v)', "s = str(v)"),
            sub("report/formatters.py", 'return "\\n".join(lines)\n', 'return "\\n".join(lines) + "\\n"\n')],
    "h03": [sub("workdays.py", "while x < b" if False else "for i in range(rest):", "for i in range(rest + 1):"),
            sub("workdays.py", "start <= h < end and h.weekday() < 5", "start <= h < end"),
            sub("workdays.py", "return -business_days_between(end, start, holidays)", "return business_days_between(end, start, holidays)"),
            sub("workdays.py", "    holidays = holidays or set()\n", "")],
    "h04": [sub("legacy.py", '    if c.startswith("0090"):\n        return c[4:]\n', ""),
            sub("legacy.py", "1 <= len(tail) <= 4", "1 <= len(tail) <= 5"),
            sub("legacy.py", 'c[0] in "234" and c[1] != "0"', 'c[0] in "234"'),
            sub("legacy.py", '        raise TypeError("raw None olamaz")', "        return None")],
    "h05": [sub("cache.py", "            self._data.move_to_end(key)\n            return self._data[key]", "            return self._data[key]"),
            sub("cache.py", "popitem(last=False)", "popitem()"),
            sub("cache.py", "        self._data[key] = value\n        self._data.move_to_end(key)\n", "        self._data[key] = value\n"),
            sub("cache.py", "        if key in self._data:", "        if self._data.get(key):")],
    "h06": [sub("ratelimit.py", "self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)", "self._tokens = self._tokens + elapsed * self.rate"),
            sub("ratelimit.py", "            if n > self.capacity or self._tokens < n:\n                return False",
                "            if n > self.capacity or self._tokens < n:\n                self._tokens = max(0.0, self._tokens - n)\n                return False"),
            sub("ratelimit.py", "elapsed = max(0.0, now - self._last)", "elapsed = now - self._last"),
            sub("ratelimit.py", '        if n <= 0:\n            raise ValueError("n pozitif olmalı")\n', "")],
    "h07": [sub("csvline.py", "cur.append('\"'); i += 2; continue", "i += 2; continue"),
            sub("csvline.py", '            if i < n and line[i] != ",":\n                raise ValueError("tırnak sonrası beklenmeyen karakter")\n', ""),
            sub("csvline.py", '        fields.append("".join(cur))\n        if i >= n:\n            return fields',
                '        fields.append("".join(cur))\n        if i >= n:\n            return [f for f in fields if f] if line == "" else fields'),
            sub("csvline.py", "                if line[i] == '\"':\n                    raise ValueError(\"tırnaksız alanda tırnak\")\n", "")],
}


def solution_dir(task, mutant=None):
    d = Path(tempfile.mkdtemp(prefix=f"sol_{task}_"))
    H.FIX[task](d)
    H.REF[task](d)
    if mutant is not None:
        MUT[task][mutant](d)
    for p in d.glob("_pristine.json"):
        p.unlink()
    return d


def run_tests(test_dir, sol):
    env = dict(os.environ, PYTHONPATH=str(sol))
    files = list(test_dir.glob("**/test*.py"))
    if not files:
        return None, "no test files"
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(test_dir), "-t", str(test_dir), "-q"],
                       cwd=sol, env=env, capture_output=True, text=True, timeout=300)
    return r.returncode == 0, (r.stdout + r.stderr)[-400:]


# ------------------------------------------------------------------ generate
def generate(label, model, reps):
    for task in H.HARD:
        for k in range(1, reps + 1):
            run_id = f"{task}_r{k}"
            base = ROOT / label / run_id
            if (base / "_meta.json").exists() and not json.loads((base / "_meta.json").read_text()).get("timeout"):
                print(f"{label} {run_id}: already done, skipping", flush=True)
                continue
            if base.exists():
                shutil.rmtree(base)
            proj, hidden = base / "project", base / "hidden"
            proj.mkdir(parents=True); hidden.mkdir()
            H.FIX[task](proj)
            for p in proj.glob("_pristine.json"):
                p.unlink()
            prompt = TEMPLATE.replace("{SPEC}", H.P[task]).replace("{WORKTREE}", str(proj)).replace("{HIDDEN}", str(hidden))
            for attempt in range(4):
                t0 = time.time()
                timeout = False
                try:
                    p = subprocess.run(["opencode", "run", "--standalone", "-m", model, "--format", "json", prompt], cwd=hidden,
                                       env=dict(os.environ, PWD=str(hidden)), capture_output=True, text=True, timeout=1200)
                    out, err = p.stdout, p.stderr
                except subprocess.TimeoutExpired as e:
                    out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
                    err, timeout = "TIMEOUT", True
                if ("usage limit" in (out + err).lower() or "rate limit" in (out + err).lower()) and attempt < 3:
                    time.sleep(90); continue
                break
            (base / "_raw.jsonl").write_text(out)
            answer, meta = parse(out)
            meta["timeout"] = timeout
            meta["model"] = model
            meta["wall_seconds"] = round(time.time() - t0, 1)
            (base / "_answer.txt").write_text(answer)
            (base / "_meta.json").write_text(json.dumps(meta))
            print(f"{label} {run_id}: {meta}", flush=True)
    print("DONE", flush=True)


# ------------------------------------------------------------------ score
_SOL_CACHE = {}


def cached_sol(task, m):
    key = (task, m)
    if key not in _SOL_CACHE:
        _SOL_CACHE[key] = solution_dir(task, m)
    return _SOL_CACHE[key]


def score(labels):
    summary = {}
    for label in labels:
        rows = []
        for task in H.HARD:
            for run in sorted((ROOT / label).glob(f"{task}_r*")):
                if not (run / "_meta.json").exists():
                    continue  # still running or crashed before writing results
                hidden = run / "hidden"
                proj = run / "project"

                def at_project(m):
                    # Put the solution variant exactly where the tester saw the project (tests may hardcode that path).
                    if proj.exists():
                        shutil.rmtree(proj)
                    shutil.copytree(cached_sol(task, m), proj)
                    return run_tests(hidden, proj)
                ref_ok, ref_out = at_project(None)
                killed = 0
                for m in range(len(MUT[task])):
                    ok, _ = at_project(m)
                    killed += ok is False
                at_project(None)
                meta = json.loads((run / "_meta.json").read_text())
                n_tests = sum(f.read_text().count("def test") for f in hidden.glob("**/test*.py"))
                rows.append({"run": run.name, "ref_pass": ref_ok, "killed": killed, "mutants": len(MUT[task]),
                             "n_tests": n_tests, "seconds": meta.get("seconds"),
                             "tokens_out": (meta.get("output_tokens") or 0) + (meta.get("reasoning_tokens") or 0),
                             "tokens_in": (meta.get("input_tokens") or 0) + (meta.get("cache_read") or 0),
                             "ref_detail": "" if ref_ok else ref_out})
        (HERE / f"tester_results_{label}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        valid = [r for r in rows if r["ref_pass"]]
        # Mutation score counts only test suites that pass on the reference (a failing suite "kills" everything).
        kill = sum(r["killed"] for r in valid); tot = sum(r["mutants"] for r in rows)
        summary[label] = {"runs": len(rows), "ref_pass": len(valid), "killed_valid": kill, "mutants_total": tot,
                          "seconds": round(sum(r["seconds"] or 0 for r in rows)),
                          "tok_in": sum(r["tokens_in"] for r in rows), "tok_out": sum(r["tokens_out"] for r in rows)}
        print(f"\n== {label}: ref-pass {len(valid)}/{len(rows)}  mutants killed (valid suites only) {kill}/{tot}  "
              f"seconds {summary[label]['seconds']}  tok in/out {summary[label]['tok_in']}/{summary[label]['tok_out']}")
        for r in rows:
            print(f"  {r['run']:8} ref={'PASS' if r['ref_pass'] else 'FAIL' if r['ref_pass'] is False else 'NONE'} "
                  f"killed={r['killed']}/{r['mutants']} tests={r['n_tests']} {r['seconds']}s {r['ref_detail'][-150:].replace(chr(10),' ')}")
    return summary


def selftest():
    """Every mutant must be detected by the hidden checker (so it is a real behaviour change)."""
    for task in H.HARD:
        for m in range(len(MUT[task])):
            d = solution_dir(task, m)
            H.FIX[task].__name__  # noqa
            # rebuild pristine snapshot so CHECK's unchanged() works on protected files
            tmp = Path(tempfile.mkdtemp()); H.FIX[task](tmp); shutil.copy(tmp / "_pristine.json", d / "_pristine.json") if (tmp / "_pristine.json").exists() else None
            try:
                sc, ok, det = H.CHECK[task](d)
            except Exception as e:
                sc, ok, det = 0, False, f"crash {e!r}"
            print(f"{task} mutant{m}: detected={not ok} ({det[:100]})")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        generate(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 2)
    elif cmd == "score":
        score(sys.argv[2:])
    elif cmd == "selftest":
        selftest()
