#!/usr/bin/env python3
"""hx — small harness the Opus orchestrator drives. Stdlib only.

  hx.py new    <task> [--base REF] [--branch NAME] [--setup CMD]   worktree (+ setup) + hidden-test dir
  hx.py call   <role> <task> <spec.md> [--read-only] [--resume]
                                                   run the role's OpenCode model; prints only its final text
                                                   (--resume continues that role's last session, e.g. after TIMEOUT)
  hx.py pair   <task> <spec.md>                    tester and worker in parallel (independent inputs)
  hx.py triage <task> <spec.md>                    judge model classifies failing hidden tests; writes
                                                   worker_feedback.txt (rules only, no test code)
  hx.py gate   <task> --test CMD [--hidden-cmd CMD] [--allow GLOBS] [--protect GLOBS]
  hx.py diff   <task> [--all]                      write the diff for the reviewer (current phase; --all = whole task)
  hx.py commit <task> -m MSG --review ONAY [--phase N] [--next TEXT]
                                                   commit an approved phase in the worktree; next phase diffs from here;
                                                   writes <state>/handoff.md (resume point after context compaction)
  hx.py note   <task> key=value ...                record a decision (verdict, solved_by, ...)
  hx.py report                                     per-task rounds, gate failures, escalations, Go cost
  hx.py prices [--refresh]                         show Go prices / refresh them from models.dev
  hx.py paths  <task>                              print worktree / hidden / state paths

State lives in <git-common-dir>/hx (inside .git, never in a diff). Roles and models: config.json.
"""
import argparse, fnmatch, json, os, re, shlex, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text())


def sh(cmd, cwd=None, check=True, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, shell=isinstance(cmd, str))
    if check and r.returncode != 0:
        sys.exit(f"hx: command failed: {cmd}\n{r.stderr[-2000:]}")
    return r


def repo_root():
    return Path(sh(["git", "rev-parse", "--show-toplevel"]).stdout.strip())


def state_dir():
    common = Path(sh(["git", "rev-parse", "--git-common-dir"]).stdout.strip())
    if not common.is_absolute():
        common = (Path.cwd() / common).resolve()
    d = common / "hx"
    d.mkdir(parents=True, exist_ok=True)
    return d


def task_paths(task):
    root = repo_root()
    st = state_dir() / task
    meta_p = st / "task.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    wt = Path(meta.get("worktree", root.parent / f"{root.name}-wt" / task))
    return {"root": root, "state": st, "worktree": wt, "hidden": st / "hidden", "meta": meta_p,
            "base": meta.get("base")}


