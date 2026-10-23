"""Synthetic mobile preparation on localhost only. Never changes Tailscale Serve.

prepare verifies the known disposable fixture, snapshots it and applies the real
private hostname. verify is read-only. set-test-passwords prompts at a local TTY.
restore-lab requires the route already be back on M0 and retains all volumes.
"""
import argparse
import copy
import getpass
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import manage
import validate

PROJECT = "familyfin-m1-synthetic"
PORT = 8090
STATE = manage.STATE / "mobile-acceptance"
REPORT = manage.REPORTS / "mobile-preparation-20261023"
TAG = "mobile-20261023"


def private_hostname(serve):
    if set(serve) - {"TCP", "Web", "AllowFunnel"} or any((serve.get("AllowFunnel") or {}).values()):
        raise RuntimeError("Unexpected Serve settings or Funnel enabled")
    if serve.get("TCP") != {"443": {"HTTPS": True}} or len(serve.get("Web", {})) != 1:
        raise RuntimeError("Expected the existing single private HTTPS listener")
    listener, handler = next(iter(serve["Web"].items()))
    hostname = listener.removesuffix(":443")
    if listener != hostname + ":443" or not hostname.endswith(".ts.net"):
        raise RuntimeError("Existing private ts.net hostname required")
    if len(hostname) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in hostname.split(".")):
        raise RuntimeError("Invalid private hostname")
    if handler != {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8088"}}}:
        raise RuntimeError("M0 must still own the original HTTPS root")
    return hostname


def preservation():
    # Include the complete restore lab in preservation, as well as M0/unrelated
    # workloads. Only the explicitly adopted primary synthetic lab may change.
    projects = manage.PROJECTS
    try:
        manage.PROJECTS = {PROJECT: PORT}
        return manage.baseline()
    finally:
        manage.PROJECTS = projects


def preserved(before, after, hostname, *, allow_trial=False):
    if manage.baseline_equal(before, after):
        return "M0"
    trial = copy.deepcopy(before)
    trial["serve"]["Web"][hostname + ":443"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:8090"
    if allow_trial and manage.baseline_equal(trial, after):
        return "FamilyFin trial (route changed externally)"
    raise RuntimeError("Protected service or Serve drift; inspect before continuing")


def environment(hostname, *, lab=False):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("COMPOSE_", "FAMILYFIN_", "FAMILY_FINANCE_"))}
    env.update(COMPOSE_DISABLE_ENV_FILE="1", FAMILYFIN_PORT=str(PORT),
               FAMILYFIN_IMAGE_TAG="local" if lab else TAG,
               FAMILYFIN_ORIGIN="https://familyfin.test" if lab else "https://" + hostname,
               FAMILYFIN_HOST="familyfin.test" if lab else hostname)
    return env


def compose(hostname, *args, stdin=None, lab=False, check=True):
    command = ["docker", "compose", "--project-name", PROJECT, "--project-directory", str(manage.ROOT),
               "--file", str(manage.ROOT / "compose.yaml"), *args]
    result = subprocess.run(command, input=stdin, text=True, encoding="utf-8",
                            capture_output=True, env=environment(hostname, lab=lab))
    if check and result.returncode:
        # Never print stdin/credentials, command arguments or HTTP bodies.
        raise RuntimeError("Mobile Compose operation failed; preserve state and inspect configuration")
    return result


def financial(state):
    return {key: value for key, value in state.items() if key != "counts"} | {
        "counts": {key: value for key, value in state["counts"].items() if not key.startswith(("api_", "actor_"))}}


def fixture():
    manage.assert_owned(PROJECT)
    expected = json.loads((manage.REPORTS / "restored-state-comparison.json").read_text(encoding="utf-8"))
    current = validate.status(PROJECT)
    if (current["financial_sha256"] != expected["financial_values_sha256"]
            or current["migrations"] != expected["migration"] or len(current["archives"]) != expected["archive_count"]
            or {key: current["counts"].get(key) for key in ("api_users", "transactions", "source_files", "net_worth_accounts")}
                != {"api_users": 2, "transactions": 1, "source_files": 1, "net_worth_accounts": 2}):
        raise RuntimeError("Refusing to adopt a changed or non-synthetic financial fixture")
    validate.execute(PROJECT, """
import sqlite3
from pathlib import Path
root=Path('/var/lib/familyfin')
assert (root/'.synthetic-lab').read_text()=='Disposable FamilyFin M1 validation only'
with sqlite3.connect(root/'family_finance.sqlite3') as db:
    assert sorted(r[0] for r in db.execute('SELECT username FROM api_users'))==['qa-one','qa-two']
""")
    return current


