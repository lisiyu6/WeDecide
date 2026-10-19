"""Single-process server with a shutdown signal for long-lived room streams."""
from contextlib import suppress

import uvicorn


class Server(uvicorn.Server):
    async def shutdown(self, sockets=None):
        # Uvicorn drains requests before ASGI lifespan shutdown. Wake SSE readers
        # here: waiting until lifespan cleanup leaves those requests open forever.
        from .app import hub
        hub.close()
        await super().shutdown(sockets=sockets)


def run(host, port):
    config = uvicorn.Config(
        "wedecide.app:app", host=host, port=port, workers=1,
        proxy_headers=False, access_log=False, limit_concurrency=512,
        timeout_keep_alive=5, timeout_graceful_shutdown=5,
    )
    server = Server(config)
    with suppress(KeyboardInterrupt):
        server.run()
    if not server.started:
        raise SystemExit(3)
