from __future__ import annotations

import ctypes
import json
import logging
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any


HOST = "127.0.0.1"
PORT = 8765
APP_URL = f"http://{HOST}:{PORT}"
ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "data" / "sevenlabs-desktop.log"


def _healthcheck() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=0.8) as response:
            return bool(json.loads(response.read()).get("ok"))
    except Exception:
        return False


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "SevenLabs could not start", 0x10)
    except Exception:
        pass


def _write_error(error: BaseException) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    LOG_FILE.write_text(details, encoding="utf-8")


def _start_server() -> tuple[Any | None, threading.Thread | None]:
    if _healthcheck():
        return None, None

    import uvicorn
    from app.main import app

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # pythonw.exe intentionally has no stdout/stderr console. Uvicorn's default
    # colored console formatter cannot be configured in that environment.
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="SevenLabs server", daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _healthcheck():
            return server, thread
        if not thread.is_alive():
            break
        time.sleep(0.15)
    raise RuntimeError("The local SevenLabs service could not start. Port 8765 may already be in use.")


def run() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SevenLabs.Desktop.1")
    except Exception:
        pass

    server, thread = _start_server()
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(
        "SevenLabs",
        APP_URL,
        width=1440,
        height=860,
        min_size=(1024, 680),
        resizable=True,
        background_color="#0d0e0c",
        text_select=True,
    )

    def stop_owned_server() -> None:
        if server is not None:
            server.should_exit = True

    window.events.closed += stop_owned_server
    try:
        webview.start(debug=False, private_mode=False)
    finally:
        stop_owned_server()
        if thread is not None:
            thread.join(timeout=5)


def main() -> int:
    try:
        run()
        return 0
    except Exception as error:
        _write_error(error)
        _show_error(f"{error}\n\nDetails were saved to:\n{LOG_FILE}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
