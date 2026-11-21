"""reap_targets / reap_orphans (HX-26): only OpenCode's own processes may be killed.

reap_targets is pure, so the decision is tested on (pid, ppid, args) rows. The process tests only touch
processes this test started itself (a fake `opencode` script plus its `sleep` child); no other process is
signalled.
"""
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import hx

WT = "/tmp/hx-wt/HX-1"
HIDDEN = "/tmp/hx-wt/HX-1/.git/hx/HX-1/hidden"

SERVE = (21075, 1, "/opt/homebrew/Cellar/opencode-v2/2.3.0/bin/opencode serve --service")
PTY = (21225, 21075, "/Users/u/.cache/opencode/bin/opencode-pty/0.5.2-x/opencode-pty daemon --runtime-dir /tmp/x")
RUN_SHELL = (67887, 21225, f"/bin/zsh -c cd {WT} && opencode run -m x --format json; wait")
RUN = (67893, 67887, f"opencode run -m opencode-go/deepseek --format json {WT}")
TEST_SHELL = (21300, 21225, f"/bin/zsh -c cd {WT} && npm test")
NODE = (21301, 21300, "node --test")
WORKER = (21302, 21301, "node /tmp/worker.js")


class IsOpencodeTest(unittest.TestCase):
    def test_plain_names_starting_with_opencode(self):
        self.assertTrue(hx.is_opencode("opencode"))
        self.assertTrue(hx.is_opencode("opencode serve --service"))
        self.assertTrue(hx.is_opencode("opencode-pty daemon --runtime-dir /tmp/x"))

    def test_absolute_paths_use_the_basename(self):
        self.assertTrue(hx.is_opencode("/opt/homebrew/Cellar/opencode-v2/2.3.0/bin/opencode"))
        self.assertTrue(hx.is_opencode("/Users/u/.cache/opencode/bin/opencode-pty/0.5.2-x/opencode-pty run"))

    def test_other_programs_and_empty_args(self):
        self.assertFalse(hx.is_opencode(""))
        self.assertFalse(hx.is_opencode("   "))
        self.assertFalse(hx.is_opencode("/bin/zsh -c opencode run"))
        self.assertFalse(hx.is_opencode("python3 /tmp/opencode_probe.py"))

    def test_a_directory_named_opencode_is_not_enough(self):
        self.assertFalse(hx.is_opencode("/Users/u/.cache/opencode/bin/runner daemon"))


class ReapTargetsTest(unittest.TestCase):
    def test_keyed_process_under_opencode_is_a_target(self):
        self.assertEqual({RUN[0]}, hx.reap_targets([SERVE, PTY, RUN], [WT]))

    def test_keyed_shell_and_its_descendants_are_targets(self):
        rows = [SERVE, PTY, TEST_SHELL, NODE, WORKER]
        self.assertEqual({TEST_SHELL[0], NODE[0], WORKER[0]}, hx.reap_targets(rows, [WT]))

    def test_user_processes_naming_the_path_are_kept(self):
        rows = [
            (100, 1, f"/bin/zsh -c tail -f {WT}/x.log"),
            (101, 1, f"tail -f {WT}/x.log"),
            (102, 1, f"/Applications/Editor.app/Contents/MacOS/Editor {WT}"),
            (103, 500, f"python3 /tmp/probe.py --worktree {WT}"),
            (104, 1, f"/bin/zsh -c cd {HIDDEN} && ls"),
        ]
        self.assertEqual(set(), hx.reap_targets(rows, [WT, HIDDEN]))

    def test_contextual_processes_without_a_path_are_kept(self):
        rows = [SERVE, PTY, (21300, 21225, "/bin/zsh -c npm test"), NODE]
        self.assertEqual(set(), hx.reap_targets(rows, [WT, HIDDEN]))

    def test_user_shell_is_kept_although_an_unrelated_opencode_process_exists(self):
        rows = [SERVE, PTY, (30000, 1, f"/bin/zsh -c tail -f {WT}/out"), TEST_SHELL, NODE]
        self.assertEqual({TEST_SHELL[0], NODE[0]}, hx.reap_targets(rows, [WT]))

    def test_protect_is_never_a_target(self):
        rows = [SERVE, PTY, RUN_SHELL, RUN]
        self.assertEqual(set(), hx.reap_targets(rows, [WT], protect={67887, 67893}))

    def test_hidden_dir_is_matched_too(self):
        rows = [SERVE, PTY, (40000, 21225, f"/bin/zsh -c pytest {HIDDEN}")]
        self.assertEqual({40000}, hx.reap_targets(rows, [WT, HIDDEN]))

    def test_no_keys_targets_nothing(self):
        rows = [SERVE, PTY, RUN, TEST_SHELL, NODE]
        self.assertEqual(set(), hx.reap_targets(rows, []))

    def test_ppid_cycle_terminates(self):
        rows = [(5, 6, f"/bin/zsh -c {WT}"), (6, 5, "/bin/zsh -c x")]
        self.assertEqual(set(), hx.reap_targets(rows, [WT]))

    def test_opencode_that_names_the_path_is_a_target_despite_ppid_1(self):
        self.assertEqual({900}, hx.reap_targets([(900, 1, f"opencode serve --dir {WT}")], [WT]))


