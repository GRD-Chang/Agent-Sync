from __future__ import annotations

from pathlib import Path

from task_bridge.codex_team.dispatcher import CodexTeamDispatcher
from task_bridge.codex_team.prompts import build_role_prompt
from task_bridge.codex_team.runner import FakeCodexRunner, RunnerResult
from task_bridge.codex_team.store import CodexTeamStore


def _envelope(
    summary: str,
    *,
    action: str,
    target: str,
    completion_scope: str = "checkpoint",
    reason: str = "ok",
    artifacts: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "summary": summary,
        "status": "completed",
        "action": action,
        "target": target,
        "completion_scope": completion_scope,
        "reason": reason,
        "artifacts": artifacts or [],
    }


class E2ERunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

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
        self.calls.append(role)
        if role == "planner":
            (run_home / "plan.md").write_text("plan")
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0,
                envelope=_envelope("planned", action="continue", target="generator"),
            )
        if role == "generator" and self.calls.count("generator") == 1:
            impl = run_home / "attempts" / "001" / "implementation.md"
            impl.parent.mkdir(parents=True, exist_ok=True)
            impl.write_text("impl 1")
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0,
                envelope=_envelope("m1 done", action="candidate_ready", target="evaluator"),
            )
        if role == "evaluator" and self.calls.count("evaluator") == 1:
            ev_md = run_home / "attempts" / "001" / "evaluation.md"
            ev_md.write_text("pass milestone")
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0,
                envelope=_envelope("m1 passed", action="continue", target="generator"),
            )
        if role == "generator":
            impl = run_home / "attempts" / "002" / "implementation.md"
            impl.parent.mkdir(parents=True, exist_ok=True)
            impl.write_text("impl final")
            return RunnerResult(
                role=role,
                returncode=0,
                duration_seconds=0,
                envelope=_envelope("final done", action="candidate_ready", target="evaluator"),
            )
        ev_md = run_home / "attempts" / "002" / "evaluation.md"
        ev_md.write_text("final pass")
        return RunnerResult(
            role=role,
            returncode=0,
            duration_seconds=0,
            envelope=_envelope("final passed", action="pass", target="system", completion_scope="final"),
        )


def test_dispatcher_fake_runner_e2e_reaches_completed(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    runner = E2ERunner()
    dispatcher = CodexTeamDispatcher(store=store, runner=runner)
    repo = tmp_path / "repo"
    repo.mkdir()

    outcome = dispatcher.start_run(repo_root=repo, input_text="build")
    outcome = dispatcher.run_until_idle(outcome.run_id)

    metadata = store.load_metadata(outcome.run_id)
    assert metadata["state"] == "completed"
    assert metadata["status"] == "completed"
    assert metadata["latest_evaluation"].endswith("attempts/002/evaluation.md")
    assert [event["type"] for event in store.read_events(outcome.run_id)].count("route") >= 4


def test_planner_plan_review_uses_plan_evaluation_without_attempt_collision(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="planning", current_owner="planner")
    plan = store.run_home("run-1") / "plan.md"
    plan.write_text("plan")
    runner = FakeCodexRunner([_envelope("review plan", action="continue", target="evaluator")])

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "evaluating_plan"
    assert metadata["current_owner"] == "evaluator"
    assert metadata["current_attempt"] == 0
    assert metadata["latest_evaluation"] is None
    assert not (store.run_home("run-1") / "attempts" / "001" / "evaluation.md").exists()


def test_plan_evaluator_result_writes_plan_evaluation_and_routes_to_generator(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="evaluating_plan", current_owner="evaluator")
    plan = store.run_home("run-1") / "plan.md"
    plan.write_text("plan")
    plan_eval = store.run_home("run-1") / "plan_evaluation.md"
    plan_eval.write_text("plan ok")
    runner = FakeCodexRunner([_envelope("plan ok", action="continue", target="generator")])

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "generating"
    assert metadata["latest_plan_evaluation"].endswith("plan_evaluation.md")
    assert metadata["latest_evaluation"] is None


def test_evaluator_checkpoint_pass_system_is_rejected_without_completing(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="evaluating_milestone", current_owner="evaluator", current_attempt=1)
    evaluation = store.run_home("run-1") / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("candidate passes, but roadmap remains")
    runner = FakeCodexRunner(
        [_envelope("milestone passed", action="pass", target="system", completion_scope="checkpoint")]
    )

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "failed"
    assert metadata["status"] == "failed"
    assert metadata["last_error"]["code"] == "InvalidCompletionScope"
    assert metadata["current_owner"] == "evaluator"


def test_evaluator_invalid_completion_scope_is_repaired_when_session_available(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="evaluating_milestone", current_owner="evaluator", current_attempt=1)
    evaluation = store.run_home("run-1") / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("candidate passes, but remaining work exists")
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="evaluator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("milestone passed", action="pass", target="system", completion_scope="checkpoint"),
            ),
            RunnerResult(
                role="evaluator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("continue roadmap", action="continue", target="generator"),
            ),
        ]
    )

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "generating"
    assert metadata["status"] == "running"
    assert metadata["latest_evaluation"].endswith("attempts/001/evaluation.md")
    assert runner.calls[1]["resume"] is True


