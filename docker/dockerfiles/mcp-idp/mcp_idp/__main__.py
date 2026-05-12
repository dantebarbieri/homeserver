"""CLI entry point — ``python -m mcp_idp`` runs uvicorn on the bundled app."""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn  # noqa: PLC0415

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    log_level = os.environ.get("LOG_LEVEL", "info")
    uvicorn.run(
        "mcp_idp:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
