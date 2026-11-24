"""Fælles opsætning for testene: tom testdatabase i en midlertidig mappe og efterlignede apps.

Kør fra mappen fangarr:  pip install pytest  og derefter  python -m pytest -q tests
Testene rører aldrig den rigtige database (/opt/fangarr/data) og sender intet til Telegram.
"""

import os
import socket
import sys
import tempfile
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import efterligning  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
DATA = tempfile.mkdtemp(prefix="fangarr-test-")
for k in list(os.environ):
    if k.endswith(("_URL", "_APIKEY", "_TOKEN")) or k in ("ARR_INSTANCES", "TELEGRAM_CHAT_ID", "WIDGET_KEY"):
        os.environ.pop(k)
os.environ.update(efterligning.env(PORT))
os.environ.update({"DATA_DIR": DATA, "DISK_PATH": DATA, "TZ": "Europe/Copenhagen", "FANGARR_VERSION": "test"})


def _start_mock():
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(efterligning.app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.05)


_start_mock()

from app import main  # noqa: E402

main.background_loop = lambda: None      # baggrundsjobbet kører ikke under testene
main._latest_version = lambda: ""        # spørg ikke GitHub
main.tg.start = lambda: None             # læs ikke knaptryk i baggrunden – testene kalder poll_once selv


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c
