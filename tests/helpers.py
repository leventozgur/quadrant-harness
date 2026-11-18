"""Shared helpers for the hx tests. Stdlib only; the real `opencode` is never started and no network is used.

`fake_opencode` returns an environment dict whose PATH starts with the directory holding the fake
`opencode` script (it is NOT a context manager). Patch it in with
`unittest.mock.patch.dict(os.environ, env)` because `hx.run_role` builds its child environment from
`os.environ`. Every invocation of the fake appends its argv (without argv[0]) as one JSON line to
`<tmpdir>/calls.jsonl`; use `read_calls(tmpdir)` to inspect them.
"""
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# The fake binary: records argv, then replays the prepared stdout/stderr and exits with the given code.
_SCRIPT = """#!/usr/bin/env python3
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
time.sleep({sleep})
with open(os.path.join(here, "stdout.txt"), encoding="utf-8") as f:
    sys.stdout.write(f.read())
with open(os.path.join(here, "stderr.txt"), encoding="utf-8") as f:
    sys.stderr.write(f.read())
sys.stdout.flush()
sys.exit({code})
"""


def fake_opencode(tmpdir, stdout_lines=(), exit_code=0, stderr="", sleep=0):
    """Write an executable `opencode` script into tmpdir and return a PATH-prepended env dict.

    The script logs its argv to tmpdir/calls.jsonl, waits `sleep` seconds, prints every entry of
    `stdout_lines` on its own line, writes `stderr` to stderr and exits with `exit_code`.
    Calling this twice with the same tmpdir replaces the prepared output and resets calls.jsonl.
    """
    tmpdir = Path(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)
    script = tmpdir / "opencode"
    script.write_text(_SCRIPT.format(sleep=float(sleep), code=int(exit_code)), encoding="utf-8")
    script.chmod(0o755)
    (tmpdir / "stdout.txt").write_text("".join(line + "\n" for line in stdout_lines), encoding="utf-8")
    (tmpdir / "stderr.txt").write_text(stderr, encoding="utf-8")
    (tmpdir / "calls.jsonl").write_text("", encoding="utf-8")
    return {"PATH": str(tmpdir) + os.pathsep + os.environ.get("PATH", "")}


def read_calls(tmpdir):
    """Return the argv lists recorded by the fake `opencode` in tmpdir (argv[0] excluded)."""
    path = Path(tmpdir) / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout


@contextlib.contextmanager
def temp_repo():
    """Create a committed throwaway git repo, chdir into it, and remove it (and its task worktrees) on exit.

    The repo lives at <tempdir>/repo, so hx's default worktree path <repo>/../<repo>-wt/<task> stays
    inside the tempdir that is deleted afterwards. The real project's .git/hx is never touched.
    """
    old = os.getcwd()
    base = tempfile.mkdtemp(prefix="hx-tests-")
    repo = Path(base) / "repo"
    repo.mkdir()
    try:
        _git(repo, "init", "-q")
        for key, value in (("user.name", "hx tests"), ("user.email", "hx-tests@example.invalid"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            _git(repo, "config", key, value)
        (repo / "README.md").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-q", "-m", "seed")
        os.chdir(repo)
        yield repo
    finally:
        os.chdir(old)
        shutil.rmtree(base, ignore_errors=True)
