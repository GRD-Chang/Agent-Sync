from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .dispatcher import CodexTeamDispatcher
from .runner import CaptureCodexRunner, RealCodexRunner
from .store import CodexTeamStore


def add_codex_team_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser], formatter_class: type[argparse.HelpFormatter]) -> None:
    parser = subparsers.add_parser(
        "codex-team",
        help="管理 Codex Team harness run",
        description="创建、查看、暂停恢复和取消 Codex Team run。",
        formatter_class=formatter_class,
    )
    nested = parser.add_subparsers(dest="codex_team_command", required=True, metavar="<codex-team-command>")

    start = nested.add_parser("start", help="创建 Codex Team run", formatter_class=formatter_class)
    start.add_argument("--repo-root", required=True, help="目标代码仓库根目录")
    input_group = start.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="用户任务说明文本")
    input_group.add_argument("--input-file", help="读取用户任务说明的文件")
    start.add_argument("--runner", choices=["real", "capture"], default="real", help="runner 类型")
    start.add_argument("--no-run", action="store_true", help="只创建 run，不启动 Codex")
    start.add_argument("--max-steps", type=int, default=50, help="最多推进多少个 agent step")
    start.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    status = nested.add_parser("status", help="查看 run 状态", formatter_class=formatter_class)
    status.add_argument("run_id", help="Codex Team run id")
    status.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    show = nested.add_parser("show", help="查看 run 详情", formatter_class=formatter_class)
    show.add_argument("run_id", help="Codex Team run id")
    show.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    logs = nested.add_parser("logs", help="查看 run event log", formatter_class=formatter_class)
    logs.add_argument("run_id", help="Codex Team run id")
    logs.add_argument("--tail", type=int, default=50, help="显示最后 N 条 event")
    logs.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    answer = nested.add_parser("answer", help="回答 paused run 的问题", formatter_class=formatter_class)
    answer.add_argument("run_id", help="Codex Team run id")
    answer_group = answer.add_mutually_exclusive_group(required=True)
    answer_group.add_argument("--text", help="回答文本")
    answer_group.add_argument("--file", help="从文件读取回答")
    answer.add_argument("--runner", choices=["real", "capture"], default="real", help="runner 类型")
    answer.add_argument("--no-run", action="store_true", help="只记录回答，不继续启动 Codex")
    answer.add_argument("--max-steps", type=int, default=50, help="最多推进多少个 agent step")
    answer.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    resume = nested.add_parser("resume", help="恢复 failed Codex Team run", formatter_class=formatter_class)
    resume.add_argument("run_id", help="Codex Team run id")
    resume.add_argument("--runner", choices=["real", "capture"], default="real", help="runner 类型")
    resume.add_argument("--max-steps", type=int, default=50, help="最多推进多少个 agent step")
    resume.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    cancel = nested.add_parser("cancel", help="取消 Codex Team run", formatter_class=formatter_class)
    cancel.add_argument("run_id", help="Codex Team run id")
    cancel.add_argument("--reason", required=True, help="取消原因")
    cancel.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")


def handle_codex_team_command(args: argparse.Namespace, *, home: Path) -> dict[str, Any]:
    store = CodexTeamStore(home=home)
    command = args.codex_team_command
    if command == "start":
        input_text = _read_input_arg(args.input, args.input_file)
        if args.no_run:
            metadata = store.create_run(repo_root=Path(args.repo_root), input_text=input_text)
            metadata = store.update_metadata(metadata["run_id"], state="planning", current_owner="planner")
            store.append_event(metadata["run_id"], {"type": "state_changed", "state": "planning", "owner": "planner"})
            return metadata
        dispatcher = CodexTeamDispatcher(store=store, runner=_runner_from_name(args.runner))
        outcome = dispatcher.start_run(repo_root=Path(args.repo_root), input_text=input_text)
        outcome = dispatcher.run_until_idle(outcome.run_id, max_steps=args.max_steps)
        return {"outcome": outcome.__dict__, "metadata": store.load_metadata(outcome.run_id)}
    if command == "status":
        metadata = store.load_metadata(args.run_id)
        return {
            "run_id": metadata["run_id"],
            "state": metadata.get("state"),
            "status": metadata.get("status"),
            "current_owner": metadata.get("current_owner"),
            "current_attempt": metadata.get("current_attempt"),
            "last_error": metadata.get("last_error"),
            "run_home": metadata.get("run_home"),
        }
    if command == "show":
        metadata = store.load_metadata(args.run_id)
        payload: dict[str, Any] = {
            "metadata": metadata,
            "events": store.read_events(args.run_id),
        }
        pending = store.pending_question_path(args.run_id)
        if pending.exists():
            payload["pending_question"] = json.loads(pending.read_text(encoding="utf-8"))
        return payload
    if command == "logs":
        events = store.read_events(args.run_id)
        tail = max(args.tail, 0)
        return {"run_id": args.run_id, "events": events[-tail:] if tail else []}
    if command == "answer":
        text = _read_input_arg(args.text, args.file)
        dispatcher = CodexTeamDispatcher(store=store, runner=_runner_from_name(args.runner))
        outcome = dispatcher.answer(args.run_id, text)
        if not args.no_run:
            outcome = dispatcher.run_until_idle(args.run_id, max_steps=args.max_steps)
        return outcome.__dict__
    if command == "resume":
        if args.max_steps <= 0:
            metadata = store.load_metadata(args.run_id)
            if metadata.get("state") != "failed":
                raise ValueError("resume is only allowed for failed codex team runs")
            error = {
                "code": "MaxStepsExceeded",
                "message": f"codex team exceeded max_steps={args.max_steps}",
            }
            outcome = {
                "run_id": args.run_id,
                "state": "failed",
                "status": "failed",
                "owner": metadata.get("current_owner"),
                "event": "failed",
                "error": error,
            }
            return {"outcome": outcome, "metadata": metadata}
        dispatcher = CodexTeamDispatcher(store=store, runner=_runner_from_name(args.runner))
        outcome = dispatcher.resume(args.run_id)
        outcome = dispatcher.run_until_idle(args.run_id, max_steps=args.max_steps - 1)
        return {"outcome": outcome.__dict__, "metadata": store.load_metadata(args.run_id)}
    if command == "cancel":
        outcome = CodexTeamDispatcher(store=store).cancel(args.run_id, args.reason)
        return outcome.__dict__
    raise ValueError(f"unsupported codex-team command: {command}")


def _read_input_arg(text: str | None, file_path: str | None) -> str:
    if text is not None:
        return text
    if file_path is None:
        raise ValueError("input text or file is required")
    return Path(file_path).read_text(encoding="utf-8")


def _runner_from_name(name: str):
    if name == "capture":
        return CaptureCodexRunner()
    if name == "real":
        return RealCodexRunner()
    raise ValueError(f"unsupported codex-team runner: {name}")
