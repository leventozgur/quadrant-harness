#!/usr/bin/env python3
"""hx — small harness the Opus orchestrator drives. Stdlib only.

  hx.py new    <task> [--base REF] [--branch NAME] [--setup CMD]   worktree (+ setup) + hidden-test dir
  hx.py call   <role> <task> <spec.md> [--read-only] [--resume] [--force-retry]
                                                   run the role's OpenCode model; prints only its final text
                                                   (--resume continues that role's last session, e.g. after TIMEOUT;
                                                   worker/escalate calls are capped per phase, --force-retry overrides)
  hx.py pair   <task> <spec.md>                    tester and worker in parallel (independent inputs)
  hx.py triage <task> <spec.md>                    judge model classifies failing hidden tests; writes
                                                   worker_feedback.txt (rules only, no test code)
  hx.py gate   <task> --test CMD [--hidden-cmd CMD] --allow GLOBS [--protect GLOBS] [--no-tests]
  hx.py diff   <task> [--all]                      write the diff for the reviewer (current phase; --all = whole task)
  hx.py review <task> <reviewer_output.md>         record the blind reviewer's ONAY/RED with the diff's sha256
  hx.py commit <task> -m MSG [--phase N] [--next TEXT]   needs a recorded ONAY for the current diff
                                                   commit an approved phase in the worktree; next phase diffs from here;
                                                   writes <state>/handoff.md (resume point after context compaction)
  hx.py note   <task> key=value ...                record a decision (verdict, solved_by, ...)
  hx.py report                                     per-task rounds, gate failures, escalations, Go cost
  hx.py prices [--refresh]                         show Go prices / refresh them from models.dev
  hx.py paths  <task>                              print worktree / hidden / state paths

State lives in <git-common-dir>/hx (inside .git, never in a diff). Roles and models: config.json.
"""
import argparse, json, os, re, shlex, subprocess, sys, threading, time
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


# ------------------------------------------------------------------ child environment
# Names that look like credentials are hidden from model processes and gate commands: the model's shell
# reads `opencode run`'s environment, so a token in the shell would otherwise reach the model and its prompt.
_SECRET_HINTS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASSPHRASE", "API_KEY", "APIKEY",
                 "PRIVATE_KEY", "CREDENTIAL", "ACCESS_KEY", "AUTHORIZATION", "COOKIE", "SESSION_KEY")
_SECRET_PREFIXES = ("AWS_", "GITHUB_", "GH_", "AZURE_", "GOOGLE_", "GCP_", "OPENAI_", "ANTHROPIC_")
# NPM_*/npm_config_* and DOCKER_* are ordinary tool configuration (registry, cache, DOCKER_HOST) and stay; only the
# known credential carriers are hidden: names containing TOKEN/PASSWORD/... already match the hints above.
_SECRET_NAMES = ("DOCKER_AUTH_CONFIG",)
_SECRET_SUFFIXES = ("_CONFIG__AUTH",)  # npm_config__auth (base64 user:password)
_ENV_ALWAYS_KEEP = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "TERM", "PWD"}


def env_hidden(name):
    """True when an environment variable name looks secret (case-insensitive substring/prefix test)."""
    up = name.upper()
    if up.startswith("OPENCODE_") or up in _ENV_ALWAYS_KEEP or up.startswith("LC_"):
        return False
    if up in _SECRET_NAMES or up.endswith(_SECRET_SUFFIXES):
        return True
    if any(h in up for h in _SECRET_HINTS) or up.startswith(_SECRET_PREFIXES):
        return True
    return "DATABASE_URL" in up or "CONNECTION_STRING" in up


def safe_env(base, keep=()):
    """Copy of `base` without secret-looking names; OPENCODE_*, core shell names and `keep` (exact names) stay."""
    keep = set(keep or ())
    return {k: v for k, v in base.items() if k in keep or not env_hidden(k)}


def child_env(base, keep=()):
    """(filtered env, sorted names of the dropped variables). Values are never logged."""
    env = safe_env(base, keep)
    return env, sorted(set(base) - set(env))


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


