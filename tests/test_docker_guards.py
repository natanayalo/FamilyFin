"""Operational guarantees survive -O; lab assertions can never silently vanish."""
import ast
import contextlib
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/docker"


def runtime(arguments, response=None, optimize=0):
    source = (DEPLOY / "runtime.py").read_text()
    with patch.object(sys, "argv", ["runtime.py", *arguments]), \
            patch("urllib.request.urlopen", return_value=contextlib.nullcontext(response)):
        exec(compile(source, str(DEPLOY / "runtime.py"), "exec", optimize=optimize), {"__name__": "__main__"})  # noqa: S102 -- Compile reviewed local source with real optimization flags.


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("failure", ["status", "cache", "body"])
def test_health_rejects_invalid_responses_even_when_optimized(optimize, failure):
    response = SimpleNamespace(status=200, headers={"Cache-Control": "private, no-store"},
                               read=lambda _: b'{"data":{"status":"ok"}}')
    if failure == "status":
        response.status = 503
    elif failure == "cache":
        response.headers["Cache-Control"] = "public"
    else:
        response.read = lambda _: b'{"data":{"status":"bad"},"unrelated":"ok"}'
    with pytest.raises(SystemExit):
        runtime(["health"], response, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_valid_health_and_missing_command_have_explicit_outcomes(optimize):
    response = SimpleNamespace(status=200, headers={"Cache-Control": "private, no-store"},
                               read=lambda _: json.dumps({"data": {"status": "ok"}}).encode())
    runtime(["health"], response, optimize)
    with pytest.raises(SystemExit, match="Select serve"):
        runtime([], optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_server_refuses_incomplete_restore_before_starting(tmp_path, monkeypatch, optimize):
    from family_finance.config import Settings
    (tmp_path / ".restore-incomplete").write_text("failed restore")
    monkeypatch.setattr(Settings, "from_environment", lambda: SimpleNamespace(data_root=tmp_path))
    with pytest.raises(SystemExit, match="Incomplete restore"), patch("uvicorn.run") as serve:
        runtime(["serve"], optimize=optimize)
    serve.assert_not_called()


def manager(optimize):
    namespace = {"__name__": "review_manage", "__file__": str(DEPLOY / "manage.py")}
    exec(compile((DEPLOY / "manage.py").read_text(), str(DEPLOY / "manage.py"), "exec", optimize=optimize), namespace)  # noqa: S102 -- Exercise the local management module under -O.
    return namespace


@pytest.mark.parametrize("optimize", [0, 2])
def test_management_hardening_gate_remains_active_without_assertions(optimize):
    module = manager(optimize)
    project = "familyfin-m1-synthetic"
    items = []
    for name in ("api", "web", "caddy"):
        items.append({"Id": name, "Config": {"Labels": {"com.docker.compose.project": project,
                      "com.docker.compose.service": name}, "User": "10001:10001",
                      "Env": ["FAMILY_FINANCE_API_PUBLIC_ORIGIN=https://familyfin.test",
                              "FAMILY_FINANCE_API_TRUSTED_HOSTS=familyfin.test,127.0.0.1"]},
                      "State": {"Health": {"Status": "healthy"}},
                      "HostConfig": {"ReadonlyRootfs": False, "Privileged": True, "CapDrop": []}})
    module["inspect_all"] = lambda: copy.deepcopy(items)
    with pytest.raises(RuntimeError, match="filesystem/capability"):
        module["verify"](project)
    # This direct guard also proves its body survives compilation with -O.
    with pytest.raises(RuntimeError, match="unsafe"):
        module["require"](False, "unsafe")


@pytest.mark.parametrize("module", ["validate", "mobile", "host_recovery", "rollout_reviewed",
                                    "validate_candidate", "validate_scheduled_backup", "validate_backup_alerts"])
def test_optimized_lab_import_is_refused_before_any_host_operation(module):
    result = subprocess.run([sys.executable, "-O", "-c",
                             "import sys;sys.path.insert(0,sys.argv[1]);__import__(sys.argv[2])",
                             str(DEPLOY), module], capture_output=True, check=False,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode != 0
    assert b"require Python without -O" in result.stderr


@pytest.mark.parametrize("script,arguments", [
    ("host_recovery.py", ["prepare"]), ("validate_scheduled_backup.py", []),
    ("validate_backup_alerts.py", []), ("rollout_reviewed.py", [])])
def test_lab_entry_points_require_explicit_host_evidence(script, arguments):
    result = subprocess.run([sys.executable, str(DEPLOY / script), *arguments],
                            capture_output=True, check=False)
    assert result.returncode == 2
    assert b"--config" in result.stderr or b"--evidence-directory" in result.stderr


def test_operational_verification_contains_no_removable_assertions():
    for name in ("manage.py", "runtime.py", "operations.py", "portable_backup.py", "backup_readiness.py"):
        tree = ast.parse((DEPLOY / name).read_text())
        assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree)), name


@pytest.mark.parametrize("option,value", [("--report-name", "../other"), ("--image-tag", "bad;command")])
def test_mobile_rejects_redirected_report_names_or_invalid_tags_before_host_access(option, value):
    result = subprocess.run([sys.executable, str(DEPLOY / "mobile.py"), "prepare", option, value],
                            capture_output=True, check=False)
    assert result.returncode == 2
    assert b"explicit lowercase report" in result.stderr
