"""Linux local-process smoke harness, not a public server."""

import argparse, fcntl, json, os, sys, tempfile
from pathlib import Path
from adapter import *

p = argparse.ArgumentParser()
p.add_argument("--state", required=True)
p.add_argument("--session", required=True)
p.add_argument("--peer", required=True)
p.add_argument("--now", type=float, default=1)
args = p.parse_args()
path = Path(args.state)
# Supervisor-selected file and trusted transport arguments, not request fields.
with open(str(path) + ".lock", "a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    host = restore(json.loads(path.read_text()))
    try:
        request = load(sys.stdin.read(262145))
        updated, ack = receive(
            host,
            request,
            transport_session=args.session,
            authenticated_peer=args.peer,
            now=args.now,
        )
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="state-")
        with os.fdopen(fd, "w") as f:
            json.dump(serialize(updated), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # Directory fsync intentionally omitted: local smoke durability not guaranteed.
        print(json.dumps({"ok": True, "ack": ack}))
    except Error as e:
        print(json.dumps({"ok": False, "error": str(e)}))