def image_id(name, tag):
    return json.loads(manage.run("docker", "image", "inspect", f"familyfin-m1-{name}:{tag}").stdout)[0]["Id"]


def check_images(images, tag):
    if set(images) != {"api", "web", "caddy"} or any(image_id(name, tag) != value for name, value in images.items()):
        raise RuntimeError("Release image identity changed; fresh review required")


def protected_folder():
    if STATE.exists() or STATE.is_symlink() or manage.STATE.is_symlink() or manage.STATE.is_junction():
        raise RuntimeError("Refusing to overwrite or redirect mobile preparation evidence")
    path = str(STATE).replace("'", "''")
    # Only this newly created folder receives an ACL; no existing ACL is changed.
    script = """
$ErrorActionPreference='Stop'
$path='__PATH__'
New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=[IO.Directory]::GetAccessControl($path)
$acl.SetAccessRuleProtection($true,$false)
foreach($principal in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
 $rule=[Security.AccessControl.FileSystemAccessRule]::new($principal,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $acl.AddAccessRule($rule)
}
[IO.Directory]::SetAccessControl($path,$acl)
$actual=[IO.Directory]::GetAccessControl($path)
$allowed=@($sid.Value,'S-1-5-18','S-1-5-32-544') | Sort-Object
$observed=@($actual.Access | ForEach-Object {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}) | Sort-Object
if(-not $actual.AreAccessRulesProtected -or @(Compare-Object $allowed $observed).Count) {throw 'Unexpected mobile evidence permissions'}
""".replace("__PATH__", path)
    manage.run("powershell.exe", "-NoProfile", "-Command", script)


def save(receipt):
    temporary = STATE / "receipt.next.json"
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temporary.replace(STATE / "receipt.json")
    if REPORT.exists():
        public={key:value for key,value in receipt.items() if key not in {"preservation","before"}}
        public["limits"]=[
            "Raw scanner gates retain FAIL; exception approval is recorded separately",
            "Phone credentials use local console prompts; no password is saved or printed",
            "Local HTTP probes simulate TLS termination; no actual mobile HTTPS/cache/network acceptance",
            "Portable scheduled application backup and host reboot acceptance remain unverified",
        ]
        (REPORT/"local-phone-preparation.json").write_text(json.dumps(public,indent=2),encoding="utf-8")


def backup(hostname, *, lab=False):
    name = compose(hostname, "run", "--rm", "--no-deps", "--pull", "never",
                   "operations", "operations", "backup", lab=lab).stdout.strip().splitlines()[-1]
    if not re.fullmatch(r"familyfin-[0-9a-f]{32}", name):
        raise RuntimeError("Invalid snapshot identity")
    compose(hostname, "run", "--rm", "--no-deps", "--pull", "never",
            "operations", "operations", "verify", name, lab=lab)
    return name


def reset_passwords(hostname, passwords):
    fixture()  # Guard immediately before credential mutation, too.
    code = """
import json,sys
from family_finance.api.auth import AuthService
from family_finance.config import Settings
from family_finance.persistence.db import Database
s=Settings.from_environment(); auth=AuthService(Database(s.database_path),s)
for name,password in zip(('qa-one','qa-two'),json.load(sys.stdin),strict=True):
    auth.reset_password(username=name,password=password)
"""
    compose(hostname, "exec", "-T", "api", "python", "-c", code, stdin=json.dumps(passwords))


