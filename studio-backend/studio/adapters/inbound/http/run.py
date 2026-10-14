"""Console entry point: run the API with uvicorn."""

from __future__ import annotations

import os

import uvicorn

__all__ = ["main"]


def main() -> None:
    """Start the uvicorn server using the app factory."""
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "studio.adapters.inbound.http.app:create_app",
        factory=True,
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
