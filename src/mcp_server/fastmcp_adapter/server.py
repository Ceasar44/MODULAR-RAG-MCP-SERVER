"""Run with python -m src.mcp_server.fastmcp_adapter.server."""

import logging
import sys

from .config import get_fastmcp_settings

logger = logging.getLogger(__name__)


def run_http_server() -> None:
    settings = get_fastmcp_settings()
    logging.basicConfig(level=settings.log_level, stream=sys.stderr)
    from .app import mcp

    mcp.run(
        transport="http", host=settings.host, port=settings.port,
        path=settings.path, log_level=settings.log_level.lower(),
    )


def main() -> int:
    try:
        run_http_server()
        return 0
    except Exception:
        logger.exception("RAG HTTP server failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