def is_opencode(args):
    """True when the executable name (basename of argv[0]) starts with "opencode": `opencode`,
    `opencode-pty`, `/opt/homebrew/.../bin/opencode`. `ps` joins argv with spaces, so an executable under a path
    with spaces (`/Users/Jane Doe/.cache/opencode/bin/opencode-pty daemon`) is recognised by growing the leading
    tokens until the joined path exists on disk."""
    toks = args.split()
    for k in range(1, min(len(toks), 6) + 1):
        cand = " ".join(toks[:k])
        if os.path.basename(cand).startswith("opencode") and (k == 1 or os.path.exists(cand)):
            return True
        if k == 1 and not toks[0].startswith("/"):
            break  # a bare command name cannot contain spaces
    return False


def reap_targets(rows, keys, protect=(), extra=()):
    """Pick the pids to signal from (pid, ppid, args) rows — pure, so the decision is testable.

    A process is a target only when BOTH hold: its command line contains one of `keys` (substring, as before) and
    it runs under OpenCode (itself or an ancestor up the ppid chain is an OpenCode process), or it is in `extra`
    (init orphans selected by reap_orphans). Every descendant of a
    target is a target too (npm test -> node --test -> workers). `protect` (hx and its ancestors) is never killed.
    A user's shell, editor, `tail -f` or probe script that merely names the path has no OpenCode ancestor, so it is
    left alone."""
    keys = [str(k) for k in keys]
    protect = set(protect)
    parent = {pid: ppid for pid, ppid, _ in rows}
    args_of = {pid: args for pid, _, args in rows}

    def under_opencode(pid):
        seen, cur = set(), pid
        while cur and cur not in seen:
            if is_opencode(args_of.get(cur, "")):
                return True
            seen.add(cur)
            cur = parent.get(cur)
        return False

    hit = {pid for pid, _, args in rows
           if pid not in protect and any(k in args for k in keys) and under_opencode(pid)}
    hit |= {pid for pid in extra if pid not in protect}  # init orphans proven to be this task's (see reap_orphans)
    # include descendants of matched shells (npm test -> node --test -> workers)
    changed = True
    while changed:
        changed = False
        for pid, ppid, _ in rows:
            if ppid in hit and pid not in hit and pid not in protect:
                hit.add(pid); changed = True
    return hit


def etime_seconds(text):
    """ps etime ([[dd-]hh:]mm:ss) -> seconds; None when unparsable."""
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", text.strip())
    if not m:
        return None
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + sec


def first_call_at(p):
    """Epoch seconds of the task's first model call, written once by run_role; None before any call."""
    f = p["state"] / "first_call_at"
    try:
        return float(f.read_text())
    except (OSError, ValueError):
        return None


def mark_first_call(p):
    f = p["state"] / "first_call_at"
    if not f.exists():
        f.write_text(str(time.time()))


def init_orphans(rows, roots, since, now=None):
    """Pids of processes that (a) were handed to init (ppid 1), (b) were born at or after `since` and (c) either
    have their cwd inside one of `roots` (checked with lsof) or name a root on their command line. Needs `since`:
    without it nothing is selected, so a user's long-running `nohup` job started earlier is never touched."""
    if since is None:
        return set()
    now = now or time.time()
    named = {pid for pid, ppid, args in rows if ppid == 1 and any(r in args for r in roots)}
    ages = {}
    for line in sh(["ps", "-Ao", "pid=,ppid=,etime="], check=False).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].isdigit() and parts[1] == "1":
            secs = etime_seconds(parts[2])
            if secs is not None and now - secs >= since - 1:  # etime has 1 s resolution
                ages[int(parts[0])] = secs
    young = set(ages)
    if not young:
        return set()
    in_root = set()
    out = sh(["lsof", "-a", "-d", "cwd", "-Fpn", "-p", ",".join(str(x) for x in sorted(young))], check=False).stdout
    cur = None
    reals = [str(r) for r in roots] + [os.path.realpath(str(r)) for r in roots]
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            cur = int(line[1:])
        elif line.startswith("n") and cur is not None:
            path = line[1:]
            if any(path == r or path.startswith(r.rstrip("/") + "/") for r in reals):
                in_root.add(cur)
    return young & (named | in_root)


_CMD_SECRET = re.compile(r"(?i)((?:token|secret|password|passwd|api[_-]?key|authorization)[\w-]*)(=|\s+)\S+")


