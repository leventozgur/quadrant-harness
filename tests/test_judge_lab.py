"""Tests for lab/judge_lab.py: hidden-test outcomes, case building, judging and scoring.

No real model is started: `JUDGE_LAB_OPENCODE` points at the fake script from tests.helpers.
All runs happen in temporary directories.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lab"))
import judge_lab as J  # noqa: E402

from tests.helpers import fake_opencode, read_calls  # noqa: E402

TEST_A = '''import unittest


class T(unittest.TestCase):
    def test_ok(self):
        """First docstring line.

        Second docstring line.
        """
        self.assertEqual(1, 1)

    def test_fail(self):
        self.assertEqual(1, 2)

    def test_error(self):
        raise RuntimeError("boom")

    @unittest.skip("later")
    def test_skip(self):
        pass
'''


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def events(*chunks):
    return [json.dumps({"type": "text", "part": {"messageID": "m1", "text": c}}, ensure_ascii=False)
            for c in chunks]


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestOutcomes(TempDirTest):
    def hidden(self):
        d = self.tmp / "hidden"
        d.mkdir()
        write(d / "test_a.py", TEST_A)
        write(d / "test_broken.py", "import nonexistent_module_xyz\n")
        return d

    def test_discover_maps_every_status(self):
        outcomes, rc, output = J.test_outcomes(self.hidden(), self.tmp / "sol")
        self.assertEqual(outcomes["test_a.T.test_ok"], "pass")
        self.assertEqual(outcomes["test_a.T.test_fail"], "fail")
        self.assertEqual(outcomes["test_a.T.test_error"], "error")
        self.assertEqual(outcomes["test_a.T.test_skip"], "skip")
        self.assertEqual(outcomes["unittest.loader._FailedTest.test_broken"], "error")
        self.assertNotEqual(rc, 0)
        self.assertIn("test_a.T.test_ok", output)

    def test_ids_runs_only_those_tests(self):
        outcomes, rc, _ = J.test_outcomes(self.hidden(), self.tmp / "sol", ids=["test_a.T.test_ok"])
        self.assertEqual(outcomes, {"test_a.T.test_ok": "pass"})
        self.assertEqual(rc, 0)

    def test_empty_ids_runs_nothing(self):
        self.assertEqual(J.test_outcomes(self.hidden(), self.tmp / "sol", ids=[]), ({}, 0, ""))

    def test_stderr_between_header_and_result_keeps_both_ids(self):
        output = ("test_a.T.test_one (test_a.T.test_one) ... \n"
                  "noise on stderr\n"
                  "ok\n"
                  "test_a.T.test_two (test_a.T.test_two) ... FAIL\n")
        self.assertEqual(J._parse_verbose(output),
                         {"test_a.T.test_one": "pass", "test_a.T.test_two": "fail"})

    def test_new_header_replaces_a_stale_pending_id(self):
        output = ("test_a.T.test_one (test_a.T.test_one) ... \n"
                  "stderr only\n"
                  "test_a.T.test_two (test_a.T.test_two) ... ok\n")
        self.assertEqual(J._parse_verbose(output), {"test_a.T.test_two": "pass"})

    def test_test_stdout_name_does_not_steal_the_pending_id(self):
        output = ("test_a.T.test_one (test_a.T.test_one) ... \n"
                  "ad (kelime)\n"
                  "ok\n")
        self.assertEqual(J._parse_verbose(output), {"test_a.T.test_one": "pass"})

    def test_expected_failure_passes_and_unexpected_success_fails(self):
        output = ("test_a.T.test_xf (test_a.T.test_xf) ... expected failure\n"
                  "test_a.T.test_xp (test_a.T.test_xp) ... unexpected success\n")
        self.assertEqual(J._parse_verbose(output),
                         {"test_a.T.test_xf": "pass", "test_a.T.test_xp": "fail"})

    def test_lone_result_line_belongs_to_the_pending_test(self):
        output = ("test_a.T.test_ok (test_a.T.test_ok)\n"
                  "First docstring line. .... ok\n"
                  "test_a.T.test_err (test_a.T.test_err) ... \n"
                  "ERROR\n")
        self.assertEqual(J._parse_verbose(output),
                         {"test_a.T.test_ok": "pass", "test_a.T.test_err": "error"})

    def test_ids_import_error_maps_to_requested_ids(self):
        d = self.tmp / "broken_ids"
        d.mkdir()
        write(d / "test_crash.py", "import nonexistent_module_xyz\n")
        outcomes, rc, _ = J.test_outcomes(d, self.tmp / "sol", ids=["test_crash.T.test_x"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(outcomes, {"test_crash.T.test_x": "error"})
        self.assertNotIn("unittest.loader._FailedTest", outcomes)

    def test_missing_requested_id_is_error_even_when_rc_is_zero(self):
        hidden = self.tmp / "hidden"
        write(hidden / "test_a.py", "x = 1\n")
        fake = mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(J.subprocess, "run", return_value=fake):
            outcomes, rc, _ = J.test_outcomes(
                hidden, self.tmp / "sol", ids=["test_a.T.test_missing"])
        self.assertEqual(rc, 0)
        self.assertEqual(outcomes, {"test_a.T.test_missing": "error"})

    def test_ids_crash_marks_missing_ids_as_error(self):
        d = self.tmp / "crash_ids"
        d.mkdir()
        write(d / "test_crash.py", "import sys\nsys.exit(7)\n")
        outcomes, rc, _ = J.test_outcomes(d, self.tmp / "sol", ids=["test_crash.T.test_x"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(outcomes, {"test_crash.T.test_x": "error"})

    def test_timeout_marks_the_whole_suite_error(self):
        hidden = self.tmp / "slow"
        write(hidden / "test_slow.py",
              "import time, unittest\n\n\nclass T(unittest.TestCase):\n"
              "    def test_sleep(self):\n        time.sleep(5)\n")
        with mock.patch.object(J, "TEST_TIMEOUT_S", 1):
            outcomes, rc, _ = J.test_outcomes(hidden, self.tmp / "sol")
        self.assertEqual(rc, -1)
        self.assertTrue(outcomes)
        self.assertEqual(set(outcomes.values()), {"error"})


class TestGateText(unittest.TestCase):
    def test_header_and_short_output(self):
        self.assertEqual(J.gate_text("python3 -m unittest", 0, "a\nb"),
                         "--- hidden (python3 -m unittest) exit 0\na\nb")

    def test_keeps_only_the_last_sixty_lines(self):
        text = J.gate_text("c", 3, "\n".join(f"L{i}" for i in range(100)))
        lines = text.splitlines()
        self.assertEqual(lines[0], "--- hidden (c) exit 3")
        self.assertEqual(len(lines), 61)
        self.assertEqual(lines[-1], "L99")


class TestVerdicts(unittest.TestCase):
    def test_counts_only_verdict_lines(self):
        text = ("KOD_HATASI — kural — kod\n"
                "  TEST_HATASI – test — neden\n"
                "BELIRSIZ - test - neden\n"
                "KOD_HATASI yok.\n"
                "KOD_HATASI-yok\n")
        self.assertEqual(J.parse_verdicts(text), {"KOD": 1, "TEST": 1, "BELIRSIZ": 1})

    def test_empty_text(self):
        self.assertEqual(J.parse_verdicts(""), {"KOD": 0, "TEST": 0, "BELIRSIZ": 0})

    def test_category_table(self):
        c = lambda kod=0, test=0, bel=0: {"KOD": kod, "TEST": test, "BELIRSIZ": bel}
        self.assertEqual(J.category(c(kod=1)), "KOD")
        self.assertEqual(J.category(c(test=1)), "TEST")
        self.assertEqual(J.category(c(kod=1, test=1)), "MIXED")
        self.assertEqual(J.category(c(bel=2)), "BELIRSIZ")
        self.assertEqual(J.category(c()), "NONE")
        self.assertEqual(J.category(c(kod=1, bel=1)), "KOD")


class TestBuildCases(TempDirTest):
    MODULE = ("import unittest\n\nimport mod\n\n\nclass T(unittest.TestCase):\n"
              "    def test_value(self):\n        self.assertEqual(mod.VALUE, 1)\n\n"
              "    def test_never(self):\n        self.assertEqual(mod.VALUE, 99)\n")

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "runs"
        run = self.root / "lbl" / "h03_r1"
        write(run / "hidden" / "test_mod.py", self.MODULE)
        (run / "project").mkdir(parents=True)
        (run / "_meta.json").write_text("{}", encoding="utf-8")
        self.run = run
        self.sols = {}
        for name, value in (("ref", 1), ("mut", 2)):
            d = self.tmp / f"sol_{name}"
            write(d / "mod.py", f"VALUE = {value}\n")
            self.sols[name] = d

    def fake_solution_dir(self, task, mutant=None):
        return self.sols["ref"] if mutant is None else self.sols["mut"]

    def build(self):
        out = self.tmp / "out"
        env = {"TESTER_LAB_ROOT": str(self.root)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(J.T, "solution_dir", side_effect=self.fake_solution_dir):
            J.build_cases(out, ["lbl"])
        return out

    def test_labels_cases_and_files(self):
        out = self.build()
        ref = out / "cases" / "lbl__h03_r1__ref"
        self.assertTrue((ref / "hidden" / "test_mod.py").exists())
        self.assertFalse((ref / "hidden" / "__pycache__").exists())
        self.assertEqual((ref / "project" / "mod.py").read_text(), "VALUE = 1\n")
        ref_json = json.loads((ref / "case.json").read_text())
        self.assertEqual(ref_json["failing"], ["test_mod.T.test_never"])
        self.assertEqual(ref_json["label"], "TEST")
        self.assertEqual(ref_json["task"], "h03")
        self.assertEqual(ref_json["suite"], "lbl/h03_r1")
        self.assertTrue((ref / "gate.txt").read_text().startswith(
            "--- hidden (python3 -m unittest) exit "))
        kod = out / "cases" / "lbl__h03_r1__m0"
        kod_json = json.loads((kod / "case.json").read_text())
        self.assertEqual(kod_json["failing"], ["test_mod.T.test_value"])
        self.assertEqual(kod_json["label"], "KOD")
        self.assertEqual(kod_json["variant"], "m0")
        self.assertEqual((kod / "project" / "mod.py").read_text(), "VALUE = 2\n")
        cases = json.loads((out / "cases.json").read_text())
        ids = [c["case_id"] for c in cases]
        self.assertEqual(ids, sorted(ids))
        self.assertIn("lbl__h03_r1__ref", ids)
        self.assertIn("lbl__h03_r1__m0", ids)
        self.assertEqual((self.run / "project" / "mod.py").read_text(), "VALUE = 1\n")

    def test_runs_without_meta_are_skipped(self):
        no_meta = self.root / "lbl" / "h04_r1"
        write(no_meta / "hidden" / "test_x.py", "def test_x():\n    pass\n")
        out = self.build()
        self.assertFalse(list((out / "cases").glob("*h04_r1*")))

    def test_solution_dirs_are_cached_per_task_and_mutant(self):
        calls = []

        def counting(task, mutant=None):
            calls.append((task, mutant))
            return self.fake_solution_dir(task, mutant)

        out = self.tmp / "out"
        with mock.patch.dict(os.environ, {"TESTER_LAB_ROOT": str(self.root)}), \
                mock.patch.object(J.T, "solution_dir", side_effect=counting):
            J.build_cases(out, ["lbl"])
        self.assertEqual(calls.count(("h03", None)), 1)
        for m in range(len(J.T.MUT["h03"])):
            self.assertEqual(calls.count(("h03", m)), 1)

    def test_build_deletes_its_solution_temp_dirs(self):
        made = []

        def temp_solution(task, mutant=None):
            d = Path(tempfile.mkdtemp(prefix=f"sol_{task}_"))
            write(d / "mod.py", f"VALUE = {1 if mutant is None else 2}\n")
            made.append(d)
            return d

        out = self.tmp / "out"
        with mock.patch.dict(os.environ, {"TESTER_LAB_ROOT": str(self.root)}), \
                mock.patch.object(J.T, "solution_dir", side_effect=temp_solution):
            J.build_cases(out, ["lbl"])
        self.assertTrue(made)
        self.assertTrue(all(not d.exists() for d in made))

    def test_stale_tmp_dirs_are_removed_and_never_scored(self):
        stale = self.tmp / "out" / "cases" / "half.tmp"
        write(stale / "case.json", json.dumps({"case_id": "stale"}))
        write(stale / "junk.txt", "x")
        out = self.build()
        self.assertFalse(stale.exists())
        self.assertNotIn("stale", [c["case_id"] for c in json.loads((out / "cases.json").read_text())])

    def test_existing_case_dir_is_not_rewritten(self):
        out = self.build()
        target = out / "cases" / "lbl__h03_r1__ref" / "case.json"
        os.utime(target, (1000000000, 1000000000))
        self.build()
        self.assertEqual(target.stat().st_mtime, 1000000000)
        self.assertEqual(len(json.loads((out / "cases.json").read_text())), 5)

    def test_incomplete_case_dir_is_rebuilt(self):
        partial = self.tmp / "out" / "cases" / "lbl__h03_r1__ref"
        partial.mkdir(parents=True)
        (partial / "stale.txt").write_text("half written")
        out = self.build()
        ref = out / "cases" / "lbl__h03_r1__ref"
        self.assertTrue((ref / "case.json").exists())
        self.assertFalse((ref / "stale.txt").exists())

    def test_project_is_restored_when_a_run_raises(self):
        real = J.test_outcomes

        def boom(hidden, proj, ids=None):
            if ids is not None:
                raise RuntimeError("boom")
            return real(hidden, proj, ids)

        out = self.tmp / "out"
        with mock.patch.dict(os.environ, {"TESTER_LAB_ROOT": str(self.root)}), \
                mock.patch.object(J.T, "solution_dir", side_effect=self.fake_solution_dir), \
                mock.patch.object(J, "test_outcomes", side_effect=boom):
            with self.assertRaises(RuntimeError):
                J.build_cases(out, ["lbl"])
        self.assertEqual((self.run / "project" / "mod.py").read_text(), "VALUE = 1\n")


class JudgeTest(TempDirTest):
    def make_case(self, task="h03", label="TEST"):
        case_id = "lbl__h03_r1__ref"
        d = self.tmp / "out" / "cases" / case_id
        write(d / "hidden" / "test_mod.py", "x = 1\n")
        write(d / "project" / "mod.py", "VALUE = 1\n")
        (d / "gate.txt").write_text(
            "--- hidden (python3 -m unittest) exit 1\n"
            f"{d / 'hidden' / 'test_mod.py'}\n{d / 'project' / 'mod.py'}\n"
            "/foreign/root/lbl/h03_r1/hidden/test_mod.py\n"
            "test_mod.T.test_never ... FAIL\n",
            encoding="utf-8")
        write(d / "case.json", json.dumps({"case_id": case_id, "task": task,
                                           "suite": "lbl/h03_r1", "variant": "ref",
                                           "label": label, "failing": ["test_mod.T.test_never"]}))
        return d

    def judge(self, fake_dir, **kwargs):
        out = self.tmp / "out"
        env = {"JUDGE_LAB_OPENCODE": str(Path(fake_dir) / "opencode")}
        with mock.patch.dict(os.environ, env):
            return J.judge(out, "test/model", **kwargs), out

    def test_rep_file_and_prompt(self):
        self.make_case()
        fake = self.tmp / "fake"
        fake_opencode(fake, stdout_lines=events("KOD_HATASI — kural — kod\n",
                                                "TEST_HATASI — test — neden\n"))
        records, out = self.judge(fake, reps=1)
        rep = json.loads((out / "cases" / "lbl__h03_r1__ref" / "rep_1.json").read_text())
        self.assertEqual(rep["counts"], {"KOD": 1, "TEST": 1, "BELIRSIZ": 0})
        self.assertEqual(rep["category"], "MIXED")
        self.assertFalse(rep["infra"])
        self.assertEqual(rep["model"], "test/model")
        self.assertEqual(records[0]["category"], "MIXED")
        calls = read_calls(fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:5], ["run", "-m", "test/model", "--format", "json"])
        prompt = calls[0][5]
        case_dir = out / "cases" / "lbl__h03_r1__ref"
        blind = out / "blind" / hashlib.sha1(b"lbl__h03_r1__ref1").hexdigest()[:12]
        self.assertIn(J.H.P["h03"], prompt)
        self.assertIn(str((blind / "hidden").resolve()), prompt)
        self.assertIn(str((blind / "project").resolve()), prompt)
        self.assertIn("test_mod.T.test_never ... FAIL", prompt)
        self.assertNotIn(str(case_dir), prompt)
        self.assertNotIn("lbl__h03_r1__ref", prompt)
        self.assertNotIn("/foreign/root", prompt)
        self.assertNotIn("{SPEC}", prompt)
        self.assertFalse(blind.exists())  # the blind copy is deleted after the rep

    def test_existing_rep_is_not_rerun(self):
        self.make_case()
        fake = self.tmp / "fake"
        fake_opencode(fake, stdout_lines=events("BELIRSIZ — test — neden\n"))
        self.judge(fake, reps=1)
        fake_opencode(fake, stdout_lines=events("BELIRSIZ — test — neden\n"))
        self.judge(fake, reps=1)
        self.assertEqual(read_calls(fake), [])

    def test_nonzero_exit_or_empty_answer_is_infra(self):
        self.make_case()
        bad = self.tmp / "bad"
        fake_opencode(bad, stdout_lines=events("KOD_HATASI — k — k\n"), exit_code=3)
        records, out = self.judge(bad, reps=1)
        self.assertTrue(records[0]["infra"])
        self.assertEqual(records[0]["category"], "INFRA")
        rep = json.loads((out / "cases" / "lbl__h03_r1__ref" / "rep_1.json").read_text())
        self.assertTrue(rep["infra"])

    def test_nonzero_exit_keeps_the_last_twenty_stderr_lines(self):
        self.make_case()
        bad = self.tmp / "bad"
        stderr = "\n".join(f"err {i}" for i in range(25))
        fake_opencode(bad, stdout_lines=events("KOD_HATASI — k — k\n"), exit_code=3, stderr=stderr)
        records, out = self.judge(bad, reps=1)
        rep = json.loads((out / "cases" / "lbl__h03_r1__ref" / "rep_1.json").read_text())
        self.assertEqual(rep["error"].splitlines(), [f"err {i}" for i in range(5, 25)])
        self.assertTrue(records[0]["infra"])

    def test_reps_run_in_a_neutral_project_and_leave_no_copy(self):
        self.make_case()
        fake = self.tmp / "fake"
        fake.mkdir()
        script = fake / "opencode"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "here = os.path.dirname(os.path.abspath(__file__))\n"
            "with open(os.path.join(here, 'cwd.txt'), 'w') as f:\n"
            "    f.write(os.getcwd())\n"
            "print(json.dumps({'type': 'text', 'part': {'messageID': 'm',\n"
            "      'text': 'KOD_HATASI — k — k'}}))\n", encoding="utf-8")
        script.chmod(0o755)
        records, _out = self.judge(fake, reps=1)
        self.assertFalse(records[0]["infra"])
        cwd = Path((fake / "cwd.txt").read_text())
        self.assertEqual(cwd.name, "project")
        self.assertEqual(cwd.parent.parent.name, "blind")
        self.assertNotIn("lbl__", str(cwd))
        self.assertNotIn("__ref", str(cwd))
        self.assertFalse(cwd.parent.exists())

    def test_empty_answer_is_infra(self):
        self.make_case()
        empty = self.tmp / "empty"
        fake_opencode(empty, stdout_lines=[])
        records, _ = self.judge(empty, reps=1)
        self.assertTrue(records[0]["infra"])
        self.assertEqual(records[0]["category"], "INFRA")

    def test_parse_exception_writes_an_infra_rep(self):
        self.make_case()
        fake = self.tmp / "fake"
        fake_opencode(fake, stdout_lines=events("not json"))
        out = self.tmp / "out"
        env = {"JUDGE_LAB_OPENCODE": str(fake / "opencode")}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(J.run_oc, "parse",
                                  side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "bad")):
            records = J.judge(out, "test/model", reps=1)
        self.assertTrue(records[0]["infra"])
        self.assertEqual(records[0]["category"], "INFRA")
        rep = json.loads((out / "cases" / "lbl__h03_r1__ref" / "rep_1.json").read_text())
        self.assertTrue(rep["infra"])
        self.assertIn("UnicodeDecodeError", rep["error"])


class TestScore(TempDirTest):
    def make_case(self, cid, label, cats, infra=0):
        d = self.tmp / "out" / "cases" / cid
        write(d / "case.json", json.dumps({"case_id": cid, "task": "h03", "suite": "lbl/h03_r1",
                                           "variant": "ref", "label": label, "failing": []}))
        for i, cat in enumerate(cats, 1):
            write(d / f"rep_{i}.json", json.dumps({"answer": "x", "counts": {}, "category": cat,
                                                   "seconds": 0, "model": "m", "infra": False}))
        for i in range(infra):
            write(d / f"rep_x{i}.json", json.dumps({"answer": "", "counts": {},
                                                    "category": "INFRA", "seconds": 0,
                                                    "model": "m", "infra": True}))

    def test_metrics(self):
        self.make_case("c1", "KOD", ["KOD", "KOD", "TEST"], infra=1)
        self.make_case("c2", "TEST", ["TEST", "TEST"])
        self.make_case("c3", "KOD", ["TEST"])
        result = J.score(self.tmp / "out")
        self.assertEqual(result["cases"], {"KOD": 2, "TEST": 1})
        self.assertEqual(result["infra_reps"], 1)
        self.assertAlmostEqual(result["rep_accuracy"]["KOD"], 0.5)
        self.assertAlmostEqual(result["rep_accuracy"]["TEST"], 1.0)
        self.assertAlmostEqual(result["majority_accuracy"], 2 / 3)
        self.assertEqual(result["majority_denominator"], 3)
        self.assertEqual(result["ties"], 0)
        self.assertAlmostEqual(result["flip_rate"], 0.5)
        self.assertAlmostEqual(result["kod_judged_test"], 0.5)
        self.assertAlmostEqual(result["test_judged_kod"], 0.0)
        self.assertAlmostEqual(result["belirsiz_rate"], 0.0)
        self.assertAlmostEqual(result["kappa"], 0.4)
        self.assertEqual(json.loads((self.tmp / "out" / "score.json").read_text()), result)

    def test_zero_denominators_are_none(self):
        self.make_case("c1", "KOD", [])
        result = J.score(self.tmp / "out")
        self.assertIsNone(result["rep_accuracy"]["KOD"])
        self.assertIsNone(result["rep_accuracy"]["TEST"])
        self.assertIsNone(result["majority_accuracy"])
        self.assertEqual(result["majority_denominator"], 0)
        self.assertEqual(result["ties"], 0)
        self.assertIsNone(result["flip_rate"])
        self.assertIsNone(result["kod_judged_test"])
        self.assertIsNone(result["test_judged_kod"])
        self.assertIsNone(result["belirsiz_rate"])
        self.assertIsNone(result["kappa"])

    def test_kappa_is_none_when_expected_agreement_is_one(self):
        self.make_case("c1", "KOD", ["KOD"])
        self.assertIsNone(J.score(self.tmp / "out")["kappa"])

    def test_tie_majority_counts_as_wrong(self):
        self.make_case("c1", "KOD", ["KOD", "TEST"])
        result = J.score(self.tmp / "out")
        self.assertAlmostEqual(result["majority_accuracy"], 0.0)
        self.assertEqual(result["majority_denominator"], 1)
        self.assertEqual(result["ties"], 1)
        self.assertAlmostEqual(result["kappa"], 0.0)

    def test_tmp_case_dirs_are_never_scored(self):
        self.make_case("c1", "KOD", ["KOD"])
        stale = self.tmp / "out" / "cases" / "hidden.tmp"
        write(stale / "case.json", json.dumps({"case_id": "stale", "task": "h03", "suite": "l",
                                               "variant": "ref", "label": "TEST", "failing": []}))
        result = J.score(self.tmp / "out")
        self.assertEqual(result["cases"], {"KOD": 1, "TEST": 0})

    def test_missing_out_is_created(self):
        result = J.score(self.tmp / "does_not_exist")
        self.assertEqual(result["cases"], {"KOD": 0, "TEST": 0})
        self.assertTrue((self.tmp / "does_not_exist" / "score.json").exists())

    def test_corrupt_rep_counts_as_infra(self):
        self.make_case("c1", "KOD", ["KOD"])
        write(self.tmp / "out" / "cases" / "c1" / "rep_bad.json", "{not json")
        result = J.score(self.tmp / "out")
        self.assertEqual(result["infra_reps"], 1)
        self.assertAlmostEqual(result["rep_accuracy"]["KOD"], 1.0)


class TestCLI(TempDirTest):
    def test_unknown_subcommand_fails(self):
        p = subprocess.run([sys.executable, "-I", str(ROOT / "lab" / "judge_lab.py"), "nope"],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)

    def test_score_cli_writes_score_json(self):
        out = self.tmp / "out"
        write(out / "cases" / "c1" / "case.json",
              json.dumps({"case_id": "c1", "task": "h03", "suite": "l", "variant": "ref",
                          "label": "TEST", "failing": []}))
        write(out / "cases" / "c1" / "rep_1.json",
              json.dumps({"answer": "x", "counts": {}, "category": "TEST", "seconds": 0,
                          "model": "m", "infra": False}))
        p = subprocess.run([sys.executable, "-I", str(ROOT / "lab" / "judge_lab.py"), "score",
                            str(out)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((out / "score.json").exists())


if __name__ == "__main__":
    unittest.main()
