#!/usr/bin/env python3
"""
run_agent.py — Single-command launcher for the Voice Scheduling Agent.

Starts the FastAPI backend, opens an ngrok tunnel, registers a fresh
Vapi assistant pointed at that tunnel, then keeps everything alive
until the user presses Ctrl+C.

Usage:
    python run_agent.py
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_PORT = 10000
HEALTH_URL = f"http://localhost:{BACKEND_PORT}/health"
NGROK_API_URL = "http://localhost:4040/api/tunnels"

HEALTH_TIMEOUT_S = 30   # seconds to wait for uvicorn to be ready
NGROK_TIMEOUT_S = 20    # seconds to wait for ngrok tunnel


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _print_step(n: int, total: int, msg: str) -> None:
    print(f"\n[{n}/{total}] {msg}")


def check_env_file() -> None:
    """Abort with a helpful message if .env is missing."""
    if not Path(".env").exists():
        print("\nERROR: .env file not found.")
        print("  Create one by copying the template and filling in your keys:")
        print()
        print("    cp .env.example .env")
        print()
        print("  Then open .env and set:")
        print("    • GOOGLE_CREDENTIALS_JSON  — your Service Account JSON (single line)")
        print("    • VAPI_API_KEY             — from https://dashboard.vapi.ai")
        sys.exit(1)


def wait_for_health(timeout: int = HEALTH_TIMEOUT_S) -> bool:
    """Poll GET /health until 200 or timeout. Returns True on success."""
    print(f"      Waiting for backend", end="", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                print(" ready ✓")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(" timed out ✗")
    return False


def wait_for_ngrok_url(timeout: int = NGROK_TIMEOUT_S) -> str | None:
    """Poll ngrok's local API until an HTTPS tunnel URL appears."""
    print("      Waiting for ngrok tunnel", end="", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(NGROK_API_URL, timeout=2)
            if r.status_code == 200:
                for tunnel in r.json().get("tunnels", []):
                    if tunnel.get("proto") == "https":
                        print(" ready ✓")
                        return tunnel["public_url"]
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(" timed out ✗")
    return None


def create_vapi_assistant(public_url: str) -> dict | None:
    """
    Import create_vapi_assistant functions directly so we can
    capture the returned assistant dict without parsing stdout.
    """
    try:
        from create_vapi_assistant import create_assistant, load_config
    except ImportError as exc:
        print(f"      ERROR: Could not import create_vapi_assistant.py — {exc}")
        return None

    api_key = os.environ.get("VAPI_API_KEY")
    if not api_key:
        print("      ERROR: VAPI_API_KEY is missing from .env")
        return None

    try:
        config = load_config(public_url)
        assistant = create_assistant(config, api_key)
        return assistant
    except SystemExit:
        # create_assistant calls sys.exit(1) on API errors; convert to None
        return None
    except Exception as exc:
        print(f"      ERROR: {exc}")
        return None


def kill_all(procs: list[subprocess.Popen]) -> None:
    """Gracefully terminate every process, escalating to SIGKILL if needed."""
    for proc in procs:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    processes: list[subprocess.Popen] = []
    TOTAL_STEPS = 5

    # ------------------------------------------------------------------
    # 1. Environment check
    # ------------------------------------------------------------------
    _print_step(1, TOTAL_STEPS, "Checking environment...")
    check_env_file()
    load_dotenv()
    print("      .env loaded ✓")

    # Validate critical keys are present before doing any real work
    missing = [k for k in ("GOOGLE_CREDENTIALS_JSON", "VAPI_API_KEY", "VAPI_PUBLIC_KEY") if not os.environ.get(k)]
    if missing:
        print(f"\nERROR: The following required keys are not set in .env:")
        for k in missing:
            print(f"  • {k}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Start FastAPI backend
    # ------------------------------------------------------------------
    _print_step(2, TOTAL_STEPS, "Starting FastAPI backend on port 10000...")
    uvicorn_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(BACKEND_PORT)],
    )
    processes.append(uvicorn_proc)

    if not wait_for_health():
        print("\n      Hint: make sure port 10000 is free (`lsof -i :10000`).")
        kill_all(processes)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Start ngrok tunnel
    # ------------------------------------------------------------------
    _print_step(3, TOTAL_STEPS, "Starting ngrok tunnel...")
    ngrok_proc = subprocess.Popen(
        ["ngrok", "http", str(BACKEND_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    processes.append(ngrok_proc)

    public_url = wait_for_ngrok_url()
    if not public_url:
        print("\n      Hints:")
        print("        • Is ngrok installed?  brew install ngrok")
        print("        • Is ngrok authenticated?  ngrok config add-authtoken <TOKEN>")
        kill_all(processes)
        sys.exit(1)

    print(f"      Tunnel URL: {public_url}")

    # ------------------------------------------------------------------
    # 4. Create Vapi assistant
    # ------------------------------------------------------------------
    _print_step(4, TOTAL_STEPS, "Registering Vapi assistant...")
    assistant = create_vapi_assistant(public_url)
    if not assistant:
        kill_all(processes)
        sys.exit(1)

    assistant_id   = assistant.get("id", "unknown")
    assistant_name = assistant.get("name", "Voice Scheduling Assistant")
    print(f"      '{assistant_name}' created (ID: {assistant_id}) ✓")

    # Inject assistant ID + public key into the running FastAPI server
    # so the /demo page is immediately usable without a restart.
    public_key = os.environ.get("VAPI_PUBLIC_KEY", "")
    try:
        httpx.post(
            f"http://localhost:{BACKEND_PORT}/internal/set-agent",
            json={"assistant_id": assistant_id, "public_key": public_key},
            timeout=5,
        )
    except Exception:
        pass  # non-fatal — demo page falls back to env vars on Render

    # ------------------------------------------------------------------
    # 5. Ready — keep alive
    # ------------------------------------------------------------------
    demo_url = f"http://localhost:{BACKEND_PORT}/demo"
    _print_step(5, TOTAL_STEPS, "Agent is live!\n")
    separator = "─" * 62
    print(separator)
    print(f"  🎤  TALK NOW  →  {demo_url}")
    print()
    print(f"  Backend     →  http://localhost:{BACKEND_PORT}")
    print(f"  Public URL  →  {public_url}")
    print(f"  API docs    →  http://localhost:{BACKEND_PORT}/docs")
    print(f"  ngrok UI    →  http://localhost:4040")
    print()
    print(f"  Vapi assistant : {assistant_name}")
    print(f"  Assistant ID   : {assistant_id}")
    print()
    print(f"  To assign a phone number:")
    print(f"    Vapi Dashboard → Phone Numbers → Buy → link to '{assistant_name}'")
    print(separator)
    print("\nPress Ctrl+C to stop all services.\n")

    # Register signal handlers for clean shutdown
    def _shutdown(sig, frame) -> None:
        print("\nShutting down services...")
        kill_all(processes)
        print("All services stopped. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Watch-dog loop — bail if a subprocess dies unexpectedly
    while True:
        for proc in processes:
            if proc.poll() is not None:
                name = "uvicorn" if proc is processes[0] else "ngrok"
                print(f"\nERROR: {name} process exited unexpectedly (code {proc.returncode}).")
                kill_all(processes)
                sys.exit(1)
        time.sleep(2)


if __name__ == "__main__":
    main()
