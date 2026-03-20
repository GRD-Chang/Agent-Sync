from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .queries import DashboardQueryService

if TYPE_CHECKING:
    from starlette.applications import Starlette


def create_dashboard_app(home: Path | None = None) -> "Starlette":
    from .app import create_dashboard_app as _create_dashboard_app

    return _create_dashboard_app(home)


def run_dashboard(
    *,
    home: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    from .app import run_dashboard as _run_dashboard

    _run_dashboard(home=home, host=host, port=port)


__all__ = ["DashboardQueryService", "create_dashboard_app", "run_dashboard"]