def test_resume_failed_runner_error_uses_thread_id(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    run_home = store.run_home("run-1")
    evaluation = run_home / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("checkpoint ok")
    stdout_log = run_home / "artifacts" / "logs" / "evaluator-001.stdout.log"
    stdout_log.write_text('{"type":"thread.started","thread_id":"thread-1"}\n')
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="evaluator",
        current_attempt=1,
        last_error={
            "code": "RunnerAuthFailed",
            "message": "auth failed",
            "details": {"stdout_log": str(stdout_log)},
        },
    )
    runner = FakeCodexRunner([_envelope("continue", action="continue", target="generator")])

    outcome = CodexTeamDispatcher(store=store, runner=runner).resume("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "generating"
    assert metadata["status"] == "running"
    assert metadata["last_error"] is None
    assert metadata["latest_evaluation"].endswith("attempts/001/evaluation.md")
    assert runner.calls[0]["resume"] is True
    assert runner.calls[0]["session_id"] == "thread-1"
    assert "继续刚才中断的 Codex Team 工作" in runner.calls[0]["prompt"]
    assert store.read_events("run-1")[-2]["type"] == "resume_started"


def test_resume_failed_runner_error_without_thread_reruns_current_owner(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="planner",
        last_error={"code": "RunnerTimeout", "message": "timed out", "details": {}},
    )
    plan = store.run_home("run-1") / "plan.md"
    plan.write_text("plan")
    runner = FakeCodexRunner([_envelope("planned", action="continue", target="generator")])

    outcome = CodexTeamDispatcher(store=store, runner=runner).resume("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "generating"
    assert metadata["status"] == "running"
    assert runner.calls[0]["resume"] is False
    assert store.read_events("run-1")[-2]["type"] == "resume_started"


def test_resume_rejects_non_runner_failures(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(
        metadata["run_id"],
        state="failed",
        status="failed",
        current_owner="evaluator",
        last_error={"code": "InvalidFixedArtifact", "message": "bad artifact"},
    )

    try:
        CodexTeamDispatcher(store=store, runner=FakeCodexRunner([])).resume("run-1")
    except ValueError as exc:
        assert "not resumable" in str(exc)
    else:
        raise AssertionError("resume should reject non-runner failures")


def test_checkpoint_repair_cannot_upgrade_to_final_completion(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="evaluating_milestone", current_owner="evaluator", current_attempt=1)
    evaluation = store.run_home("run-1") / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("candidate passes, but remaining work exists")
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="evaluator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("milestone passed", action="pass", target="system", completion_scope="checkpoint"),
            ),
            RunnerResult(
                role="evaluator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("final passed", action="pass", target="system", completion_scope="final"),
            ),
        ]
    )

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    metadata = store.load_metadata("run-1")
    assert outcome.state == "failed"
    assert metadata["status"] == "failed"
    assert metadata["last_error"]["code"] == "InvalidCompletionScope"
    assert "cannot upgrade" in metadata["last_error"]["issues"][0]["message"]
    assert metadata["current_owner"] == "evaluator"
    assert runner.calls[1]["resume"] is True


def test_generator_direct_stop_is_repaired_when_session_available(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="generating", current_owner="generator")
    repaired_impl = store.run_home("run-1") / "attempts" / "001" / "implementation.md"
    repaired = _envelope("fixed", action="candidate_ready", target="evaluator")
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="generator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("bad", action="stop", target="system"),
            ),
            RunnerResult(
                role="generator",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=repaired,
            ),
        ]
    )

    def write_repair_artifact(*args, **kwargs):  # type: ignore[no-untyped-def]
        repaired_impl.parent.mkdir(parents=True, exist_ok=True)
        repaired_impl.write_text("impl")
        return original_run(*args, **kwargs)

    original_run = runner.run
    runner.run = write_repair_artifact  # type: ignore[method-assign]

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    assert outcome.state == "evaluating_milestone"
    assert runner.calls[1]["resume"] is True


