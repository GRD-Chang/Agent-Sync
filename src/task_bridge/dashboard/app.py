from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlencode

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from .i18n import DEFAULT_LOCALE, LOCALE_SWITCH_ITEMS, get_messages, resolve_locale
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
DEFAULT_FONT_PRESET = "sans"
FONT_PRESET_ITEMS = (
    {"key": "sans"},
    {"key": "editorial"},
    {"key": "precision"},
    {"key": "mono"},
)

templates = Jinja2Templates(directory=str(files("task_bridge.dashboard").joinpath("templates")))


def create_dashboard_app(home: Path | None = None) -> Starlette:
    app = Starlette(
        debug=False,
        routes=[
            Route("/", endpoint=redirect_to_overview),
            Route("/overview", endpoint=overview_page),
            Route("/jobs", endpoint=jobs_page),
            Route("/tasks", endpoint=tasks_page),
            Route("/worker-queue", endpoint=worker_queue_page),
            Route("/alerts", endpoint=alerts_page),
            Route("/health", endpoint=health_page),
            Mount(
                "/static",
                app=StaticFiles(directory=str(files("task_bridge.dashboard").joinpath("static"))),
                name="static",
            ),
        ],
    )
    app.state.dashboard_home = home
    return app


async def redirect_to_overview(request: Request):
    return RedirectResponse(
        _path_with_locale(request.url_for("overview_page").path, (), _request_locale(request)),
        status_code=307,
    )


