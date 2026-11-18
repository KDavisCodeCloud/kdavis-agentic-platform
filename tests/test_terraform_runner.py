"""
G16 gate: the isolated terraform runner (services/terraform_runner).

Unit tests drive runner.check() with a fake subprocess.run so CI needs no
terraform binary or network. Verified against real terraform 1.14.8 locally
on 2026-11-17: a valid edit passes; the lab's JSON-in-.tf fails at fmt with
"Argument or block definition required"; an unknown argument fails validate;
a non-hashicorp provider fails init.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_DIR = Path(__file__).resolve().parents[1] / "services" / "terraform_runner"
sys.path.insert(0, str(_DIR))
_spec = importlib.util.spec_from_file_location("tf_runner", _DIR / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

GOOD = 'resource "null_resource" "web" {}\n'


class FakeTerraform:
    """Answers by subcommand; records every call and the CLI config it saw."""

    def __init__(self, fmt=0, fmt_original=0, init=0, validate=(0, '{"valid": true, "diagnostics": []}'),
                 timeout_on=None):
        self.answers = {"fmt": fmt, "init": init, "validate": validate}
        self.fmt_original = fmt_original
        self.timeout_on = timeout_on
        self.calls, self.cli_config = [], None

    def __call__(self, cmd, cwd, env, capture_output, text, timeout):
        sub = cmd[1]
        self.calls.append(sub)
        self.cli_config = Path(env["TF_CLI_CONFIG_FILE"]).read_text()
        assert "AWS_SECRET_ACCESS_KEY" not in env and "DATABASE_URL" not in env
        if sub == self.timeout_on:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if sub == "fmt" and cmd[-1].endswith(".original.tf"):
            return SimpleNamespace(returncode=self.fmt_original, stdout="", stderr="")
        answer = self.answers[sub]
        code, out = answer if isinstance(answer, tuple) else (answer, "")
        return SimpleNamespace(returncode=code, stdout=out, stderr="Error: boom" if code else "")


def _check(fake, files=None, original=GOOD):
    return runner.check(files or {"infra/main.tf": GOOD}, "infra", "infra/main.tf", original, run=fake)


def test_valid_edit_passes_all_three_stages():
    fake = FakeTerraform()
    result = _check(fake)
    assert result.ok and result.stage == "done"
    assert fake.calls == ["fmt", "init", "validate"]


def test_providers_restricted_to_hashicorp_namespace():
    fake = FakeTerraform()
    _check(fake)
    assert 'include = ["registry.terraform.io/hashicorp/*"]' in fake.cli_config


def test_parse_error_fails_at_fmt_and_never_inits():
    fake = FakeTerraform(fmt=2)
    result = _check(fake)
    assert not result.ok and result.stage == "fmt" and "doesn't parse" in result.reason
    assert fake.calls == ["fmt"]


def test_unformatted_edit_of_a_clean_file_fails():
    result = _check(FakeTerraform(fmt=3, fmt_original=0))
    assert not result.ok and "canonically formatted" in result.reason


def test_file_that_was_already_unformatted_is_not_blamed_on_the_edit():
    fake = FakeTerraform(fmt=3, fmt_original=3)
    assert _check(fake).ok
    assert fake.calls == ["fmt", "fmt", "init", "validate"]


def test_init_failure_fails_the_gate():
    result = _check(FakeTerraform(init=1))
    assert not result.ok and result.stage == "init"


def test_validate_errors_are_reported():
    report = '{"valid": false, "diagnostics": [{"severity": "error", "summary": "Unsupported argument"}]}'
    result = _check(FakeTerraform(validate=(1, report)))
    assert not result.ok and result.stage == "validate" and "Unsupported argument" in result.reason


def test_timeout_fails_closed():
    result = _check(FakeTerraform(timeout_on="init"))
    assert not result.ok and result.stage == "timeout"


@pytest.mark.parametrize("files,edited", [
    ({"/etc/passwd": "x"}, "/etc/passwd"),
    ({"../escape.tf": "x"}, "../escape.tf"),
    ({"a.tf": "x"}, "b.tf"),
    ({}, "a.tf"),
])
def test_bad_requests_are_refused(files, edited):
    with pytest.raises(runner.RequestError):
        runner.check(files, ".", edited, "", run=FakeTerraform())


def test_temp_dir_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "work"))
    (tmp_path / "work").mkdir()
    _check(FakeTerraform())
    assert not (tmp_path / "work").exists()


def test_http_endpoint_requires_the_bearer_token(monkeypatch):
    from fastapi.testclient import TestClient
    app_spec = importlib.util.spec_from_file_location("tf_runner_app", _DIR / "app.py")
    app_mod = importlib.util.module_from_spec(app_spec)
    app_spec.loader.exec_module(app_mod)
    client = TestClient(app_mod.app)
    body = {"files": {"a.tf": GOOD}, "edited_path": "a.tf"}

    monkeypatch.delenv("TERRAFORM_RUNNER_TOKEN", raising=False)
    assert client.post("/check", json=body).status_code == 503  # never runs unauthenticated
    monkeypatch.setenv("TERRAFORM_RUNNER_TOKEN", "t0ken")
    assert client.post("/check", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    monkeypatch.setattr(app_mod, "check", lambda *a: runner.CheckResult(True, "done"))
    ok = client.post("/check", json=body, headers={"Authorization": "Bearer t0ken"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
