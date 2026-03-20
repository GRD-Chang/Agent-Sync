from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .snapshots import PaginationLink, PaginationSnapshot

T = TypeVar("T")


def parse_page_number(value: str | None) -> int:
    if value is None:
        return 1
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def page_for_task(tasks: list[dict[str, object]], task_id: str, *, per_page: int) -> int:
    for index, task in enumerate(tasks):
        if str(task["id"]) == task_id:
            return index // per_page + 1
    return 1


def build_pagination_links(
    *,
    page_count: int,
    current_page: int,
    href_builder: Callable[[int], str],
) -> list[PaginationLink]:
    if page_count <= 1:
        return []

    if page_count <= 7:
        pages = list(range(1, page_count + 1))
    else:
        pages = sorted(
            {
                1,
                2,
                page_count - 1,
                page_count,
                max(current_page - 1, 1),
                current_page,
                min(current_page + 1, page_count),
            }
        )

    links: list[PaginationLink] = []
    previous_page = 0
    for page in pages:
        if page - previous_page > 1:
            links.append(PaginationLink(label="...", page=None, href=None, is_gap=True))
        links.append(
            PaginationLink(
                label=str(page),
                page=page,
                href=None if page == current_page else href_builder(page),
                is_current=page == current_page,
            )
        )
        previous_page = page
    return links


def paginate_items(
    items: list[T],
    *,
    page: int,
    per_page: int,
    href_builder: Callable[[int], str],
) -> tuple[list[T], PaginationSnapshot]:
    total_items = len(items)
    if total_items == 0:
        return (
            [],
            PaginationSnapshot(
                page=1,
                page_count=1,
                per_page=per_page,
                total_items=0,
                start_index=0,
                end_index=0,
                prev_href=None,
                next_href=None,
                page_links=[],
            ),
        )

    page_count = max((total_items - 1) // per_page + 1, 1)
    current_page = min(max(page, 1), page_count)
    start_index = (current_page - 1) * per_page
    end_index = min(start_index + per_page, total_items)
    return (
        items[start_index:end_index],
        PaginationSnapshot(
            page=current_page,
            page_count=page_count,
            per_page=per_page,
            total_items=total_items,
            start_index=start_index + 1,
            end_index=end_index,
            prev_href=href_builder(current_page - 1) if current_page > 1 else None,
            next_href=href_builder(current_page + 1) if current_page < page_count else None,
            page_links=build_pagination_links(
                page_count=page_count,
                current_page=current_page,
                href_builder=href_builder,
            ),
        ),
    )
