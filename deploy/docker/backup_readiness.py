"""Bounded startup readiness for the local Windows synthetic backup task.

Never starts/reconfigures Docker or containers. Wrong endpoints or release
identities fail immediately; only engine/container startup is retried.
"""
import json
import os
import subprocess
import time

ENDPOINT = "npipe:////./pipe/dockerDesktopLinuxEngine"


def wait_ready(config, *, timeout=300, interval=5, runner=None, clock=None, sleep=None):
    runner = runner or subprocess.run
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    if not 0 < timeout <= 300 or not 0 < interval <= 5:
        raise ValueError("Readiness wait exceeds its fixed limits")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise ValueError("Ambient Docker endpoint overrides forbidden")
    started = clock()
    deadline = started + timeout

    def command(*args):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Local Docker/API startup readiness timed out")
        prefix = ["docker"] if args[0] == "context" else ["docker", "--host", ENDPOINT]
        return runner([*prefix, *args], capture_output=True, text=True,
                      timeout=min(5, remaining), check=False)

    context = command("context", "inspect")
    if context.returncode or json.loads(context.stdout)[0]["Endpoints"]["docker"]["Host"] != ENDPOINT:
        raise ValueError("Only the local Docker Desktop Linux endpoint is permitted")
    attempts = 0
    while clock() < deadline:
        attempts += 1
        try:
            info = command("info", "--format", "{{json .}}")
            if info.returncode == 0:
                engine = json.loads(info.stdout)
                if engine["OSType"] != "linux" or int(engine["ServerVersion"].split(".")[0]) < 28:
                    raise ValueError("Expected local Linux Engine 28+")
                inspected = command("inspect", config["project"] + "-api-1")
                if inspected.returncode:
                    raise ValueError("Reviewed API container is missing; never create a replacement implicitly")
                api = json.loads(inspected.stdout)[0]
                labels = api["Config"].get("Labels") or {}
                if (api["Image"] != config["container_image"]
                        or labels.get("com.docker.compose.project") != config["project"]
                        or labels.get("com.docker.compose.service") != "api"):
                    raise ValueError("API identity changed; fresh review required")
                if api["State"].get("Running") and api["State"].get("Health", {}).get("Status") == "healthy":
                    return {"status": "READY", "attempts": attempts,
                            "elapsed_seconds": round(clock() - started, 3)}
        except subprocess.TimeoutExpired:
            pass  # A hung startup probe has its own five-second bound.
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(interval, remaining))
    raise TimeoutError("Local Docker/API startup readiness timed out")
