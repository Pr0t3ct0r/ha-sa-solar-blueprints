"""Test set-up. Home Assistant's harness is made for Linux; on Windows (development only) asyncio's event loop needs a
loopback socket pair, which the harness's socket guard blocks (it lets only AF_UNIX through, which Windows' event loop
does not use), so the guard is left off there; connections stay limited to 127.0.0.1. CI runs on Linux with the guard."""
import sys

if sys.platform == "win32":
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None