class FakeOS:
    """Stands in for hx.os so that no signal reaches a real process."""

    path = os.path

    def __init__(self, pid=700, lookup=()):
        self.pid = pid
        self.lookup = set(lookup)
        self.killed = []

    def getpid(self):
        return self.pid

    def kill(self, pid, sig):
        if pid in self.lookup:
            raise ProcessLookupError(pid)
        self.killed.append((pid, sig))


def ps_text(rows):
    return "".join(f"  {pid}   {ppid} {args}\n" for pid, ppid, args in rows)


PS_ROWS = [SERVE, PTY, TEST_SHELL, NODE, WORKER, RUN_SHELL, RUN, (100, 1, f"tail -f {WT}/x.log")]


class ReapOrphansTest(unittest.TestCase):
    def reap(self, rows, paths, lookup=()):
        fake = FakeOS(lookup=lookup)
        ps_rows = list(rows) + [(700, 701, "python3 -m unittest"), (701, 1, "/bin/zsh -c tests")]
        fake_sh = lambda *a, **k: SimpleNamespace(stdout=ps_text(ps_rows))
        with mock.patch.object(hx, "os", fake), mock.patch.object(hx, "sh", fake_sh), \
                mock.patch.object(hx.time, "sleep", lambda *_: None):
            count = hx.reap_orphans(list(paths), grace=0)
        return count, [pid for pid, _ in fake.killed], fake.killed

    def test_only_opencode_targets_and_their_descendants_are_signalled(self):
        count, pids, killed = self.reap(PS_ROWS, [WT])
        expected = {TEST_SHELL[0], NODE[0], WORKER[0], RUN[0], RUN_SHELL[0]}
        self.assertEqual(expected, set(pids))
        self.assertEqual(len(set(pids)), count)
        self.assertNotIn(100, pids)
        self.assertIn((TEST_SHELL[0], 15), killed)
        self.assertIn((TEST_SHELL[0], 9), killed)

    def test_hx_and_its_ancestors_are_never_signalled(self):
        rows = PS_ROWS + [(700, 701, f"/bin/zsh -c cd {WT} && python3 -m unittest")]
        count, pids, _ = self.reap(rows, [WT])
        self.assertNotIn(700, pids)
        self.assertNotIn(701, pids)
        self.assertEqual({TEST_SHELL[0], NODE[0], WORKER[0], RUN[0], RUN_SHELL[0]}, set(pids))
        self.assertEqual(5, count)

    def test_no_match_signals_nothing(self):
        count, pids, killed = self.reap(PS_ROWS, ["/nowhere/else"])
        self.assertEqual(0, count)
        self.assertEqual([], pids)
        self.assertEqual([], killed)

    def test_a_vanished_target_does_not_break_the_sweep(self):
        count, pids, killed = self.reap(PS_ROWS, [WT], lookup={NODE[0]})
        self.assertNotIn((NODE[0], 15), killed)
        self.assertIn((WORKER[0], 15), killed)
        self.assertEqual(5, count)
        self.assertEqual({TEST_SHELL[0], WORKER[0], RUN[0], RUN_SHELL[0]}, set(pids))


