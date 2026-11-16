"""Run all 19 lab runs on opencode/deepseek-v4.1-flash-free, sequentially, with free-tier retry.
Usage: python3 -I run_ds.py [run_id ...]
"""
import json, os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build as B  # noqa: E402

MODEL = "opencode/deepseek-v4.1-flash-free"
SUFFIX = {None: "", "high": "", "low": "#low", "max": "#max"}


def run_one(run_id, test_id, effort):
    d = B.build("deepseek", run_id)
    env = dict(os.environ, PWD=str(d))
    for attempt in range(6):
        t0 = time.time()
        p = subprocess.run(["opencode", "run", "-m", MODEL + SUFFIX[effort], "--format", "json", B.P[test_id]],
                           cwd=d, env=env, capture_output=True, text=True, timeout=900)
        raw = p.stdout
        if "usage limit" in (raw + p.stderr).lower() or (p.returncode != 0 and not raw.strip()):
            print(f"  {run_id}: limit/err (rc={p.returncode}), waiting 75 s", flush=True)
            time.sleep(75)
            B.build("deepseek", run_id)  # reset workdir
            continue
        break
    (d / "_raw.jsonl").write_text(raw)
    (d / "_stderr.txt").write_text(p.stderr)
    events = [json.loads(l) for l in raw.splitlines() if l.strip().startswith("{")]
    texts, out_tok, reason_tok, steps, tools = [], 0, 0, 0, 0
    for e in events:
        part = e.get("part", {})
        if e["type"] == "text":
            texts.append((part.get("messageID"), part.get("text", "")))
        elif e["type"] == "step_finish":
            steps += 1
            tk = part.get("tokens", {})
            out_tok += tk.get("output", 0); reason_tok += tk.get("reasoning", 0)
        elif e["type"] in ("tool_use", "tool"):
            tools += 1
    last_msg = texts[-1][0] if texts else None
    answer = "".join(t for m, t in texts if m == last_msg)
    (d / "_answer.txt").write_text(answer)
    ts = [e["timestamp"] for e in events if "timestamp" in e]
    meta = {"seconds": round((ts[-1] - ts[0]) / 1000, 1) if len(ts) > 1 else None,
            "output_tokens": out_tok, "reasoning_tokens": reason_tok, "steps": steps, "tool_calls": tools,
            "wall_seconds": round(time.time() - t0, 1)}
    (d / "_meta.json").write_text(json.dumps(meta))
    print(f"{run_id}: {meta}", flush=True)


if __name__ == "__main__":
    want = set(sys.argv[1:])
    for r, t, e in B.RUNS:
        if not want or r in want:
            run_one(r, t, e)
            time.sleep(5)
    print("DONE")
