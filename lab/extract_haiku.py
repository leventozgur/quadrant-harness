"""Pull final answer + usage for each Haiku subagent run from its transcript JSONL."""
import json, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import build as B
TASKS = Path("/private/tmp/claude-501/-Users-leventozgur-Library-Application-Support-Claude-scratch-workspaces-cfeb6691-a261-43a7-9488-3e61b44377eb-e054b7f3-568b-49b7-8e9d-6be84230842a-scratch-2026-11-15-f2fc3e/e40996d0-05c9-4d3b-8348-8c83be878dfc/tasks")
MAP = {"t01":"adfffde45f648598d","t02":"aa842ad5cf411e4c9","t03":"ada42730c6180c04c","t04":"aa96154479bf9d80e",
 "t05":"a754495e127491a22","t06":"a2ff3aa4ffdfd649b","t06b":"abc295c2e966f80d1","t07":"ac09e53217468fe9e",
 "t08":"aecba657ff00fe1df","t09":"a2ee4340b6fcf769c","t10":"a6c8dcdd9e22474e5","t11_low1":"aabb5b077bd5a91a2",
 "t11_low2":"a0b5e57999ed9ab1b","t11_high1":"a0c2fc1e930eb6475","t11_high2":"ab36b17de4177b919",
 "t11_high3":"a32e4c134830ce1f9","t11_max1":"acd4c556d96c8f2d5","t11_max2":"ab9877012debf6718","t12":"a97a29019436b797f"}
def ts(x):
    return datetime.fromisoformat(x.replace("Z","+00:00")).timestamp()
for run, aid in MAP.items():
    f = TASKS / f"{aid}.output"
    if not f.exists():
        print(run, "missing"); continue
    lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip().startswith("{")]
    out_tok = 0; tools = 0; times = []; last_text = None; models=set()
    seen = set()
    for e in lines:
        if "timestamp" in e: times.append(ts(e["timestamp"]))
        if e.get("type") != "assistant": continue
        m = e.get("message", {})
        models.add(m.get("model"))
        mid = m.get("id")
        if mid not in seen and m.get("usage"):
            seen.add(mid); out_tok += m["usage"].get("output_tokens", 0)
        texts = [c.get("text","") for c in m.get("content", []) if c.get("type") == "text"]
        tools += sum(1 for c in m.get("content", []) if c.get("type") == "tool_use")
        if texts and any(t.strip() for t in texts): last_text = "".join(texts)
    d = B.RUN_ROOT / "haiku" / run
    (d / "_answer.txt").write_text(last_text or "")
    meta = {"seconds": round(times[-1]-times[0],1) if len(times)>1 else None, "output_tokens": out_tok,
            "tool_calls": tools, "models": sorted(x for x in models if x)}
    (d / "_meta.json").write_text(json.dumps(meta))
    print(run, meta)
