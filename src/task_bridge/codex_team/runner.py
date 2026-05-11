from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from contextlib import contextmanager
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fcntl


DEFAULT_TIMEOUT_SECONDS = 7200
DEFAULT_TAIL_BYTES = 100000


@dataclass
class RunnerResult:
    role: str
    returncode: int
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    envelope: dict[str, Any] | None = None
    last_message_path: Path | None = None
    session_id: str | None = None
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.error is None


class FakeCodexRunner:
    def __init__(self, results: Sequence[RunnerResult | dict[str, Any]]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        run_home: Path,
        schema_path: Path | None = None,
        output_last_message_path: Path | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> RunnerResult:
        self.calls.append(
            {
                "role": role,
                "prompt": prompt,
                "repo_root": str(repo_root),
                "run_home": str(run_home),
                "schema_path": str(schema_path) if schema_path else None,
                "output_last_message_path": str(output_last_message_path) if output_last_message_path else None,
                "session_id": session_id,
                "resume": resume,
            }
        )
        if not self._results:
            return RunnerResult(
                role=role,
                returncode=1,
                duration_seconds=0.0,
                error={"code": "RunnerFailed", "message": "fake runner has no queued result"},
            )
        result = self._results.pop(0)
        if isinstance(result, RunnerResult):
            return result
        return RunnerResult(role=role, returncode=0, duration_seconds=0.0, envelope=result)


class CaptureCodexRunner:
    def run(
        self,
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        run_home: Path,
        schema_path: Path | None = None,
        output_last_message_path: Path | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> RunnerResult:
        logs_dir = run_home / "artifacts" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        sequence = len(list(logs_dir.glob(f"{role}-*.prompt.txt"))) + 1
        prompt_path = logs_dir / f"{role}-{sequence:03d}.prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        envelope = {
            "schema_version": 1,
            "summary": f"captured prompt for {role}",
            "status": "completed",
            "action": "stop",
            "target": "system",
            "reason": "capture runner does not execute Codex",
            "artifacts": [str(prompt_path)],
        }
        if output_last_message_path:
            output_last_message_path.parent.mkdir(parents=True, exist_ok=True)
            output_last_message_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
        return RunnerResult(
            role=role,
            returncode=0,
            duration_seconds=0.0,
            envelope=envelope,
            last_message_path=output_last_message_path,
        )


class RealCodexRunner:
    def __init__(
        self,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        tail_bytes: int = DEFAULT_TAIL_BYTES,
        ignore_user_config: bool = False,
        disabled_features: Sequence[str] = (),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.tail_bytes = tail_bytes
        self.ignore_user_config = ignore_user_config
        self.disabled_features = tuple(disabled_features)

    def build_command(
        self,
        *,
        repo_root: Path,
        schema_path: Path,
        output_last_message_path: Path,
    ) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--cd",
            str(repo_root),
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if self.ignore_user_config:
            cmd.append("--ignore-user-config")
        for feature in self.disabled_features:
            cmd.extend(["--disable", feature])
        cmd.extend(
            [
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_last_message_path),
                "--json",
                "-",
            ]
        )
        return cmd

    def build_resume_command(
        self,
        *,
        session_id: str,
        output_last_message_path: Path,
    ) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "resume",
            session_id,
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if self.ignore_user_config:
            cmd.append("--ignore-user-config")
        for feature in self.disabled_features:
            cmd.extend(["--disable", feature])
        cmd.extend(
            [
                "--output-last-message",
                str(output_last_message_path),
                "--json",
                "-",
            ]
        )
        return cmd

    def run(
        self,
        *,
        role: str,
        prompt: str,
        repo_root: Path,
        run_home: Path,
        schema_path: Path | None = None,
        output_last_message_path: Path | None = None,
        session_id: str | None = None,
        resume: bool = False,
    ) -> RunnerResult:
        if shutil.which("codex") is None:
            return RunnerResult(
                role=role,
                returncode=127,
                duration_seconds=0.0,
                error={"code": "RunnerUnavailable", "message": "codex binary not found"},
            )
        logs_dir = run_home / "artifacts" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_last_message_path or logs_dir / f"{role}-{int(time.time())}.last-message.json"
        stdout_log_path, stderr_log_path = _stdio_log_paths(logs_dir, output_path, role)
        if resume:
            if not session_id:
                return RunnerResult(
                    role=role,
                    returncode=2,
                    duration_seconds=0.0,
                    error={"code": "RunnerFailed", "message": "resume requires session_id"},
                )
            cmd = self.build_resume_command(session_id=session_id, output_last_message_path=output_path)
        else:
            if schema_path is None:
                return RunnerResult(
                    role=role,
                    returncode=2,
                    duration_seconds=0.0,
                    error={"code": "RunnerFailed", "message": "schema_path is required for new codex exec"},
                )
            cmd = self.build_command(repo_root=repo_root, schema_path=schema_path, output_last_message_path=output_path)

        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        try:
            with _codex_runner_locks(run_home):
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=repo_root,
                    start_new_session=True,
                )
                stdout, stderr = process.communicate(input=prompt, timeout=self.timeout_seconds)
        except RunnerLockBusy as exc:
            return RunnerResult(
                role=role,
                returncode=75,
                duration_seconds=time.monotonic() - started,
                error={
                    "code": "RunnerLockBusy",
                    "message": str(exc),
                    "details": exc.details,
                },
            )
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    stdout, stderr = process.communicate()
            else:
                stdout, stderr = "", ""
            stdout_text = (exc.stdout or "") + (stdout or "")
            stderr_text = (exc.stderr or "") + (stderr or "")
            _write_text_log(stdout_log_path, stdout_text)
            _write_text_log(stderr_log_path, stderr_text)
            stdout_tail = _tail(stdout_text, self.tail_bytes)
            stderr_tail = _tail(stderr_text, self.tail_bytes)
            return RunnerResult(
                role=role,
                returncode=124,
                duration_seconds=time.monotonic() - started,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                error={
                    "code": "RunnerTimeout",
                    "message": "codex runner timed out",
                    "details": {
                        "stdout_log": str(stdout_log_path),
                        "stderr_log": str(stderr_log_path),
                        "stdout_tail": stdout_tail,
                        "stderr_tail": stderr_tail,
                    },
                },
            )

        _write_text_log(stdout_log_path, stdout)
        _write_text_log(stderr_log_path, stderr)
        stdout_tail = _tail(stdout, self.tail_bytes)
        stderr_tail = _tail(stderr, self.tail_bytes)
        envelope = None
        if output_path.exists():
            try:
                envelope = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                envelope = None
        error = None
        returncode = process.returncode
        if returncode != 0:
            error_code = "RunnerAuthFailed" if _looks_like_auth_failure(stderr) else "RunnerFailed"
            error = {
                "code": error_code,
                "message": "codex exec returned non-zero",
                "details": {
                    "returncode": returncode,
                    "stdout_log": str(stdout_log_path),
                    "stderr_log": str(stderr_log_path),
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                },
            }
        elif envelope is None:
            error = {
                "code": "MissingNextAction",
                "message": "codex did not produce valid final JSON envelope",
                "details": {
                    "stdout_log": str(stdout_log_path),
                    "stderr_log": str(stderr_log_path),
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                },
            }
        return RunnerResult(
            role=role,
            returncode=returncode,
            duration_seconds=time.monotonic() - started,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            envelope=envelope,
            last_message_path=output_path,
            session_id=_extract_session_id(stdout),
            error=error,
        )


