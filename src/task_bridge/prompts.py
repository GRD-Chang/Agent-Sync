from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_TEMPLATES_DIRNAME = "prompt_templates"

PROMPT_TEMPLATE_FILES = {
    "dispatch": "dispatch.txt",
    "notify": "notify.txt",
    "notify_team_leader_follow_up": "notify_team_leader_follow_up.txt",
    "worker_reminder": "worker_reminder.txt",
    "running_summary": "running_summary.txt",
    "leader_unresolved_followup": "leader_unresolved_followup.txt",
}


@dataclass(frozen=True)
class PromptSet:
    dispatch: str
    notify: str
    notify_team_leader_follow_up: str
    worker_reminder: str
    running_summary: str
    leader_unresolved_followup: str


def prompt_templates_dir() -> Path:
    return Path(__file__).with_name(PROMPT_TEMPLATES_DIRNAME)


def prompt_template_path(name: str) -> Path:
    try:
        filename = PROMPT_TEMPLATE_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown prompt template: {name}") from exc
    return prompt_templates_dir() / filename


def _read_prompt_template(name: str) -> str:
    path = prompt_template_path(name)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"prompt template not found: {path}") from exc


def load_prompts() -> PromptSet:
    return PromptSet(
        dispatch=_read_prompt_template("dispatch"),
        notify=_read_prompt_template("notify"),
        notify_team_leader_follow_up=_read_prompt_template("notify_team_leader_follow_up"),
        worker_reminder=_read_prompt_template("worker_reminder"),
        running_summary=_read_prompt_template("running_summary"),
        leader_unresolved_followup=_read_prompt_template("leader_unresolved_followup"),
    )
