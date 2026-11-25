"""HX-47: produced-code size per lab run (worker minimal-diff experiment).
Usage: python3 -I loc.py <label> [<label> ...]   (labels under LAB_RUN_ROOT, as written by run_oc.py)

Produced LOC of one run = non-blank lines the worker added or changed in the fixture (difflib against a freshly
built fixture) + non-blank lines inside fenced code blocks of its final answer. Files the runner writes
(_answer.txt, _meta.json, _raw.jsonl, _stderr.txt) and caches/binaries are ignored.
Code tasks (pre-registered): every base and hard run except the text-only tasks t01, t02, t08, t10, t12.
"""
import difflib, json, re, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build as B  # noqa: E402
import hard as H  # noqa: E402
import run_oc as R  # noqa: E402

TEXT_ONLY = {"t01", "t02", "t08", "t10", "t12"}
SKIP_DIRS = {"__pycache__", ".git", ".opencode", "node_modules", ".pytest_cache", ".venv"}
SKIP_SUFFIX = {".pyc", ".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".gif", ".zip"}
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def files(root: Path):
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or rel.name.startswith("_") and len(rel.parts) == 1:
            continue
        if any(part in SKIP_DIRS for part in rel.parts) or p.suffix.lower() in SKIP_SUFFIX:
            continue
        try:
            out[str(rel)] = p.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
    return out


def added(old, new):
    n = 0
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            n += sum(1 for line in new[j1:j2] if line.strip())
    return n


def fresh(tier, test_id):
    d = Path(tempfile.mkdtemp(prefix="hx47-fix-"))
    if tier == "base":
        B.build_fixture(test_id, d)
    else:
        H.FIX[test_id](d)
    return d


def measure(run_dir: Path, tier, test_id):
    base, now = files(fresh(tier, test_id)), files(run_dir)
    file_loc = sum(added(base.get(k, []), v) for k, v in now.items())
    new_files = sorted(k for k in now if k not in base)
    ans = (run_dir / "_answer.txt").read_text() if (run_dir / "_answer.txt").exists() else ""
    fence_loc = sum(1 for block in FENCE.findall(ans) for line in block.splitlines() if line.strip())
    return {"file_loc": file_loc, "fence_loc": fence_loc, "loc": file_loc + fence_loc, "new_files": new_files}


def main(labels):
    report = {}
    for label in labels:
        rows = {}
        for run_id, tier, test_id, _e in R.runs(1):
            if tier == "base" and test_id in TEXT_ONLY:
                continue
            d = B.RUN_ROOT / label / run_id
            if not (d / "_answer.txt").exists():
                rows[run_id] = None
                continue
            rows[run_id] = measure(d, tier, test_id)
        total = sum(r["loc"] for r in rows.values() if r)
        missing = [k for k, v in rows.items() if v is None]
        report[label] = {"total_loc": total, "missing": missing, "runs": rows}
        print(f"{label}: total_loc={total} runs={len(rows) - len(missing)} missing={missing}")
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
