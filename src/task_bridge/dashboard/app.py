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

from .i18n import DEFAULT_LOCALE, get_messages
from .queries import DashboardQueryService


@dataclass(frozen=True)
class NavItem:
    key: str
    href: str


NAV_ITEMS = [
    NavItem("overview", "/overview"),
    NavItem("jobs", "/jobs"),
    NavItem("tasks", "/tasks"),
    NavItem("worker-queue", "/worker-queue"),
    NavItem("alerts", "/alerts"),
    NavItem("health", "/health"),
]

templates = Jinja2Templates(directory=str(files("task_bridge.dashboard").joinpath("templates")))


def create_dashboard_app(home: Path | None = None) -> Starlette:
    service = DashboardQueryService(home, locale=DEFAULT_LOCALE)
    app = Starlette(
        debug=False,
        routes=[
            Route("/", endpoint=redirect_to_overview),
            Route("/overview", endpoint=overview_page),
            Route("/jobs", endpoint=jobs_page),
            Route("/tasks", endpoint=tasks_page),
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
    context = _base_context(request, "overview")
    try:
        overview = request.app.state.dashboard_query_service.overview()
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["overview"]["error_title"],
            error_body=context["ui"]["overview"]["error_body"],
            error_label=context["ui"]["overview"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-overview-error-state",
        )

    context["overview"] = overview
    return templates.TemplateResponse(request=request, name="overview.html", context=context)


async def jobs_page(request: Request):
    context = _base_context(request, "jobs")
    context["page_title"] = context["ui"]["jobs"]["title"]
    try:
        jobs = request.app.state.dashboard_query_service.jobs(
            selected_job_id=_query_param_value(request, "job"),
        )
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["jobs"]["error_title"],
            error_body=context["ui"]["jobs"]["error_body"],
            error_label=context["ui"]["jobs"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-jobs-error-state",
        )

    context["jobs"] = jobs
    return templates.TemplateResponse(request=request, name="jobs.html", context=context)


async def tasks_page(request: Request):
    context = _base_context(request, "tasks")
    context["page_title"] = context["ui"]["tasks"]["title"]
    try:
        tasks = request.app.state.dashboard_query_service.tasks(
            selected_job_id=_query_param_value(request, "job"),
            selected_task_id=_query_param_value(request, "task"),
        )
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["tasks"]["error_title"],
            error_body=context["ui"]["tasks"]["error_body"],
            error_label=context["ui"]["tasks"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-tasks-error-state",
        )

    context["tasks"] = tasks
    return templates.TemplateResponse(request=request, name="tasks.html", context=context)


async def placeholder_page(request: Request):
    page_key = request.url.path.strip("/") or "overview"
    active = page_key if any(item.key == page_key for item in NAV_ITEMS) else "overview"
    context = _base_context(request, active)
    ui = context["ui"]
    context["placeholder_copy"] = ui["placeholder"]["copy"][active]
    context["placeholder_heading"] = ui["placeholder"]["shell_heading"].format(page_title=context["page_title"])
    return templates.TemplateResponse(request=request, name="placeholder.html", context=context)


def run_dashboard(*, home: Path | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(create_dashboard_app(home), host=host, port=port, log_level="warning")


def _render_live_page_error(
    request: Request,
    *,
    context: dict[str, object],
    error_title: str,
    error_body: str,
    error_label: str,
    error_message: str,
    error_testid: str,
):
    context.update(
        {
            "page_title": error_title,
            "error_title": error_title,
            "error_body": error_body,
            "error_label": error_label,
            "error_message": error_message,
            "error_testid": error_testid,
        }
    )
    return templates.TemplateResponse(request=request, name="error.html", context=context, status_code=500)


def _base_context(request: Request, active_page: str) -> dict[str, object]:
    ui = get_messages(DEFAULT_LOCALE)
    return {
        "request": request,
        "active_page": active_page,
        "page_title": ui["nav"][active_page],
        "nav_items": [{"key": item.key, "label": ui["nav"][item.key], "href": item.href} for item in NAV_ITEMS],
        "ui": ui,
        "html_lang": ui["html_lang"],
    }


def _query_param_value(request: Request, key: str) -> str | None:
    value = request.query_params.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
