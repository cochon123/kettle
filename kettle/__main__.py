"""Kettle command line.

    python -m kettle demo [--plug sim|shelly:<ip>|...]   cloud + edge hub together (the stage demo)
    python -m kettle cloud [--port 8700]                  cloud service only
    python -m kettle edge  [--plug ...] [--cloud ws://host:8700]
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def cloud(argv: list[str]) -> None:
    import argparse
    import logging
    import uvicorn
    ap = argparse.ArgumentParser(prog="kettle cloud")
    ap.add_argument("--port", type=int, default=int(os.getenv("KETTLE_PORT", 8700)))
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run("kettle.cloud.app:app", host=a.host, port=a.port, log_level="warning")


def demo(argv: list[str]) -> None:
    py = sys.executable
    procs = [subprocess.Popen([py, "-m", "kettle", "cloud"]),]
    time.sleep(1.5)
    procs.append(subprocess.Popen([py, "-m", "kettle", "edge", *argv]))
    print("\n  Kettle demo running")
    print("  stage   http://localhost:8700/stage/")
    print("  circle  http://localhost:8700/circle/?m=priya")
    print("  kitchen http://localhost:8701/hub/   (edge hub, local only)\n")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()


def main() -> None:
    cmd, argv = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("demo", [])
    if cmd == "cloud":
        cloud(argv)
    elif cmd == "edge":
        from .edge.hub import main as edge_main
        edge_main(argv)
    elif cmd == "demo":
        demo(argv)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
