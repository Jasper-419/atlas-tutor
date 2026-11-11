#!/usr/bin/env python3
"""One-command Atlas local setup and development runner; stdlib only."""

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def check_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(
                f"Port {port} is occupied. Use --port / --api-port to select another port."
            )


def restart_existing(ports):
    """Stop only listeners whose cwd and command identify this Atlas checkout."""
    if not shutil.which("lsof"):
        raise SystemExit("Automatic restart requires lsof; stop the previous Atlas terminal first.")

    def process(pid, option):
        return subprocess.run(["ps", "-p", str(pid), "-o", option + "="], capture_output=True, text=True).stdout.strip()

    def directory(pid):
        result = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True)
        paths = [line[1:] for line in result.stdout.splitlines() if line.startswith("n")]
        return Path(paths[0]).resolve() if paths else None

    listeners, parents = set(), set()
    for port in ports:
        result = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True)
        for value in result.stdout.split():
            pid = int(value)
            command, cwd = process(pid, "command"), directory(pid)
            if cwd not in {ROOT, ROOT / "frontend"} or not any(part in command for part in ("backend.main:app", "next-server", "next dev")):
                raise SystemExit(f"Port {port} belongs to another process; it was left running.")
            listeners.add(pid)
            parent = process(pid, "ppid")
            if parent.isdigit() and "scripts/dev.py" in process(int(parent), "command") and directory(int(parent)) == ROOT:
                parents.add(int(parent))
    # The project runner already shuts down both children gracefully.
    for pid in parents or listeners:
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    if listeners:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                for port in ports:
                    with socket.socket() as sock:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        sock.bind(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.2)
        raise SystemExit("Atlas is still shutting down; run the command again after it exits.")


def setup():
    if not shutil.which("npm"):
        raise SystemExit("Install Node.js 22+ and npm first.")
    python = (
        ROOT
        / ".venv-atlas"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not python.exists():
        candidates = ["python3.12", "python3.11", "python3.13", sys.executable]
        executable = None
        for candidate in candidates:
            path = shutil.which(candidate)
            if (
                path
                and subprocess.run(
                    [path, "-c", "import sys;sys.exit(sys.version_info < (3,11))"],
                    capture_output=True,
                ).returncode
                == 0
            ):
                executable = path
                break
        if not executable:
            raise SystemExit("Install Python 3.11+ first.")
        subprocess.run(
            [executable, "-m", "venv", str(ROOT / ".venv-atlas")], check=True
        )
    marker = ROOT / ".venv-atlas" / ".atlas-requirements"
    requirements_file = ROOT / "requirements.lock.txt"
    if not requirements_file.exists():
        requirements_file = ROOT / "requirements.txt"
    requirements = requirements_file.read_text()
    if not marker.exists() or marker.read_text() != requirements:
        if subprocess.run(
            [str(python), "-m", "pip", "--version"], capture_output=True
        ).returncode:
            subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements_file)],
            cwd=ROOT,
            check=True,
        )
        marker.write_text(requirements)
    if not (ROOT / "frontend/node_modules/next/package.json").exists():
        subprocess.run(["npm", "ci"], cwd=ROOT / "frontend", check=True)
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        print(
            "Created .env. Add a model key for AI features; curated courses work immediately.",
            flush=True,
        )
    return str(python)


def main():
    parser = argparse.ArgumentParser(description="Start the complete Atlas app.")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--restart", action="store_true", help="Gracefully restart only this checkout's existing Atlas services.")
    args = parser.parse_args()
    python = setup()
    if args.setup_only:
        return
    if args.restart:
        restart_existing((args.port, args.api_port))
    check_port(args.port)
    check_port(args.api_port)
    env = dict(os.environ)
    env["API_URL"] = f"http://127.0.0.1:{args.api_port}"
    env.setdefault(
        "CORS_ORIGINS", f"http://localhost:{args.port},http://127.0.0.1:{args.port}"
    )
    processes = []

    def stop(*_):
        for process in processes:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(
            subprocess.Popen(
                [
                    python,
                    "-m",
                    "uvicorn",
                    "backend.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.api_port),
                ],
                cwd=ROOT,
                env=env,
                start_new_session=os.name != "nt",
            )
        )
        processes.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", str(args.port)],
                cwd=ROOT / "frontend",
                env=env,
                start_new_session=os.name != "nt",
            )
        )
        print(
            f"Atlas: http://127.0.0.1:{args.port}  |  API docs: http://127.0.0.1:{args.api_port}/docs",
            flush=True,
        )
        print("Press Ctrl+C to stop both services.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        print("A service exited; stopping the other service.", flush=True)
    finally:
        stop()


if __name__ == "__main__":
    main()
