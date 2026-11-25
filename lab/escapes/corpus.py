"""Escapes corpus tool (HX-46).

Takes real, already-accepted hx jobs (one commit each), injects exactly ONE defect
of a fixed class with a model, validates it, runs the visible/hidden tests, splits
the valid cases into tuning/holdout and packages blind reviewer inputs. Reviewer
outputs are then scored against the mutation's answer key.

Subcommands (all end with a single summary line):
  build <manifest> <out>
  mutate <out> [--model M] [--ids a,b]
  check <out>
  split <out> [--seed 46]
  review-pack <out>
  score <out> <label> [--grader M]
  clean <out>
"""
import argparse
import hashlib
import json
import math
import os
import random
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent  # lab/escapes
LAB = HERE.parent  # lab/ -- run_oc.py lives here (SPEC: answers come from run_oc.parse)
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from run_oc import parse  # noqa: E402

CLASSES = ("EDGE", "SWALLOW", "REGRESS", "SCOPE", "SECURITY", "BOUNDARY", "ORDER")
CLASS_DESC = {
    "EDGE": "spec'te yazan bir sınır/özel durumu (boş girdi, eksik alan, BOM/CRLF, büyük-küçük harf) yanlış ele al.",
    "SWALLOW": "bir hatayı sessizce yut ya da hata yerine yanlış başarı dön.",
    "REGRESS": "değişiklikten önce var olan bir davranışı veya varsayılan yolu bozacak şekilde değiştir.",
    "SCOPE": "spec'in istemediği, aynı dosyalardaki başka bir davranışı değiştir.",
    "SECURITY": "kodun yaptığı bir doğrulamayı/korumayı (yol, izin, girdi kontrolü) atla veya zayıflat.",
    "BOUNDARY": "bir eşitlik/eşik/aralık karşılaştırmasını bir birim kaydır (<= yerine <, +1/-1).",
    "ORDER": "iki adımın sırasını değiştirerek bir kuralı ihlal et.",
}
MUTATE_MODEL = "opencode-go/glm-5.3-flash#max"
GRADER_MODEL = "opencode-go/qwen3.7-plus#high"
OPENCODE = os.environ.get("ESCAPES_OPENCODE", "opencode")
SANDBOX_EXEC = "sandbox-exec"
DEFECT_PROMPT = HERE / "defect_prompt.md"
GRADE_PROMPT = HERE / "grade_prompt.md"
TIMEOUT = 900
ATTEMPTS = 2
LOG_LINES = 60


# --- small helpers -----------------------------------------------------------
def class_for(index):
    """Defect class assigned to the index-th id-sorted manifest entry."""
    return CLASSES[index % len(CLASSES)]


def rate(numerator, denominator):
    return None if not denominator else round(numerator / denominator, 3)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def fill(template, mapping):
    """Replace {PLACEHOLDER} keys in one pass (inserted text is never re-expanded)."""
    out, i = [], 0
    while True:
        start = template.find("{", i)
        if start < 0:
            out.append(template[i:])
            return "".join(out)
        end = template.find("}", start)
        if end < 0:
            out.append(template[i:])
            return "".join(out)
        key = template[start:end + 1]
        if key not in mapping:
            # Unknown placeholder or an unmatched "{" (e.g. a JSON example inside the
            # template): keep the text and resume right after this "{", so a later
            # real placeholder is still filled.
            out.append(template[i:start + 1])
            i = start + 1
            continue
        out.append(template[i:start])
        out.append(mapping[key])
        i = end + 1


def abspath(value, base):
    """Absolute path for a manifest value; relative paths are tried against base first."""
    path = Path(os.path.expanduser(str(value)))
    if path.is_absolute():
        return os.path.abspath(str(path))
    candidate = Path(base) / path
    return os.path.abspath(str(candidate if candidate.exists() else Path.cwd() / path))


def item_of(case_id, variant):
    return f"{case_id}__{variant}"