def describe_proc(pid, args):
    """{pid, cmd} for the logs: command line cut to 200 chars with secret-looking values masked."""
    return {"pid": pid, "cmd": _CMD_SECRET.sub(r"\1\2***", args)[:200]}


def reap_orphans(paths, grace=3.0, since=None, report=None):
    """OpenCode runs shell commands through its long-lived pty daemon; they can keep running (or start late)
    after `opencode run` returns and then race the gate or edit the worktree. Kill every process that names the
    task's worktree or hidden dir AND runs under OpenCode (see reap_targets), children first, plus init orphans
    born since `since` (the task's first hx call, see init_orphans): the user's own processes are not touched.
    Returns how many were signalled; when `report` is a list, a {pid, cmd} entry per signalled process is
    appended to it (for metrics)."""
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
    hit = reap_targets(rows, keys, protect, init_orphans(rows, keys, since))
    if report is not None:
        args_of = {pid: args for pid, _, args in rows}
        report.extend(describe_proc(pid, args_of.get(pid, "")) for pid in sorted(hit))
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


RATE_LIMIT_SIGNALS = ("rate limit", "rate_limit", "usage limit", "too many requests", "429")
# "429" is a status code, not a digit sequence: a millisecond timestamp (1795004290000) or an id such as
# "msg_429"/"ses_429" must not fake a signal, while 429, "HTTP 429" and `"statusCode": 429` still count.
STATUS_429 = re.compile(r"(?<!\w)429(?!\w)")

# Transport metadata whose values may contain "429" by accident (a millisecond timestamp, a session or
# message id).
META_KEYS = ("timestamp", "sessionID", "messageID")
# The envelope of an event object: those names plus the event's own "type". Only the event object carries
# an envelope; a NESTED "type" such as "rate_limit_error" names the error kind and must stay searchable.
EVENT_META_KEYS = META_KEYS + ("type",)


def strip_meta(obj):
    """Copy of a TOP-LEVEL event object without its envelope (`EVENT_META_KEYS`), so timestamp/id digits are
    never searched.

    Only the event object itself has an envelope. Nested objects are payload and are copied unchanged: a
    nested `"type": "rate_limit_error"` and any nested error message/status ("HTTP 429", `"statusCode": 429`)
    keep their values, and a nested timestamp or id is not silently dropped either.
    """
    if not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k not in EVENT_META_KEYS}


def error_payload(e):
    """Searchable text of one `"type": "error"` event: the event object without its top-level envelope, with
    every nested field kept, serialised back to JSON."""
    return json.dumps(strip_meta(e), ensure_ascii=False, default=str).lower()


def has_signal(text):
    """True when `text` mentions a rate limit; "429" only counts as a standalone status code."""
    low = text.lower()
    if any(s in low for s in RATE_LIMIT_SIGNALS if s != "429"):
        return True
    return bool(STATUS_429.search(low))


def rate_limited(raw, err):
    """True when this attempt carries a rate-limit signal: in stderr, or in an error event's payload.

    Model prose ("text" events) and tool input/output never count — a task that merely writes about a rate
    limiter must not be retried. `raw`/`err` are one attempt's stdout/stderr.
    """
    low = err.lower()
    if has_signal(low):
        return True
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and e.get("type") == "error" and has_signal(error_payload(e)):
            return True
    return False


