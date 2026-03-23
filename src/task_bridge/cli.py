from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import sys
import time
from typing import Any

from .runtime import BridgeRuntime, LEADER_UNRESOLVED_FOLLOWUP_SECONDS
from .store import TaskStore, infer_worker_status


class HelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="task-bridge",
        description="本地任务桥：管理 job/task，分发任务给 worker，并回收终态结果。",
        epilog=(
            "常用示例:\n"
            "  task-bridge create-job --title \"开发模块 A\"\n"
            "  task-bridge create-task --requirement \"实现接口\" --assign code-agent\n"
            "  task-bridge list-tasks --json\n"
            "  task-bridge worker-status --json\n"
            "\n"
            "数据目录默认来自 TASK_BRIDGE_HOME；未设置时使用 ~/.openclaw/task-bridge"
        ),
        formatter_class=HelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="<command>",
    )

    create_job = subparsers.add_parser(
        "create-job",
        help="创建新 job，并自动设为当前 job",
        description="创建一个新的 job，并把它设为当前 job，后续未显式指定 --job 的命令默认作用于它。",
        formatter_class=HelpFormatter,
    )
    create_job.add_argument("--title", required=True, help="job 标题，用于说明这组任务的目标")
    create_job.add_argument(
        "--notify-target",
        default="team-leader",
        help="任务进入终态后默认通知的目标 agent",
    )

    list_jobs = subparsers.add_parser(
        "list-jobs",
        help="列出全部 job",
        description="列出当前数据目录中的全部 job，并标记哪个 job 是当前 job。",
        formatter_class=HelpFormatter,
    )
    list_jobs.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    show_job = subparsers.add_parser(
        "show-job",
        help="查看单个 job 详情",
        description="查看一个 job 的完整信息；未提供 job_id 时默认读取当前 job。",
        formatter_class=HelpFormatter,
    )
    show_job.add_argument("job_id", nargs="?", help="要查看的 job_id；省略时使用当前 job")
    show_job.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    use_job = subparsers.add_parser(
        "use-job",
        help="切换当前 job",
        description="把指定 job 设为当前 job，便于后续 create-task / show-job / list-tasks 省略 --job。",
        formatter_class=HelpFormatter,
    )
    use_job.add_argument("job_id", help="要切换到的 job_id")

    current_job = subparsers.add_parser(
        "current-job",
        help="查看当前 job",
        description="读取当前 job 的详细信息。如果当前 job 不存在，会返回错误。",
        formatter_class=HelpFormatter,
    )
    current_job.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    create_task = subparsers.add_parser(
        "create-task",
        help="创建 task，可选分配给 worker",
        description="创建一个新 task。若提供 --assign，则 bridge 后续可以把它派发给对应 worker。",
        formatter_class=HelpFormatter,
    )
    create_task.add_argument("--job", help="任务所属 job_id；省略时使用当前 job")
    create_task.add_argument("--assign", default="", dest="assigned_agent", help="assigned_agent，例如 code-agent")
    create_task.add_argument("--requirement", required=True, help="任务要求，建议写成自包含说明")

    list_tasks = subparsers.add_parser(
        "list-tasks",
        help="列出 task，可按状态或 worker 过滤",
        description="列出指定 job 下的 task；未提供 --job 时默认读取当前 job。",
        formatter_class=HelpFormatter,
    )
    list_tasks.add_argument("--job", help="要查看的 job_id；省略时使用当前 job")
    list_tasks.add_argument("--state", help="按任务状态过滤，例如 queued/running/done")
    list_tasks.add_argument("--agent", help="按 assigned_agent 过滤，例如 code-agent")
    list_tasks.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    show_task = subparsers.add_parser(
        "show-task",
        help="查看单个 task 详情",
        description="查看一个 task 的完整信息；如果同名 task_id 存在于多个 job，可用 --job 消除歧义。",
        formatter_class=HelpFormatter,
    )
    show_task.add_argument("task_id", help="要查看的 task_id")
    show_task.add_argument("--job", help="task 所属 job_id；存在歧义时必须指定")
    show_task.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    update_task = subparsers.add_parser(
        "update-task",
        help="修改 queued task",
        description="仅允许在 queued 状态下修改 requirement 或 assigned_agent。",
        formatter_class=HelpFormatter,
    )
    update_task.add_argument("task_id", help="要修改的 task_id")
    update_task.add_argument("--job", help="task 所属 job_id；存在歧义时建议指定")
    update_task.add_argument("--requirement", help="新的任务要求；仅 queued task 可修改")
    update_task.add_argument("--assign", dest="assigned_agent", help="新的 assigned_agent；仅 queued task 可修改")

    delete_task = subparsers.add_parser(
        "delete-task",
        help="删除 task",
        description="删除已有 task；仅允许删除 queued 或 done task。如果同名 task_id 存在于多个 job，可用 --job 消除歧义。",
        formatter_class=HelpFormatter,
    )
    delete_task.add_argument("task_id", help="要删除的 task_id")
    delete_task.add_argument("--job", help="task 所属 job_id；存在歧义时建议指定")

    worker_status = subparsers.add_parser(
        "worker-status",
        help="汇总所有 worker 当前状态",
        description="聚合所有 job 下的 task，推导每个 worker 的当前状态、运行中任务和排队数量。",
        formatter_class=HelpFormatter,
    )
    worker_status.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    queue = subparsers.add_parser(
        "queue",
        help="查看单个 worker 的队列",
        description="查看指定 worker 当前的 running task 和 queued tasks。",
        formatter_class=HelpFormatter,
    )
    queue.add_argument("agent", help="worker 名称，例如 code-agent")
    queue.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    for name, default_result, required_result in (
        ("claim", "claimed", False),
        ("start", None, True),
        ("update-result", None, True),
        ("complete", None, True),
        ("block", None, True),
        ("fail", None, True),
    ):
        help_map = {
            "claim": ("认领任务并标记为 running", "worker 认领任务，并清除 awaiting_claim 标记。"),
            "start": ("标记任务开始执行", "把任务状态更新为 running，并记录开始摘要。"),
            "update-result": ("更新任务进展结果", "写入阶段性结果，不改变任务状态。"),
            "complete": ("标记任务完成", "把任务状态更新为 done，并写入最终结果。"),
            "block": ("标记任务阻塞", "把任务状态更新为 blocked，并写入阻塞原因和解阻建议。"),
            "fail": ("标记任务失败", "把任务状态更新为 failed，并写入失败原因与证据。"),
        }
        sub = subparsers.add_parser(
            name,
            help=help_map[name][0],
            description=help_map[name][1],
            formatter_class=HelpFormatter,
        )
        sub.add_argument("task_id", help="要更新的 task_id")
        sub.add_argument("--job", help="task 所属 job_id；存在歧义时建议指定")
        if required_result:
            sub.add_argument("--result", required=True, help="要写入 task.result 的说明文本")
        else:
            sub.add_argument(
                "--result",
                default=default_result,
                help="要写入 task.result 的说明文本",
            )

    dispatch_once = subparsers.add_parser(
        "dispatch-once",
        help="执行一轮派发扫描",
        description="扫描全部 job，把已分配且可派发的 queued task 发给对应 worker。",
        formatter_class=HelpFormatter,
    )
    dispatch_once.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出")

    notify = subparsers.add_parser(
        "notify",
        help="通知终态任务结果",
        description="把指定 task 的终态结果通知给 notify_target；加 --force 可强制发送。",
        formatter_class=HelpFormatter,
    )
    notify.add_argument("task_id", help="要通知的 task_id")
    notify.add_argument("--job", help="task 所属 job_id；存在歧义时建议指定")
    notify.add_argument("--force", action="store_true", help="即使未进入终态，也强制发送一次通知")

    daemon = subparsers.add_parser(
        "daemon",
        help="循环执行派发与通知",
        description="以轮询方式持续运行 bridge：每轮先 dispatch，再发送周期提醒、终态 notify，以及未收口 follow-up。",
        formatter_class=HelpFormatter,
    )
    daemon.add_argument("--poll-seconds", type=float, default=10.0, help="每轮之间的等待秒数")
    daemon.add_argument("--iterations", type=int, default=0, help="轮询次数；0 表示持续运行")
    daemon.add_argument(
        "--worker-reminder-seconds",
        type=float,
        default=900.0,
        help="向已分发 worker 发送跟进提醒的间隔秒数；0 表示每轮都发",
    )
    daemon.add_argument(
        "--leader-reminder-seconds",
        type=float,
        default=3600.0,
        help="存在 running task 时向 team-leader 发送汇总提醒的间隔秒数；0 表示每轮都发",
    )
    daemon.add_argument(
        "--leader-followup",
        type=float,
        dest="leader_followup",
        default=LEADER_UNRESOLVED_FOLLOWUP_SECONDS,
        help="仅对 current job 的 terminal tasks 按 job 聚合生效：若最新终态通知后窗口内仍无新 task，则向 team-leader 发送 1 条 unresolved follow-up；0 表示禁用",
    )

    dashboard = subparsers.add_parser(
        "dashboard",
        help="启动 dashboard Web 界面",
        description=(
            "启动 task-bridge dashboard，集中查看 Overview / Jobs / Tasks / Worker Queue / Alerts / Health。"
            "支持通过页面内切换器切换 en / zh-CN 与本地字体风格；"
            "启动后会输出本机访问地址，并在需要时给出同网段访问、SSH 端口转发与端口冲突建议。"
        ),
        formatter_class=HelpFormatter,
    )
    dashboard.add_argument("--host", default="127.0.0.1", help="dashboard 监听地址")
    dashboard.add_argument("--port", type=int, default=8000, help="dashboard 监听端口")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = TaskStore()
    store.ensure_dirs()

    try:
        match args.command:
            case "create-job":
                job = store.create_job(title=args.title, notify_target=args.notify_target)
                return _print_payload(job, as_json=True)
            case "list-jobs":
                return _print_payload(store.list_jobs(), as_json=args.as_json)
            case "show-job":
                return _print_payload(store.load_job(store.resolve_job_id(args.job_id)), as_json=args.as_json)
            case "use-job":
                job = store.set_current_job(args.job_id)
                return _print_payload(job, as_json=True)
            case "current-job":
                job_id = store.resolve_job_id()
                return _print_payload(store.load_job(job_id), as_json=args.as_json)
            case "create-task":
                task = store.create_task(
                    job_id=args.job,
                    assigned_agent=args.assigned_agent,
                    requirement=args.requirement,
                )
                return _print_payload(task, as_json=True)
            case "list-tasks":
                tasks = store.list_tasks(job_id=args.job)
                if args.state:
                    tasks = [task for task in tasks if task.get("state") == args.state]
                if args.agent:
                    tasks = [task for task in tasks if task.get("assigned_agent") == args.agent]
                return _print_payload(tasks, as_json=args.as_json)
            case "show-task":
                return _print_payload(store.load_task(args.task_id, job_id=args.job), as_json=args.as_json)
            case "update-task":
                if args.requirement is None and args.assigned_agent is None:
                    raise ValueError("update-task requires --requirement or --assign")
                task = store.update_task(
                    args.task_id,
                    job_id=args.job,
                    requirement=args.requirement,
                    assigned_agent=args.assigned_agent,
                )
                return _print_payload(task, as_json=True)
            case "delete-task":
                payload = store.delete_task(args.task_id, job_id=args.job)
                return _print_payload(payload, as_json=True)
            case "worker-status":
                payload = {"workers": infer_worker_status(store.list_tasks(all_jobs=True))}
                return _print_payload(payload, as_json=args.as_json)
            case "queue":
                runtime = BridgeRuntime(home=store.home)
                return _print_payload(runtime.queue_for_agent(args.agent), as_json=args.as_json)
            case "claim":
                task = store.update_task(
                    args.task_id,
                    job_id=args.job,
                    state="running",
                    result=args.result,
                    clear_awaiting_claim=True,
                )
                return _print_payload(task, as_json=True)
            case "start":
                task = store.update_task(
                    args.task_id,
                    job_id=args.job,
                    state="running",
                    result=args.result,
                    clear_awaiting_claim=True,
                )
                return _print_payload(task, as_json=True)
            case "update-result":
                return _print_payload(
                    store.update_task(args.task_id, job_id=args.job, result=args.result),
                    as_json=True,
                )
            case "complete":
                return _print_payload(
                    store.update_task(args.task_id, job_id=args.job, state="done", result=args.result),
                    as_json=True,
                )
            case "block":
                return _print_payload(
                    store.update_task(args.task_id, job_id=args.job, state="blocked", result=args.result),
                    as_json=True,
                )
            case "fail":
                return _print_payload(
                    store.update_task(args.task_id, job_id=args.job, state="failed", result=args.result),
                    as_json=True,
                )
            case "dispatch-once":
                runtime = BridgeRuntime(home=store.home)
                payload = runtime.dispatch_once()
                return _print_payload(
                    {
                        "dispatched": payload.dispatched,
                        "skipped_busy": payload.skipped_busy,
                        "skipped_pending_claim": payload.skipped_pending_claim,
                    },
                    as_json=args.as_json,
                )
            case "notify":
                runtime = BridgeRuntime(home=store.home)
                notified = runtime.notify_task(args.task_id, job_id=args.job, force=args.force)
                return _print_payload({"task_id": args.task_id, "notified": notified}, as_json=True)
            case "daemon":
                runtime = BridgeRuntime(
                    home=store.home,
                    leader_unresolved_followup_seconds=args.leader_followup,
                )
                return _run_daemon(
                    runtime,
                    poll_seconds=args.poll_seconds,
                    iterations=args.iterations,
                    worker_reminder_seconds=args.worker_reminder_seconds,
                    leader_reminder_seconds=args.leader_reminder_seconds,
                )
            case "dashboard":
                _run_dashboard_command(home=store.home, host=args.host, port=args.port)
                return 0
            case _:
                raise ValueError(f"unsupported command: {args.command}")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _run_daemon(
    runtime: BridgeRuntime,
    *,
    poll_seconds: float,
    iterations: int,
    worker_reminder_seconds: float,
    leader_reminder_seconds: float,
) -> int:
    rounds = 0
    while True:
        dispatch = runtime.dispatch_once()
        reminders = runtime.send_due_reminders(
            worker_interval_seconds=worker_reminder_seconds,
            leader_interval_seconds=leader_reminder_seconds,
        )
        notify = runtime.notify_updates()
        followups = runtime.send_due_leader_unresolved_followups()
        payload = {
            "dispatched": dispatch.dispatched,
            "worker_reminded": reminders.worker_reminded,
            "leader_pinged": reminders.leader_pinged,
            "notified": notify.notified,
            "leader_followed_up": followups.followed_up,
            "skipped_busy": dispatch.skipped_busy,
            "skipped_pending_claim": dispatch.skipped_pending_claim,
        }
        print(json.dumps(payload, ensure_ascii=False))
        rounds += 1
        if iterations and rounds >= iterations:
            return 0
        time.sleep(poll_seconds)