async def overview_page(request: Request):
    context = _base_context(request, "overview")
    try:
        overview = _dashboard_service(request).overview()
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
        jobs = _dashboard_service(request).jobs(
            selected_job_id=_query_param_value(request, "job"),
            selected_task_id=_query_param_value(request, "task"),
            selected_view=_query_param_value(request, "view"),
            selected_detail_view=_query_param_value(request, "detail_view"),
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
    context["page_chrome"] = _page_chrome_context(
        context,
        breadcrumbs=_selection_breadcrumbs(
            request,
            context,
            current_label=(
                jobs.selected_task.task_id
                if jobs.selected_task and _query_param_value(request, "task")
                else jobs.selected_job.title if jobs.selected_job and _query_param_value(request, "job") else None
            ),
            exclude_query_keys=("job", "task", "detail_view", "lang"),
        ),
    )
    return templates.TemplateResponse(request=request, name="jobs.html", context=context)


async def tasks_page(request: Request):
    context = _base_context(request, "tasks")
    context["page_title"] = context["ui"]["tasks"]["title"]
    try:
        tasks = _dashboard_service(request).tasks(
            selected_job_id=_query_param_value(request, "job"),
            selected_task_id=_query_param_value(request, "task"),
            selected_state=_query_param_value(request, "state"),
            selected_agent=_query_param_value(request, "agent"),
            selected_page=_query_param_value(request, "page"),
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
    context["page_chrome"] = _page_chrome_context(
        context,
        breadcrumbs=_selection_breadcrumbs(
            request,
            context,
            current_label=tasks.selected_task.task_id if tasks.selected_task and _query_param_value(request, "task") else None,
            exclude_query_keys=("task", "lang"),
        ),
    )
    return templates.TemplateResponse(request=request, name="tasks.html", context=context)


async def worker_queue_page(request: Request):
    context = _base_context(request, "worker-queue")
    context["page_title"] = context["ui"]["worker_queue"]["title"]
    try:
        snapshot = _dashboard_service(request).worker_queue()
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["worker_queue"]["error_title"],
            error_body=context["ui"]["worker_queue"]["error_body"],
            error_label=context["ui"]["worker_queue"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-worker-queue-error-state",
        )

    context["worker_queue"] = snapshot
    return templates.TemplateResponse(request=request, name="worker_queue.html", context=context)


async def alerts_page(request: Request):
    context = _base_context(request, "alerts")
    context["page_title"] = context["ui"]["alerts"]["title"]
    try:
        snapshot = _dashboard_service(request).alerts(
            risk_page=_query_param_value(request, "risk_page"),
            followup_page=_query_param_value(request, "followup_page"),
        )
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["alerts"]["error_title"],
            error_body=context["ui"]["alerts"]["error_body"],
            error_label=context["ui"]["alerts"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-alerts-error-state",
        )

    context["alerts"] = snapshot
    return templates.TemplateResponse(request=request, name="alerts.html", context=context)


async def health_page(request: Request):
    context = _base_context(request, "health")
    context["page_title"] = context["ui"]["health"]["title"]
    try:
        snapshot = _dashboard_service(request).health()
    except Exception as exc:  # pragma: no cover
        return _render_live_page_error(
            request,
            context=context,
            error_title=context["ui"]["health"]["error_title"],
            error_body=context["ui"]["health"]["error_body"],
            error_label=context["ui"]["health"]["error_label"],
            error_message=str(exc),
            error_testid="dashboard-health-error-state",
        )

    context["health"] = snapshot
    return templates.TemplateResponse(request=request, name="health.html", context=context)


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
    locale = _request_locale(request)
    ui = get_messages(locale)
    return {
        "request": request,
        "active_page": active_page,
        "page_title": ui["nav"][active_page],
        "nav_items": [
            {
                "key": item.key,
                "label": ui["nav"][item.key],
                "href": _path_with_locale(item.href, (), locale),
            }
            for item in NAV_ITEMS
        ],
        "locale": locale,
        "locale_options": _locale_options(request, locale),
        "font_options": [
            {
                "key": item["key"],
                "label": ui["shell"]["font_options"][item["key"]],
                "sample": ui["shell"]["font_samples"][item["key"]],
                "is_default": item["key"] == DEFAULT_FONT_PRESET,
            }
            for item in FONT_PRESET_ITEMS
        ],
        "default_font_preset": DEFAULT_FONT_PRESET,
        "page_chrome": _page_chrome_context(
            {
                "active_page": active_page,
                "locale": locale,
                "ui": ui,
            }
        ),
        "ui": ui,
        "html_lang": ui["html_lang"],
    }


def _query_param_value(request: Request, key: str) -> str | None:
    value = request.query_params.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _dashboard_service(request: Request) -> DashboardQueryService:
    locale = _request_locale(request)
    now_override = os.environ.get("TASK_BRIDGE_DASHBOARD_NOW")
    if now_override:
        return DashboardQueryService(
            request.app.state.dashboard_home,
            locale=locale,
            now_provider=lambda: now_override,
        )
    return DashboardQueryService(request.app.state.dashboard_home, locale=locale)


def _request_locale(request: Request) -> str:
    return resolve_locale(_query_param_value(request, "lang"))


def _locale_options(request: Request, active_locale: str) -> list[dict[str, object]]:
    base_params = _request_query_pairs(request, exclude_keys=("lang",))
    return [
        {
            **item,
            "href": _path_with_locale(request.url.path, base_params, str(item["code"])),
            "is_active": str(item["code"]) == active_locale,
        }
        for item in LOCALE_SWITCH_ITEMS
    ]


def _page_chrome_context(
    context: dict[str, object],
    *,
    breadcrumbs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    ui = context["ui"]
    active_page = str(context["active_page"])
    breadcrumb_items = breadcrumbs or [{"label": ui["nav"][active_page], "href": None, "is_current": True}]
    root_label = str(breadcrumb_items[0]["label"])
    root_href = breadcrumb_items[0].get("href")
    return {
        "label": ui["shell"]["breadcrumb_label"],
        "breadcrumbs": breadcrumb_items,
        "back_href": root_href,
        "back_label": ui["shell"]["back_to_section"].format(section=root_label) if root_href else None,
    }


def _selection_breadcrumbs(
    request: Request,
    context: dict[str, object],
    *,
    current_label: str | None,
    exclude_query_keys: tuple[str, ...],
) -> list[dict[str, object]]:
    ui = context["ui"]
    active_page = str(context["active_page"])
    locale = str(context["locale"])
    root_pairs = _request_query_pairs(request, exclude_keys=exclude_query_keys)
    root_href = _path_with_locale(request.url.path, root_pairs, locale)
    breadcrumbs = [
        {
            "label": ui["nav"][active_page],
            "href": root_href if current_label else None,
            "is_current": current_label is None,
        }
    ]
    if current_label:
        breadcrumbs.append({"label": current_label, "href": None, "is_current": True})
    return breadcrumbs


def _request_query_pairs(request: Request, *, exclude_keys: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    return [
        (key, value.strip())
        for key, value in request.query_params.multi_items()
        if key not in exclude_keys and value.strip()
    ]


def _path_with_locale(path: str, pairs: tuple[tuple[str, str], ...] | list[tuple[str, str]], locale: str) -> str:
    query_items = [(key, value) for key, value in pairs if value]
    if locale != DEFAULT_LOCALE:
        query_items.append(("lang", locale))
    if not query_items:
        return path
    return f"{path}?{urlencode(query_items)}"
