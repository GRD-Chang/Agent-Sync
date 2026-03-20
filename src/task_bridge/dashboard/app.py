from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .queries import DashboardQueryService


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    href: str


NAV_ITEMS = [
    NavItem("overview", "Overview", "/overview"),
    NavItem("jobs", "Jobs", "/jobs"),
    NavItem("tasks", "Tasks", "/tasks"),
    NavItem("worker-queue", "Worker & Queue", "/worker-queue"),
    NavItem("alerts", "Alerts", "/alerts"),
    NavItem("health", "Health", "/health"),
]
PLACEHOLDER_COPY = {
    "jobs": "Job-level browsing will land here in a later slice. This foundation stays read-only and tied to existing job.json records.",
    "tasks": "Task details and filtering will land here in a later slice. The dashboard currently uses the existing task JSON contract without introducing write actions.",
    "worker-queue": "Worker lanes and queue drill-down will land here in a later slice. Current queue facts already power the Overview worker utilization section.",
    "alerts": "Alert summaries will land here in a later slice. This MVP only surfaces terminal-state and follow-up semantics indirectly through Overview data.",
    "health": "Daemon and storage health views will land here in a later slice. The shell is ready, but this page is intentionally a placeholder in MVP v1.",
}

templates = Jinja2Templates(directory=str(files("task_bridge.dashboard").joinpath("templates")))


def create_dashboard_app(home: Path | None = None) -> Starlette:
    service = DashboardQueryService(home)
    app = Starlette(
        debug=False,
        routes=[
            Route("/", endpoint=redirect_to_overview),
            Route("/overview", endpoint=overview_page),
            Route("/jobs", endpoint=placeholder_page),
            Route("/tasks", endpoint=placeholder_page),
            Route("/worker-queue", endpoint=placeholder_page),
            Route("/alerts", endpoint=placeholder_page),
            Route("/health", endpoint=placeholder_page),
            Mount(
                "/static",
                app=StaticFiles(directory=str(files("task_bridge.dashboard").joinpath("static"))),
                name="static",
            ),
        ],
    )
    app.state.dashboard_query_service = service
    return app


async def redirect_to_overview(request: Request):
    return RedirectResponse(request.url_for("overview_page"), status_code=307)


async def overview_page(request: Request):
    context = _base_context(request, "overview", "Overview")
    try:
        overview = request.app.state.dashboard_query_service.overview()
    except Exception as exc:  # pragma: no cover - exercised via browser smoke path
        context.update(
            {
                "error_title": "Dashboard unavailable",
                "error_message": str(exc),
            }
        )
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=context,
            status_code=500,
        )

    context["overview"] = overview
    return templates.TemplateResponse(request=request, name="overview.html", context=context)


async def placeholder_page(request: Request):
    page_key = request.url.path.strip("/") or "overview"
    active = page_key if any(item.key == page_key for item in NAV_ITEMS) else "overview"
    context = _base_context(request, active, next(item.label for item in NAV_ITEMS if item.key == active))
    context["placeholder_copy"] = PLACEHOLDER_COPY[active]
    return templates.TemplateResponse(request=request, name="placeholder.html", context=context)


def run_dashboard(
    *,
    home: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    uvicorn.run(
        create_dashboard_app(home),
        host=host,
        port=port,
        log_level="warning",
    )


def _base_context(request: Request, active_page: str, page_title: str) -> dict[str, object]:
    return {
        "request": request,
        "active_page": active_page,
        "page_title": page_title,
        "nav_items": NAV_ITEMS,
    }
