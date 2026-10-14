"""Container dependency for FastAPI routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from studio.container import Container

__all__ = ["get_container", "ContainerDep"]

_container: Container | None = None


def get_container() -> Container:
    """Return the shared Container singleton, creating it on first use."""
    global _container
    if _container is None:
        _container = Container()
    return _container


ContainerDep = Annotated[Container, Depends(get_container)]
