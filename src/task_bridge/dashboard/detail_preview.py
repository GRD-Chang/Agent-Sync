from __future__ import annotations

import re
from pathlib import Path

from .snapshots import (
    DETAIL_PREVIEW_CHAR_LIMIT,
    DETAIL_PREVIEW_LINE_LIMIT,
    DetailPreview,
    DetailPreviewBlock,
)

_HEADING_PATTERN = re.compile(r"^(#{1,3})\s+(.+)$")
_LIST_ITEM_PATTERN = re.compile(r"^[-*]\s+(.+)$")
_QUOTE_PATTERN = re.compile(r"^>\s?(.*)$")


def detail_preview_status(path_value: str) -> str:
    if not path_value:
        return "missing"

    path = Path(path_value)
    if not path.is_file():
        return "missing"

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:  # pragma: no cover
        return "error"

    return "empty" if not raw_text.strip() else "rendered"


def load_detail_preview(path_value: str) -> DetailPreview:
    if not path_value:
        return DetailPreview(status="missing", path=path_value)

    path = Path(path_value)
    if not path.is_file():
        return DetailPreview(status="missing", path=path_value)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        return DetailPreview(status="error", path=path_value, error_message=str(exc))

    if not raw_text.strip():
        return DetailPreview(status="empty", path=path_value)

    preview_text, is_truncated = clamp_preview_text(raw_text)
    blocks = parse_markdown_blocks(preview_text)
    if not blocks:
        return DetailPreview(status="empty", path=path_value, is_truncated=is_truncated)

    return DetailPreview(
        status="rendered",
        path=path_value,
        blocks=tuple(blocks),
        is_truncated=is_truncated,
    )


def clamp_preview_text(
    text: str,
    *,
    line_limit: int = DETAIL_PREVIEW_LINE_LIMIT,
    char_limit: int = DETAIL_PREVIEW_CHAR_LIMIT,
) -> tuple[str, bool]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    is_truncated = False
    if len(lines) > line_limit:
        lines = lines[:line_limit]
        is_truncated = True
    limited = "\n".join(lines)
    if len(limited) > char_limit:
        limited = limited[:char_limit].rstrip()
        is_truncated = True
    return limited.strip(), is_truncated


def parse_markdown_blocks(text: str) -> list[DetailPreviewBlock]:
    if not text:
        return []

    blocks: list[DetailPreviewBlock] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    quote_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append(DetailPreviewBlock(kind="paragraph", text=" ".join(paragraph_lines).strip()))
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append(DetailPreviewBlock(kind="list", items=tuple(list_items)))
            list_items = []

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            blocks.append(DetailPreviewBlock(kind="quote", text=" ".join(quote_lines).strip()))
            quote_lines = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            blocks.append(DetailPreviewBlock(kind="code", text="\n".join(code_lines).rstrip()))
            code_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if in_code:
            if line.startswith("```"):
                flush_code()
                in_code = False
                continue
            code_lines.append(raw_line)
            continue

        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_quote()
            in_code = True
            continue

        heading = _HEADING_PATTERN.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_quote()
            blocks.append(
                DetailPreviewBlock(
                    kind="heading",
                    text=heading.group(2).strip(),
                    level=len(heading.group(1)),
                )
            )
            continue

        list_item = _LIST_ITEM_PATTERN.match(line)
        if list_item:
            flush_paragraph()
            flush_quote()
            list_items.append(list_item.group(1).strip())
            continue

        quote = _QUOTE_PATTERN.match(line)
        if quote and quote.group(1).strip():
            flush_paragraph()
            flush_list()
            quote_lines.append(quote.group(1).strip())
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_quote()
            continue

        paragraph_lines.append(line.strip())

    flush_paragraph()
    flush_list()
    flush_quote()
    if in_code:
        flush_code()
    return blocks