class IsOpenCodeTest(unittest.TestCase):
    def test_real_ps_lines_of_the_opencode_service_and_pty_daemon(self):
        # copied from `ps -Ao pid=,ppid=,args=` on the maintainer's Mac (OpenCode v2.3.0), user paths kept as-is
        self.assertTrue(hx.is_opencode("/opt/homebrew/Cellar/opencode-v2/2.3.0/bin/opencode serve --service"))
        self.assertTrue(hx.is_opencode("/Users/leventozgur/.cache/opencode/bin/opencode-pty/0.5.2-ed3adb8c7531fef5/"
                                       "opencode-pty daemon --runtime-dir /Users/leventozgur/.local/state/opencode/pty"))

    def test_native_binary_not_node_or_bun_and_lookalikes_are_not_matched(self):
        self.assertFalse(hx.is_opencode("node /x/opencode-thing.js"))
        self.assertFalse(hx.is_opencode("bun run /x/opencode.ts"))
        self.assertFalse(hx.is_opencode("tail -f /x/opencode.log"))
        self.assertFalse(hx.is_opencode("/usr/bin/tail /opencode.log"))
        self.assertFalse(hx.is_opencode(""))

    def test_executable_under_a_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "Jane Doe" / ".cache" / "opencode-pty"
            exe.parent.mkdir(parents=True)
            exe.write_text("#!/bin/sh\n")
            self.assertTrue(hx.is_opencode(f"{exe} daemon --name x"))
            self.assertFalse(hx.is_opencode(f"{Path(d) / 'Jane Doe' / 'missing'} daemon"))


class InitOrphanTest(unittest.TestCase):
    NOW = 10_000.0

    def run_with(self, ps_text_out, lsof_out, rows, roots, since):
        def fake_sh(cmd, *a, **k):
            return SimpleNamespace(stdout=lsof_out if cmd[0] == "lsof" else ps_text_out)
        with mock.patch.object(hx, "sh", fake_sh):
            return hx.init_orphans(rows, roots, since, now=self.NOW)

    def test_etime_seconds(self):
        self.assertEqual(5, hx.etime_seconds("00:05"))
        self.assertEqual(3725, hx.etime_seconds("1:02:05"))
        self.assertEqual(86400 + 3725, hx.etime_seconds("1-01:02:05"))
        self.assertIsNone(hx.etime_seconds("soon"))

    def test_without_since_nothing_is_selected(self):
        self.assertEqual(set(), hx.init_orphans([(5, 1, f"sleep {WT}")], [WT], None))

    def test_young_init_orphan_with_cwd_in_root_is_selected_old_one_is_not(self):
        ps_out = "  60     1 00:03\n  61     1 01:00:00\n  62   900 00:01\n"
        lsof_out = f"p60\nn{WT}/sub\np61\nn{WT}\n"
        got = self.run_with(ps_out, lsof_out, [], [WT], since=self.NOW - 30)
        self.assertEqual({60}, got)  # 61 is older than `since`, 62 has a live parent

    def test_cwd_elsewhere_is_kept_unless_the_path_is_named(self):
        ps_out = "  60     1 00:03\n  63     1 00:03\n"
        lsof_out = "p60\nn/Users/x/other\np63\nn/Users/x/other\n"
        rows = [(63, 1, f"python3 job.py --wt {WT}")]
        self.assertEqual({63}, self.run_with(ps_out, lsof_out, rows, [WT], since=self.NOW - 30))

    def test_first_call_marker_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = {"state": Path(d)}
            self.assertIsNone(hx.first_call_at(p))
            hx.mark_first_call(p)
            t = hx.first_call_at(p)
            self.assertIsNotNone(t)
            hx.mark_first_call(p)  # written once
            self.assertEqual(t, hx.first_call_at(p))


def alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def wait_for(predicate, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class RealProcessTest(unittest.TestCase):
    """The fake `opencode` and the `sleep` under it are started by this test only.

    The fake opencode is a bash process whose argv[0] is literally an `opencode...` path (`exec -a`), not
    `python3 /tmp/.../opencode`, so `ps` reports it as an OpenCode process in any shell. Its command line also
    names the key path, and the `sleep` it starts is its child.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-reap-"))
        self.key = str(self.tmp / "wt")
        (self.tmp / "wt").mkdir()
        self.argv0 = str(self.tmp / "opencode-hx")
        self.pidfile = self.tmp / "child.pid"
        self.procs = []
        self.popen = []
        self.addCleanup(self._stop)

    def _stop(self):
        for pid in list(self.procs):
            try:
                os.kill(pid, 9)
            except (ProcessLookupError, PermissionError):
                pass
        for proc in self.popen:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self):
        inner = 'sleep 30 & echo $! > "$1"; wait'  # $0 is the key (argv), $1 the pidfile
        outer = (f'exec -a {shlex.quote(self.argv0)} /bin/bash -c {shlex.quote(inner)} '
                 f'{shlex.quote(self.key)} {shlex.quote(str(self.pidfile))}')
        proc = subprocess.Popen(["/bin/bash", "-c", outer], cwd=str(self.tmp),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.popen.append(proc)
        self.procs.append(proc.pid)
        self.assertTrue(wait_for(self.pidfile.exists))
        child = int(self.pidfile.read_text())
        self.procs.append(child)
        return proc, child

    def test_the_fake_opencode_tree_is_killed(self):
        parent, child = self.start()
        self.assertTrue(alive(child))
        count = hx.reap_orphans([self.key], grace=0.2)
        self.assertGreaterEqual(count, 2)
        self.assertIsNotNone(parent.wait(timeout=5))
        self.assertTrue(wait_for(lambda: not alive(child)))

    def orphan(self, cwd):
        """A detached `sleep` handed to init: its parent bash exits right after starting it."""
        pidfile = self.tmp / f"orphan-{len(self.procs)}.pid"
        subprocess.run(["/bin/bash", "-c", 'sleep 40 & echo $! > "$1"', "x", str(pidfile)], cwd=str(cwd), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(wait_for(pidfile.exists))
        pid = int(pidfile.read_text())
        self.procs.append(pid)

        def ppid():
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout
            return int(out.strip() or 0)
        self.assertTrue(wait_for(lambda: ppid() == 1))
        return pid

    def test_an_init_orphan_started_after_the_first_call_with_cwd_in_the_worktree_is_killed(self):
        since = time.time() - 1
        pid = self.orphan(self.tmp / "wt")
        self.assertTrue(alive(pid))
        self.assertGreaterEqual(hx.reap_orphans([self.key], grace=0.2, since=since), 1)
        self.assertTrue(wait_for(lambda: not alive(pid)))

    def test_a_nohup_style_process_started_before_the_call_survives(self):
        pid = self.orphan(self.tmp / "wt")
        time.sleep(3.2)  # ps etime has 1 s resolution
        since = time.time()
        self.assertEqual(0, hx.reap_orphans([self.key], grace=0.2, since=since))
        self.assertTrue(alive(pid))

    def test_an_init_orphan_elsewhere_survives_and_without_since_nothing_is_selected(self):
        since = time.time() - 1
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        other = self.orphan(elsewhere)
        inside = self.orphan(self.tmp / "wt")
        self.assertEqual(0, hx.reap_orphans([self.key], grace=0.2))  # no since: init orphans are not selected
        self.assertTrue(alive(inside))
        self.assertGreaterEqual(hx.reap_orphans([self.key], grace=0.2, since=since), 1)
        self.assertTrue(wait_for(lambda: not alive(inside)))
        self.assertTrue(alive(other))

    def test_an_opencode_tree_is_kept_when_the_path_is_not_named(self):
        parent, child = self.start()
        count = hx.reap_orphans([str(self.tmp / "other-worktree")], grace=0.2)
        self.assertEqual(0, count)
        self.assertIsNone(parent.poll())
        self.assertTrue(alive(child))


if __name__ == "__main__":
    unittest.main()
