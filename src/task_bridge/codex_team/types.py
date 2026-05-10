from __future__ import annotations

SCHEMA_VERSION = 1

ROLES = {"planner", "generator", "evaluator"}
ACTIONS = {"continue", "candidate_ready", "pass", "needs_fix", "needs_design", "ask_user", "stop"}
TARGETS = {"planner", "generator", "evaluator", "user", "system"}
AGENT_STATUSES = {"completed", "needs_input", "blocked", "failed"}
RUN_STATES = {
    "created",
    "planning",
    "evaluating_plan",
    "generating",
    "evaluating_milestone",
    "evaluating_final",
    "paused",
    "completed",
    "cancelled",
    "failed",
}
GRADES = {"pass", "weak", "fail", "not_applicable"}

BASE_GRADING_CRITERIA = (
    "goal_alignment",
    "functional_correctness",
    "code_quality",
    "test_evidence",
    "regression_risk",
    "scope_control",
)
