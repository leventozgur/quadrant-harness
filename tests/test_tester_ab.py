"""Tests for lab/escapes/tester_ab.py.

Throwaway git repositories and a fake `ESCAPES_OPENCODE` script: no real model runs.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ESCAPES = Path(__file__).resolve().parent.parent / "lab" / "escapes"
sys.path.insert(0, str(ESCAPES))

import corpus  # noqa: E402
import tester_ab  # noqa: E402

SPEC = "# Görev\ntriple ekle\n\n## Kapsam\nsrc/calc.py\n"
BASE_CALC = "def double(n):\n    return n * 2\n"
FEAT_CALC = BASE_CALC + "\n\ndef triple(n):\n    return n * 3\n"
TEST_CMD = ("python3 -c \"import sys; sys.path.insert(0, '.'); "
            "from src.calc import triple; assert triple(3) == 9\"")

FAKE = """#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
calls = []
log = os.path.join(here, "calls.jsonl")
if os.path.exists(log):
    calls = [line for line in open(log, encoding="utf-8") if line.strip()]
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
with open(os.path.join(here, "cwds.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(os.getcwd()) + "\\n")
with open(os.path.join(here, "pwds.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(os.environ.get("PWD")) + "\\n")
plan = json.load(open(os.path.join(here, "action.json"), encoding="utf-8"))
for name, content in (plan.get("files") or {}).items():
    path = os.path.join(os.getcwd(), name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
for path, content in (plan.get("foreign") or {}).items():
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
sys.stdout.write(json.dumps({"type": "text", "part": {"messageID": "m1", "text": "tamam"}},
                            ensure_ascii=False) + "\\n")
"""

SANDBOX_SHIM = """#!/bin/sh
shift 2
exec "$@"
"""

STRAY_FAKE = """#!/usr/bin/env python3
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
prompt = sys.argv[-1]
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps([part for part in ("tbase/a", "tbase/b", "tbase/c") if part in prompt])
                 + "\\n")
if "tbase/a" in prompt:
    with open(os.path.join(here, "a.done"), "w", encoding="utf-8") as handle:
        handle.write("1")
    with open("@TARGET@", "w", encoding="utf-8") as handle:
        handle.write("hacked\\n")
else:
    deadline = time.time() + 20
    while not os.path.exists(os.path.join(here, "a.done")) and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(1)
sys.stdout.write(json.dumps({"type": "text", "part": {"messageID": "m1", "text": "tamam"}}) + "\\n")
"""


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def make_repo(root, before, after, name="repo"):
    repo = Path(root) / name
    repo.mkdir()
    git(repo, "init", "-q")
    for key, value in (("user.name", "tester-ab tests"), ("user.email", "tester@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        git(repo, "config", key, value)
    for files, message in ((before, "base"), (after, "feature")):
        for relative, text in files.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)
    return repo, git(repo, "rev-parse", "HEAD^").strip(), git(repo, "rev-parse", "HEAD").strip()


def fake(root, name="fake", files=None, foreign=None):
    directory = Path(root) / name
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "opencode"
    script.write_text(FAKE, encoding="utf-8")
    script.chmod(0o755)
    (directory / "action.json").write_text(
        json.dumps({"files": files or {"tests/test_hidden.py": "def test_ok():\n    assert True\n"},
                    "foreign": foreign or {}}), encoding="utf-8")
    (directory / "calls.jsonl").write_text("", encoding="utf-8")
    (directory / "cwds.jsonl").write_text("", encoding="utf-8")
    (directory / "pwds.jsonl").write_text("", encoding="utf-8")
    return script, directory


def read_jsonl(path):
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class TesterAbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tester-ab-tests-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo, self.base, self.commit = make_repo(
            self.tmp, {"src/calc.py": BASE_CALC, "src/other.py": "def one():\n    return 1\n"},
            {"src/calc.py": FEAT_CALC})
        self.spec = self.tmp / "spec.md"
        self.spec.write_text(SPEC, encoding="utf-8")
        self.out = self.tmp / "out"
        self.template = self.tmp / "tester.md"
        self.template.write_text("SPEC:\n{SPEC}\nTBASE: {WORKTREE}\nALT: {TBASE}\nHIDDEN: {HIDDEN}\n",
                                 encoding="utf-8")
        self.sandbox_bin = self.tmp / "sandbox-bin"
        self.sandbox_bin.mkdir()
        shim = self.sandbox_bin / "sandbox-exec"
        shim.write_text(SANDBOX_SHIM, encoding="utf-8")
        shim.chmod(0o755)

    def seed_case(self, case_id="c1", hidden_cmd=TEST_CMD):
        case = {"id": case_id, "repo": str(self.repo), "spec": str(self.spec),
                "commit": self.commit, "base": self.base, "hidden_cmd": hidden_cmd,
                "status": "valid"}
        corpus.write_json(self.out / "cases" / f"{case_id}.json", case)
        return case

    def make_wt(self, case_id="c1", variant="clean", content=None):
        wt = self.out / "wt" / f"{case_id}__{variant}"
        wt.parent.mkdir(parents=True, exist_ok=True)
        git(self.repo, "worktree", "add", "--detach", str(wt), self.commit)
        if content is not None:
            (wt / "src" / "calc.py").write_text(content, encoding="utf-8")
        return wt

    def cli(self, *args, opencode=None, expect_ok=True):
        env = dict(os.environ)
        env["PATH"] = str(self.sandbox_bin) + os.pathsep + env.get("PATH", "")
        if opencode is not None:
            env["ESCAPES_OPENCODE"] = str(opencode)
        proc = subprocess.run([sys.executable, "-I", str(ESCAPES / "tester_ab.py"),
                               *[str(arg) for arg in args]],
                              capture_output=True, text=True, env=env)
        if expect_ok and proc.returncode != 0:
            raise AssertionError(f"tester_ab {args} failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
        return proc

    def gen(self, label="A", script=None, *extra):
        if script is None:
            script, _ = fake(self.tmp, f"fake-{label}")
        return self.cli("gen", self.out, label, "--template", self.template, *extra, opencode=script)

    def hidden(self, label="A", case_id="c1"):
        return self.out / "tester" / label / case_id / "hidden"


class GenTest(TesterAbTestCase):
    def test_gen_writes_tbase_hidden_raw_and_meta(self):
        _, directory = fake(self.tmp, "fake-A")
        self.seed_case()
        proc = self.gen("A", directory / "opencode")
        tbase = self.out / "tbase" / "c1"
        self.assertEqual(self.base, git(tbase, "rev-parse", "HEAD").strip())
        self.assertTrue((self.hidden() / "tests" / "test_hidden.py").exists())
        meta = json.loads((self.out / "tester" / "A" / "c1" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual({"model", "seconds", "rc", "timeout"}, set(meta))
        self.assertEqual(tester_ab.DEFAULT_MODEL, meta["model"])
        self.assertEqual(0, meta["rc"])
        self.assertIs(False, meta["timeout"])
        self.assertTrue((self.out / "tester" / "A" / "c1" / "raw.jsonl").read_text(encoding="utf-8"))
        self.assertIn("gen: 1 generated", proc.stdout)
        sent = read_jsonl(directory / "calls.jsonl")[0]
        self.assertEqual(["run", "--standalone", "-m", tester_ab.DEFAULT_MODEL, "--format", "json"],
                         sent[:6])
        self.assertIn(SPEC.strip(), sent[6])
        self.assertIn(str(tbase), sent[6])
        self.assertIn(str(self.hidden()), sent[6])
        self.assertEqual([os.path.realpath(self.hidden()), os.path.realpath(self.hidden())],
                         [os.path.realpath(path) for path in read_jsonl(directory / "cwds.jsonl")
                          + read_jsonl(directory / "pwds.jsonl")])

    def test_meta_makes_the_case_idempotent(self):
        self.seed_case()
        script, directory = fake(self.tmp, "fake-A")
        self.gen("A", script)
        before = (self.out / "tester" / "A" / "c1" / "meta.json").read_text(encoding="utf-8")
        proc = self.gen("A", script)
        self.assertIn("gen: 0 generated, 1 skipped", proc.stdout)
        self.assertEqual(1, len(read_jsonl(directory / "calls.jsonl")))
        self.assertEqual(before, (self.out / "tester" / "A" / "c1" / "meta.json").read_text(encoding="utf-8"))

    def test_ids_and_jobs_limit_the_selection(self):
        self.seed_case("a")
        self.seed_case("b")
        script, directory = fake(self.tmp, "fake-A")
        proc = self.gen("A", script, "--ids", "a", "--jobs", "1")
        self.assertIn("1 generated", proc.stdout)
        self.assertEqual(1, len(read_jsonl(directory / "calls.jsonl")))
        self.assertTrue((self.out / "tbase" / "a").is_dir())
        self.assertFalse((self.out / "tbase" / "b").exists())

    def test_tbase_is_shared_between_labels(self):
        self.seed_case()
        first, _ = fake(self.tmp, "fake-A")
        self.gen("A", first)
        sentinel = self.out / "tbase" / "c1" / "sentinel.txt"
        sentinel.write_text("keep\n", encoding="utf-8")
        second, directory = fake(self.tmp, "fake-B")
        self.gen("B", second)
        self.assertTrue(sentinel.exists())
        self.assertIn(str(self.out / "tbase" / "c1"),
                      read_jsonl(directory / "calls.jsonl")[0][6])

    def test_an_invalid_case_is_not_generated(self):
        case = self.seed_case()
        case["status"] = "invalid"
        corpus.write_json(self.out / "cases" / "c1.json", case)
        script, directory = fake(self.tmp, "fake-A")
        self.gen("A", script)
        self.assertEqual([], read_jsonl(directory / "calls.jsonl"))

    def test_a_stray_write_stops_gen(self):
        self.seed_case()
        script, _ = fake(self.tmp, "fake-A", foreign={str(self.repo / "src" / "calc.py"): "hacked\n"})
        proc = self.cli("gen", self.out, "A", "--template", self.template, opencode=script, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("stray_write", proc.stderr)
        self.assertFalse((self.out / "tester" / "A" / "c1" / "meta.json").exists())

    def test_a_stray_write_stops_the_other_jobs(self):
        self.seed_case("a")
        self.seed_case("b")
        self.seed_case("c")
        directory = self.tmp / "fake-stray"
        directory.mkdir()
        script = directory / "opencode"
        script.write_text(STRAY_FAKE.replace("@TARGET@", str(self.repo / "src" / "calc.py")),
                          encoding="utf-8")
        script.chmod(0o755)
        proc = self.cli("gen", self.out, "A", "--template", self.template, "--jobs", "2",
                        opencode=script, expect_ok=False)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("stray_write", proc.stderr)
        for case_id in ("a", "b", "c"):
            self.assertFalse((self.out / "tester" / "A" / case_id / "meta.json").exists())
        called = [line for line in read_jsonl(directory / "calls.jsonl") if line]
        self.assertNotIn(["tbase/c"], called)


class RunTest(TesterAbTestCase):
    def prepare(self, hidden_cmd=TEST_CMD, tests=True):
        self.seed_case(hidden_cmd=hidden_cmd)
        hidden = self.hidden()
        hidden.mkdir(parents=True)
        if tests:
            (hidden / "test_hidden.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def test_clean_pass_and_defect_fail_are_valid_and_caught(self):
        self.prepare()
        self.make_wt("c1", "clean")
        self.make_wt("c1", "defect", FEAT_CALC.replace("n * 3", "n + 3"))
        proc = self.cli("run", self.out, "A")
        result = json.loads((self.out / "tester" / "A" / "c1" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual({"clean": "pass", "defect": "fail", "valid": True, "caught": True}, result)
        self.assertIn("run: 1 run", proc.stdout)

    def test_a_failing_clean_suite_is_invalid_and_not_caught(self):
        self.prepare(hidden_cmd="python3 -c \"import sys; sys.exit(3)\"")
        self.make_wt("c1", "clean")
        self.make_wt("c1", "defect")
        self.cli("run", self.out, "A")
        result = json.loads((self.out / "tester" / "A" / "c1" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual({"clean": "fail", "defect": "fail", "valid": False, "caught": False}, result)

    def test_a_defect_timeout_is_caught(self):
        self.prepare(hidden_cmd="sleep 5")
        self.make_wt("c1", "clean")
        self.make_wt("c1", "defect")
        saved = corpus.TIMEOUT
        corpus.TIMEOUT = 0.2
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                tester_ab.cmd_run(str(self.out), "A")
        finally:
            corpus.TIMEOUT = saved
        result = json.loads((self.out / "tester" / "A" / "c1" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("timeout", result["clean"])
        self.assertEqual("timeout", result["defect"])
        self.assertIs(False, result["valid"])

    def test_no_test_file_writes_no_tests_without_running(self):
        self.prepare()
        (self.hidden() / "test_hidden.py").unlink()
        self.make_wt("c1", "clean")
        self.make_wt("c1", "defect")
        self.cli("run", self.out, "A")
        result = json.loads((self.out / "tester" / "A" / "c1" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual({"valid": False, "caught": False,
                          "clean": "no_tests", "defect": "no_tests"}, result)
        self.assertFalse((self.out / "tester" / "A" / "c1" / "clean.log").exists())

    def test_logs_keep_the_last_sixty_lines(self):
        self.prepare(hidden_cmd="python3 -c \"import sys; [print(i) for i in range(100)]; sys.exit(1)\"")
        self.make_wt("c1", "clean")
        self.make_wt("c1", "defect")
        self.cli("run", self.out, "A")
        lines = (self.out / "tester" / "A" / "c1" / "clean.log").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(60, len(lines))
        self.assertEqual("99", lines[-1])
        self.assertNotIn("0", lines)


class ScoreTest(TesterAbTestCase):
    def seed(self, case_id, split_name, result=None):
        self.seed_case(case_id)
        if result is not None:
            corpus.write_json(self.out / "tester" / "A" / case_id / "result.json", result)
            corpus.write_json(self.out / "tester" / "B" / case_id / "result.json", result)
        return case_id

    def score(self, *labels):
        corpus.write_json(self.out / "split.json",
                          {"tuning": ["c1", "c2"], "holdout": ["c3", "c4"]})
        return self.cli("score", self.out, *labels)

    def report(self):
        return json.loads((self.out / "tester_score.json").read_text(encoding="utf-8"))

    def test_per_split_counts_and_rates(self):
        self.seed("c1", "tuning", {"valid": True, "caught": True})
        self.seed("c2", "tuning", {"valid": False, "caught": False})
        self.seed("c3", "holdout", {"valid": True, "caught": False})
        self.seed("c4", "holdout")
        proc = self.score("A")
        report = self.report()
        tuning = report["A"]["tuning"]
        self.assertEqual({"n": 2, "suites": 2, "valid": 1, "caught": 1,
                          "catch_rate": 0.5, "invalid": 1}, tuning)
        self.assertEqual({"n": 2, "suites": 1, "valid": 1, "caught": 0,
                          "catch_rate": 0.0, "invalid": 0}, report["A"]["holdout"])
        self.assertEqual({"n": 4, "suites": 3, "valid": 2, "caught": 1,
                          "catch_rate": 0.25, "invalid": 1}, report["A"]["all"])
        self.assertEqual(report["A"], report["labels"]["A"])
        self.assertIn("tuning", proc.stdout)
        self.assertTrue((self.out / "tester_score.json").exists())

    def test_zero_denominator_is_none(self):
        corpus.write_json(self.out / "split.json", {"tuning": [], "holdout": []})
        self.cli("score", self.out, "A")
        all_stats = self.report()["A"]["all"]
        self.assertEqual(0, all_stats["n"])
        self.assertIsNone(all_stats["catch_rate"])

    def test_two_labels_report_only_the_differences(self):
        self.seed("c1", "tuning", {"valid": True, "caught": True})
        self.seed("c2", "tuning", {"valid": True, "caught": True})
        self.seed("c3", "holdout", {"valid": True, "caught": False})
        self.seed("c4", "holdout", {"valid": True, "caught": False})
        corpus.write_json(self.out / "split.json",
                          {"tuning": ["c1", "c2"], "holdout": ["c3", "c4"]})
        corpus.write_json(self.out / "tester" / "A" / "c4" / "result.json",
                          {"valid": True, "caught": True})
        corpus.write_json(self.out / "tester" / "B" / "c3" / "result.json",
                          {"valid": True, "caught": True})
        self.cli("score", self.out, "A", "B")
        report = self.report()
        self.assertEqual(["c4"], report["only_A"])
        self.assertEqual(["c3"], report["only_B"])


class CleanTest(TesterAbTestCase):
    def test_only_tbase_worktrees_are_removed(self):
        self.seed_case()
        tbase = self.out / "tbase" / "c1"
        tbase.parent.mkdir(parents=True)
        git(self.repo, "worktree", "add", "--detach", str(tbase), self.base)
        keep = self.out / "tbase" / "not-a-worktree"
        keep.mkdir()
        (keep / "keep.txt").write_text("keep\n", encoding="utf-8")
        tester_file = self.out / "tester" / "A" / "c1" / "meta.json"
        corpus.write_json(tester_file, {"model": "x"})
        proc = self.cli("clean", self.out)
        self.assertFalse(tbase.exists())
        self.assertTrue((keep / "keep.txt").exists())
        self.assertTrue(tester_file.exists())
        self.assertIn("clean: 1 worktrees removed", proc.stdout)


class CliTest(TesterAbTestCase):
    def test_unknown_subcommand_exits_non_zero(self):
        proc = self.cli("bogus", expect_ok=False)
        self.assertNotEqual(0, proc.returncode)


class HelperTest(unittest.TestCase):
    def test_test_files_uses_test_shapes(self):
        root = Path(tempfile.mkdtemp(prefix="tester-files-"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text("x\n", encoding="utf-8")
        (root / "notes.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual([root / "tests" / "test_a.py"], tester_ab.test_files(root))
        (root / "tests" / "test_a.py").unlink()
        self.assertEqual([], tester_ab.test_files(root))


if __name__ == "__main__":
    unittest.main()
