"""Production entry point with a clean (exit 0) idle shutdown."""

import uvicorn

from .config import get_settings
from .main import create_app


def run():
    settings = get_settings()

    def shutdown():
        # Raising SIGTERM can produce a nonzero exit and an immediate Fly
        # on-failure restart. Let Uvicorn drain and return normally instead.
        server.should_exit = True

    app = create_app(settings, idle_shutdown=shutdown)
    server = uvicorn.Server(uvicorn.Config(
        app, host=settings.host, port=settings.port, workers=1,
        proxy_headers=True, forwarded_allow_ips="*",
    ))
    server.run()


if __name__ == "__main__":
    run()
