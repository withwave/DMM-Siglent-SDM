#!/usr/bin/env python3
"""Launch the web UI as a chromeless desktop window.

Starts the FastAPI/uvicorn backend, waits for the port, and opens the
page in a Chromium-based browser using --app= so there is no tab bar
or URL bar - looks like a native app, no extra build toolchain needed.

Usage:
    python3 launch.py            # default 127.0.0.1:8000, local only
    python3 launch.py --lan      # bind 0.0.0.0 so other devices can connect

Ctrl-C in the terminal stops the server; closing the browser window
leaves the server running so other devices on the LAN keep working.
"""
import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PORT = 8000


def wait_for_port(host, port, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def find_chromium_browser():
    """Return path to a Chromium-based browser that supports --app."""
    system = platform.system()
    if system == "Darwin":
        for app in ("Google Chrome", "Microsoft Edge",
                    "Brave Browser", "Chromium", "Arc"):
            path = f"/Applications/{app}.app/Contents/MacOS/{app}"
            if os.path.exists(path):
                return path
    elif system == "Linux":
        for cmd in ("google-chrome", "google-chrome-stable", "chromium",
                    "chromium-browser", "microsoft-edge", "brave-browser"):
            p = shutil.which(cmd)
            if p:
                return p
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        for path in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            f"{local}\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ):
            if path and os.path.exists(path):
                return path
    return None


def open_app_window(url):
    """Open url in a chromeless --app window if Chromium is available,
    otherwise fall back to the OS default browser (regular tab)."""
    browser = find_chromium_browser()
    if browser:
        # --user-data-dir keeps this app's cookies/session separate from
        # the user's normal browsing profile, and lets --app work even
        # if their main Chrome is already running.
        user_data = HERE / ".browser-profile"
        args = [
            browser,
            f"--app={url}",
            f"--user-data-dir={user_data}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1100,800",
        ]
        print(f"[launch] opening chromeless window via {Path(browser).name}")
        return subprocess.Popen(args)
    # Fallback: regular browser tab.
    print("[launch] no Chromium-based browser found, opening default browser")
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", url])
    elif system == "Linux":
        subprocess.run(["xdg-open", url])
    elif system == "Windows":
        os.startfile(url)  # type: ignore[attr-defined]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--lan", action="store_true",
                        help="bind 0.0.0.0 instead of 127.0.0.1")
    parser.add_argument("--no-browser", action="store_true",
                        help="just run the server, don't open a window")
    args = parser.parse_args()

    bind_host = "0.0.0.0" if args.lan else "127.0.0.1"
    open_host = "127.0.0.1"  # always open the local URL in the browser
    url = f"http://{open_host}:{args.port}"

    print(f"[launch] starting uvicorn on {bind_host}:{args.port}")
    uvi = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web_app:app",
         "--host", bind_host, "--port", str(args.port)],
        cwd=HERE,
    )
    try:
        if not wait_for_port(open_host, args.port, timeout=20):
            print("[launch] uvicorn did not come up in 20s", file=sys.stderr)
            uvi.terminate()
            sys.exit(1)
        # Give DMM init + /api/info a moment so the UI doesn't flash empty.
        time.sleep(0.5)
        if not args.no_browser:
            open_app_window(url)
        print(f"[launch] {url} - Ctrl-C to stop server")
        uvi.wait()
    except KeyboardInterrupt:
        print("\n[launch] Ctrl-C, stopping uvicorn...")
    finally:
        if uvi.poll() is None:
            uvi.terminate()
            try:
                uvi.wait(timeout=5)
            except subprocess.TimeoutExpired:
                uvi.kill()


if __name__ == "__main__":
    main()