def _run_dashboard_command(*, home: Any, host: str, port: int) -> None:
    port_issue = _dashboard_port_issue(host=host, port=port)
    if port_issue:
        raise ValueError(port_issue)

    print(_dashboard_launch_message(home=home, host=host, port=port))
    sys.stdout.flush()

    from .dashboard import run_dashboard

    run_dashboard(home=home, host=host, port=port)


def _dashboard_port_issue(*, host: str, port: int) -> str | None:
    if not 0 < port < 65536:
        return f"Dashboard 启动失败：端口 {port} 超出有效范围，请使用 1 到 65535 之间的端口。"
    if _can_bind_dashboard_port(host=host, port=port):
        return None

    suggestion = _find_available_dashboard_port(host=host, start_port=port + 1)
    lines = [
        f"Dashboard 启动失败：{host}:{port} 已被占用。",
        "请释放当前端口，或换一个未占用的端口后重试。",
    ]
    if suggestion is not None:
        lines.append("建议直接改用下面的命令：")
        lines.append(f"task-bridge dashboard --host {host} --port {suggestion}")
    return "\n".join(lines)


def _dashboard_launch_message(*, home: Any, host: str, port: int) -> str:
    local_url = _dashboard_local_url(host=host, port=port)
    network_url = _dashboard_network_url(host=host, port=port)
    ssh_target = _dashboard_ssh_target()
    remote_session = _dashboard_is_remote_session()
    gui_session = _dashboard_has_gui_session()
    browser_line = (
        "浏览器: 当前会话看起来像远程或无 GUI 环境；"
        f"建议先在本机执行下面的 SSH 端口转发，再打开 {local_url}"
        if remote_session or not gui_session
        else f"浏览器: 当前命令不会自动打开浏览器；请手动打开 {local_url}"
    )
    remote_line = (
        f"远程访问: ssh -L {port}:127.0.0.1:{port} {ssh_target}"
        if ssh_target
        else "远程访问: 未能自动识别可重连地址；请在本机用你平时登录这台机器时使用的主机名执行 SSH 端口转发，"
        f"映射 {port}:127.0.0.1:{port}"
    )
    lines = [
        "Dashboard 启动中",
        f"监听地址: {host}",
        f"监听端口: {port}",
        f"本机打开: {local_url}",
    ]
    if network_url:
        lines.append(f"同网段打开: {network_url}")
    lines.extend(
        [
            f"数据目录: {home}",
            remote_line,
            browser_line,
            "停止方式: Ctrl+C",
        ]
    )
    return "\n".join(
        lines
    )