def is_test_path(path):
    """True when any path component has a test shape (tests/, test_, _test., .test., __tests__)."""
    for part in str(path).replace("\\", "/").split("/"):
        if part in ("tests", "__tests__"):
            return True
        if part.startswith("test_") or "_test." in part or ".test." in part:
            return True
    return False


def last_json_object(text):
    """Last decodable {...} JSON object in text (None when there is none)."""
    decoder, found, i = json.JSONDecoder(), None, 0
    while True:
        start = text.find("{", i)
        if start < 0:
            return found
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            i = start + 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = start + max(end, 1)


def read_verdict(text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return "ONAY" if stripped == "ONAY" else "RED"
    return "RED"


def grader_verdict(text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return "EVET" if stripped.startswith("EVET") else "HAYIR"
    return "HAYIR"


_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(text, index):
    """One diff-header token as bytes: a C-quoted path or everything up to the next space."""
    if text[index] != '"':
        end = text.find(" ", index)
        end = len(text) if end < 0 else end
        return text[index:end].encode("utf-8"), end
    buf, index = bytearray(), index + 1
    while index < len(text) and text[index] != '"':
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            follow = text[index + 1]
            if follow in _C_ESCAPES:
                buf.append(_C_ESCAPES[follow])
                index += 2
                continue
            if follow in "01234567":
                end = index + 2
                while end < len(text) and end < index + 4 and text[end] in "01234567":
                    end += 1
                buf.append(int(text[index + 1:end], 8))
                index = end
                continue
        buf.extend(char.encode("utf-8"))
        index += 1
    return bytes(buf), index + 1


def diff_files(text):
    """Paths from the `diff --git` headers; paths with spaces or C-quoted bytes survive."""
    files = []
    for line in text.splitlines():
        if not line.startswith("diff --git "):
            continue
        rest = line[len("diff --git "):]
        half = (len(rest) - 1) // 2
        # Plain unchanged path: "a/<path> b/<path>" is symmetric, so split it in half.
        if (len(rest) % 2 and rest.startswith("a/") and rest[half] == " "
                and rest[half + 1:half + 3] == "b/" and rest[2:half] == rest[half + 3:]):
            name = rest[2:half]
        else:
            first, index = _unquote(rest, 0)
            while index < len(rest) and rest[index] == " ":
                index += 1
            second = _unquote(rest, index)[0] if index < len(rest) else b""
            name = (second or first).decode("utf-8", "replace")
            prefix = "b/" if second else "a/"
            if name.startswith(prefix):
                name = name[2:]
        if name not in files:
            files.append(name)
    return files


# --- paths / git -------------------------------------------------------------
def case_path(out, case_id):
    return Path(out) / "cases" / f"{case_id}.json"


def wt_path(out, item):
    return Path(out) / "wt" / item


def diff_path(out, item):
    return Path(out) / "diffs" / f"{item}.diff"


def gate_path(out, item):
    return Path(out) / "gates" / f"{item}.txt"


def review_dir(out, label):
    return Path(out) / "reviews" / label


def all_cases(out):
    directory = Path(out) / "cases"
    if not directory.is_dir():
        return []
    return [read_json(path) for path in sorted(directory.glob("*.json"))]


def save_case(out, case):
    write_json(case_path(out, case["id"]), case)


def select_cases(out, ids, statuses):
    selected = [case for case in all_cases(out) if case.get("status") in statuses]
    if ids:
        selected = [case for case in selected if case["id"] in ids]
    return sorted(selected, key=lambda case: case["id"])


def repo_statuses(root):
    """`git status --porcelain` for every unique repo named by the cases."""
    status = {}
    for case in all_cases(root):
        repo = case.get("repo")
        if repo and repo not in status:
            status[repo] = git_out(repo, "status", "--porcelain")
    return status


def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise SystemExit(f"corpus: git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def git_out(repo, *args):
    return git(repo, *args).stdout


def add_worktree(repo, path, commit):
    path = Path(path)
    if path.exists():
        git(repo, "worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
        git(repo, "worktree", "prune", check=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(path), commit)


def reset_worktree(wt, commit):
    """Return the worktree to `commit`: drop model commits, edits and gitignored files."""
    git(wt, "reset", "-q", "--hard", commit, check=False)
    git(wt, "clean", "-fdx", check=False)


# --- model calls -------------------------------------------------------------
def opencode_bin():
    return os.environ.get("ESCAPES_OPENCODE", OPENCODE)


def _kill_group(proc):
    """Kill the whole process group (the child runs in its own session and may have children)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def _run(command, cwd, shell=False, env=None):
    """Run a command in its own session (900 s timeout).

    Returns (stdout, stderr, returncode, error or None); returncode is None on a
    timeout or exec failure. On a timeout the whole process group is killed so no
    orphan process keeps running or writing to the worktree.
    """
    try:
        proc = subprocess.Popen(command, cwd=str(cwd), shell=shell, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", env=env, start_new_session=True)
    except OSError as exc:
        return "", "", None, f"exec: {exc}"
    try:
        out, err = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        out, err = proc.communicate()
        return out or "", err or "", None, "timeout"
    return out or "", err or "", proc.returncode, None


def require_sandbox():
    """The write sandbox is mandatory on macOS; a missing sandbox-exec fails closed."""
    if not shutil.which(SANDBOX_EXEC):
        raise SystemExit(f"corpus: {SANDBOX_EXEC} yok; yazma sandbox'ı olmadan model çalıştırılmaz")


def sandbox_profile(out, case_id, cwd):
    """Per-case profile: writes only to the defect worktree, temp dirs and opencode's dirs."""
    roots = (cwd, tempfile.gettempdir(), "/private/var/folders", "/dev",
             "~/.local/share/opencode", "~/.cache", "~/.config/opencode")
    subpaths = "".join(f' (subpath "{os.path.realpath(os.path.expanduser(str(root)))}")' for root in roots)
    path = Path(out) / "sandbox" / f"{case_id}.sb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"(version 1)(allow default)(deny file-write* (require-not (require-any{subpaths})))\n",
                    encoding="utf-8")
    return path


def run_model(prompt, cwd, model, profile=None):
    """Run opencode once (standalone, PWD = cwd, sandboxed when a profile is given)."""
    command = [opencode_bin(), "run", "--standalone", "-m", model, "--format", "json", prompt]
    if profile is not None:
        command = [SANDBOX_EXEC, "-f", str(profile), *command]
    out, _, _, error = _run(command, cwd, env=dict(os.environ, PWD=str(cwd)))
    return out, error


def parse_answer(raw):
    """Answer text via lab/run_oc.py's parse(); returns (text, error) and keeps the reason."""
    try:
        return parse(raw)[0], None
    except Exception as exc:  # noqa: BLE001 - the reason is reported as mutate_error
        return "", f"no_json: {exc}"


def answer_object(answer):
    obj = last_json_object(answer)
    if not isinstance(obj, dict):
        return None, "no_json"
    key = obj.get("answer_key")
    if not isinstance(key, str) or not key.strip():
        return None, "answer_key"
    if "file" not in obj:
        return None, "file"
    return obj, None


def spec_path(case):
    return abspath(case["spec"], case["repo"])


def hidden_path(case):
    return abspath(case["hidden_dir"], case["repo"])


def subst(command, wt, hidden):
    return str(command or "").replace("{wt}", shlex.quote(str(wt))).replace("{hidden}", shlex.quote(str(hidden)))


# --- build -------------------------------------------------------------------
def cmd_build(manifest, out):
    manifest = Path(os.path.abspath(str(manifest)))
    entries = read_json(manifest)
    if not isinstance(entries, list):
        raise SystemExit("corpus: manifest must be a JSON list")
    root = Path(os.path.abspath(str(out)))
    for name in ("wt", "diffs", "cases"):
        (root / name).mkdir(parents=True, exist_ok=True)
    built = skipped = 0
    for index, entry in enumerate(sorted(entries, key=lambda item: item["id"])):
        case_id = entry["id"]
        if case_path(root, case_id).exists():
            skipped += 1
            continue
        repo = abspath(entry["repo"], manifest.parent)
        commit = entry["commit"]
        base = git_out(repo, "rev-parse", f"{commit}^").strip()
        ref_files = sorted(name for name in git_out(repo, "diff", "--name-only", base, commit).splitlines() if name)
        for variant in ("clean", "defect"):
            add_worktree(repo, wt_path(root, item_of(case_id, variant)), commit)
        diff_path(root, item_of(case_id, "clean")).write_text(git_out(repo, "diff", base, commit), encoding="utf-8")
        case = dict(entry)
        case["repo"] = repo
        case["spec"] = abspath(entry["spec"], manifest.parent)
        case["hidden_dir"] = abspath(entry["hidden_dir"], manifest.parent)
        case["base"] = base
        case["ref_files"] = ref_files
        case["class"] = class_for(index)
        case["status"] = "built"
        save_case(root, case)
        built += 1
    print(f"build: {built} built, {skipped} skipped -> {root}")


# --- mutate ------------------------------------------------------------------
def defect_prompt(out, case):
    diff = diff_path(out, item_of(case["id"], "clean")).read_text(encoding="utf-8")
    template = DEFECT_PROMPT.read_text(encoding="utf-8")
    return fill(template, {
        "{SPEC}": Path(spec_path(case)).read_text(encoding="utf-8"),
        "{DIFF}": diff,
        "{CLASS}": case["class"],
        "{CLASS_DESC}": CLASS_DESC[case["class"]],
        "{FILES}": "\n".join(case["ref_files"]),
    })


def _relpath(value):
    value = str(value).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value


def validate_defect(wt, commit, ref_files, answer_file=None):
    """Spec step (a)-file + (b)+(c); returns ({"lines": n}, error or None)."""
    head = git_out(wt, "rev-parse", "HEAD").strip()
    if head != git_out(wt, "rev-parse", commit).strip():
        return None, f"head_moved: {head}"
    names = [name for name in git_out(wt, "diff", "--name-only", commit).splitlines() if name.strip()]
    if not names:
        return None, "no_changes"
    outside = [name for name in names if name not in ref_files]
    if outside:
        return None, "out_of_scope: " + ", ".join(outside)
    tests = [name for name in names if is_test_path(name)]
    if tests:
        return None, "test_file: " + ", ".join(tests)
    changed = {_relpath(name) for name in names}
    if answer_file is not None and _relpath(answer_file) not in changed:
        return None, f"file: {answer_file} not changed"
    total = 0
    for line in git_out(wt, "diff", "--numstat", commit).splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            total += (int(fields[0]) if fields[0].isdigit() else 0)
            total += (int(fields[1]) if fields[1].isdigit() else 0)
    if not 1 <= total <= 30:
        return None, f"lines: {total}"
    return {"lines": total}, None


def cmd_mutate(out, model=MUTATE_MODEL, ids=None):
    root = Path(os.path.abspath(str(out)))
    if sys.platform == "darwin":
        require_sandbox()
    selected = select_cases(root, ids, ("built", "mutate_failed"))
    done = failed = 0
    for case in selected:
        case_id = case["id"]
        wt = wt_path(root, item_of(case_id, "defect"))
        if not wt.is_dir():
            case["status"] = "mutate_failed"
            case["mutate_error"] = "missing worktree"
            save_case(root, case)
            failed += 1
            continue
        obj = info = None
        error = None
        attempts = int(case.get("attempts") or 0)
        remaining = max(0, ATTEMPTS - attempts)
        if not remaining:
            case["status"] = "mutate_failed"
            case.setdefault("mutate_error", "attempts exhausted")
            save_case(root, case)
            failed += 1
            continue
        prompt = defect_prompt(root, case)
        profile = sandbox_profile(root, case_id, wt) if sys.platform == "darwin" else None
        for _ in range(remaining):
            attempts += 1
            case["attempts"] = attempts
            before = repo_statuses(root)
            raw, error = run_model(prompt, wt, model, profile)
            (root / "cases" / f"{case_id}.mutate{attempts}.jsonl").write_text(raw or "", encoding="utf-8")
            after = repo_statuses(root)
            stray = next((repo for repo in after if before.get(repo) != after[repo]), None)
            if stray:
                case["status"] = "mutate_failed"
                case["mutate_error"] = f"stray_write: {stray}"
                save_case(root, case)
                raise SystemExit(f"corpus: stray_write: {stray}")
            git(wt, "add", "-A", "-N", check=False)
            obj = info = None
            if error is None:
                answer, error = parse_answer(raw)
            if error is None:
                obj, error = answer_object(answer)
            if error is None:
                info, error = validate_defect(wt, case["commit"], case["ref_files"], obj.get("file"))
            if error is None:
                break
            reset_worktree(wt, case["commit"])
        if error is None and obj is not None and info is not None:
            diff_path(root, item_of(case_id, "defect")).write_text(git_out(wt, "diff", case["base"]), encoding="utf-8")
            case["answer_key"] = obj["answer_key"]
            case["defect_file"] = obj["file"]
            case["defect_lines"] = info["lines"]
            case["status"] = "mutated"
            case.pop("mutate_error", None)
            done += 1
        else:
            case["status"] = "mutate_failed"
            case["mutate_error"] = error or "unknown"
            failed += 1
        save_case(root, case)
    skipped = len(all_cases(root)) - len(selected)
    print(f"mutate: {done} mutated, {failed} failed, {skipped} skipped")


# --- check -------------------------------------------------------------------
def run_step(command, wt, hidden):
    command = subst(command, wt, hidden).strip()
    if not command:
        return "skipped", ""
    out, err, code, error = _run(command, wt, shell=True)
    if error == "timeout":
        return "timeout", out + err
    if error:
        return "fail", error
    return ("pass" if code == 0 else "fail"), out + err


def write_log(out, case, variant, step, text):
    lines = text.splitlines()[-LOG_LINES:]
    path = Path(out) / "cases" / f"{case['id']}.{variant}.{step}.log"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def cmd_check(out):
    root = Path(os.path.abspath(str(out)))
    valid = invalid = 0
    for case in select_cases(root, None, ("mutated",)):
        hidden = hidden_path(case)
        results = {}
        for variant in ("clean", "defect"):
            wt = wt_path(root, item_of(case["id"], variant))
            result = {"setup": "skipped", "tests": "skipped", "hidden": "skipped"}
            status, text = run_step(case.get("setup", ""), wt, hidden)
            result["setup"] = status
            write_log(root, case, variant, "setup", text)
            if status in ("pass", "skipped"):
                for step, key in (("tests", "test_cmd"), ("hidden", "hidden_cmd")):
                    status, text = run_step(case.get(key, ""), wt, hidden)
                    result[step] = status
                    write_log(root, case, variant, step, text)
            results[variant] = result
        case["clean"], case["defect"] = results["clean"], results["defect"]
        # An empty setup ("skipped") is not a reason; a skipped or broken setup/tests step is.
        reasons = [f"clean.{step}" for step in ("tests", "hidden") if results["clean"][step] != "pass"]
        if results["clean"]["setup"] not in ("pass", "skipped"):
            reasons.insert(0, "clean.setup")
        if results["clean"]["tests"] == "pass" and results["clean"]["hidden"] == "pass":
            case["status"] = "valid"
            case.pop("invalid_reason", None)
            valid += 1
        else:
            case["status"] = "invalid"
            case["invalid_reason"] = ",".join(reasons) or "clean.tests"
            invalid += 1
        save_case(root, case)
    print(f"check: {valid} valid, {invalid} invalid")


# --- split -------------------------------------------------------------------
def split_ids(ids, seed=46):
    ordered = sorted(ids)
    random.Random(seed).shuffle(ordered)
    cut = math.ceil(len(ordered) / 2)
    return sorted(ordered[:cut]), sorted(ordered[cut:])


def load_split(out):
    path = Path(out) / "split.json"
    if not path.exists():
        raise SystemExit(f"corpus: {path} yok (önce `split` çalıştır)")
    return read_json(path)


def split_of(split, case_id):
    return "holdout" if case_id in split.get("holdout", []) else "tuning"


def require_split(split, cases):
    known = set(split.get("tuning", [])) | set(split.get("holdout", []))
    missing = sorted(case["id"] for case in cases
                     if case.get("status") == "valid" and case["id"] not in known)
    if missing:
        raise SystemExit("corpus: split is missing valid cases: " + ", ".join(missing)
                         + " (split'i yeniden çalıştır)")


def cmd_split(out, seed=46):
    root = Path(os.path.abspath(str(out)))
    ids = [case["id"] for case in all_cases(root) if case.get("status") == "valid"]
    tuning, holdout = split_ids(ids, seed)
    write_json(root / "split.json", {"seed": seed, "tuning": tuning, "holdout": holdout})
    print(f"split: {len(tuning)} tuning, {len(holdout)} holdout (seed {seed})")


# --- review-pack -------------------------------------------------------------
def blind_name(item, extension):
    return f"{hashlib.sha1(item.encode('utf-8')).hexdigest()[:10]}.{extension}"


def cmd_review_pack(out):
    root = Path(os.path.abspath(str(out)))
    split = load_split(root)
    cases = all_cases(root)
    require_split(split, cases)
    blind = root / "blind"
    shutil.rmtree(blind, ignore_errors=True)
    blind.mkdir(parents=True, exist_ok=True)
    (root / "gates").mkdir(parents=True, exist_ok=True)
    entries = []
    for case in sorted(cases, key=lambda item: item["id"]):
        if case.get("status") != "valid":
            continue
        for variant in ("clean", "defect"):
            item = item_of(case["id"], variant)
            diff = diff_path(root, item).read_text(encoding="utf-8")
            result = case.get(variant) or {}
            gate = "PASS" if result.get("tests") == "pass" and result.get("hidden") == "pass" else "FAIL"
            payload = {"changed": diff_files(diff), "tests": result.get("tests"),
                       "hidden": result.get("hidden"), "gate": gate}
            write_json(gate_path(root, item), payload)
            blind_diff = blind / blind_name(item, "diff")
            blind_gate = blind / blind_name(item, "txt")
            blind_diff.write_text(diff, encoding="utf-8")
            write_json(blind_gate, payload)
            entries.append({"item": item, "case": case["id"], "variant": variant,
                            "split": split_of(split, case["id"]), "spec": spec_path(case),
                            "diff": str(blind_diff), "gate": str(blind_gate)})
    write_json(root / "review_inputs.json", entries)
    print(f"review-pack: {len(entries)} items -> {root}")


# --- score -------------------------------------------------------------------
def review_meta(out):
    path = Path(out) / "review_inputs.json"
    if not path.exists():
        return {}
    return {entry["item"]: entry for entry in read_json(path)
            if isinstance(entry, dict) and entry.get("item")}


def grade_item(out, label, case, item, review, model):
    cache = review_dir(out, label) / f"{item}.grade.json"
    if cache.exists():
        record = read_json(cache)
        if record.get("model") == model:
            return record
    template = GRADE_PROMPT.read_text(encoding="utf-8")
    defect_diff = diff_path(out, item).read_text(encoding="utf-8")
    answers, verdicts = [], []
    failed = False
    for _ in range(2):
        prompt = fill(template, {"{ANSWER_KEY}": str(case.get("answer_key", "")),
                                 "{REVIEW}": review, "{DIFF}": defect_diff})
        # An empty scratch directory per call: the grader must not read cases/, diffs/ or keys.
        with tempfile.TemporaryDirectory(prefix="corpus-grade-") as scratch:
            raw, error = run_model(prompt, scratch, model)
        answer, parse_error = ("", None) if error else parse_answer(raw)
        if error or parse_error or not str(answer).strip():
            failed = True
        answers.append(answer)
        verdicts.append(grader_verdict(answer))
    if failed:
        return {"answers": answers, "verdicts": verdicts,
                "caught": False, "unsure": False, "grader_error": True}
    record = {"answers": answers, "verdicts": verdicts, "model": model,
              "caught": all(verdict == "EVET" for verdict in verdicts),
              "unsure": len(set(verdicts)) > 1}
    write_json(cache, record)
    return record


def case_stats(items, name):
    defect = [item for item in items if item["variant"] == "defect"]
    clean = [item for item in items if item["variant"] == "clean"]
    scored = [item for item in defect if not item.get("grader_error")]
    grader_error = len(defect) - len(scored)
    caught = sum(1 for item in scored if item.get("caught"))
    false_red = sum(1 for item in clean if item.get("false_red"))
    unsure = sum(1 for item in scored if item.get("unsure"))
    # A defect whose setup broke never reached the tests: a "skipped" step there is not a
    # catch, and such an item must not dilute the tester-side rate.
    tested = [item for item in defect if (item.get("setup") or "skipped") in ("pass", "skipped")]
    setup_broken = len(defect) - len(tested)
    hidden_caught = sum(1 for item in tested if item.get("hidden") in ("fail", "timeout"))
    visible_caught = sum(1 for item in tested if item.get("tests") in ("fail", "timeout"))
    return {"split": name,
            "n_defect": len(defect), "caught": caught, "catch_rate": rate(caught, len(scored)),
            "n_clean": len(clean), "false_red": false_red, "false_red_rate": rate(false_red, len(clean)),
            "unsure": unsure, "grader_error": grader_error, "defect_setup_broken": setup_broken,
            "caught_hidden": hidden_caught, "caught_hidden_rate": rate(hidden_caught, len(tested)),
            "caught_visible": visible_caught, "caught_visible_rate": rate(visible_caught, len(tested))}


def show(value):
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def cmd_score(out, label, model=GRADER_MODEL):
    root = Path(os.path.abspath(str(out)))
    directory = review_dir(root, label)
    metas = review_meta(root)
    split = load_split(root)
    cases = all_cases(root)
    require_split(split, cases)
    graded = []
    for review_file in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        item = review_file.stem
        if "__" not in item:
            continue
        case_id, variant = item.rsplit("__", 1)
        if variant not in ("clean", "defect"):
            continue
        path = case_path(root, case_id)
        if not path.exists():
            continue
        case = read_json(path)
        if case.get("status") != "valid":
            continue
        meta = metas.get(item, {})
        review = review_file.read_text(encoding="utf-8")
        verdict = read_verdict(review)
        result = case.get(variant) or {}
        record = {"item": item, "case": case_id, "variant": variant,
                  "split": meta.get("split") or split_of(split, case_id),
                  "verdict": verdict, "setup": result.get("setup"),
                  "tests": result.get("tests"), "hidden": result.get("hidden")}
        if variant == "clean":
            record["false_red"] = verdict == "RED"
        elif verdict == "ONAY":
            record["caught"], record["unsure"] = False, False
        else:
            grade = grade_item(root, label, case, item, review, model)
            record["caught"], record["unsure"] = bool(grade.get("caught")), bool(grade.get("unsure"))
            if grade.get("grader_error"):
                record["grader_error"] = True
            record["grader"] = {"answers": grade.get("answers", []), "verdicts": grade.get("verdicts", [])}
        graded.append(record)
    splits = {"tuning": case_stats([item for item in graded if item["split"] == "tuning"], "tuning"),
              "holdout": case_stats([item for item in graded if item["split"] == "holdout"], "holdout")}
    total = case_stats(graded, "total")
    report = {"label": label, "grader": model, "items": graded, "splits": dict(splits, all=total),
              "tuning": splits["tuning"], "holdout": splits["holdout"], "total": total, "all": total}
    write_json(root / f"score_{label}.json", report)
    print(f"{'split':<9} {'n_defect':>8} {'caught':>6} {'catch_rate':>10} {'n_clean':>7} "
          f"{'false_red':>9} {'false_red_rate':>14} {'unsure':>6} {'grader_err':>10} "
          f"{'hidden_rate':>11} {'visible_rate':>12}")
    for name, stats in (("tuning", splits["tuning"]), ("holdout", splits["holdout"]), ("total", total)):
        print(f"{name:<9} {stats['n_defect']:>8} {stats['caught']:>6} {show(stats['catch_rate']):>10} "
              f"{stats['n_clean']:>7} {stats['false_red']:>9} {show(stats['false_red_rate']):>14} "
              f"{stats['unsure']:>6} {stats['grader_error']:>10} "
              f"{show(stats['caught_hidden_rate']):>11} {show(stats['caught_visible_rate']):>12}")
    print(f"score: {len(graded)} items, caught {total['caught']}/{total['n_defect']}, "
          f"false_red {total['false_red']}/{total['n_clean']}, "
          f"defect_setup_broken {total['defect_setup_broken']} -> {root / f'score_{label}.json'}")


# --- clean -------------------------------------------------------------------
def worktree_repo(wt):
    """Repo that owns a linked worktree, read from its .git file (None when it is not one)."""
    gitfile = Path(wt) / ".git"
    try:
        if not gitfile.is_file():
            return None
        text = gitfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = Path(wt) / gitdir
    gitdir = Path(os.path.abspath(str(gitdir)))
    for parent in (gitdir, *gitdir.parents):
        if parent.name == ".git":
            return str(parent.parent)
    return None


def cmd_clean(out):
    root = Path(os.path.abspath(str(out)))
    case_repos = {}
    for case in all_cases(root):
        if case.get("repo"):
            for variant in ("clean", "defect"):
                case_repos[str(wt_path(root, item_of(case["id"], variant)))] = case["repo"]
    repos, removed = set(), 0
    wt_root = root / "wt"
    if wt_root.is_dir():
        for path in sorted(wt_root.iterdir()):
            if not path.is_dir() or not (path / ".git").is_file():
                continue
            repo = case_repos.get(str(path)) or worktree_repo(path)
            if not repo:
                continue
            repos.add(repo)
            git(repo, "worktree", "remove", "--force", str(path), check=False)
            if not path.exists():
                removed += 1
    for repo in sorted(repos):
        git(repo, "worktree", "prune", check=False)
    print(f"clean: {removed} worktrees removed")


# --- CLI ---------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(prog="corpus.py", description="Escapes corpus tool (HX-46).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build", help="create worktrees, correct diffs and case records")
    build.add_argument("manifest")
    build.add_argument("out")
    mutate = sub.add_parser("mutate", help="inject one defect per case with a model")
    mutate.add_argument("out")
    mutate.add_argument("--model", default=MUTATE_MODEL)
    mutate.add_argument("--ids", default=None)
    check = sub.add_parser("check", help="run setup, visible and hidden tests")
    check.add_argument("out")
    split = sub.add_parser("split", help="split valid cases into tuning/holdout")
    split.add_argument("out")
    split.add_argument("--seed", type=int, default=46)
    pack = sub.add_parser("review-pack", help="write gates and blind reviewer inputs")
    pack.add_argument("out")
    score = sub.add_parser("score", help="score reviewer outputs against the answer keys")
    score.add_argument("out")
    score.add_argument("label")
    score.add_argument("--grader", default=GRADER_MODEL)
    clean = sub.add_parser("clean", help="remove the corpus worktrees")
    clean.add_argument("out")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        cmd_build(args.manifest, args.out)
    elif args.cmd == "mutate":
        ids = [part.strip() for part in (args.ids or "").split(",") if part.strip()]
        cmd_mutate(args.out, model=args.model, ids=ids)
    elif args.cmd == "check":
        cmd_check(args.out)
    elif args.cmd == "split":
        cmd_split(args.out, seed=args.seed)
    elif args.cmd == "review-pack":
        cmd_review_pack(args.out)
    elif args.cmd == "score":
        cmd_score(args.out, args.label, model=args.grader)
    elif args.cmd == "clean":
        cmd_clean(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