def metric(rec):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(state_dir() / "metrics.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ new
def cmd_new(a):
    p = task_paths(a.task)
    if p["worktree"].exists():
        sys.exit(f"hx: worktree exists: {p['worktree']}")
    base = a.base or sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    p["state"].mkdir(parents=True, exist_ok=True)
    p["hidden"].mkdir(exist_ok=True)
    p["worktree"].parent.mkdir(parents=True, exist_ok=True)
    branch = a.branch or f"hx/{a.task}"
    sh(["git", "worktree", "add", "-b", branch, str(p["worktree"]), base])
    p["meta"].write_text(json.dumps({"task": a.task, "worktree": str(p["worktree"]), "base": base, "branch": branch}))
    setup = a.setup if a.setup is not None else CFG.get("setup")
    if setup:
        r = sh(setup, cwd=p["worktree"], check=False)
        if r.returncode != 0:
            sys.exit(f"hx: setup failed ({setup}): {(r.stdout + r.stderr)[-1500:]}")
    metric({"task": a.task, "event": "new", "base": base, "branch": branch, "setup": bool(setup)})
    print(json.dumps({"worktree": str(p["worktree"]), "hidden": str(p["hidden"]), "base": base, "branch": branch}))


def cmd_paths(a):
    p = task_paths(a.task)
    print(json.dumps({k: str(v) for k, v in p.items()}))


# ------------------------------------------------------------------ call
def parse_events(raw):
    texts, tok = [], {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    step_toks = []
    steps = tools = errors = 0
    ts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        if "timestamp" in e:
            ts.append(e["timestamp"])
        part = e.get("part") or {}
        t = e.get("type")
        if t == "text":
            texts.append((part.get("messageID"), part.get("text", "")))
        elif t == "step_finish":
            steps += 1
            k = part.get("tokens") or {}
            tok["input"] += k.get("input", 0); tok["output"] += k.get("output", 0)
            c = k.get("cache") or {}
            st = {"input": k.get("input", 0), "output": k.get("output", 0), "reasoning": k.get("reasoning", 0),
                  "cache_read": c.get("read", 0), "cache_write": c.get("write", 0)}
            step_toks.append(st)
            tok["reasoning"] += st["reasoning"]; tok["cache_read"] += st["cache_read"]; tok["cache_write"] += st["cache_write"]
        elif t in ("tool_use", "tool"):
            tools += 1
        elif t == "error":
            errors += 1
    last = texts[-1][0] if texts else None
    final = "".join(x for m, x in texts if m == last)
    secs = round((ts[-1] - ts[0]) / 1000, 1) if len(ts) > 1 else None
    return final, tok, steps, tools, errors, secs, step_toks


def est_cost(model, steps, tiers=True):
    """Go usage estimate in USD. steps: per-step token dicts (or one aggregate dict). Prices per 1M tokens from
    config.prices (refresh with `hx prices --refresh`); cache reads/writes have their own rates, and a context tier
    (e.g. Qwen above 256k) applies per step. Opencode reports cost 0 for Go, so this is the only number we have."""
    p = CFG["prices"].get(model.split("#")[0])
    if not p:
        return None
    if isinstance(p, list):  # legacy [input, output]
        p = {"input": p[0], "output": p[1]}
    total = 0.0
    for t in ([steps] if isinstance(steps, dict) else steps):
        ctx = t.get("input", 0) + t.get("cache_read", 0) + t.get("cache_write", 0)
        r = p["tier"] if tiers and p.get("tier") and ctx > p.get("tier_ctx", 1e18) else p
        total += (t.get("input", 0) * r["input"] + t.get("cache_read", 0) * r.get("cache_read", r["input"])
                  + t.get("cache_write", 0) * r.get("cache_write", r["input"])
                  + (t.get("output", 0) + t.get("reasoning", 0)) * r["output"]) / 1e6
    return round(total, 4)


def cmd_prices(a):
    """Show the configured prices, or refresh the opencode-go ones from models.dev (public price list)."""
    if a.refresh:
        import urllib.request
        req = urllib.request.Request("https://models.dev/api.json", headers={"User-Agent": "hx-harness/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        models = (data.get("opencode-go") or {}).get("models") or {}
        new = {}
        for mid, m in models.items():
            c = m.get("cost") or {}
            if "input" not in c or "output" not in c:
                continue
            e = {k: c[k] for k in ("input", "output", "cache_read", "cache_write") if k in c}
            tiers = c.get("tiers") or []
            if tiers and tiers[0].get("tier", {}).get("type") == "context":
                e["tier_ctx"] = tiers[0]["tier"]["size"]
                e["tier"] = {k: tiers[0][k] for k in ("input", "output", "cache_read", "cache_write") if k in tiers[0]}
            new[f"opencode-go/{mid}"] = e
        if not new:
            sys.exit("hx: no opencode-go prices found; config unchanged")
        cfg_path = HERE / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["prices"] = dict(sorted(new.items()))
        cfg["prices_source"] = f"models.dev opencode-go, {time.strftime('%Y-%m-%d', time.gmtime())}"
        tmp = cfg_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, cfg_path)
        CFG["prices"] = cfg["prices"]
    for mid, e in CFG["prices"].items():
        print(f"{mid:40} {json.dumps(e)}")


_lock = threading.Lock()


def reap_orphans(paths, grace=3.0):
    """OpenCode runs shell commands through its long-lived pty daemon; they can keep running (or start late)
    after `opencode run` returns and then race the gate or edit the worktree. Kill every process whose command
    line names the task's worktree or hidden dir, children first. Returns how many were signalled."""
    me = os.getpid()
    keys = [str(x) for x in paths]
    def scan():
        out = sh(["ps", "-Ao", "pid=,ppid=,args="], check=False).stdout.splitlines()
        rows = []
        for line in out:
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit():
                rows.append((int(parts[0]), int(parts[1]), parts[2]))
        return rows
    rows = scan()
    parent = {pid: ppid for pid, ppid, _ in rows}
    protect, cur = set(), me
    while cur and cur not in protect:  # never signal hx itself or the shell that started it
        protect.add(cur); cur = parent.get(cur)
    hit = {pid for pid, _, args in rows if pid not in protect and any(k in args for k in keys)}
    # include descendants of matched shells (npm test -> node --test -> workers)
    changed = True
    while changed:
        changed = False
        for pid, ppid, _ in rows:
            if ppid in hit and pid not in hit and pid not in protect:
                hit.add(pid); changed = True
    for sig in (15, 9):
        for pid in sorted(hit, reverse=True):
            try: os.kill(pid, sig)
            except (ProcessLookupError, PermissionError): pass
        if sig == 15 and hit:
            time.sleep(grace)
    return len(hit)


HIDDEN_HEADING = re.compile(r"^(#+)\s*(hidden test format|gizli test biçimi)\b.*$", re.I | re.M)


def strip_hidden_section(spec):
    """Remove the spec's hidden-test section (tester-only instructions and paths) for roles that must not see it."""
    m = HIDDEN_HEADING.search(spec)
    if not m:
        return spec
    level = len(m.group(1))
    rest = spec[m.end():]
    nxt = re.search(r"^#{1,%d}\s" % level, rest, re.M)
    end = m.end() + (nxt.start() if nxt else len(rest))
    return (spec[:m.start()] + spec[end:]).rstrip() + "\n"


def run_streaming(args, cwd, env, limit, stall_limit):
    """Run opencode and read its JSON event stream. Kill it on the total time limit, or when it emits no event for
    stall_limit seconds (models can hang silently, e.g. a tool-call repetition loop)."""
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, errbuf, last = [], [], [time.time()]
    def pump(stream, sink, touch):
        for line in stream:
            sink.append(line)
            if touch:
                last[0] = time.time()
    t1 = threading.Thread(target=pump, args=(proc.stdout, out, True), daemon=True)
    t2 = threading.Thread(target=pump, args=(proc.stderr, errbuf, False), daemon=True)
    t1.start(); t2.start()
    start, timeout, stalled = time.time(), False, False
    while proc.poll() is None:
        time.sleep(2)
        now = time.time()
        if now - start > limit:
            timeout = True
        elif now - last[0] > stall_limit:
            timeout = stalled = True
        if timeout:
            proc.kill(); break
    proc.wait(); t1.join(5); t2.join(5)
    err = "".join(errbuf) + ("\nSTALLED" if stalled else "\nTIMEOUT" if timeout else "")
    return "".join(out), err, timeout, stalled


def run_role(role_name, task, spec_path, feedback=None, model=None, read_only=False, max_chars=None, reap=True, timeout_s=None, resume=False):
    """Run one role; returns (final_text, summary_line). feedback = path or None."""
    role = CFG["roles"].get(role_name)
    if not role:
        sys.exit(f"hx: unknown role {role_name}; roles: {', '.join(CFG['roles'])}")
    p = task_paths(task)
    spec = Path(spec_path).read_text()
    sees_hidden = role.get("cwd") == "hidden"  # tester and judge only
    if not sees_hidden:
        spec = strip_hidden_section(spec)
    tmpl = (HERE / "templates" / role["template"]).read_text()
    cwd = p["hidden"] if role.get("cwd") == "hidden" else p["worktree"]
    cwd.mkdir(parents=True, exist_ok=True)
    prompt = (tmpl.replace("{SPEC}", spec).replace("{WORKTREE}", str(p["worktree"]))
              .replace("{HIDDEN}", str(p["hidden"]) if sees_hidden else "(not available to this role)").replace("{FEEDBACK}", Path(feedback).read_text() if feedback else "Yok."))
    model = model or role["model"]
    args = ["opencode", "run", "-m", model, "--format", "json"]
    session = None
    if resume:
        session = last_session(task, role_name)
        if not session:
            sys.exit(f"hx: no earlier {role_name} session recorded for {task}; call without --resume")
        args += ["--session", session]
        prompt = ("You were stopped before you finished (time limit). Continue the same task in the same worktree from "
                  "where you stopped. Run `git status` and `git diff --stat` first; do not redo finished work.\n\n"
                  "# Feedback (fix these too; \"Yok.\" means none)\n" + (Path(feedback).read_text() if feedback else "Yok.")
                  + "\n\nThen go through the final checklist of the original instructions and write the report as asked there.")
    if read_only or role.get("read_only"):
        args += ["--agent", "plan"]
    args.append(prompt)
    env = dict(os.environ, PWD=str(cwd))
    with _lock:
        n = len(list(p["state"].glob(f"{role_name}-*.jsonl"))) + 1
        (p["state"] / f"{role_name}-{n}.jsonl").write_text("")  # reserve the number
    t0 = time.time()
    raw, err, timeout = "", "", False
    limit = timeout_s or role.get("timeout_s") or CFG["timeout_s"]
    stall_limit = role.get("stall_s") or CFG.get("stall_s", 900)
    stalled = False
    for attempt in range(4):
        raw, err, timeout, stalled = run_streaming(args, cwd, env, limit, stall_limit)
        low = (raw + err).lower()
        if ("usage limit" in low or "rate limit" in low) and attempt < 3:
            time.sleep(90); continue
        break
    (p["state"] / f"{role_name}-{n}.jsonl").write_text(raw)
    reaped = reap_orphans([p["worktree"], p["hidden"]]) if reap else 0
    final, tok, steps, tools, errors, secs, step_toks = parse_events(raw)
    m = re.search(r'"sessionID"\s*:\s*"([^"]+)"', raw)
    rec = {"task": task, "event": "call", "role": role_name, "n": n, "model": model, "seconds": secs,
           "session": m.group(1) if m else session, "resumed": bool(resume),
           "wall": round(time.time() - t0, 1), "steps": steps, "tool_calls": tools, "errors": errors,
           "timeout": timeout, "stalled": stalled, "hidden_access": (not sees_hidden) and (str(p["hidden"]) in raw or "/.git/hx/" in raw), "tokens": tok, "go_cost_est": est_cost(model, step_toks), "price_v": 2, "reaped": reaped}
    with _lock:
        metric(rec)
    full = final.strip()
    out = full or f"(no final text; errors={errors}, timeout={timeout}; raw in {p['state']}/{role_name}-{n}.jsonl)"
    max_chars = max_chars or CFG["max_chars"]
    if len(out) > max_chars:
        out = out[: max_chars] + f"\n…[truncated; full text in {p['state']}/{role_name}-{n}.jsonl]"
    line = (f"[hx] {role_name}#{n}{' (resumed)' if resume else ''} {model} {secs}s steps={steps} out={tok['output']+tok['reasoning']} cost≈${rec['go_cost_est']}"
            + (" WARNING: touched the hidden-test directory" if rec["hidden_access"] else "")
            + (f" TIMEOUT({limit}s; continue with --resume)" if timeout and not stalled else "") + (f" STALLED(no event for {stall_limit}s)" if stalled else "")
            + (f" reaped={reaped} leftover processes" if reaped else ""))
    return full, out, line


def last_session(task, role_name):
    mp = state_dir() / "metrics.jsonl"
    sid = None
    for l in (mp.read_text().splitlines() if mp.exists() else []):
        r = json.loads(l)
        if r.get("task") == task and r.get("event") == "call" and r.get("role") == role_name and r.get("session"):
            sid = r["session"]
    return sid


def cmd_call(a):
    _, out, line = run_role(a.role, a.task, a.spec, a.feedback, a.model, a.read_only, a.max_chars, timeout_s=a.timeout, resume=a.resume)
    print(out); print("\n" + line)


def cmd_pair(a):
    """Tester and worker read the same spec and never each other's output, so they run concurrently."""
    res = {}
    def go(role):
        res[role] = run_role(role, a.task, a.spec, max_chars=a.max_chars, reap=False)
    th = [threading.Thread(target=go, args=(r,)) for r in ("tester", "worker")]
    for t in th: t.start()
    for t in th: t.join()
    p = task_paths(a.task)
    reaped = reap_orphans([p["worktree"], p["hidden"]])  # only after both roles are done
    if reaped:
        print(f"[hx] pair: stopped {reaped} leftover processes")
    for role in ("tester", "worker"):
        print(f"===== {role.upper()}\n{res[role][1]}\n{res[role][2]}\n")


def cmd_triage(a):
    """Judge model reads spec + hidden failure; split into test errors and code errors (rules, no test code)."""
    p = task_paths(a.task)
    fail = p["state"] / "hidden_failure.txt"
    if not fail.exists():
        sys.exit("hx: no hidden_failure.txt (hidden tests did not fail in the last gate)")
    full, out, line = run_role("judge", a.task, a.spec, feedback=str(fail), max_chars=a.max_chars)
    # Only verdict lines in the template's form ("KOD_HATASI — rule — what the code does"); prose such as
    # "KOD_HATASI yok. ..." is not a verdict and must never reach the worker (it may quote test details).
    verdict = lambda tag: [l.strip() for l in full.splitlines() if re.match(tag + r"\s*[—–-]\s+\S", l.strip())]
    code, test = verdict("KOD_HATASI"), verdict("TEST_HATASI")
    fb = p["state"] / "worker_feedback.txt"
    vis = p["state"] / "visible_failure.txt"
    parts = []
    if vis.exists():
        parts.append(vis.read_text())
    if code:
        parts.append("Gizli kabul testleri şu spec kurallarının ihlal edildiğini gösteriyor (test kodu paylaşılmaz):\n"
                     + "\n".join(re.sub(r"^KOD_HATASI\s*[—-]\s*", "- ", l) for l in code))
    fb.write_text("\n\n".join(parts) if parts else "")
    (p["state"] / "test_issues.txt").write_text("\n".join(test))
    metric({"task": a.task, "event": "triage", "code_errors": len(code), "test_errors": len(test)})
    print(out); print("\n" + line)
    print(f"[hx] triage: code_errors={len(code)} test_errors={len(test)}; worker feedback: {fb}"
          + (f"; test issues: {p['state'] / 'test_issues.txt'}" if test else ""))


# ------------------------------------------------------------------ gate
def changed_files(wt, base):
    tracked = sh(["git", "diff", "--name-only", base], cwd=wt).stdout.split()
    untracked = sh(["git", "ls-files", "--others", "--exclude-standard"], cwd=wt).stdout.split()
    return sorted(set(tracked + untracked))


def match_any(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def tail(s, n=30):
    lines = s.strip().splitlines()
    return "\n".join(lines[-n:])


def cmd_gate(a):
    p = task_paths(a.task)
    wt, base = p["worktree"], p["base"]
    allow = [g for g in (a.allow or "").split(",") if g]
    protect = [g for g in (a.protect or "").split(",") if g]
    reaped = reap_orphans([wt, p["hidden"]])
    if reaped:
        print(f"[hx] gate: stopped {reaped} leftover processes in the worktree before testing")
    files = changed_files(wt, base)
    out_of_scope = [f for f in files if allow and not match_any(f, allow)]
    touched_protected = [f for f in files if match_any(f, protect)]
    results = {"changed": files, "out_of_scope": out_of_scope, "protected_touched": touched_protected}
    env = dict(os.environ, PYTHONPATH=str(wt) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    fails = []
    for f in ("visible_failure.txt", "hidden_failure.txt"):
        (p["state"] / f).unlink(missing_ok=True)
    for label, cmd in (("tests", a.test), ("hidden", a.hidden_cmd)):
        if not cmd:
            continue
        cmd = cmd.replace("{hidden}", shlex.quote(str(p["hidden"]))).replace("{wt}", shlex.quote(str(wt)))
        tries = 1 + (a.retry if label == "tests" else 0)
        for attempt in range(tries):
            r = subprocess.run(cmd, cwd=wt, shell=True, capture_output=True, text=True, env=env, timeout=a.gate_timeout)
            (p["state"] / f"{label}.log").write_text(r.stdout + r.stderr)
            if r.returncode == 0:
                break
            if attempt + 1 < tries:
                print(f"[hx] gate: {label} failed (attempt {attempt + 1}); retrying once (flaky timing tests)")
                reap_orphans([wt, p["hidden"]])
        results[label] = "pass" if r.returncode == 0 else "fail"
        if attempt and r.returncode == 0:
            results[f"{label}_retried"] = attempt
        if r.returncode != 0:
            out = r.stdout + r.stderr
            # TAP runners (node --test, prove, ...): list the failing test names first; TODO/SKIP lines are not failures.
            failing = [l for l in out.splitlines() if l.startswith("not ok") and "# TODO" not in l and "# SKIP" not in l]
            head = ("failing tests:\n" + "\n".join(failing[:20]) + "\n") if failing else ""
            text = (f"--- {label} ({cmd}) exit {r.returncode}\n{head}{tail(out, 60 if label == 'hidden' else 30)}"
                    f"\n(full log: {p['state'] / (label + '.log')})")
            fails.append(text)
            (p["state"] / ("hidden_failure.txt" if label == "hidden" else "visible_failure.txt")).write_text(text)
    ok = not out_of_scope and not touched_protected and not fails
    results["gate"] = "PASS" if ok else "FAIL"
    (p["state"] / "last_gate.json").write_text(json.dumps({"gate": results["gate"], "fingerprint": tree_fingerprint(wt, base)}))
    metric({"task": a.task, "event": "gate", **{k: v for k, v in results.items() if k != "changed"}, "n_changed": len(files)})
    print(json.dumps(results, ensure_ascii=False))
    (p["state"] / "last_gate.txt").write_text(json.dumps(results, ensure_ascii=False, indent=1) + ("\n\n" + "\n".join(fails) if fails else ""))
    if fails:
        fb = p["state"] / "last_gate_failure.txt"
        fb.write_text("\n".join(fails))
        print("\n".join(fails))
        if results.get("hidden") == "fail":
            print(f"\n[hx] hidden tests failed: run `hx triage {a.task} <spec>` before feeding back (do not send {fb} to the worker)")
        else:
            print(f"\n[hx] visible failure only; worker feedback: {p['state'] / 'visible_failure.txt'}")
    else:
        (p["state"] / "last_gate_failure.txt").unlink(missing_ok=True)
    sys.exit(0 if ok else 1)


# ------------------------------------------------------------------ diff / commit / note / report
def tree_fingerprint(wt, base):
    import hashlib
    sh(["git", "add", "-N", "."], cwd=wt, check=False)
    return hashlib.sha256(sh(["git", "diff", "--binary", base], cwd=wt).stdout.encode()).hexdigest()


def cmd_diff(a):
    p = task_paths(a.task)
    wt = p["worktree"]
    base = (json.loads(p["meta"].read_text()).get("task_base") or p["base"]) if a.all else p["base"]
    sh(["git", "add", "-N", "."], cwd=wt, check=False)  # include new files in diff without staging content
    diff = sh(["git", "diff", base], cwd=wt).stdout
    stat = sh(["git", "diff", "--stat", base], cwd=wt).stdout
    out = p["state"] / "review.diff"
    out.write_text(diff)
    print(f"{out}\n{stat.strip()}\nlines={len(diff.splitlines())}")


def cmd_commit(a):
    """Commit one approved phase inside the worktree. Refuses unless the last gate passed on exactly this tree and the
    blind review said ONAY. The next phase is gated and diffed against this commit."""
    p = task_paths(a.task)
    wt, base = p["worktree"], p["base"]
    if a.review != "ONAY":
        sys.exit("hx: commit needs --review ONAY (blind review approval)")
    gp = p["state"] / "last_gate.json"
    g = json.loads(gp.read_text()) if gp.exists() else {}
    if g.get("gate") != "PASS":
        sys.exit("hx: last gate did not pass; run hx gate first")
    if g.get("fingerprint") != tree_fingerprint(wt, base):
        sys.exit("hx: worktree changed after the last gate; run hx gate again")
    sh(["git", "add", "-A"], cwd=wt)
    if not sh(["git", "diff", "--cached", "--name-only"], cwd=wt).stdout.strip():
        sys.exit("hx: nothing to commit")
    trailer = CFG.get("commit_trailer", "")
    msg = a.m + (f"\n\n{trailer}" if trailer else "")
    sh(["git", "commit", "-q", "-m", msg], cwd=wt)
    head = sh(["git", "rev-parse", "HEAD"], cwd=wt).stdout.strip()
    meta = json.loads(p["meta"].read_text())
    meta.setdefault("task_base", meta["base"])
    meta["base"] = head
    meta["phases"] = meta.get("phases", []) + [{"phase": a.phase, "commit": head, "msg": a.m.splitlines()[0]}]
    p["meta"].write_text(json.dumps(meta))
    gp.unlink()
    metric({"task": a.task, "event": "phase_commit", "phase": a.phase, "commit": head})
    done = "\n".join(f"- faz {x['phase'] or '?'}: {x['commit'][:9]} {x['msg']}" for x in meta["phases"])
    hand = (f"# {a.task} — devir notu\n\nworktree: {wt}\nbranch: {meta['branch']}\ntask_base: {meta['task_base']}\n"
            f"hidden: {p['hidden']}\n\n## Biten fazlar\n{done}\n\n## Sıradaki\n{a.next or '(yazılmadı)'}\n")
    (p["state"] / "handoff.md").write_text(hand)
    print(f"[hx] phase {a.phase or '?'} committed {head[:9]} on {meta['branch']}; next phase diffs from here")
    print(f"[hx] handoff: {p['state'] / 'handoff.md'}")


def cmd_note(a):
    rec = {"task": a.task, "event": "note"}
    for kv in a.kv:
        k, _, v = kv.partition("=")
        rec[k] = v
    metric(rec)
    print("noted")


def cmd_report(a):
    mp = state_dir() / "metrics.jsonl"
    if not mp.exists():
        print("no metrics yet"); return
    tasks = {}
    for line in mp.read_text().splitlines():
        r = json.loads(line)
        t = tasks.setdefault(r["task"], {"calls": {}, "gates": 0, "gate_fail": 0, "cost": 0.0, "notes": {}})
        if r["event"] == "call":
            t["calls"][r["role"]] = t["calls"].get(r["role"], 0) + 1
            # recomputed from stored tokens with current prices (older records used a wrong price table)
            # price_v 2 = per-step estimate; older records are recomputed from their token totals (no context tier)
            t["cost"] += (r.get("go_cost_est") if r.get("price_v") == 2 else est_cost(r.get("model", ""), r.get("tokens") or {}, tiers=False)) or 0
        elif r["event"] == "gate":
            t["gates"] += 1; t["gate_fail"] += r["gate"] == "FAIL"
        elif r["event"] == "triage":
            t.setdefault("triage", [0, 0]); t["triage"][0] += r.get("code_errors", 0); t["triage"][1] += r.get("test_errors", 0)
        elif r["event"] == "note":
            t["notes"].update({k: v for k, v in r.items() if k not in ("task", "event", "ts")})
    print(f"{'task':20} {'calls':32} {'gates':>5} {'fail':>4} {'go$':>7}  notes")
    for name, t in tasks.items():
        calls = " ".join(f"{k}:{v}" for k, v in t["calls"].items())
        tri = f" triage(code/test)={t['triage'][0]}/{t['triage'][1]}" if "triage" in t else ""
        print(f"{name:20} {calls:32} {t['gates']:>5} {t['gate_fail']:>4} {t['cost']:>7.3f}  {t['notes']}{tri}")


def main():
    ap = argparse.ArgumentParser(prog="hx")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("new"); s.add_argument("task"); s.add_argument("--base"); s.add_argument("--branch")
    s.add_argument("--setup", help="shell command run in the new worktree (default: config.setup)"); s.set_defaults(fn=cmd_new)
    s = sp.add_parser("pair"); s.add_argument("task"); s.add_argument("spec")
    s.add_argument("--max-chars", type=int, default=CFG["max_chars"]); s.set_defaults(fn=cmd_pair)
    s = sp.add_parser("triage"); s.add_argument("task"); s.add_argument("spec")
    s.add_argument("--max-chars", type=int, default=CFG["max_chars"]); s.set_defaults(fn=cmd_triage)
    s = sp.add_parser("paths"); s.add_argument("task"); s.set_defaults(fn=cmd_paths)
    s = sp.add_parser("call"); s.add_argument("role"); s.add_argument("task"); s.add_argument("spec")
    s.add_argument("--feedback"); s.add_argument("--model"); s.add_argument("--read-only", action="store_true")
    s.add_argument("--max-chars", type=int, default=CFG["max_chars"]); s.add_argument("--timeout", type=int, help="seconds (default: role or config timeout_s)")
    s.add_argument("--resume", action="store_true", help="continue this role's last session for the task (after TIMEOUT/STALLED)")
    s.set_defaults(fn=cmd_call)
    s = sp.add_parser("gate"); s.add_argument("task"); s.add_argument("--test"); s.add_argument("--hidden-cmd")
    s.add_argument("--allow"); s.add_argument("--protect")
    s.add_argument("--retry", type=int, default=CFG.get("gate_retry", 1), help="re-run the visible test command this many times on failure")
    s.add_argument("--gate-timeout", type=int, default=CFG.get("gate_timeout_s", 1800)); s.set_defaults(fn=cmd_gate)
    s = sp.add_parser("diff"); s.add_argument("task"); s.add_argument("--all", action="store_true", help="whole task, all phases"); s.set_defaults(fn=cmd_diff)
    s = sp.add_parser("commit"); s.add_argument("task"); s.add_argument("-m", required=True); s.add_argument("--review", required=True)
    s.add_argument("--phase"); s.add_argument("--next", help="what the next phase is (goes into handoff.md)"); s.set_defaults(fn=cmd_commit)
    s = sp.add_parser("note"); s.add_argument("task"); s.add_argument("kv", nargs="+"); s.set_defaults(fn=cmd_note)
    s = sp.add_parser("report"); s.set_defaults(fn=cmd_report)
    s = sp.add_parser("prices"); s.add_argument("--refresh", action="store_true"); s.set_defaults(fn=cmd_prices)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