def _dashboard_local_url(*, host: str, port: int) -> str:
    access_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]", "localhost"} else host
    return _dashboard_http_url(access_host, port=port)


def _dashboard_network_url(*, host: str, port: int) -> str | None:
    if host not in {"0.0.0.0", "::", "[::]"}:
        return None
    candidate = _dashboard_detect_network_host()
    if not candidate:
        return None
    return _dashboard_http_url(candidate, port=port)


def _dashboard_http_url(host: str, *, port: int) -> str:
    access_host = host.strip()
    if ":" in access_host and not access_host.startswith("["):
        access_host = f"[{access_host}]"
    return f"http://{access_host}:{port}/overview"


def _dashboard_ssh_target() -> str | None:
    override = os.environ.get("TASK_BRIDGE_DASHBOARD_SSH_TARGET", "").strip()
    if override:
        return override

    user = getpass.getuser().strip() or "user"
    host = _dashboard_detect_ssh_host()
    if not host:
        return None
    return host if "@" in host else f"{user}@{host}"


def _dashboard_detect_ssh_host() -> str | None:
    ssh_connection = os.environ.get("SSH_CONNECTION", "").strip().split()
    if len(ssh_connection) >= 3:
        candidate = _dashboard_clean_host_candidate(ssh_connection[2])
        if candidate:
            return candidate

    for candidate in (
        _dashboard_detect_network_host(),
        socket.getfqdn().strip(),
        socket.gethostname().strip(),
    ):
        cleaned = _dashboard_clean_host_candidate(candidate)
        if cleaned:
            return cleaned
    return None