def run_role(role_name, task, spec_path, feedback=None, model=None, read_only=False, max_chars=None, reap=True, timeout_s=None, resume=False, force=False):
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
    base_env = dict(os.environ)
    env, env_dropped = child_env(base_env, CFG.get("env_passthrough") or [])
    env["PWD"] = str(cwd)  # added after filtering so the role's cwd is never dropped
    with _lock:
        # only plain "<role>-<n>.jsonl" files count; "<role>-<n>.attempt<k>.jsonl" retries must not shift n
        n = sum(1 for f in p["state"].glob(f"{role_name}-*.jsonl") if f.stem[len(role_name) + 1:].isdigit()) + 1
        (p["state"] / f"{role_name}-{n}.jsonl").write_text("")  # reserve the number
    mark_first_call(p)
    t0 = time.time()
    raw, err, timeout = "", "", False
    limit = timeout_s or role.get("timeout_s") or CFG["timeout_s"]
    stall_limit = role.get("stall_s") or CFG.get("stall_s", 900)
    stalled = False
    attempts = 0
    for attempt in range(4):
        raw, err, timeout, stalled = run_streaming(args, cwd, env, limit, stall_limit)
        attempts = attempt + 1
        steps_now = parse_events(raw)[2]
        # retry only a clean-looking rate-limited attempt: no step finished AND a signal in stderr/an error event.
        # timeouts/stalls are never retried, and the last of the 4 attempts is always final.
        if timeout or stalled or steps_now or attempt == 3 or not rate_limited(raw, err):
            break
        (p["state"] / f"{role_name}-{n}.attempt{attempts}.jsonl").write_text(raw)
        time.sleep(CFG.get("rate_limit_wait_s", 90))
    (p["state"] / f"{role_name}-{n}.jsonl").write_text(raw)
    reaped_procs = []
    reaped = reap_orphans([p["worktree"], p["hidden"]], since=first_call_at(p), report=reaped_procs) if reap else 0
    final, tok, steps, tools, errors, secs, step_toks = parse_events(raw)
    m = re.search(r'"sessionID"\s*:\s*"([^"]+)"', raw)
    rec = {"task": task, "event": "call", "role": role_name, "n": n, "model": model, "seconds": secs,
           "session": m.group(1) if m else session, "resumed": bool(resume),
           "wall": round(time.time() - t0, 1), "steps": steps, "tool_calls": tools, "errors": errors,
           "timeout": timeout, "stalled": stalled, "attempts": attempts, "hidden_access": (not sees_hidden) and (str(p["hidden"]) in raw or "/.git/hx/" in raw), "tokens": tok, "go_cost_est": est_cost(model, step_toks), "price_v": 2, "reaped": reaped, "env_dropped": env_dropped}
    if reaped_procs:
        rec["reaped_procs"] = reaped_procs
    if force:
        rec["forced"] = True
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
    force = getattr(a, "force_retry", False)
    check_retry_budget(a.task, a.role, force=force, resume=a.resume)
    _, out, line = run_role(a.role, a.task, a.spec, a.feedback, a.model, a.read_only, a.max_chars,
                            timeout_s=a.timeout, resume=a.resume, force=force)
    print(out); print("\n" + line)


def max_worker_retries():
    """config.max_worker_retries; 2 when the key is missing (or holds something unusable)."""
    try:
        return max(0, int(CFG.get("max_worker_retries", 2)))
    except (TypeError, ValueError):
        return 2


def phase_calls(task, role):
    """Non-resumed `call` records for `task` in the current phase: everything after the task's last
    `phase_commit` record (all of them when the task has no commit yet)."""
    mp = state_dir() / "metrics.jsonl"
    recs = []
    for line in (mp.read_text().splitlines() if mp.exists() else []):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and r.get("task") == task:
            recs.append(r)
    cut = 0
    for i, r in enumerate(recs):
        if r.get("event") == "phase_commit":
            cut = i + 1
    return [r for r in recs[cut:]
            if r.get("event") == "call" and r.get("role") == role and not r.get("resumed")]


def check_retry_budget(task, role, force=False, resume=False):
    """Refuse a `call` that would exceed the phase budget (HX-28): one worker call plus max_worker_retries
    retries, then exactly one escalate. A resumed call continues an earlier attempt, so it is never counted
    and never refused; `--force-retry` overrides the budget. tester/judge/pair are not limited."""
    limit = {"worker": 1 + max_worker_retries(), "escalate": 1}.get(role)
    if limit is None or force or resume:
        return
    used = len(phase_calls(task, role))
    if used < limit:
        return
    if role == "worker":
        sys.exit(f"hx: worker retry limit reached for this phase ({used} calls, allowed {limit}: first call + "
                 f"{limit - 1} retries); run `hx call escalate {task} <spec>` instead (--force-retry overrides)")
    sys.exit(f"hx: escalate already called once in this phase; stop and report to the user, do not call "
             f"escalate again (--force-retry overrides)")


def exit_text(code):
    """SystemExit.code as a message: a string code is already the message, an int becomes "exit code N"."""
    if code is None or code == 0:
        return "exit"
    return f"exit code {code}" if isinstance(code, int) else str(code)


