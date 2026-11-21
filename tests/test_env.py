"""HX-27: secret-looking environment variables never reach model processes or gate commands.

Only fake variables are used here (values such as "hx-fake-token-value"); the real environment is never read.
"""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import hx
from tests.helpers import temp_repo

SECRETS = {
    "HX_FAKE_TOKEN": "hx-fake-token-value",
    "hx_fake_SECRET": "hx-fake-secret-value",
    "HX_FAKE_PASSWORD": "hx-fake-password-value",
    "HX_FAKE_PASSWD": "hx-fake-passwd-value",
    "HX_FAKE_PASSPHRASE": "hx-fake-passphrase-value",
    "HX_FAKE_API_KEY": "hx-fake-api-key-value",
    "HX_FAKE_APIKEY": "hx-fake-apikey-value",
    "HX_FAKE_PRIVATE_KEY": "hx-fake-private-key-value",
    "HX_FAKE_CREDENTIAL": "hx-fake-credential-value",
    "HX_FAKE_ACCESS_KEY": "hx-fake-access-key-value",
    "HX_FAKE_AUTHORIZATION": "hx-fake-auth-value",
    "HX_FAKE_COOKIE": "hx-fake-cookie-value",
    "HX_FAKE_SESSION_KEY": "hx-fake-session-key-value",
    "AWS_FAKE_KEY": "hx-fake-aws-value",
    "GITHUB_FAKE": "hx-fake-github-value",
    "GH_FAKE": "hx-fake-gh-value",
    "AZURE_FAKE": "hx-fake-azure-value",
    "GOOGLE_FAKE": "hx-fake-google-value",
    "GCP_FAKE": "hx-fake-gcp-value",
    "OPENAI_FAKE": "hx-fake-openai-value",
    "ANTHROPIC_FAKE": "hx-fake-anthropic-value",
    "DOCKER_AUTH_CONFIG": "hx-fake-docker-auth-value",
    "npm_config__auth": "hx-fake-npm-auth-value",
    "NPM_TOKEN": "hx-fake-npm-token-value",
    "DOCKER_PASSWORD": "hx-fake-docker-password-value",
    "HX_FAKE_DATABASE_URL": "hx-fake-db-value",
    "HX_FAKE_CONNECTION_STRING": "hx-fake-conn-value",
}

KEPT = {
    "PATH": "hx-fake-path-value",
    "HOME": "hx-fake-home-value",
    "USER": "hx-fake-user-value",
    "LOGNAME": "hx-fake-logname-value",
    "SHELL": "hx-fake-shell-value",
    "TMPDIR": "hx-fake-tmpdir-value",
    "LANG": "hx-fake-lang-value",
    "LC_ALL": "hx-fake-lc-all-value",
    "LC_CTYPE": "hx-fake-lc-ctype-value",
    "TERM": "hx-fake-term-value",
    "PWD": "hx-fake-pwd-value",
    "OPENCODE_CONFIG_CONTENT": "hx-fake-opencode-config",
    "OPENCODE_API_KEY": "hx-fake-opencode-key",
    "HX_FAKE_PLAIN": "hx-fake-plain-value",
    "DOCKER_HOST": "hx-fake-docker-host",
    "npm_config_registry": "hx-fake-registry",
    "npm_config_cache": "hx-fake-npm-cache",
    "NPM_CONFIG_USERCONFIG": "hx-fake-npmrc-path",
    "DOCKER_CONFIG": "hx-fake-docker-config-dir",
    "DOCKER_BUILDKIT": "1",
    "SSH_AUTH_SOCK": "hx-fake-ssh-sock",  # socket path needed by git over ssh in tests; not a secret value
}

SPEC_TEXT = """# Görev
metin

## Kapsam
hx.py
"""

PASS_CMD = "python3 -c \"pass\""


