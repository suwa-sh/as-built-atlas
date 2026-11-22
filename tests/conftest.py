"""Browser fixtures shared by the web application and the published site."""

import os
import socket
import time
from contextlib import contextmanager
from threading import Thread

import pytest
import uvicorn
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(
            executable_path=os.getenv("ABATLAS_CHROME")
        )
        yield chromium
        chromium.close()


@pytest.fixture
def serve_app():
    @contextmanager
    def serve(app):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            thread = Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() >= deadline:
                        pytest.fail("The browser test server failed to start")
                    time.sleep(0.01)
                yield f"http://127.0.0.1:{listener.getsockname()[1]}/"
            finally:
                server.should_exit = True
                thread.join(timeout=10)

    return serve