def cmd_pair(a):
    """Tester and worker read the same spec and never each other's output, so they run concurrently."""
    res, fails = {}, {}

    def go(role):
        try:
            res[role] = run_role(role, a.task, a.spec, max_chars=a.max_chars, reap=False)
        except SystemExit as e:  # sys.exit inside a thread only ends that thread; record it instead
            fails[role] = exit_text(e.code)
        except Exception as e:  # noqa: BLE001 - one failing role must not lose the other role's output
            fails[role] = f"{type(e).__name__}: {e}"

    th = [threading.Thread(target=go, args=(r,)) for r in ("tester", "worker")]
    for t in th: t.start()
    for t in th: t.join()
    p = task_paths(a.task)
    reaped_procs = []
    reaped = reap_orphans([p["worktree"], p["hidden"]], since=first_call_at(p), report=reaped_procs)  # only after both roles are done
    if reaped:
        print(f"[hx] pair: stopped {reaped} leftover processes")
        metric({"task": a.task, "event": "reap", "where": "pair", "reaped_procs": reaped_procs})
    for role in ("tester", "worker"):
        if role in res:
            print(f"===== {role.upper()}\n{res[role][1]}\n{res[role][2]}\n")
    for role in ("tester", "worker"):
        if role in fails:
            print(f"[hx] pair: {role} failed: {fails[role]}", file=sys.stderr)
    if fails:
        sys.exit(2)


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
    code, test, unclear = verdict("KOD_HATASI"), verdict("TEST_HATASI"), verdict("BELIRSIZ")
    fb = p["state"] / "worker_feedback.txt"
    vis = p["state"] / "visible_failure.txt"
    parts = []
    if vis.exists():
        parts.append(vis.read_text())
    if code:
        parts.append("Gizli kabul testleri şu spec kurallarının ihlal edildiğini gösteriyor (test kodu paylaşılmaz):\n"
                     + "\n".join(re.sub(r"^KOD_HATASI\s*[—-]\s*", "- ", l) for l in code))
    fb.write_text("\n\n".join(parts) if parts else "")  # BELIRSIZ lines never reach the worker
    issues = list(test)
    if unclear:  # a separate heading, written only when there is at least one BELIRSIZ line
        issues += ["BELIRSIZ:"] + unclear
    (p["state"] / "test_issues.txt").write_text("\n".join(issues))
    metric({"task": a.task, "event": "triage", "code_errors": len(code), "test_errors": len(test),
            "unclear": len(unclear)})
    print(out); print("\n" + line)
    print(f"[hx] triage: code_errors={len(code)} test_errors={len(test)} unclear={len(unclear)}; worker feedback: {fb}"
          + (f"; test issues: {p['state'] / 'test_issues.txt'}" if test or unclear else ""))


# ------------------------------------------------------------------ gate
def _nul_split(raw):
    """Split NUL-separated git output; a path with spaces stays one entry."""
    return [x for x in raw.split("\0") if x]


def changed_files(wt, base):
    tracked = _nul_split(sh(["git", "diff", "--name-only", "-z", base], cwd=wt).stdout)
    untracked = _nul_split(sh(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=wt).stdout)
    return sorted(set(tracked + untracked))


def _glob_segment(seg):
    """Regex for one path segment: `*`/`?`/character classes never cross a "/"."""
    out, i = [], 0
    while i < len(seg):
        c = seg[i]
        i += 1
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i
            if j < len(seg) and seg[j] == "!":  # fnmatch: only "!" negates a class, "^" is literal
                j += 1
            if j < len(seg) and seg[j] == "]":
                j += 1
            while j < len(seg) and seg[j] != "]":
                j += 1
            if j >= len(seg):  # unterminated class: a literal "["
                out.append(r"\[")
                continue
            stuff, i = seg[i:j], j + 1
            if stuff == "":  # empty class: literal "["
                out.append(r"\[")
                continue
            cls = stuff.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
            if stuff.startswith("!"):  # fnmatch: only "!" negates a class
                cls = "^" + cls[1:]
            elif stuff.startswith("^"):  # "^" is a literal character inside the class
                cls = "\\" + cls
            out.append("(?!/)[" + cls + "]")
        else:
            out.append(re.escape(c))
    return "".join(out)


