"""Launcher for VideoEditorY.

Run with: python run.py
Starts the local server and opens it in your default browser. Works the
same way on Windows and Linux — the "GUI" is just this local web app.
"""

import socket
import threading
import time
import webbrowser

import uvicorn

from backend.main import app


def _find_free_port(preferred: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def main():
    port = _find_free_port(8000)
    url = f"http://127.0.0.1:{port}"

    def _open_browser():
        time.sleep(1.0)
        try:
            webbrowser.open(url)
        except Exception:
            print(f"Could not auto-open a browser — open {url} manually.")

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"VideoEditorY running at {url}  (press Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
