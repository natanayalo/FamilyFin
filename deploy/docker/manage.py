"""Windows host operations. Stdlib only; never modifies Serve or unrelated services."""
import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".state"
REPORTS = ROOT / "reports"
PROJECTS = {"familyfin-m1-synthetic": 8090, "familyfin-m1-restore": 8091}


def require(condition, message):
    """Operational verification must remain active under Python optimization."""
    if not condition:
        raise RuntimeError(message)


def run(*args, stdin=None, check=True):
    result = subprocess.run(list(args), input=stdin, text=True, encoding="utf-8", check=False,
                            capture_output=True)
    if check and result.returncode:
        # Do not echo arguments/stdin, which may contain test-only credentials.
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[-2500:]}")
    return result


def engine():
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise RuntimeError("Remove ambient Docker endpoint overrides before local deployment")
    endpoint = json.loads(run("docker", "context", "inspect").stdout)[0]["Endpoints"]["docker"]["Host"]
    if endpoint != "npipe:////./pipe/dockerDesktopLinuxEngine":
        raise RuntimeError("Select the local desktop-linux named pipe; remote engines forbidden")
    info = json.loads(run("docker", "info", "--format", "{{json .}}").stdout)
    if info["OSType"] != "linux" or int(info["ServerVersion"].split(".")[0]) < 28:
        raise RuntimeError("Linux Docker Engine 28+ required")


def compose(project, *args, stdin=None, check=True, restore_source=None, image_tag="local"):
    if image_tag not in {"local", "security-review"} and not re.fullmatch(r"candidate-[a-z0-9][a-z0-9.-]{0,63}", image_tag):
        raise ValueError("Unsupported lab image tag")
    command = ["docker", "compose", "--project-name", project, "--project-directory", str(ROOT),
               "--file", str(ROOT / "compose.yaml")]
    if restore_source:
        command += ["--file", str(ROOT / "compose.restore.yaml")]
    # Do not inherit ambient development, origin, port or Compose overrides.
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("COMPOSE_", "FAMILYFIN_", "FAMILY_FINANCE_")):
            env.pop(key)
    env.update(FAMILYFIN_PORT=str(PROJECTS[project]), FAMILYFIN_ORIGIN="https://familyfin.test",
               FAMILYFIN_HOST="familyfin.test", FAMILYFIN_IMAGE_TAG=image_tag, COMPOSE_DISABLE_ENV_FILE="1")
    if restore_source:
        env["FAMILYFIN_RESTORE_BACKUP_VOLUME"] = restore_source
    result = subprocess.run(command + list(args), input=stdin, text=True, encoding="utf-8", check=False,
                            capture_output=True, env=env)
    if check and result.returncode:
        raise RuntimeError(f"Compose failed ({result.returncode}): {result.stderr[-4000:]}")
    return result


def inspect_all():
    ids = run("docker", "ps", "--all", "--quiet").stdout.split()
    return json.loads(run("docker", "inspect", *ids).stdout) if ids else []


def baseline():
    items = []
    for item in inspect_all():
        project = (item["Config"].get("Labels") or {}).get("com.docker.compose.project")
        if project in PROJECTS:
            continue
        raw = json.dumps([item["Config"], item["HostConfig"]], sort_keys=True).encode()
        items.append({"id": item["Id"], "name": item["Name"], "configuration_sha256": hashlib.sha256(raw).hexdigest(),
                          "status": item["State"]["Status"], "started_at": item["State"]["StartedAt"],
                          "mounts": sorted([{k: m.get(k) for k in ("Type", "Source", "Destination", "RW")} for m in item["Mounts"]], key=lambda m:m["Destination"]),
                          "ports": item["HostConfig"]["PortBindings"]})
    serve = json.loads(run("tailscale", "serve", "status", "--json").stdout)
    return {"containers": sorted(items, key=lambda x: x["id"]), "serve": serve}