def _glob_regex(pattern):
    """Full-path regex. A `**` that is a whole segment matches zero or more directory segments."""
    parts = pattern.split("/")
    out, need_sep, i = [], False, 0
    while i < len(parts):
        part = parts[i]
        if part == "**":
            last = i == len(parts) - 1
            if last:
                # a trailing `**` covers what is UNDER the prefix: "src/**" is "src/<something>",
                # while a bare "**" is every path.
                out.append("(?:/[^/]+)+" if need_sep else "[^/]+(?:/[^/]+)*")
                need_sep = False
            else:
                if need_sep:
                    out.append("/")
                out.append("(?:[^/]+/)*")
                need_sep = False
        else:
            if need_sep:
                out.append("/")
            out.append(_glob_segment(part))
            need_sep = True
        i += 1
    return "".join(out)


def glob_match(path, pattern):
    """Whole-path match of a repo-relative, "/"-separated path against one glob pattern."""
    return re.fullmatch(_glob_regex(pattern), path) is not None


def match_any(path, globs):
    return any(glob_match(path, g) for g in globs)


def tail(s, n=30):
    lines = s.strip().splitlines()
    return "\n".join(lines[-n:])


def _as_text(v):
    if not v:
        return ""
    return v.decode(errors="replace") if isinstance(v, bytes) else v


