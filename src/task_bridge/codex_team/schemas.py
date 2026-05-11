from __future__ import annotations

from copy import deepcopy

from .types import ACTIONS, AGENT_STATUSES, COMPLETION_SCOPES, SCHEMA_VERSION, TARGETS


ACTION_ENVELOPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "status",
        "summary",
        "action",
        "target",
        "completion_scope",
        "reason",
        "artifacts",
    ],
    "properties": {
        "schema_version": {
            "type": "integer",
            "enum": [SCHEMA_VERSION],
            "description": "Codex Team schema version. Always output 1.",
        },
        "status": {
            "enum": sorted(AGENT_STATUSES),
            "description": "Status of this agent run, not the whole project.",
        },
        "summary": {
            "type": "string",
            "minLength": 1,
            "description": "One or two sentences summarizing what this agent completed.",
        },
        "action": {
            "enum": sorted(ACTIONS),
            "description": "Business action for the dispatcher. Use candidate_ready after generator work, needs_fix after failed evaluation, pass only for final completion.",
        },
        "target": {
            "enum": sorted(TARGETS),
            "description": "Next receiver. Must be consistent with action and current role.",
        },
        "completion_scope": {
            "enum": sorted(COMPLETION_SCOPES),
            "description": "Use checkpoint when the current plan/candidate/phase is done but more roadmap work may remain. Use final only when the whole requested run is complete; evaluator pass->system requires final.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "description": "Short human-readable routing reason. Put detailed handoff content in Markdown artifacts, not here.",
        },
        "artifacts": {
            "type": "array",
            "description": "Optional supplemental artifact paths that may help the next agent. Core handoff files are fixed by protocol and validated separately. Include only useful files under run_home or repo_root. Do not put summaries here.",
            "items": {"type": "string"},
        },
    },
}

PENDING_QUESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": ["schema_version", "run_id", "question", "created_at"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "run_id": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "payload": {"type": "object"},
        "created_at": {"type": "string", "minLength": 1},
    },
}

RUNNER_ERROR_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": ["code", "message"],
    "properties": {
        "code": {"type": "string", "minLength": 1},
        "message": {"type": "string", "minLength": 1},
        "details": {"type": "object"},
    },
}


def schema_for_role(role: str) -> dict:
    schema = deepcopy(ACTION_ENVELOPE_SCHEMA)
    schema["title"] = f"codex-team-{role}-action"
    action_schema = schema["properties"]["action"]
    target_schema = schema["properties"]["target"]
    if role == "planner":
        action_schema["enum"] = ["continue", "ask_user", "stop"]
        target_schema["enum"] = ["generator", "evaluator", "user", "system"]
    elif role == "generator":
        action_schema["enum"] = ["candidate_ready", "needs_design"]
        target_schema["enum"] = ["evaluator", "planner"]
    elif role == "evaluator":
        action_schema["enum"] = ["continue", "pass", "needs_fix", "needs_design", "stop"]
        target_schema["enum"] = ["generator", "planner", "system"]
    return schema