def _dashboard_detect_network_host() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        cleaned = _dashboard_clean_host_candidate(candidate)
        if cleaned:
            return cleaned
    except OSError:
        pass

    try:
        hostname = socket.gethostname().strip()
        if not hostname:
            return None
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                cleaned = _dashboard_clean_host_candidate(sockaddr[0])
                if cleaned:
                    return cleaned
    except OSError:
        pass

    return None


def _dashboard_clean_host_candidate(candidate: str | None) -> str | None:
    if candidate is None:
        return None
    value = candidate.strip().strip("[]")
    if not value:
        return None

    if value.lower() in {"localhost", "ip6-localhost"}:
        return None
    if value in {"0.0.0.0", "127.0.0.1", "::", "::1"}:
        return None
    return value


def _dashboard_is_remote_session() -> bool:
    return any(os.environ.get(name, "").strip() for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"))


def _dashboard_has_gui_session() -> bool:
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return any(os.environ.get(name, "").strip() for name in ("DISPLAY", "WAYLAND_DISPLAY"))


def _can_bind_dashboard_port(*, host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host and "." not in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def _find_available_dashboard_port(*, host: str, start_port: int, attempts: int = 20) -> int | None:
    for candidate in range(max(start_port, 1), max(start_port, 1) + attempts):
        if _can_bind_dashboard_port(host=host, port=candidate):
            return candidate
    return None


def _print_payload(payload: Any, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