def test_missing_fixed_artifact_triggers_repair(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="planning", current_owner="planner")
    plan = store.run_home("run-1") / "plan.md"
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="planner",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("planned", action="continue", target="generator"),
            ),
            RunnerResult(
                role="planner",
                returncode=0,
                duration_seconds=0,
                session_id="session-1",
                envelope=_envelope("planned", action="continue", target="generator"),
            ),
        ]
    )

    original_run = runner.run

    def write_plan_on_repair(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("resume"):
            plan.write_text("plan")
        return original_run(*args, **kwargs)

    runner.run = write_plan_on_repair  # type: ignore[method-assign]

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    assert outcome.state == "generating"
    assert runner.calls[1]["resume"] is True


def test_supplemental_artifacts_are_filtered_without_failing(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="planning", current_owner="planner")
    plan = store.run_home("run-1") / "plan.md"
    plan.write_text("plan")
    kept = repo / "README.md"
    kept.write_text("readme")
    runner = FakeCodexRunner(
        [
            _envelope(
                "planned",
                action="continue",
                target="generator",
                artifacts=[str(kept), str(tmp_path / "outside.md")],
            )
        ]
    )

    outcome = CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    assert outcome.state == "generating"
    assert store.load_next_action("run-1")["artifacts"] == [str(kept)]
    assert any(event["type"] == "supplemental_artifacts_dropped" for event in store.read_events("run-1"))


def test_prompts_use_lightweight_action_protocol(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="generating", current_owner="generator")
    impl = store.run_home("run-1") / "attempts" / "001" / "implementation.md"
    impl.parent.mkdir(parents=True, exist_ok=True)
    impl.write_text("impl")
    runner = FakeCodexRunner([_envelope("ready", action="candidate_ready", target="evaluator")])

    CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    prompt = runner.calls[0]["prompt"]
    assert "action=candidate_ready,target=evaluator" in prompt
    assert "artifacts 只是可选补充索引" in prompt


def test_prompt_injects_previous_action_short_context(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.write_next_action(
        "run-1",
        _envelope(
            "计划已完成，下一步实现核心路径。",
            action="continue",
            target="generator",
            reason="plan is ready for implementation",
        ),
    )

    prompt = build_role_prompt(
        role="generator",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )

    assert "上一轮 agent 结果" in prompt
    assert "summary: 计划已完成，下一步实现核心路径。" in prompt
    assert "action: continue" in prompt
    assert "target: generator" in prompt
    assert "completion_scope: checkpoint" in prompt
    assert "reason: plan is ready for implementation" in prompt
    assert "详细交接仍以固定 Markdown artifact 为准" in prompt


def test_generator_prompt_reads_latest_implementation_with_latest_evaluation(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    impl = store.run_home("run-1") / "attempts" / "001" / "implementation.md"
    eval_md = store.run_home("run-1") / "attempts" / "001" / "evaluation.md"
    impl.parent.mkdir(parents=True)
    impl.write_text("implementation summary")
    eval_md.write_text("evaluation summary")
    metadata["latest_implementation"] = str(impl)
    metadata["latest_evaluation"] = str(eval_md)

    prompt = build_role_prompt(
        role="generator",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )

    assert str(impl) in prompt
    assert str(eval_md) in prompt
    assert "如果存在 latest_implementation，必须结合 latest evaluation.md" in prompt


def test_role_prompts_include_core_worker_standards(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")

    planner_prompt = build_role_prompt(
        role="planner",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )
    generator_prompt = build_role_prompt(
        role="generator",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )
    evaluator_prompt = build_role_prompt(
        role="evaluator",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )

    for prompt in (planner_prompt, generator_prompt, evaluator_prompt):
        assert "团队组成与协作模型" in prompt
        assert "Dispatcher：只负责启动下一位 agent" in prompt
        assert "你只负责当前 role" in prompt
        assert "通用工作边界" in prompt
        assert "优先查看当前会话可用的 skills" in prompt
        assert "符合本轮目标、范围、验收和验证要求的 skill" in prompt
        assert "Codex 进程拥有最大执行权限" in prompt
        assert "固定 Markdown artifact 是跨 agent 的主要交接内容" in prompt
        assert "completion_scope" in prompt
        assert "跨 agent handoff 有显著时间和 token 成本" in prompt
        assert "Handoff economy policy" in prompt
        assert "Generator 根据代码事实判断 candidate_boundary_status" in prompt
        assert "Evaluator 批量评审并给出聚合反馈" in prompt
        assert "Completion scope policy" in prompt
        assert "Blocking fix policy" in prompt
        assert "blocking_fixes / required_fixes 只放阻塞当前 candidate" in prompt
        assert "Run artifact 目录规则" in prompt
        assert "attempts/<n>/implementation.md" in prompt
        assert "attempts/<n>/evaluation.md" in prompt
        assert "metadata.json" in prompt
        assert "next_action.json" in prompt
        assert "评审术语" in prompt
        assert "acceptance = 本轮交付必须满足的可观察条件" in prompt
        assert "verification = 如何证明 acceptance 已满足" in prompt
        assert "base grading criteria" in prompt
        assert "task-specific grading criteria = 当前任务特有的可判定质量项" in prompt
        assert "不做无关重构" in prompt

    assert "有野心但可执行的产品/工程 spec" in planner_prompt
    assert "delivery_roadmap" in planner_prompt
    assert "功能、产品能力或风险边界级路线图" in planner_prompt
    assert "定义 goal_and_scope、delivery_roadmap、candidate_boundary" in planner_prompt
    assert "工作规则" in planner_prompt
    assert "goal_and_scope 必须区分 required_scope、later_scope、non-goal 和 final_condition" in planner_prompt
    assert "不要把单个 helper、单个测试修复或单个小 bug 当成本 run 的完整 scope" in planner_prompt
    assert "required_scope 是本次 run 必须完成的范围，不是函数级实现计划" in planner_prompt
    assert "candidate_boundary 定义什么规模的成果可以交给 Evaluator" in planner_prompt
    assert "handoff_condition" in planner_prompt
    assert "Markdown 字段只是关键锚点，不是表格式 schema" in planner_prompt
    assert "goal_and_scope、architecture_direction、delivery_roadmap、candidate_boundary" in planner_prompt
    assert "acceptance_and_verification、risks_and_open_questions" in planner_prompt
    assert "goal_and_scope 中写清 required_scope、later_scope、non-goal 和 final_condition" in planner_prompt
    assert "acceptance_and_verification 中写清验收、验证方法和 task-specific grading criteria" in planner_prompt
    assert "不要把 roadmap 写成低层实现步骤" in planner_prompt
    assert "Generator 可以在 spec 边界内自主选择实现顺序" in planner_prompt
    assert "roadmap 粒度" in planner_prompt
    assert "避免过粗" in planner_prompt
    assert "持久化、状态机、权限、安全、公共接口、复杂迁移" in planner_prompt
    assert "自主选择实现顺序" in generator_prompt
    assert "changes_and_evidence 中说明实现计划和关键判断" in generator_prompt
    assert "需求、产品边界、acceptance、verification、设计或执行路径不清" in generator_prompt
    assert "开发前先自主调研" in generator_prompt
    assert "开源项目、优秀实现、官方文档或成熟实践" in generator_prompt
    assert "只复用设计思想、接口模式、验证策略和风险控制方法" in generator_prompt
    assert "修复轮必须读取 latest evaluation.md 的 blocking_fixes / required_fixes" in generator_prompt
    assert "在 plan 边界内连续推进一组相关工作" in generator_prompt
    assert "达到 candidate_boundary 后提交 Evaluator" in generator_prompt
    assert "不是机械地尽量完成多个 phase" in generator_prompt
    assert "不要每完成一个小步骤就交给 Evaluator" in generator_prompt
    assert "如果问题仍在你的实现能力范围内，继续实现和自测" in generator_prompt
    assert "不要把 Evaluator 当作每个小步骤后的确认按钮" in generator_prompt
    assert "工作规则" in generator_prompt
    assert "在 plan 边界内连续推进一组相关工作" in generator_prompt
    assert "处理 blocking_fixes，并把 non_blocking_findings、scope_status、route_decision 作为下一批输入" in generator_prompt
    assert "自主管理内部任务拆分、实现顺序、自测和修复" in generator_prompt
    assert "summary、candidate_boundary_status、changes_and_evidence、scope_status" in generator_prompt
    assert "feedback_addressed、known_limitations" in generator_prompt
    assert "candidate_boundary_status 中说明为什么本轮达到或未达到" in generator_prompt
    assert "changes_and_evidence 中写清关键改动、必要调研、设计或根因判断、测试和验证证据" in generator_prompt
    assert "scope_status 中写清 completed_scope、remaining_scope" in generator_prompt
    assert "feedback_addressed 中说明上一轮 blocking_fixes" in generator_prompt
    assert "结论是 continue" in generator_prompt
    assert "candidate_assessment、non_blocking_findings、scope_status 和 route_decision" in generator_prompt
    assert "修改 repo 前先查看 git status" in generator_prompt
    assert "如果任务表现为 bug、回归、异常或失败链路不清，先做根因调查" in generator_prompt
    assert "不要修改 plan.md 或 evaluation.md 来适配自己的实现" in generator_prompt
    assert "只有满足以下至少一项" in generator_prompt
    assert "完成一个用户工作流、模块边界、公共接口、状态机、持久化格式" in generator_prompt
    assert "一组可一起验证的相关修复" in generator_prompt
    assert "action=candidate_ready,target=evaluator" in generator_prompt
    assert "completion_scope=checkpoint" in generator_prompt
    assert "action=needs_design,target=planner" in generator_prompt
    assert "Generator 不能使用 action=stop,target=system" in generator_prompt
    assert "不得作为单独 candidate 的边界" in generator_prompt
    assert "单个 helper、单个测试、单个 lint" in generator_prompt
    assert "评估规则" in evaluator_prompt
    assert "不是第二个 Generator" in evaluator_prompt
    assert "判断 candidate_boundary、scope_status、validation 和 blocking/non-blocking 问题" in evaluator_prompt
    assert "确保最终 JSON 路由与 evaluation.md 的 route_decision 一致" in evaluator_prompt
    assert "不要只读 summary" in evaluator_prompt
    assert "当前 implementation.md、代码 diff 和测试证据" in evaluator_prompt
    assert "评估模式" in evaluator_prompt
    assert "plan evaluation" in evaluator_prompt
    assert "不要求 diff" in evaluator_prompt
    assert "product context、scope、delivery roadmap" in evaluator_prompt
    assert "implementation evaluation" in evaluator_prompt
    assert "risk_flags、open_questions 和 task-specific grading criteria" in evaluator_prompt
    assert "不做默认逐 phase gate" in evaluator_prompt
    assert "Evaluator 是阶段性质量门，不是频繁打断 Generator 的调度器" in evaluator_prompt
    assert "blocking_fixes / required_fixes 只放阻塞项" in evaluator_prompt
    assert "non_blocking_findings" in evaluator_prompt
    assert "summary、candidate_assessment、blocking_fixes、non_blocking_findings、scope_status、route_decision" in evaluator_prompt
    assert "candidate_assessment 中说明 candidate_boundary 是否成立" in evaluator_prompt
    assert "route_decision 必须解释最终 JSON 路由" in evaluator_prompt
    assert "candidate pass 不等于 final completion" in evaluator_prompt
    assert "先检查 final_condition 和 required_scope" in evaluator_prompt
    assert "remaining_scope" in evaluator_prompt
    assert "不要修改 repo 源码来替 Generator 完成任务" in evaluator_prompt
    assert "证据不足、验收不满足或存在 fail 时不能 pass" in evaluator_prompt
    assert "final candidate 存在任何 fail 时不能 pass" in evaluator_prompt
    assert "product_depth、feature_completeness、workflow_completeness" in evaluator_prompt
    assert "默认路由" in evaluator_prompt
    assert "blocking issue -> action=needs_fix,target=generator,completion_scope=checkpoint" in evaluator_prompt
    assert "required_scope 仍有 remaining_scope" in evaluator_prompt
    assert "final_condition 满足，remaining_scope 为空或仅剩 later_scope" in evaluator_prompt
    assert "candidate 边界无法判定 -> action=needs_design,target=planner,completion_scope=checkpoint" in evaluator_prompt
    assert "continue 不是忽略评审意见" in evaluator_prompt
    assert "action=continue,target=generator,completion_scope=checkpoint" in evaluator_prompt
    assert "roadmap 已失效" in evaluator_prompt
    assert "action=pass,target=system,completion_scope=final" in evaluator_prompt
    assert "不要使用 action=stop,target=system" in evaluator_prompt


def test_planner_prompt_reads_returned_artifacts_and_user_answers(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.append_answer("run-1", "dashboard must stay read-only")
    impl = store.run_home("run-1") / "attempts" / "001" / "implementation.md"
    eval_md = store.run_home("run-1") / "attempts" / "001" / "evaluation.md"
    impl.parent.mkdir(parents=True)
    impl.write_text("implementation issue")
    eval_md.write_text("design issue")
    metadata["latest_implementation"] = str(impl)
    metadata["latest_evaluation"] = str(eval_md)

    prompt = build_role_prompt(
        role="planner",
        repo_root=repo,
        run_home=store.run_home("run-1"),
        metadata=metadata,
    )

    assert str(store.run_home("run-1") / "answers.jsonl") in prompt
    assert str(impl) in prompt
    assert str(eval_md) in prompt
