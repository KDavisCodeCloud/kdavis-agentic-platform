"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Isolated terraform fmt/validate runner (G16 gate, Kelvin 2026-11-17).

Why a separate service: `terraform validate` needs `terraform init`, which
downloads and EXECUTES the provider binaries a customer's .tf declares. The
API process holds every tenant's decrypted credentials, so customer HCL is
never initialised there. This service holds no database access and no
customer credentials -- only its own bearer token.

Hardening:
  - Providers only from registry.terraform.io/hashicorp/* (CLI config
    below); any other provider source fails init, and so fails the gate.
  - -backend=false: no remote state, no backend credentials.
  - Every run in a fresh temp dir, deleted afterwards; hard timeouts.
  - Request size and path limits; paths must be relative, no '..'.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

TERRAFORM_BIN = os.environ.get("TERRAFORM_BIN", "terraform")
PLUGIN_CACHE_DIR = os.environ.get("TF_PLUGIN_CACHE_DIR", "/var/cache/terraform-plugins")
STEP_TIMEOUT_SECONDS = int(os.environ.get("TERRAFORM_STEP_TIMEOUT", "180"))
MAX_FILES = 200
MAX_TOTAL_BYTES = 2_000_000
_FMT_NEEDS_FORMATTING = 3  # `terraform fmt -check` exit code for "parses, but not canonical"; parse errors exit 2

CLI_CONFIG = """
plugin_cache_dir = "%s"
provider_installation {
  direct {
    include = ["registry.terraform.io/hashicorp/*"]
  }
}
"""


class RequestError(ValueError):
    pass


@dataclass
class CheckResult:
    ok: bool
    stage: str                      # "fmt" | "init" | "validate" | "done"
    reason: str = ""
    fmt_diff: str = ""
    diagnostics: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_request(files: dict, workdir: str, edited_path: str) -> None:
    if not isinstance(files, dict) or not files:
        raise RequestError("files must be a non-empty {path: content} map")
    if len(files) > MAX_FILES:
        raise RequestError(f"at most {MAX_FILES} files")
    if sum(len(str(v).encode()) for v in files.values()) > MAX_TOTAL_BYTES:
        raise RequestError(f"at most {MAX_TOTAL_BYTES} bytes in total")
    for path in [*files, workdir or ".", edited_path]:
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts:
            raise RequestError(f"paths must be relative without '..': {path!r}")
    if edited_path not in files:
        raise RequestError("edited_path must be one of files")


def check(files: dict, workdir: str, edited_path: str, original: str, run=subprocess.run) -> CheckResult:
    """fmt (only blamed when the edit made it worse), init, validate."""
    validate_request(files, workdir, edited_path)
    root = Path(tempfile.mkdtemp(prefix="tfcheck-"))
    try:
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        cli_config = root / ".terraformrc"
        cli_config.write_text(CLI_CONFIG % PLUGIN_CACHE_DIR)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root),
               "TF_CLI_CONFIG_FILE": str(cli_config), "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1"}
        module = root / (workdir or ".")

        # fmt: the edited file must be canonically formatted -- unless the
        # original wasn't either, in which case the edit isn't to blame.
        fmt = _tf(run, ["fmt", "-check", "-diff", "-no-color", str(root / edited_path)], root, env)
        if fmt.returncode not in (0, _FMT_NEEDS_FORMATTING):
            return CheckResult(False, "fmt", "the edited file doesn't parse as Terraform: "
                               + _tail(fmt.stderr or fmt.stdout))
        if fmt.returncode == _FMT_NEEDS_FORMATTING:
            original_copy = root / ".original.tf"
            original_copy.write_text(original)
            was_clean = _tf(run, ["fmt", "-check", "-no-color", str(original_copy)], root, env).returncode == 0
            original_copy.unlink()
            if was_clean:
                return CheckResult(False, "fmt", "terraform fmt: the proposed change isn't canonically formatted",
                                   fmt_diff=fmt.stdout[-8000:])

        init = _tf(run, ["init", "-backend=false", "-input=false", "-no-color"], module, env)
        if init.returncode != 0:
            return CheckResult(False, "init", "terraform init failed: " + _tail(init.stderr or init.stdout))

        validate = _tf(run, ["validate", "-json", "-no-color"], module, env)
        try:
            report = json.loads(validate.stdout or "{}")
        except json.JSONDecodeError:
            report = {}
        diagnostics = [
            {"severity": d.get("severity"), "summary": d.get("summary"), "detail": d.get("detail"),
             "range": d.get("range")}
            for d in report.get("diagnostics", [])
        ]
        if validate.returncode != 0 or not report.get("valid", False):
            errors = [d["summary"] for d in diagnostics if d["severity"] == "error"]
            return CheckResult(False, "validate", "terraform validate: " + ("; ".join(errors[:5]) or
                               _tail(validate.stderr) or "invalid configuration"), diagnostics=diagnostics)
        return CheckResult(True, "done", diagnostics=diagnostics)
    except subprocess.TimeoutExpired as exc:
        return CheckResult(False, "timeout", f"terraform {' '.join(exc.cmd[1:2])} timed out")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _tf(run, args, cwd, env):
    return run([TERRAFORM_BIN, *args], cwd=cwd, env=env, capture_output=True, text=True,
               timeout=STEP_TIMEOUT_SECONDS)


def _tail(text: str, limit: int = 600) -> str:
    return (text or "").strip()[-limit:]