def run_with_timeout(cmd, cwd, env, timeout):
    """Run one shell command; on timeout kill its whole process group and keep the partial output.
    Returns (returncode or None, output, timed_out)."""
    proc = subprocess.Popen(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out + err, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        out, err = proc.communicate()
        return None, _as_text(out) + _as_text(err), True


def cmd_gate(a):
    p = task_paths(a.task)
    wt, base = p["worktree"], p["base"]
    allow = [g.strip() for g in (a.allow or "").split(",") if g.strip()]
    protect = [g.strip() for g in (a.protect or "").split(",") if g.strip()]
    no_tests = getattr(a, "no_tests", False)
    if not no_tests and not a.test and not a.hidden_cmd:
        sys.exit("hx: gate needs --test or --hidden-cmd (or --no-tests to gate without tests)")
    if not allow:
        sys.exit("hx: gate needs --allow GLOBS (use --allow '**' to allow every path)")
    gate_reaped = []
    reaped = reap_orphans([wt, p["hidden"]], since=first_call_at(p), report=gate_reaped)
    if reaped:
        print(f"[hx] gate: stopped {reaped} leftover processes in the worktree before testing")
    files = changed_files(wt, base)
    out_of_scope = [f for f in files if not match_any(f, allow)]
    touched_protected = [f for f in files if match_any(f, protect)]
    results = {"changed": files, "out_of_scope": out_of_scope, "protected_touched": touched_protected}
    if no_tests:
        results["no_tests"] = True
    env, env_dropped = child_env(dict(os.environ), CFG.get("env_passthrough") or [])
    env["PYTHONPATH"] = str(wt) + os.pathsep + env.get("PYTHONPATH", "")  # appended after filtering
    results["env_dropped"] = env_dropped
    fails = []
    for f in ("visible_failure.txt", "hidden_failure.txt"):
        (p["state"] / f).unlink(missing_ok=True)
    for label, cmd in (("tests", a.test), ("hidden", a.hidden_cmd)):
        if no_tests or not cmd:  # --no-tests means no test command runs at all
            continue
        cmd = cmd.replace("{hidden}", shlex.quote(str(p["hidden"]))).replace("{wt}", shlex.quote(str(wt)))
        tries = 1 + (a.retry if label == "tests" else 0)
        rc, timed_out, attempt, started = None, False, 0, time.time()
        for attempt in range(tries):
            started = time.time()
            rc, out, timed_out = run_with_timeout(cmd, wt, env, a.gate_timeout)
            (p["state"] / f"{label}.log").write_text(out)
            if rc == 0 or timed_out:  # a hung command stays hung: never retried
                break
            if attempt + 1 < tries:
                print(f"[hx] gate: {label} failed (attempt {attempt + 1}); retrying once (flaky timing tests)")
                reap_orphans([wt, p["hidden"]], since=first_call_at(p), report=gate_reaped)
        failure = p["state"] / ("hidden_failure.txt" if label == "hidden" else "visible_failure.txt")
        if timed_out:
            results[label] = "timeout"
            secs = time.time() - started
            text = (f"--- {label} ({cmd}) TIMEOUT after {secs:.1f}s (limit {a.gate_timeout}s)\n"
                    f"{tail(out, 60 if label == 'hidden' else 30)}"
                    f"\n(full log: {p['state'] / (label + '.log')})")
            fails.append(text)
            failure.write_text(text)
        elif rc == 0:
            results[label] = "pass"
            if attempt:
                results[f"{label}_retried"] = attempt
        else:
            results[label] = "fail"
            # TAP runners (node --test, prove, ...): list the failing test names first; TODO/SKIP lines are not failures.
            failing = [l for l in out.splitlines() if l.startswith("not ok") and "# TODO" not in l and "# SKIP" not in l]
            head = ("failing tests:\n" + "\n".join(failing[:20]) + "\n") if failing else ""
            text = (f"--- {label} ({cmd}) exit {rc}\n{head}{tail(out, 60 if label == 'hidden' else 30)}"
                    f"\n(full log: {p['state'] / (label + '.log')})")
            fails.append(text)
            failure.write_text(text)
    ok = not out_of_scope and not touched_protected and not fails
    results["gate"] = "PASS" if ok else "FAIL"
    if gate_reaped:  # pid + command line of every process the gate stopped, for the audit trail
        results["reaped_procs"] = gate_reaped
    gate_json = {"gate": results["gate"], "fingerprint": tree_fingerprint(wt, base), "env_dropped": env_dropped}
    if no_tests:  # the result JSON records that the gate ran without any test command
        gate_json["no_tests"] = True
    (p["state"] / "last_gate.json").write_text(json.dumps(gate_json))
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


def current_diff(wt, base):
    sh(["git", "add", "-N", "."], cwd=wt, check=False)  # include new files in diff without staging content
    return sh(["git", "diff", base], cwd=wt).stdout


def diff_sha(diff):
    import hashlib
    return hashlib.sha256(diff.encode()).hexdigest()


def parse_review_verdict(text):
    """(verdict, findings) from the reviewer's output. ONAY only when the whole output is the single line ONAY
    (the reviewer template's contract); everything else, including ONAY followed by findings, is RED."""
    lines = [l.strip().strip("*`#> ").strip() for l in text.splitlines() if l.strip()]
    if len(lines) == 1 and lines[0].rstrip(".!").upper() == "ONAY":
        return "ONAY", []
    return "RED", [l for l in lines if l.rstrip(".!").upper() not in ("RED", "ONAY")]


def cmd_review(a):
    """Record the blind reviewer's verdict next to the sha256 of the diff it reviewed (review.diff, from `hx diff`).
    `hx commit` accepts only an ONAY whose diff hash still equals the current tree's diff."""
    p = task_paths(a.task)
    dp = p["state"] / "review.diff"
    if not dp.exists():
        sys.exit("hx: no review.diff; run hx diff first")
    src = Path(a.output)
    if not src.exists():
        sys.exit(f"hx: reviewer output not found: {src}")
    text = src.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        sys.exit("hx: reviewer output is empty")
    verdict, findings = parse_review_verdict(text)
    try:
        dmeta = json.loads((p["state"] / "review.diff.json").read_text())
    except (OSError, ValueError):
        dmeta = {}
    rec = {"verdict": verdict, "findings": len(findings), "diff_sha256": diff_sha(dp.read_text()),
           "base": dmeta.get("base"), "all": dmeta.get("all"),
           "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (p["state"] / "review.json").write_text(json.dumps(rec))
    metric({"task": a.task, "event": "review", "verdict": verdict, "findings": len(findings)})
    print(f"[hx] review recorded: {verdict}" + (f" ({len(findings)} findings)" if findings else ""))
    sys.exit(0 if verdict == "ONAY" else 1)


def cmd_diff(a):
    p = task_paths(a.task)
    wt = p["worktree"]
    base = (json.loads(p["meta"].read_text()).get("task_base") or p["base"]) if a.all else p["base"]
    diff = current_diff(wt, base)
    stat = sh(["git", "diff", "--stat", base], cwd=wt).stdout
    out = p["state"] / "review.diff"
    out.write_text(diff)
    (p["state"] / "review.diff.json").write_text(json.dumps({"base": base, "all": bool(a.all)}))
    print(f"{out}\n{stat.strip()}\nlines={len(diff.splitlines())}")


def cmd_commit(a):
    """Commit one approved phase inside the worktree. Refuses unless the last gate passed on exactly this tree and the
    blind review said ONAY. The next phase is gated and diffed against this commit."""
    p = task_paths(a.task)
    wt, base = p["worktree"], p["base"]
    if a.review not in (None, "ONAY"):
        sys.exit("hx: commit needs --review ONAY (blind review approval)")
    gp = p["state"] / "last_gate.json"
    g = json.loads(gp.read_text()) if gp.exists() else {}
    if g.get("gate") != "PASS":
        sys.exit("hx: last gate did not pass; run hx gate first")
    if g.get("fingerprint") != tree_fingerprint(wt, base):
        sys.exit("hx: worktree changed after the last gate; run hx gate again")
    rp = p["state"] / "review.json"
    if not rp.exists():
        sys.exit("hx: no recorded review; run hx diff, review blind, then hx review <task> <reviewer_output.md>")
    rv = json.loads(rp.read_text())
    if rv.get("verdict") != "ONAY":
        sys.exit("hx: recorded review is not ONAY")
    if rv.get("diff_sha256") != diff_sha(current_diff(wt, base)):
        if rv.get("base") and rv.get("base") != base:
            sys.exit(f"hx: recorded review covers the diff from {str(rv['base'])[:9]}"
                     f"{' (hx diff --all?)' if rv.get('all') else ''}, but this commit's diff starts at {str(base)[:9]}; "
                     "run hx diff (without --all) and review that diff again")
        sys.exit("hx: recorded review belongs to an older diff; run hx diff and review again")
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
    rp.unlink(missing_ok=True)
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
            t.setdefault("triage", [0, 0, 0])
            t["triage"][0] += r.get("code_errors", 0); t["triage"][1] += r.get("test_errors", 0)
            t["triage"][2] += r.get("unclear", 0)
        elif r["event"] == "note":
            t["notes"].update({k: v for k, v in r.items() if k not in ("task", "event", "ts")})
    print(f"{'task':20} {'calls':32} {'gates':>5} {'fail':>4} {'go$':>7}  notes")
    for name, t in tasks.items():
        calls = " ".join(f"{k}:{v}" for k, v in t["calls"].items())
        tri = f" triage(code/test/unclear)={t['triage'][0]}/{t['triage'][1]}/{t['triage'][2]}" if "triage" in t else ""
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
    s.add_argument("--force-retry", action="store_true", help="call even when the phase's retry budget is used up (recorded as forced)")
    s.set_defaults(fn=cmd_call)
    s = sp.add_parser("gate"); s.add_argument("task"); s.add_argument("--test"); s.add_argument("--hidden-cmd")
    s.add_argument("--allow"); s.add_argument("--protect")
    s.add_argument("--no-tests", action="store_true", help="gate without running any test command (recorded as no_tests in the result)")
    s.add_argument("--retry", type=int, default=CFG.get("gate_retry", 1), help="re-run the visible test command this many times on failure")
    s.add_argument("--gate-timeout", type=int, default=CFG.get("gate_timeout_s", 1800)); s.set_defaults(fn=cmd_gate)
    s = sp.add_parser("diff"); s.add_argument("task"); s.add_argument("--all", action="store_true", help="whole task, all phases"); s.set_defaults(fn=cmd_diff)
    s = sp.add_parser("review"); s.add_argument("task"); s.add_argument("output", help="file holding the reviewer's output"); s.set_defaults(fn=cmd_review)
    s = sp.add_parser("commit"); s.add_argument("task"); s.add_argument("-m", required=True)
    s.add_argument("--review", help="legacy and optional; the commit is gated on the review.json that `hx review` writes")
    s.add_argument("--phase"); s.add_argument("--next", help="what the next phase is (goes into handoff.md)"); s.set_defaults(fn=cmd_commit)
    s = sp.add_parser("note"); s.add_argument("task"); s.add_argument("kv", nargs="+"); s.set_defaults(fn=cmd_note)
    s = sp.add_parser("report"); s.set_defaults(fn=cmd_report)
    s = sp.add_parser("prices"); s.add_argument("--refresh", action="store_true"); s.set_defaults(fn=cmd_prices)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
