"""Run base (19) + hard (7 x reps) lab runs on one opencode model, sequentially.
Usage: python3 -I run_oc.py <label> <model> [hard_reps=2] [only=run1,run2]
Writes <RUN_ROOT>/<label>/<run>/{_answer.txt,_meta.json,_raw.jsonl}.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build as B  # noqa: E402
import hard as H  # noqa: E402

SUFFIX = {None: "", "high": "", "low": "#low", "max": "#max"}


def runs(hard_reps):
    out = [(r, "base", t, e) for r, t, e in B.RUNS]
    out += [(f"{t}_r{k}", "hard", t, None) for t in H.HARD for k in range(1, hard_reps + 1)]
    return out


TEMPLATE = Path(os.environ["WORKER_TEMPLATE"]).read_text() if os.environ.get("WORKER_TEMPLATE") else None
EFFORT_OVERRIDE = os.environ.get("EFFORT")  # e.g. "#low" applied to runs without their own effort


def wrap(prompt, d):
    if not TEMPLATE:
        return prompt
    return TEMPLATE.replace("{SPEC}", prompt).replace("{WORKTREE}", str(d)).replace("{FEEDBACK}", "Yok.").replace("{HIDDEN}", "")


def prepare(label, run_id, tier, test_id):
    d = B.RUN_ROOT / label / run_id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    if tier == "base":
        B.build_fixture(test_id, d)
        return d, wrap(B.P[test_id], d)
    H.FIX[test_id](d)
    return d, wrap(H.P[test_id], d)


def parse(raw):
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    texts, out_tok, reason_tok, in_tok, cache_read, steps, tools, errors = [], 0, 0, 0, 0, 0, 0, 0
    for e in events:
        part = e.get("part", {}) if isinstance(e, dict) else {}
        typ = e.get("type")
        if typ == "text":
            texts.append((part.get("messageID"), part.get("text", "")))
        elif typ == "step_finish":
            steps += 1
            tk = part.get("tokens", {})
            out_tok += tk.get("output", 0); reason_tok += tk.get("reasoning", 0); in_tok += tk.get("input", 0)
            cache_read += tk.get("cache", {}).get("read", 0)
        elif typ in ("tool_use", "tool"):
            tools += 1
        elif typ == "error":
            errors += 1
    last = texts[-1][0] if texts else None
    answer = "".join(t for m, t in texts if m == last)
    ts = [e["timestamp"] for e in events if isinstance(e, dict) and "timestamp" in e]
    meta = {"seconds": round((ts[-1] - ts[0]) / 1000, 1) if len(ts) > 1 else None, "output_tokens": out_tok,
            "reasoning_tokens": reason_tok, "input_tokens": in_tok, "cache_read": cache_read, "steps": steps,
            "tool_calls": tools, "errors": errors}
    return answer, meta


def run_one(label, model, run_id, tier, test_id, effort):
    for attempt in range(6):
        d, prompt = prepare(label, run_id, tier, test_id)
        env = dict(os.environ, PWD=str(d))
        t0 = time.time()
        try:
            suffix = SUFFIX[effort] if effort is not None or not EFFORT_OVERRIDE else EFFORT_OVERRIDE
            p = subprocess.run(["opencode", "run", "-m", model + suffix, "--format", "json", *os.environ.get("LAB_OC_EXTRA", "").split(), prompt],
                               cwd=d, env=env, capture_output=True, text=True, timeout=1200)
            raw, err = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            raw, err = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "TIMEOUT"
        low = (raw + err).lower()
        if ("usage limit" in low or "rate limit" in low or "429" in err) and attempt < 5:
            print(f"  {run_id}: limit, waiting 90 s", flush=True)
            time.sleep(90)
            continue
        break
    (d / "_raw.jsonl").write_text(raw)
    (d / "_stderr.txt").write_text(err[-5000:])
    answer, meta = parse(raw)
    meta["wall_seconds"] = round(time.time() - t0, 1)
    meta["model"] = model + (SUFFIX[effort] if effort is not None or not EFFORT_OVERRIDE else EFFORT_OVERRIDE)
    meta["template"] = os.environ.get("WORKER_TEMPLATE", "raw")
    meta["timeout"] = err == "TIMEOUT"
    (d / "_answer.txt").write_text(answer)
    (d / "_meta.json").write_text(json.dumps(meta))
    print(f"{run_id}: {meta}", flush=True)


if __name__ == "__main__":
    label, model = sys.argv[1], sys.argv[2]
    reps = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    only = set(sys.argv[4].split(",")) if len(sys.argv) > 4 else None
    for r, tier, t, e in runs(reps):
        if only and r not in only:
            continue
        run_one(label, model, r, tier, t, e)
        time.sleep(3)
    print("DONE", flush=True)