def auth_checks(hostname):
    passwords = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
    reset_passwords(hostname, passwords)
    origin = "https://" + hostname
    def request(path="/api/v1/auth/session", method="GET", **kwargs):
        return manage.request(PORT, path, method, host=hostname, **({"origin":origin} | kwargs))
    for path in ("/api/v1/auth/session", "/api/v1/net-worth/accounts", "/api/v1/planning/scenarios"):
        assert request(path)[0] == 401
    for wrong_origin in (None, "https://attacker.example", "https://familyfin.test"):
        assert request(method="POST", data={"username":"qa-one", "password":passwords[0]}, origin=wrong_origin)[0] == 403
    assert request(method="POST", data={"username":"qa-one", "password":"incorrect"})[0] == 401
    sessions = []
    for name, password in zip(("qa-one", "qa-two"), passwords, strict=True):
        status, headers, body = request(method="POST", data={"username":name, "password":password})
        assert status == 200
        assert all(flag in headers["set-cookie"].lower() for flag in ("secure", "httponly", "samesite=strict", "path=/api/v1"))
        data = json.loads(body)["data"]
        assert data["user"]["username"] == name
        cookie, csrf = headers["set-cookie"].split(";",1)[0], data["csrf_token"]
        assert request(cookie=cookie)[0] == 200
        assert request("/api/v1/net-worth/accounts", cookie=cookie)[0] == 200
        assert request(method="DELETE", cookie=cookie)[0] == 403
        assert request(method="DELETE", cookie=cookie, csrf="incorrect")[0] == 403
        assert request(method="DELETE", cookie=cookie, csrf=csrf, origin="https://attacker.example")[0] == 403
        sessions.append((cookie,csrf))
    assert request(method="DELETE",cookie=sessions[0][0],csrf=sessions[1][1])[0] == 403
    for cookie,csrf in sessions:
        assert request(method="DELETE",cookie=cookie,csrf=csrf)[0] == 204
        assert request(cookie=cookie)[0] == 401
    # Destroy the smoke passwords by rotating again; phone credentials will be
    # selected interactively at the local console, after these probes finish.
    reset_passwords(hostname,[secrets.token_urlsafe(32),secrets.token_urlsafe(32)])
    return "PASS two users, actual HTTPS origin, secure cookies, protected reads, wrong/missing/old origin, cross-session/missing/wrong CSRF, logout/revocation; passwords discarded"


def restart_preservation(receipt, *, path=None):
    """Use a separately reviewed restart baseline; never overwrite original evidence."""
    path = path or STATE / "restart-preservation.json"
    if not path.exists():
        return receipt["preservation"]
    if path.is_symlink() or path.is_junction():
        raise RuntimeError("Redirected restart preservation record")
    current = json.loads(path.read_text(encoding="utf-8"))
    actual = hashlib.sha256((STATE / "receipt.json").read_bytes()).hexdigest()
    if current.get("original_receipt_sha256") != actual or current.get("status") != "VERIFIED_RESTART":
        raise RuntimeError("Restart preservation does not match the original mobile receipt")
    def configuration(value):
        value = copy.deepcopy(value)
        for item in value["containers"]:
            item.pop("started_at", None)
        return value
    if not manage.baseline_equal(configuration(receipt["preservation"]), configuration(current["preservation"])):
        raise RuntimeError("Restart baseline changes more than process start times")
    return current["preservation"]


def verify(receipt, *, reviewed_preservation=None):
    if reviewed_preservation is None:
        expected_preservation = restart_preservation(receipt)
    else:
        original, reviewed = copy.deepcopy(receipt["preservation"]), copy.deepcopy(reviewed_preservation)
        for snapshot in (original, reviewed):
            for item in snapshot["containers"]:
                item.pop("started_at", None)
        if not manage.baseline_equal(original, reviewed):
            raise RuntimeError("Reviewed restart baseline changes more than process start times")
        expected_preservation = reviewed_preservation
    hostname = receipt["hostname"]
    check_images(receipt["images"], TAG)
    fixture()
    result = manage.verify(PROJECT, origin="https://"+hostname, host=hostname)
    serving = preserved(expected_preservation, preservation(), hostname, allow_trial=True)
    expected_configs = json.loads((manage.REPORTS / "security-review-6/tested-configs.json").read_text())
    for item in manage.inspect_all():
        labels=item["Config"].get("Labels") or {}
        if labels.get("com.docker.compose.project")==PROJECT:
            name=labels["com.docker.compose.service"]
            assert item["Image"] in {receipt["images"][name],expected_configs[name]}
    for item in manage.inspect_all():
        for values in (item["HostConfig"].get("PortBindings") or {}).values():
            assert all(value["HostIp"]=="127.0.0.1" for value in values or [])
    listeners=json.loads(manage.run("powershell.exe","-NoProfile","-Command",
        "Get-NetTCPConnection -State Listen | ForEach-Object { [pscustomobject]@{address=$_.LocalAddress;port=$_.LocalPort;process=(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName} } | ConvertTo-Json").stdout)
    assert {(i["address"],i["port"]) for i in listeners if i["process"]=="com.docker.backend"}=={("127.0.0.1",p) for p in (8080,8088,8090,8091)}
    result.update(route=serving, protected_services_and_Serve="PASS", exact_Docker_loopback_listeners="PASS",
                  configured_origin="https://"+hostname,
                  security_exception_approval="APPROVED" if receipt.get("risk_exceptions_approved") else "PENDING",
                  actual_mobile_acceptance="UNVERIFIED")
    return result


