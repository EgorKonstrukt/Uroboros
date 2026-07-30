import asyncio
import threading
import uvicorn
from pathlib import Path
from typing import Optional

from server.app import app
from server.auth.database import init_db, close_db


class AuthServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 25581, db_path: Optional[Path] = None):
        self.host = host
        self.port = port
        self.db_path = db_path
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self):
        db_path = self.db_path
        host = self.host
        port = self.port

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if db_path:
                    loop.run_until_complete(init_db(db_path))
                config = uvicorn.Config(
                    app,
                    host=host,
                    port=port,
                    log_level="error",
                    loop="asyncio",
                )
                self._server = uvicorn.Server(config)
                loop.run_until_complete(self._server.serve())
            finally:
                loop.run_until_complete(close_db())
                loop.close()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
