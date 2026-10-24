"""Create a new protected, synthetic-only portable backup configuration.

Never adopts an existing external directory or initializes real household data.
The generated age identity is a disposable drill key, not a production recovery key.
"""
import argparse
import json
import uuid
from pathlib import Path

import manage
import mobile
import portable_backup as backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--tools", required=True, type=Path)
    args = parser.parse_args()
    if args.state.exists() or args.directory.exists():
        raise ValueError("New state and external directories required; existing contents are never adopted")
    receipt = json.loads((mobile.STATE / "receipt.json").read_text())
    mobile.verify(receipt)
    tools = args.tools.resolve()
    for name in backup.HASHES:
        backup.tool({"tools": str(tools)}, name)
    observed = backup.media("inspect", args.directory)
    backup.media("private-create", args.state)
    state = args.state.resolve()
    token = uuid.uuid4().hex
    config = {"format": 1, "project": mobile.PROJECT, "image": receipt["images"]["api"],
              "container_image": next(i["Image"] for i in manage.inspect_all()
                  if i["Name"] == "/" + mobile.PROJECT + "-api-1"),
              "directory": str(args.directory.absolute()), "volume_id": observed["VolumeId"],
              "disk_id": observed["DiskId"], "media_token": token,
              "tools": str(tools), "identity": str(state / "disposable-drill-identity.txt"),
              "synthetic": True, "production_key_custody": "NOT_CONFIGURED"}
    backup.call([backup.tool(config, "age-keygen.exe"), "-o", config["identity"]])
    config["recipient"] = backup.call([backup.tool(config, "age-keygen.exe"), "-y", config["identity"]]).decode().strip()
    backup.media("create", args.directory, config)
    with (state / "config.json").open("x", encoding="utf-8") as output:
        json.dump(config, output, indent=2)
    backup.identity(config)
    backup.check_media(config)
    print("Synthetic-only backup configuration created. Identity remains in the protected local directory, never on backup media. Production key custody and scheduler are not configured.")


if __name__ == "__main__":
    main()