class NS:
    """Minimal argparse.Namespace stand-in for the cmd_* handlers."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def env_dropped_names(base):
    return sorted(set(base) - set(hx.safe_env(base)))


class SafeEnvTest(unittest.TestCase):
    def test_secret_substrings_are_dropped_case_insensitively(self):
        self.assertEqual({}, hx.safe_env(SECRETS))

    def test_plain_names_survive(self):
        self.assertEqual(KEPT["HX_FAKE_PLAIN"], hx.safe_env({"HX_FAKE_PLAIN": "hx-fake-plain-value"})["HX_FAKE_PLAIN"])

    def test_exceptions_are_never_dropped(self):
        self.assertEqual(KEPT, hx.safe_env(KEPT))
        self.assertEqual([], env_dropped_names(KEPT))

    def test_keep_uses_exact_names(self):
        base = {"HX_FAKE_TOKEN": "hx-fake-token-value", "HX_FAKE_OTHER_TOKEN": "hx-fake-other-value"}
        self.assertEqual({"HX_FAKE_TOKEN": "hx-fake-token-value"}, hx.safe_env(base, keep=["HX_FAKE_TOKEN"]))
        self.assertEqual({}, hx.safe_env(base, keep=["HX_FAKE"]))
        self.assertEqual({"HX_FAKE_TOKEN": "hx-fake-token-value"},
                         hx.safe_env(base, keep=["HX_FAKE_TOKEN", "HX_FAKE_TOKEN"]))

    def test_safe_env_returns_a_copy(self):
        base = {"HX_FAKE_PLAIN": "hx-fake-plain-value"}
        out = hx.safe_env(base)
        out["HX_FAKE_NEW"] = "hx-fake-new-value"
        self.assertNotIn("HX_FAKE_NEW", base)


class RoleEnvTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-E1", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-E1")
        self.spec = self.repo.parent / "spec.md"
        self.spec.write_text(SPEC_TEXT, encoding="utf-8")

    def run_with_capture(self, patch_extra, pass_through=None):
        seen = {}

        def fake_run_streaming(args, cwd, env, limit, stall_limit):
            seen.update(env)
            return "", "", False, False

        cfg = mock.patch.dict(hx.CFG, {"env_passthrough": pass_through}) if pass_through is not None \
            else contextlib.nullcontext()
        with mock.patch.dict(os.environ, patch_extra), cfg, \
                mock.patch.object(hx, "run_streaming", side_effect=fake_run_streaming):
            hx.run_role("worker", "HX-E1", str(self.spec), reap=False)
        return seen

    def test_run_role_spawns_opencode_without_secrets(self):
        env = dict(SECRETS, OPENCODE_CONFIG_CONTENT="hx-fake-opencode-config",
                   HX_FAKE_PLAIN=KEPT["HX_FAKE_PLAIN"])
        seen = self.run_with_capture(env)

        self.assertEqual(str(self.p["worktree"]), seen["PWD"])
        for name in SECRETS:
            self.assertNotIn(name, seen)
        self.assertEqual("hx-fake-opencode-config", seen["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(KEPT["HX_FAKE_PLAIN"], seen["HX_FAKE_PLAIN"])
        self.assertIn("PATH", seen)

        metrics = (self.repo / ".git" / "hx" / "metrics.jsonl").read_text(encoding="utf-8")
        call = [json.loads(l) for l in metrics.splitlines() if json.loads(l).get("event") == "call"][-1]
        self.assertTrue(set(SECRETS) <= set(call["env_dropped"]))
        self.assertEqual(sorted(call["env_dropped"]), call["env_dropped"])
        for value in SECRETS.values():
            self.assertNotIn(value, metrics)

    def test_config_env_passthrough_keeps_a_named_secret(self):
        seen = self.run_with_capture({"HX_FAKE_TOKEN": "hx-fake-token-value"},
                                     pass_through=["HX_FAKE_TOKEN"])
        self.assertEqual("hx-fake-token-value", seen["HX_FAKE_TOKEN"])


class GateEnvTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.repo = self.stack.enter_context(temp_repo())
        with contextlib.redirect_stdout(io.StringIO()):
            hx.cmd_new(NS(task="HX-E2", base=None, branch=None, setup=None))
        self.p = hx.task_paths("HX-E2")
        self.wt = self.p["worktree"]

    def gate(self, **kwargs):
        args = dict(task="HX-E2", test=PASS_CMD, hidden_cmd=None, allow="**", protect=None,
                    retry=0, gate_timeout=120, no_tests=False)
        args.update(kwargs)
        buf = io.StringIO()
        code = None
        with contextlib.redirect_stdout(buf):
            try:
                hx.cmd_gate(NS(**args))
            except SystemExit as e:
                code = e.code
        payload = None
        for line in buf.getvalue().splitlines():
            if line.startswith("{"):
                payload = json.loads(line)
                break
        return code, payload, buf.getvalue()

    def test_gate_command_does_not_see_secrets(self):
        cmd = ("python3 -c \"import os,pathlib; "
               "pathlib.Path('seen.txt').write_text(os.environ.get('HX_FAKE_TOKEN','MISSING') + '|' + "
               "os.environ.get('OPENCODE_CONFIG_CONTENT','MISSING') + '|' + "
               "os.environ.get('PYTHONPATH','MISSING'))\"")
        env = dict(SECRETS, OPENCODE_CONFIG_CONTENT="hx-fake-opencode-config")
        with mock.patch.dict(os.environ, env):
            code, payload, out = self.gate(test=cmd)
        self.assertEqual(0, code)
        seen = (self.wt / "seen.txt").read_text(encoding="utf-8").split("|")
        self.assertEqual("MISSING", seen[0])
        self.assertEqual("hx-fake-opencode-config", seen[1])
        self.assertTrue(seen[2].startswith(str(self.wt)))

        self.assertTrue(set(SECRETS) <= set(payload["env_dropped"]))
        self.assertEqual(sorted(payload["env_dropped"]), payload["env_dropped"])
        saved = json.loads((self.p["state"] / "last_gate.json").read_text())
        self.assertTrue(set(SECRETS) <= set(saved["env_dropped"]))
        self.assertIn("env_dropped", json.loads((self.p["state"] / "last_gate.txt").read_text()))
        for text in (out, (self.p["state"] / "tests.log").read_text(),
                     (self.p["state"] / "last_gate.txt").read_text(),
                     (self.repo / ".git" / "hx" / "metrics.jsonl").read_text()):
            for value in SECRETS.values():
                self.assertNotIn(value, text)

    def test_gate_without_tests_still_reports_dropped_names(self):
        env = dict(SECRETS, OPENCODE_CONFIG_CONTENT="hx-fake-opencode-config")
        with mock.patch.dict(os.environ, env):
            code, payload, _ = self.gate(no_tests=True)
        self.assertEqual(0, code)
        self.assertTrue(set(SECRETS) <= set(payload["env_dropped"]))


if __name__ == "__main__":
    unittest.main()
