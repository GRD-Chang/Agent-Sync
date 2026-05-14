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
    reason: str = "ok",
    artifacts: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "summary": summary,
        "status": "completed",
        "action": action,
        "target": target,
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
                envelope=_envelope("m1 done", action="ready_for_review", target="evaluator"),
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
                envelope=_envelope("final done", action="ready_for_review", target="evaluator"),
            )
        ev_md = run_home / "attempts" / "002" / "evaluation.md"
        ev_md.write_text("final pass")
        return RunnerResult(
            role=role,
            returncode=0,
            duration_seconds=0,
            envelope=_envelope("final passed", action="pass", target="system"),
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


def test_dispatcher_records_agent_step_observability_events(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="planning", current_owner="planner")
    plan = store.run_home("run-1") / "plan.md"
    plan.write_text("plan")
    runner = FakeCodexRunner(
        [
            RunnerResult(
                role="planner",
                returncode=0,
                duration_seconds=2.5,
                stdout_tail="planner stdout",
                envelope=_envelope("planned", action="continue", target="evaluator"),
                last_message_path=store.run_home("run-1") / "artifacts" / "logs" / "planner-001.last-message.json",
            )
        ]
    )

    CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    events = store.read_events("run-1")
    started = next(event for event in events if event["type"] == "agent_step_started")
    finished = next(event for event in events if event["type"] == "agent_step_finished")
    assert started["role"] == "planner"
    assert started["invocation_id"] == "planner-001"
    assert started["stdout_log"].endswith("planner-001.stdout.log")
    assert finished["invocation_id"] == "planner-001"
    assert finished["duration_seconds"] == 2.5
    assert finished["returncode"] == 0
    assert finished["stdout_tail"] == "planner stdout"


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


def test_resume_failed_runner_error_uses_thread_id(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    run_home = store.run_home("run-1")
    evaluation = run_home / "attempts" / "001" / "evaluation.md"
    evaluation.parent.mkdir(parents=True)
    evaluation.write_text("review ok")
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
    assert any(event["type"] == "resume_started" for event in store.read_events("run-1"))


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
    assert any(event["type"] == "resume_started" for event in store.read_events("run-1"))


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


def test_generator_direct_stop_is_repaired_when_session_available(tmp_path: Path) -> None:
    store = CodexTeamStore(home=tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata = store.create_run(repo_root=repo, input_text="x", run_id="run-1")
    store.update_metadata(metadata["run_id"], state="generating", current_owner="generator")
    repaired_impl = store.run_home("run-1") / "attempts" / "001" / "implementation.md"
    repaired = _envelope("fixed", action="ready_for_review", target="evaluator")
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

    assert outcome.state == "evaluating_final"
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
    runner = FakeCodexRunner([_envelope("ready", action="ready_for_review", target="evaluator")])

    CodexTeamDispatcher(store=store, runner=runner).step("run-1")

    prompt = runner.calls[0]["prompt"]
    assert "action=ready_for_review,target=evaluator" in prompt
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
        assert "跨 agent handoff 有显著时间和 token 成本" in prompt
        assert "Round harness policy" in prompt
        assert "Generator 是 build round owner" in prompt
        assert "Evaluator 只做 round-level review" in prompt
        assert "Review gate policy" in prompt
        assert "input.md 是最高优先级事实源" in prompt
        assert "Issues 为无且证据充分时允许" in prompt
        assert "continue 只表示当前 build round 合格" in prompt
        assert "Run artifact 目录规则" in prompt
        assert "attempts/<n>/implementation.md" in prompt
        assert "attempts/<n>/evaluation.md" in prompt
        assert "metadata.json" in prompt
        assert "next_action.json" in prompt
        assert "评审术语" in prompt
        assert "Done Contract = pass 前必须真实满足的硬完成条件" in prompt
        assert "Verification Contract = 证明 Done Contract 已满足所需的测试、检查和证据" in prompt
        assert "base grading criteria" in prompt
        assert "Evaluation Criteria = Planner 为当前任务定义的 3-5 条质量轴" in prompt
        assert "不做无关重构" in prompt
        assert "checkpoint" not in prompt
        assert "candidate_boundary" not in prompt
        assert "completion_scope" not in prompt
        assert "implementation_strategy" not in prompt

    assert "产品契约制定者，不是详细工程方案作者" in planner_prompt
    assert "判断本轮是 Scope-Lock 还是 Concept-Expand" in planner_prompt
    assert "简洁、可执行、可验证且不漂移的产品契约" in planner_prompt
    assert "少而强的 Evaluation Criteria" in planner_prompt
    assert "工作规则" in planner_prompt
    assert "input.md 是最高优先级事实源" in planner_prompt
    assert "Scope-Lock：用户已经给出明确目标" in planner_prompt
    assert "Concept-Expand：用户只给出初步想法" in planner_prompt
    assert "用户显式 required 不能静默降级为 later_scope" in planner_prompt
    assert "不能用 fake/stub/controlled failure 包装成 pass" in planner_prompt
    assert "不替 Generator 预先规定函数级、文件级、类级" in planner_prompt
    assert "Markdown 字段只是关键锚点，不是表格式 schema" in planner_prompt
    assert "Planning Mode、Input Contract、Outcome Contract、Scope Contract、Done Contract、Verification Contract、Evaluation Criteria" in planner_prompt
    assert "不要写 Route section" in planner_prompt
    assert "Input Contract 中逐条列出 input.md 的显式要求" in planner_prompt
    assert "每条标记 required / non_goal / blocked / needs_clarification" in planner_prompt
    assert "Outcome Contract 中写清完成后用户能观察到什么变化" in planner_prompt
    assert "Scope Contract 中写清本轮必须完成什么" in planner_prompt
    assert "Done Contract 不能弱于 Input Contract" in planner_prompt
    assert "Verification Contract 中写清需要运行的测试、smoke、人工检查和证据" in planner_prompt
    assert "如果包含 E2E，必须列出各链路段哪些必须真实" in planner_prompt
    assert "Evaluation Criteria 中默认写 3-5 条任务特定质量标准" in planner_prompt
    assert "只有任务风险确实需要时才增加条目" in planner_prompt
    assert "每条标准都说明要评判的核心质量" in planner_prompt
    assert "什么表现算好、什么表现应失败" in planner_prompt
    assert "不要堆实现 checklist" in planner_prompt
    assert "实现路径由 Generator 根据代码事实决定" in planner_prompt
    assert "目标忠实度、核心能力深度、集成真实性" in planner_prompt
    assert "持久化、状态机、权限、安全、公共接口、复杂迁移" in planner_prompt
    assert "自主选择实现顺序" in generator_prompt
    assert "implementation.md 中说明关键判断" in generator_prompt
    assert "需求、产品边界、Done Contract、Verification Contract、设计或执行路径不清" in generator_prompt
    assert "开发前先自主调研" in generator_prompt
    assert "开源项目、优秀实现、官方文档或成熟实践" in generator_prompt
    assert "只复用设计思想、接口模式、验证策略和风险控制方法" in generator_prompt
    assert "修复轮必须读取 latest evaluation.md 的 Issues、Criteria Review 和 Route Decision" in generator_prompt
    assert "在 plan 边界内连续推进完整 build round" in generator_prompt
    assert "产品契约、Done Contract 和 Verification Contract 都已实现" in generator_prompt
    assert "遵循软件工程原则" in generator_prompt
    assert "完成产品契约才能交给 Evaluator；但 commit 不需要等到产品契约完成" in generator_prompt
    assert "按可审阅的逻辑单元持续小步 commit" in generator_prompt
    assert "commit 是内部工程持久化记录，不是外部交审点，也不是交审信号" in generator_prompt
    assert "用后续 fix commit 修复" in generator_prompt
    assert "selective staging" in generator_prompt
    assert "conventional commits" in generator_prompt
    assert "不能提交，必须在 implementation.md 中说明原因" in generator_prompt
    assert "不要每完成一个小步骤就交给 Evaluator" in generator_prompt
    assert "如果问题仍在你的实现能力范围内，继续实现和自测" in generator_prompt
    assert "不要把 Evaluator 当作每个小步骤后的确认按钮" in generator_prompt
    assert "工作规则" in generator_prompt
    assert "处理 evaluation.md 的 Issues，并把 Criteria Review、Evidence Review 和 Route Decision 作为下一批输入" in generator_prompt
    assert "自主管理内部任务拆分、实现顺序、自测和修复" in generator_prompt
    assert "summary、build_round_status、changes_and_evidence、contract_status" in generator_prompt
    assert "feedback_addressed、residual_risks" in generator_prompt
    assert "build_round_status 中说明产品契约是否已经实现并可进入 review" in generator_prompt
    assert "changes_and_evidence 中写清关键改动、必要调研、设计或根因判断、测试和验证证据" in generator_prompt
    assert "contract_status 中写清 Done Contract、Verification Contract、completed_scope 和 remaining_scope" in generator_prompt
    assert "feedback_addressed 中说明上一轮 Issues、Criteria Review、Evidence Review 和 Route Decision 如何处理" in generator_prompt
    assert "residual_risks 中只写真实存在的剩余风险" in generator_prompt
    assert "本轮提交的 commit hash" in generator_prompt
    assert "没有提交 commit" in generator_prompt
    assert "仍有未提交的本轮 task-scoped repo 改动" in generator_prompt
    assert "结论是 continue" in generator_prompt
    assert "Verdict、Criteria Review、Evidence Review、Issues 和 Route Decision" in generator_prompt
    assert "修改 repo 前先查看 git status" in generator_prompt
    assert "如果任务表现为 bug、回归、异常或失败链路不清，先做根因调查" in generator_prompt
    assert "不要修改 plan.md 或 evaluation.md 来适配自己的实现" in generator_prompt
    assert "只有产品契约已实现、自测完成且 implementation.md 已写好" in generator_prompt
    assert "本轮 task-scoped repo 改动已完成验证并提交" in generator_prompt
    assert "不能提交的本轮改动必须在 implementation.md 中说明文件、原因和下一步" in generator_prompt
    assert "helper、schema、fixture、CLI 子命令、局部 bug fix" in generator_prompt
    assert "action=ready_for_review,target=evaluator" in generator_prompt
    assert "action=needs_design,target=planner" in generator_prompt
    assert "Generator 不能使用 action=stop,target=system" in generator_prompt
    assert "评估规则" in evaluator_prompt
    assert "批判性的专家评审者" in evaluator_prompt
    assert "不是第二个 Generator，也不是风险分拣员" in evaluator_prompt
    assert "是否忠实于 input.md、plan.md 的产品契约和真实可用性" in evaluator_prompt
    assert "implementation evaluation 必须审查相关源码和真实 diff" in evaluator_prompt
    assert "不能只根据 implementation.md、日志摘要或测试结果下结论" in evaluator_prompt
    assert "有影响用户目标、Input Contract、Done Contract、真实性、安全性、资源控制或可维护性的实质问题，就不能 pass" in evaluator_prompt
    assert "确保最终 JSON 路由与 evaluation.md 的 Route Decision 一致" in evaluator_prompt
    assert "input.md 是最高优先级事实源" in evaluator_prompt
    assert "如果 plan.md 弱化、遗漏或重解释用户显式 required / non_goal / forbidden 项" in evaluator_prompt
    assert "如果 implementation 满足 plan.md 但不满足 input.md" in evaluator_prompt
    assert "不要只读 summary" in evaluator_prompt
    assert "当前 implementation.md、相关源码、真实代码 diff 和测试证据" in evaluator_prompt
    assert "代码审查必须覆盖本轮修改文件、关键调用链、接口边界、错误处理、状态持久化和测试覆盖" in evaluator_prompt
    assert "implementation.md 记录的 commit hash" in evaluator_prompt
    assert "git show --stat" in evaluator_prompt
    assert "如果没有 commit，使用 git diff / git status 审查未提交的 task-scoped 改动" in evaluator_prompt
    assert "没有遗漏的 task-scoped dirty changes" in evaluator_prompt
    assert "同时对照 base criteria 和 plan.md 的 3-5 条 Evaluation Criteria" in evaluator_prompt
    assert "两层 criteria 都必须评审" in evaluator_prompt
    assert "Issues 中只列导致当前不能 pass 的实质问题" in evaluator_prompt
    assert "用户显式 required 项、Done Contract、真实性、安全性相关标准没有降低标准通过选项" in evaluator_prompt
    assert "controlled failure 只能证明 failure path" in evaluator_prompt
    assert "评估模式" in evaluator_prompt
    assert "plan evaluation" in evaluator_prompt
    assert "不要求 diff" in evaluator_prompt
    assert "Input Contract、Done Contract、Verification Contract、Evaluation Criteria" in evaluator_prompt
    assert "implementation evaluation" in evaluator_prompt
    assert "必须审查相关源码与真实 diff" in evaluator_prompt
    assert "如果 plan.md 没有 Evaluation Criteria" in evaluator_prompt
    assert "不做默认逐工作区域 gate" in evaluator_prompt
    assert "Evaluator 是 round-level QA，不是频繁打断 Generator 的调度器" in evaluator_prompt
    assert "Verdict、Contract Fidelity、Evidence Review、Criteria Review、Issues、Route Decision" in evaluator_prompt
    assert "Authenticity Review" in evaluator_prompt
    assert "Verdict 中写 pass / needs_fix / needs_design / continue" in evaluator_prompt
    assert "Contract Fidelity 中对照 input.md 和 plan.md" in evaluator_prompt
    assert "Evidence Review 中列出实际检查过的源码文件、diff/commit/worktree" in evaluator_prompt
    assert "Criteria Review 中同时评审 base criteria 和 plan.md 的 Evaluation Criteria" in evaluator_prompt
    assert "每条给出 pass / fail / blocked / not_applicable" in evaluator_prompt
    assert "Issues 中列出所有导致当前不能 pass 的问题" in evaluator_prompt
    assert "Route Decision 必须解释最终 JSON 路由" in evaluator_prompt
    assert "本轮 review 通过不等于整个 run 结束" in evaluator_prompt
    assert "先检查 Input Contract、Done Contract、Verification Contract 和 Evaluation Criteria" in evaluator_prompt
    assert "不要修改 repo 源码来替 Generator 完成任务" in evaluator_prompt
    assert "任一 base criteria 或 plan Evaluation Criteria 为 fail / blocked 时不能 pass" in evaluator_prompt
    assert "product_depth、feature_completeness、workflow_completeness" in evaluator_prompt
    assert "默认路由" in evaluator_prompt
    assert "实现有实质问题但方向明确" in evaluator_prompt
    assert "plan 弱化 input" in evaluator_prompt
    assert "当前 build round 合格，但 run 明确还有下一阶段 required work" in evaluator_prompt
    assert "Issues 为无，证据充分 -> action=pass,target=system" in evaluator_prompt
    assert "不要用 continue 绕开 Issues" in evaluator_prompt
    assert "action=continue,target=generator" in evaluator_prompt
    assert "Done Contract、Verification Contract 或 Evaluation Criteria 需要调整" in evaluator_prompt
    assert "action=pass,target=system" in evaluator_prompt
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