def prepare():
    expected=json.loads((manage.STATE/"baseline.json").read_text(encoding="utf-8"))
    if not manage.baseline_equal(expected,manage.baseline()):
        raise RuntimeError("Resolve original-service baseline drift before preparation")
    before = preservation()
    hostname = private_hostname(before["serve"])
    fixture_state = fixture()
    manage.verify(PROJECT)
    images=json.loads((REPORT / "reviewed-images.json").read_text())
    check_images(images,"local")
    check_images(images,"security-review")
    for name,value in images.items():
        scan=json.loads((REPORT/f"trivy-familyfin-m1-{name}-security-review-summary.json").read_text())
        assert scan["docker_image_id"]==value
        existing=manage.run("docker","image","inspect",f"familyfin-m1-{name}:{TAG}",check=False)
        if existing.returncode==0 and json.loads(existing.stdout)[0]["Id"]!=value:
            raise RuntimeError("Refusing to overwrite a different frozen trial image")
    protected_folder()
    receipt={"status":"PREPARING","checked_at":datetime.now(UTC).isoformat(),"hostname":hostname,
             "images":images,"preservation":before,"before":fixture_state,"risk_exceptions_approved":False,
             "Serve_change":"NOT_PERFORMED","phone_password_setup":"PENDING_LOCAL_CONSOLE"}
    save(receipt)
    try:
        receipt["pre_configuration_snapshot"]=backup(hostname,lab=True)
        assert validate.status(PROJECT)==fixture_state
        save(receipt)
        for name,value in images.items():
            manage.run("docker","image","tag",value,f"familyfin-m1-{name}:{TAG}")
        compose(hostname,"config","--quiet")
        compose(hostname,"up","-d","--no-build","--pull","never","--wait","--wait-timeout","180")
        assert validate.status(PROJECT)==fixture_state
        receipt["verification"]=verify(receipt)
        receipt["origin_authentication_smoke"]=auth_checks(hostname)
        assert financial(validate.status(PROJECT))==financial(fixture_state)
        receipt["post_configuration_snapshot"]=backup(hostname)
        preserved(before,preservation(),hostname)
        receipt["status"]="PREPARED_LOCAL_ONLY"
    except BaseException:
        receipt["status"]="FAILED_PRESERVE_EVIDENCE"
        receipt["recovery"]="Serve remains unmodified by this tool; inspect evidence, then mobile.py restore-lab while M0 owns the route. Never delete a volume or downgrade a schema."
        raise
    finally:
        receipt["finished_at"]=datetime.now(UTC).isoformat()
        save(receipt)
    print("PASS local phone configuration and actual-origin two-user smoke; M0/Serve and restore lab unchanged. Phone credentials and route approval pending.")


def restore_lab(receipt):
    preserved(restart_preservation(receipt),preservation(),receipt["hostname"])
    fixture()
    check_images(receipt["images"],"local")
    before=financial(validate.status(PROJECT))
    compose(receipt["hostname"],"up","-d","--no-build","--pull","never","--wait","--wait-timeout","180",lab=True)
    assert financial(validate.status(PROJECT))==before
    manage.verify(PROJECT)
    preserved(restart_preservation(receipt),preservation(),receipt["hostname"])
    receipt["status"]="RESTORED_LAB"
    save(receipt)
    print("Original lab configuration restored; volumes retained; Serve unchanged. Test password resets are retained.")


def set_test_passwords(receipt):
    if not sys.stdin.isatty():
        raise RuntimeError("Use an interactive protected local console; credentials must not pass through chat or tool output")
    verify(receipt)
    passwords=[]
    for name in ("qa-one","qa-two"):
        password=getpass.getpass(f"{name} test password (14+ characters): ")
        if password!=getpass.getpass("Confirm: ") or not 14<=len(password)<=1024 or "\x00" in password:
            raise RuntimeError("Passwords must match, contain 14–1024 characters, and contain no NUL")
        passwords.append(password)
    reset_passwords(receipt["hostname"],passwords)
    receipt["phone_password_setup"]="SET_AT_LOCAL_CONSOLE"
    save(receipt)
    print("Two disposable test passwords set; prior sessions revoked. No household accounts changed.")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","verify","restore-lab","set-test-passwords"))
    args=parser.parse_args()
    manage.engine()
    if args.action=="prepare":
        prepare()
        return
    receipt=json.loads((STATE/"receipt.json").read_text(encoding="utf-8"))
    if args.action=="restore-lab":
        restore_lab(receipt)
    elif receipt["status"]!="PREPARED_LOCAL_ONLY":
        raise RuntimeError("Inspect incomplete or restored preparation before proceeding")
    elif args.action=="verify":
        print(json.dumps(verify(receipt)))
    else:
        set_test_passwords(receipt)


if __name__=="__main__":
    main()