class RunnerLockBusy(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, str]) -> None:
        super().__init__(message)
        self.details = details


@contextmanager
def _codex_runner_locks(run_home: Path):
    run_home.mkdir(parents=True, exist_ok=True)
    global_lock = run_home.parent / ".codex-team-runner.lock"
    run_lock = run_home / ".runner.lock"
    global_lock.parent.mkdir(parents=True, exist_ok=True)
    with global_lock.open("a+", encoding="utf-8") as global_handle:
        try:
            fcntl.flock(global_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerLockBusy(
                "another codex team runner is active",
                details={"lock": str(global_lock), "scope": "global"},
            ) from exc
        try:
            with run_lock.open("a+", encoding="utf-8") as run_handle:
                try:
                    fcntl.flock(run_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RunnerLockBusy(
                        "another codex team runner is active for this run",
                        details={"lock": str(run_lock), "scope": "run"},
                    ) from exc
                try:
                    yield
                finally:
                    fcntl.flock(run_handle.fileno(), fcntl.LOCK_UN)
        finally:
            fcntl.flock(global_handle.fileno(), fcntl.LOCK_UN)


def _stdio_log_paths(logs_dir: Path, output_path: Path, role: str) -> tuple[Path, Path]:
    prefix = output_path.name.removesuffix(".last-message.json")
    if prefix == output_path.name:
        prefix = f"{role}-{int(time.time())}"
    return logs_dir / f"{prefix}.stdout.log", logs_dir / f"{prefix}.stderr.log"


def _write_text_log(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    path.write_text(text, encoding="utf-8")


def _tail(text: str | bytes, limit: int) -> str:
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[-limit:].decode("utf-8", errors="replace")


def _extract_session_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("session_id", "conversation_id", "id"):
            value = event.get(key) if isinstance(event, dict) else None
            if isinstance(value, str) and value:
                return value
    return None


def _looks_like_auth_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "401 unauthorized",
            "authrequired",
            "no access token",
            "not logged in",
            "authentication",
        )
    )