def baseline_equal(left, right):
    # Engine inspect does not promise mount-list ordering. Compare its meaning.
    def canonical(value):
        value = json.loads(json.dumps(value))
        for item in value["containers"]:
            item["mounts"].sort(key=lambda m:m["Destination"])
        return value
    return canonical(left) == canonical(right)


def assert_owned(project):
    for item in inspect_all():
        labels = item["Config"].get("Labels") or {}
        if labels.get("com.docker.compose.project") == project:
            directory = labels.get("com.docker.compose.project.working_dir", "")
            if os.path.normcase(os.path.abspath(directory)) != os.path.normcase(str(ROOT)):
                raise RuntimeError("Project name belongs to another directory")
    for suffix in ("financial", "backups"):
        volume = run("docker", "volume", "inspect", f"{project}_{suffix}", check=False)
        if volume.returncode == 0:
            labels = json.loads(volume.stdout)[0].get("Labels") or {}
            if labels.get("com.docker.compose.project") != project:
                raise RuntimeError("Volume ownership mismatch")


def request(port, path, method="GET", data=None, cookie=None, csrf=None, origin="https://familyfin.test", host="familyfin.test", raw=None):
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    body = raw
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    connection.close()
    return result


def verify(project, *, origin="https://familyfin.test", host="familyfin.test"):
    items = [i for i in inspect_all() if (i["Config"].get("Labels") or {}).get("com.docker.compose.project") == project]
    services = {(i["Config"]["Labels"])["com.docker.compose.service"]: i for i in items
                if (i["Config"]["Labels"]).get("com.docker.compose.oneoff", "False").lower() == "false"}
    require(set(services) == {"api", "web", "caddy"}, "Expected three runtime services")
    environment = dict(value.split("=", 1) for value in services["api"]["Config"]["Env"] if "=" in value)
    require(environment["FAMILY_FINANCE_API_PUBLIC_ORIGIN"] == origin, "API origin mismatch")
    require(environment["FAMILY_FINANCE_API_TRUSTED_HOSTS"] == host + ",127.0.0.1", "Trusted host mismatch")
    require(not environment.get("FAMILY_FINANCE_LOCAL_DEV"), "Development mode forbidden")
    financial = f"{project}_financial"
    for name, item in services.items():
        hc = item["HostConfig"]
        require(item["State"]["Health"]["Status"] == "healthy", name + " unhealthy")
        require(item["Config"]["User"] == {"api":"10001:10001", "web":"10002:10002", "caddy":"10003:10003"}[name], name + " user mismatch")
        require(hc["ReadonlyRootfs"] and not hc["Privileged"] and hc["CapDrop"] == ["ALL"], name + " filesystem/capability mismatch")
        require("no-new-privileges:true" in hc["SecurityOpt"], name + " privilege guard missing")
        require(hc["Memory"] > 0 and hc["NanoCpus"] > 0 and hc["PidsLimit"] > 0, name + " limits missing")
        require(hc["RestartPolicy"]["Name"] == "unless-stopped", name + " restart policy mismatch")
        require(all("docker.sock" not in m["Destination"] for m in item["Mounts"]), "Docker socket mount forbidden")
        require(all(m["Type"] != "bind" for m in item["Mounts"]), "Unexpected host bind")
        bindings = hc.get("PortBindings") or {}
        if name == "caddy":
            require(bindings == {"8080/tcp": [{"HostIp":"127.0.0.1", "HostPort":str(PROJECTS[project])}]}, "Caddy binding mismatch")
        else:
            require(not bindings, name + " must not publish ports")
        mounts = [m.get("Name") for m in item["Mounts"] if m["Type"] == "volume"]
        require((financial in mounts) == (name == "api"), "Financial volume isolation mismatch")
    for item in inspect_all():
        if item["Id"] != services["api"]["Id"]:
            require(financial not in [m.get("Name") for m in item["Mounts"]], "Data shared outside API")
    network = json.loads(run("docker", "network", "inspect", f"{project}_private").stdout)[0]
    require(network["Internal"], "Private network must be internal")
    require(set(network["Containers"]) == {i["Id"] for i in services.values()}, "Private network membership mismatch")
    edge = json.loads(run("docker", "network", "inspect", f"{project}_edge").stdout)[0]
    require(set(edge["Containers"]) == {services["caddy"]["Id"]}, "Edge network membership mismatch")
    require(services["caddy"]["NetworkSettings"]["Ports"]["8080/tcp"] == [
        {"HostIp":"127.0.0.1", "HostPort":str(PROJECTS[project])}], "Published Caddy port mismatch")
    volume = json.loads(run("docker", "volume", "inspect", financial).stdout)[0]
    require(volume["Driver"] == "local" and not volume.get("Options"), "Expected Linux-managed local volume")
    for path in ("/", "/api/v1/health", "/sw.js", "/manifest.webmanifest"):
        status, headers, _body = request(PROJECTS[project], path, origin=origin, host=host)
        require(status == 200, "HTTP health failed: " + path)
        require(headers["cache-control"] == "private, no-store", "Cache policy mismatch: " + path)
        require(headers["strict-transport-security"] == "max-age=31536000", "HSTS mismatch")
        require("server" not in headers and "x-powered-by" not in headers, "Unexpected server metadata")
        require("content-security-policy" in headers, "CSP missing")
    require(request(PROJECTS[project], "/api/v1/health", origin=origin, host="evil.example")[0] == 400, "Untrusted host accepted")
    return {"status":"PASS", "checks":"health, hardening, headers, exact ports, storage and network membership"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "verify", "backup"])
    parser.add_argument("--project", choices=PROJECTS, default="familyfin-m1-synthetic")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.action in {"start", "stop", "verify", "backup"} and args.project == "familyfin-m1-synthetic" and (STATE / "mobile-acceptance" / "receipt.json").exists():
        mobile = json.loads((STATE / "mobile-acceptance" / "receipt.json").read_text(encoding="utf-8"))
        if mobile.get("status") != "RESTORED_LAB":
            if args.action in {"verify", "backup"}:
                import mobile as mobile_operations
                if mobile["status"] != "PREPARED_LOCAL_ONLY":
                    raise RuntimeError("Inspect incomplete mobile preparation before operating this lab")
                engine()
                result = mobile_operations.verify(mobile)
                result["checked_at"] = datetime.now(UTC).isoformat()
                if args.action == "backup":
                    result["verified_snapshot"] = mobile_operations.backup(mobile["hostname"])
                (REPORTS / f"{args.project}-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result))
                return
            raise RuntimeError("Mobile preparation owns this lab. Use mobile.py verify or restore-lab; do not replace its HTTPS origin through lab wrappers.")
    engine()
    assert_owned(args.project)
    STATE.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    receipt = STATE / "baseline.json"
    if args.action == "start":
        if not receipt.exists():
            receipt.write_text(json.dumps(baseline(), indent=2), encoding="utf-8")
        existing = compose(args.project, "ps", "--quiet", "caddy").stdout.strip()
        if not existing:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", PROJECTS[args.project]))
        compose(args.project, "config", "--quiet")
        if args.build:
            compose(args.project, "build")
        compose(args.project, "up", "--detach", "--wait", "--wait-timeout", "180")
        print(json.dumps(verify(args.project)))
    elif args.action == "stop":
        compose(args.project, "down")
        print("Stopped; volumes retained. Serve unchanged.")
    elif args.action == "backup":
        print(compose(args.project, "run", "--rm", "--no-deps", "operations", "operations", "backup").stdout.strip())
    else:
        result = verify(args.project)
        if receipt.exists():
            require(baseline_equal(json.loads(receipt.read_text(encoding="utf-8")), baseline()), "Unrelated service/Serve drift")
            result["unrelated_services_and_serve"] = "PASS"
        else:
            result["unrelated_services_and_serve"] = "UNVERIFIED: no pre-start baseline"
        result["checked_at"] = datetime.now(UTC).isoformat()
        (REPORTS / f"{args.project}-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
