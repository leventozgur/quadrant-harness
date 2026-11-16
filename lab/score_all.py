"""Score base + hard tiers for one or more labels and print a comparison.
Usage: python3 -I score_all.py ds-go glmf-go mmf-go
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build as B  # noqa: E402
import hard as H  # noqa: E402
import score as S  # noqa: E402
import run_oc as R  # noqa: E402

# Go prices per 1M tokens (input, output) as listed 2026-11-15; DeepSeek uses peak price (upper bound).
PRICE = {"deepseek-v4.1-flash": (0.30, 1.20), "glm-5.3-flash": (0.15, 0.50), "minimax-m3.1-flash": (0.15, 0.60)}


def score_label(label):
    rows = []
    for run_id, tier, test_id, effort in R.runs(2):
        d = B.RUN_ROOT / label / run_id
        meta = json.loads((d / "_meta.json").read_text()) if (d / "_meta.json").exists() else {}
        if not (d / "_answer.txt").exists():
            rows.append({"run": run_id, "tier": tier, "ok": False, "score": 0, "detail": "NOT RUN", **meta}); continue
        try:
            if tier == "base":
                ok, detail = S.CHECK["t" + test_id[1:]]((d / "_answer.txt").read_text(), d)
                sc = None if ok is None else float(bool(ok))
            else:
                sc, ok, detail = H.CHECK[test_id](d)
        except Exception as e:
            sc, ok, detail = 0.0, False, f"checker error {type(e).__name__}: {e}"
        rows.append({"run": run_id, "tier": tier, "effort": effort, "ok": ok, "score": sc, "detail": detail, **meta})
    Path(__file__).with_name(f"results_{label}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def cost(label, rows):
    """Go cost via hx.est_cost (separate cache-read rate, config.prices). Older labs priced cache reads as input."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import hx
    model = next((r.get("model", "") for r in rows if r.get("model")), "")
    key = next((k for k in hx.CFG["prices"] if k.split("/")[-1] in model), None)
    if not key:
        return None
    tok = {"input": sum(r.get("input_tokens") or 0 for r in rows), "cache_read": sum(r.get("cache_read") or 0 for r in rows),
           "output": sum(r.get("output_tokens") or 0 for r in rows), "reasoning": sum(r.get("reasoning_tokens") or 0 for r in rows)}
    return hx.est_cost(key, tok, tiers=False), tok["input"] + tok["cache_read"], tok["output"] + tok["reasoning"]


if __name__ == "__main__":
    for label in sys.argv[1:]:
        rows = score_label(label)
        base = [r for r in rows if r["tier"] == "base" and r["score"] is not None]
        hard = [r for r in rows if r["tier"] == "hard"]
        print(f"\n== {label}")
        print(f"base pass {sum(r['ok'] is True for r in base)}/{len(base)}")
        print(f"hard full-pass {sum(r['ok'] is True for r in hard)}/{len(hard)}  mean score {sum(r['score'] for r in hard)/max(1,len(hard)):.3f}")
        print(f"seconds base {sum(r.get('seconds') or 0 for r in base):.0f}  hard {sum(r.get('seconds') or 0 for r in hard):.0f}")
        print("cost (upper bound $, in_tok, out_tok):", cost(label, rows))
        for r in rows:
            if r["tier"] == "hard" or r["ok"] is not True:
                mark = {True: "PASS", False: "FAIL", None: "INFO"}[r["ok"]]
                print(f"  {r['run']:10} {mark} score={r['score'] if r['score'] is None else round(r['score'],2)} "
                      f"{r.get('seconds','?')}s steps={r.get('steps','?')}  {str(r['detail'])[:140]}")
