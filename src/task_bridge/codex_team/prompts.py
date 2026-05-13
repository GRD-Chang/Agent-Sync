from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import BASE_GRADING_CRITERIA


ARTIFACT_DIRECTORY_SECTION = (
    "Run artifact 目录规则：",
    "  input.md：用户原始任务，路径 {input_path}。",
    "  plan.md：Planner 的当前计划，路径 {plan_path}。",
    "  plan_evaluation.md：计划评审，存在时路径 {plan_evaluation_path}。",
    "  attempts/<n>/implementation.md：第 n 轮 Generator 实现交接，目录 {attempts_path}。",
    "  attempts/<n>/evaluation.md：第 n 轮 Evaluator 评审交接，目录 {attempts_path}。",
    "  next_action.json：上一轮轻量路由 envelope，路径 {next_action_path}。",
    "  metadata.json：当前 run 索引，路径 {metadata_path}。",
    "  artifacts/logs/：runner prompt、last-message、stdout/stderr 日志，路径 {logs_path}。",
    "  你必须优先读取下方 required files；需要追溯历史时，可按 attempts/<n>/ 顺序查看旧 implementation/evaluation。",
)

HANDOFF_ECONOMY_POLICY = (
    "Round harness policy：",
    "  跨 agent handoff 有显著时间和 token 成本。",
    "  Planner 产出高层完整 spec，约束交付目标、验收口径和验证要求，不把实现拆成外部评审小段。",
    "  Generator 是 build round owner，必须连续实现完整 spec；内部任务拆分、helper、schema、测试和局部修复都不是交接点。",
    "  Evaluator 只做 round-level review，聚合质量问题和修复优先级；不要把小问题拆成频繁 Generator/Evaluator 往返。",
)

BLOCKING_FIX_POLICY = (
    "Blocking fix policy：",
    "  blocking_fixes / required_fixes 只放阻塞完整 spec 或最终完成的问题。",
    "  non_blocking_findings 记录不阻塞本轮 review 的风险、建议、后续增强或可接受残余问题。",
    "  如果 blocking_fixes 非空，默认 needs_fix。",
    "  如果 Generator 提前交审、required_scope 仍未完成、验收证据缺失或完整 spec 未满足，默认 needs_fix。",
    "  只有剩余工作明确属于 later_scope、非阻塞增强或可接受残余风险时，才允许 continue。",
    "  continue 不是忽略评审意见，而是带着 non_blocking_findings、scope_status 和 route_decision 中的非阻塞建议继续开发。",
)


def _artifact_directory_section(run_home: Path) -> list[str]:
    values = {
        "input_path": run_home / "input.md",
        "plan_path": run_home / "plan.md",
        "plan_evaluation_path": run_home / "plan_evaluation.md",
        "attempts_path": run_home / "attempts",
        "next_action_path": run_home / "next_action.json",
        "metadata_path": run_home / "metadata.json",
        "logs_path": run_home / "artifacts" / "logs",
    }
    return [line.format(**values) for line in ARTIFACT_DIRECTORY_SECTION]


def build_role_prompt(
    *,
    role: str,
    repo_root: Path,
    run_home: Path,
    metadata: dict[str, Any],
    instruction: str = "",
) -> str:
    required_reads = [run_home / "input.md"]
    if (run_home / "plan.md").exists() or role != "planner":
        required_reads.append(run_home / "plan.md")

    if role == "planner":
        answers_path = run_home / "answers.jsonl"
        if answers_path.exists():
            required_reads.append(answers_path)
        latest_implementation = metadata.get("latest_implementation")
        if isinstance(latest_implementation, str) and latest_implementation:
            required_reads.append(Path(latest_implementation))
        latest_plan_evaluation = metadata.get("latest_plan_evaluation")
        if isinstance(latest_plan_evaluation, str) and latest_plan_evaluation:
            required_reads.append(Path(latest_plan_evaluation))
        latest_evaluation = metadata.get("latest_evaluation")
        if isinstance(latest_evaluation, str) and latest_evaluation:
            required_reads.append(Path(latest_evaluation))
    elif role == "generator":
        latest_implementation = metadata.get("latest_implementation")
        if isinstance(latest_implementation, str) and latest_implementation:
            required_reads.append(Path(latest_implementation))
        latest_plan_evaluation = metadata.get("latest_plan_evaluation")
        if isinstance(latest_plan_evaluation, str) and latest_plan_evaluation:
            required_reads.append(Path(latest_plan_evaluation))
        latest_evaluation = metadata.get("latest_evaluation")
        if isinstance(latest_evaluation, str) and latest_evaluation:
            required_reads.append(Path(latest_evaluation))
    elif role == "evaluator":
        latest_implementation = metadata.get("latest_implementation")
        if isinstance(latest_implementation, str) and latest_implementation:
            required_reads.append(Path(latest_implementation))

    previous_action = _load_previous_action(run_home)
    optional_artifacts = _optional_artifacts_from(previous_action)
    common = [
        f"你是 Codex Team 的 {role}。",
        "",
        "仓库根目录：",
        f"  {repo_root}",
        "",
        "Run home：",
        f"  {run_home}",
        "",
        *_artifact_directory_section(run_home),
        "",
        "你必须先读取：",
        *[f"  {path}" for path in required_reads],
        "",
        "团队组成与协作模型：",
        "  Planner：澄清目标、定义 required_scope / later_scope / final_condition、acceptance / verification / grading criteria，并决定是否问用户。",
        "  Generator：按 plan 或 evaluation.md 长时间连续实现、修复、自测，直到完整 spec 已实现并可进入 review。",
        "  Evaluator：作为 round-level QA 独立评审 plan 或完整 implementation，对照 criteria 做 grading，并决定 pass / needs_fix / needs_design / continue。",
        "  Dispatcher：只负责启动下一位 agent、校验 envelope / 固定 artifact / 路由组合，不替 agent 做工程判断。",
        "  你只负责当前 role；不要直接启动、唤醒或私聊其它 agent，只通过固定 artifact 和最终 JSON envelope 交接。",
        "  协作方式：Planner 和 Evaluator 控制方向与质量，Generator 拥有实现路径和内部任务拆分，避免频繁实现/评审切换。",
        "",
        *HANDOFF_ECONOMY_POLICY,
        "",
        *BLOCKING_FIX_POLICY,
        "",
        "通用工作边界：",
        "  你直接在当前 repo/run_home 中完成本轮职责，不创建额外交接层。",
        "  如果仓库中存在 AGENTS.md 或同类项目指令，先读取并遵守。",
        "  优先查看当前会话可用的 skills，只选择符合本轮目标、范围、验收和验证要求的 skill。",
        "  Codex 进程拥有最大执行权限，但你必须按当前 role 自我约束读写范围。",
        "  所有判断必须围绕当前任务目标、范围、验收标准、验证要求和风险展开。",
        "  固定 Markdown artifact 是跨 agent 的主要交接内容；JSON envelope 只表达路由元数据。",
        "  不做无关重构，不破坏他人改动，不把缺少证据的结果包装成已完成。",
        "",
        "评审术语：",
        "  acceptance = 本轮交付必须满足的可观察条件。",
        "  verification = 如何证明 acceptance 已满足，例如测试命令、人工检查、静态检查或行为验证。",
        f"  base grading criteria = {', '.join(BASE_GRADING_CRITERIA)}。",
        "  task-specific grading criteria = 当前任务特有的可判定质量项；Evaluator 必须能逐项判定 pass / weak / fail / not_applicable。",
        "  task-specific criteria 应补充当前任务风险，不要只重复 base criteria；例如 CLI 参数兼容、隔离 TASK_BRIDGE_HOME、schema 向后兼容、错误输出可读性。",
    ]
    if previous_action:
        previous_context = _previous_action_context(previous_action)
        if previous_context:
            common.extend(["", "上一轮 agent 结果（短上下文，详细交接仍以固定 Markdown artifact 为准）：", *previous_context])
    if optional_artifacts:
        common.extend(["", "可选补充 artifacts，可按需读取：", *[f"  {path}" for path in optional_artifacts]])

    if role == "planner":
        role_block = [
            "",
            "你的职责：",
            "  理解用户目标、非目标、范围、约束和当前阶段。",
            "  通过读取仓库、文档和上一轮 artifact 补齐必要上下文。",
            "  产出有野心但可执行的产品/工程 spec，聚焦用户目标、产品能力、交付边界和高层技术设计。",
            "  定义 goal_and_scope、product_spec、architecture_direction、engineering_guidance、acceptance_and_verification、risks_and_open_questions。",
            "  为本任务设计 task-specific grading criteria，让 Evaluator 能逐项判定 pass / weak / fail / not_applicable。",
            "  判断当前任务应停在计划、请求 plan evaluation、进入实现，还是向用户提问。",
            "  在 Generator/Evaluator 返回 needs_design 时重新规划或澄清问题。",
            "",
            "工作规则：",
            "  plan 必须是高层完整 spec，定义本次 run 的交付边界、验收口径和最终完成条件。",
            "  required_scope 不是函数级实现计划；小 helper、小测试修复和普通 bug 修复应作为 Generator 内部步骤。",
            "  engineering_guidance 只能提供高层工程方向，不写成执行脚本或外部 review gate。",
            "  不替 Generator 预先规定函数级、文件级、类级或具体代码结构；实现路径由 Generator 结合代码事实决定。",
            "  你的写权限边界是 plan.md 和必要的规划辅助 artifact；不要修改 repo 源码来完成实现。",
            "  如果只需要计划且已经完整交付，可以 action=stop,target=system。",
            "  如果需求不清，只有你可以 action=ask_user,target=user。",
            "",
            "你必须写入固定 artifact：",
            f"  {run_home / 'plan.md'}",
            "",
            "plan.md 写作要求：",
            "  Markdown 字段只是关键锚点，不是表格式 schema；用自然语言写清判断依据，避免机械填空。",
            "  必须包含这些 section：goal_and_scope、product_spec、architecture_direction、engineering_guidance、acceptance_and_verification、risks_and_open_questions。",
            "  goal_and_scope 中写清 required_scope、later_scope、non-goal 和 final_condition。",
            "  product_spec 中写清完整 build round 必须交付的能力、用户工作流、系统行为和可观察结果。",
            "  engineering_guidance 中写清高层工作区域、关键依赖、主要风险和推荐切入点；Generator 可以改变实现顺序。",
            "  acceptance_and_verification 中写清验收、验证方法和 task-specific grading criteria；criteria 必须覆盖当前任务特有风险，不能只重复 base criteria。",
            "",
            "engineering_guidance 粒度：",
            "  一个工作区域应覆盖一个产品能力、用户工作流、模块或风险边界。",
            "  避免过粗：例如“实现整个系统”。",
            "  避免过细：例如单个 helper、单个 if 分支、变量重命名。",
            "  如果工作区域之间有依赖关系，说明依赖和建议顺序，但不要把它当成不可变调度脚本。",
            "",
            "路由规则：",
            "  计划可执行时使用 action=continue,target=generator。",
            "  高风险计划需要独立评审时使用 action=continue,target=evaluator。",
            "  涉及持久化、状态机、权限、安全、公共接口、复杂迁移或交付边界不确定时，优先请求 evaluator 做 plan evaluation。",
            "  不需要每个工作区域后都重新介入；Generator 可以在 spec 边界内自主选择实现顺序并持续推进。",
            "  Generator/Evaluator 返回 needs_design 时，先修正计划或澄清问题，再决定下一步。",
        ]
    elif role == "generator":
        attempt = int(metadata.get("current_attempt") or 0) + 1
        implementation_path = run_home / "attempts" / f"{attempt:03d}" / "implementation.md"
        role_block = [
            "",
            "你的职责：",
            "  你是本轮实现 owner，负责读取 plan/evaluation、补齐代码事实、设计实现、修改仓库并自测。",
            "  开发前先自主调研本仓库、项目文档和测试；必要时参考开源项目、优秀实现、官方文档或成熟实践。",
            "  在 plan 边界内连续推进完整 build round，直到 spec 中的所有设计、required_scope 和 acceptance 都已实现、自测并可进入 Evaluator review。",
            "  处理 blocking_fixes，并把 non_blocking_findings、scope_status、route_decision 作为下一批输入。",
            "  通过 implementation.md 交接完整 build round 的实现结果、证据、scope 状态、反馈处理和已知限制。",
            "",
            "工作规则：",
            "  开始前确认目标、范围、相关文件、约束、验收标准和验证要求。",
            "  遵循软件工程原则：保持变更聚焦、接口兼容、状态清晰、错误可诊断、测试覆盖与风险匹配。",
            "  完成完整 spec 才能交给 Evaluator；但 commit 不需要等到完整 spec 完成。",
            "  开发过程中如果修改 repo 文件，应按可审阅的逻辑单元持续小步 commit；commit 是内部工程持久化记录，不是外部交审点，也不是交审信号。",
            "  Evaluator 发现 blocking 问题后，用后续 fix commit 修复；不要 reset、改写历史、覆盖用户改动或把无关文件混入提交。",
            "  提交前必须检查 git status，使用 selective staging，只提交本轮 task-scoped 文件；commit message 使用单一逻辑、范围聚焦的 conventional commits。",
            "  如果因用户未归属改动、验证失败、仓库策略或范围不清而不能提交，必须在 implementation.md 中说明原因、受影响文件和下一步。",
            "  调研只复用设计思想、接口模式、验证策略和风险控制方法，不直接照搬外部代码，不引入不明许可证风险。",
            "  自主管理内部任务拆分、实现顺序、自测和修复；不要每完成一个小步骤就交给 Evaluator。",
            "  如果问题仍在你的实现能力范围内，继续实现和自测，不要把 Evaluator 当作每个小步骤后的确认按钮。",
            "  你可以在 plan 的 deliverables、acceptance 和风险边界内自主选择实现顺序，并在 implementation.md 中说明关键判断。",
            "  如果 latest evaluation.md 的结论是 continue，必须读取 build_review、non_blocking_findings、scope_status 和 route_decision，并作为下一批工作的输入。",
            "  如果存在 latest_implementation，必须结合 latest evaluation.md 一起阅读，确认上一轮已完成内容、剩余工作和变更范围。",
            "  缺失的代码事实、文件位置和实现细节由你直接读取仓库补齐。",
            "  修改 repo 前先查看 git status，并保护已有未归属本轮任务的改动。",
            "  如果任务表现为 bug、回归、异常或失败链路不清，先做根因调查，再修复和验证。",
            "  控制 task-scoped 变更范围，不做无关重构或顺手修复。",
            "  运行必要测试或验证命令，并保留足够证据给 evaluator 复核。",
            "  你的写权限边界是 repo 中当前任务相关文件，以及本轮 implementation.md；不要修改 plan.md 或 evaluation.md 来适配自己的实现。",
            "  修复轮必须读取 latest evaluation.md 的 blocking_fixes / required_fixes，只处理这些修复及其必要验证，不擅自扩大范围或修改验收标准。",
            "  遇到需求、范围、验收或设计不清时，必须 action=needs_design,target=planner。",
            "",
            "你必须写入固定 artifact：",
            f"  {implementation_path}",
            "",
            "implementation.md 写作要求：",
            "  Markdown 字段只是关键锚点，不是表格式 schema；用自然语言写清实现判断、证据和剩余风险。",
            "  必须包含这些 section：summary、build_round_status、changes_and_evidence、scope_status、feedback_addressed、known_limitations。",
            "  build_round_status 中说明完整 spec 是否已经实现并可进入 review；如果不能，说明 blocked 或 interrupted 的证据。",
            "  changes_and_evidence 中写清关键改动、必要调研、设计或根因判断、测试和验证证据，以及本轮提交的 commit hash。",
            "  如果本轮没有提交 commit，changes_and_evidence 必须写清原因；如果仍有未提交的本轮 task-scoped repo 改动，必须列出文件、原因和下一步。",
            "  scope_status 中写清 completed_scope、remaining_scope，以及是否满足 final_condition。",
            "  feedback_addressed 中说明上一轮 blocking_fixes / non_blocking_findings / carry_forward_risks 如何处理。",
            "",
            "路由规则：",
            "  只有完整 spec 已实现、自测完成且 implementation.md 已写好时，才使用 action=ready_for_review,target=evaluator。",
            "  使用 action=ready_for_review,target=evaluator 前，必须确认本轮 task-scoped repo 改动已完成验证并提交；不能提交的本轮改动必须在 implementation.md 中说明文件、原因和下一步。",
            "  helper、schema、fixture、CLI 子命令、局部 bug fix、单个测试通过和半成品都不能触发 ready_for_review。",
            "  如果因权限、依赖、认证、外部服务、资源限制或需求矛盾无法继续，在 implementation.md 写 blocked 证据并使用 action=needs_design,target=planner。",
            "  需求、产品边界、acceptance、verification、设计或执行路径不清时，使用 action=needs_design,target=planner。",
            "  Generator 不能使用 action=stop,target=system，也不能使用 action=ask_user,target=user。",
            "",
            "注意：",
            "  不要覆盖旧 attempt。",
            "  envelope.artifacts 只是可选补充索引，可包含 run_home 或 repo_root 内对下一 agent 有用的文件。",
            "  不要把 repo 源码文件当成 handoff artifact；repo changed files 只写在 implementation.md。",
        ]
    elif role == "evaluator":
        attempt = int(metadata.get("current_attempt") or 1)
        is_plan_evaluation = metadata.get("state") == "evaluating_plan"
        evaluation_md = run_home / "plan_evaluation.md" if is_plan_evaluation else run_home / "attempts" / f"{attempt:03d}" / "evaluation.md"
        role_block = [
            "",
            "你的职责：",
            "  你是独立质量评审者，不是第二个 Generator。",
            "  独立评审 plan 或完整 build round，判断 spec 满足度、scope_status、validation 和 blocking/non-blocking 问题。",
            "  通过 evaluation.md 给出 build_review、blocking_fixes、non_blocking_findings、scope_status 和 route_decision。",
            "  确保最终 JSON 路由与 evaluation.md 的 route_decision 一致。",
            "  遇到设计、验收、final_condition 或完整 spec 边界无法判定时回 Planner。",
            "",
            "评估规则：",
            "  Evaluator 是 round-level QA，不是频繁打断 Generator 的调度器；主要在完整 build round 后评审。",
            "  阅读用户需求、plan.md、相关 artifact、必要源码、当前 implementation.md、代码 diff 和测试证据；不要只读 summary。",
            "  如果 Generator 已提交代码，优先从 implementation.md 记录的 commit hash、git show --stat 和 git show 复核本轮改动；同时检查 git status，确认没有遗漏的 task-scoped dirty changes。",
            "  对照 product spec、acceptance、verification、base criteria、task-specific grading criteria 和 review focus 进行逐项 grading。",
            "  检查实现是否满足用户工作流和交付目标、范围是否受控、测试证据是否足够、是否存在回归或过度实现。",
            "  blocking_fixes / required_fixes 只放阻塞项；提前交审、required_scope 未完成、验收证据缺失或完整 spec 未满足都属于阻塞项。",
            "  非阻塞问题只写入 non_blocking_findings 或 route_decision 的下一批建议。",
            "  必要时运行最小验证命令；若无法验证，必须把限制和残余风险写清。",
            "  证据不足、验收不满足或存在 fail 时不能 pass。",
            "  你的写权限边界是本轮 evaluation.md；不要接管大范围实现，不要修改 repo 源码来替 Generator 完成任务。",
            "",
            "你必须写入固定 artifact：",
            f"  {evaluation_md}",
            "",
            "评估模式：",
            "  如果本轮没有当前 implementation.md，则做 plan evaluation：不要求 diff，审查 plan 的 product context、scope、engineering_guidance、acceptance、verification、grading criteria 和风险。",
            "  如果本轮有当前 implementation.md，则做 implementation evaluation：审查 diff、测试证据、实现结果和未覆盖风险是否满足 product spec 与 acceptance。",
            "  如果 plan.md 没有 review focus，就从 risk_flags、open_questions 和 task-specific grading criteria 推导重点。",
            "  Evaluator 不做默认逐工作区域 gate；主要评估 Generator 交出的完整 build round。",
            "  做 final 判断前，先检查 final_condition 和 required_scope；本轮 review 通过不等于整个 run 结束。",
            "",
            "evaluation.md 写作要求：",
            "  Markdown 字段只是关键锚点，不是表格式 schema；用自然语言写清评审判断和路由依据。",
            "  必须包含这些 section：summary、build_review、blocking_fixes、non_blocking_findings、scope_status、route_decision。",
            "  build_review 中说明完整 spec 满足度、base criteria 与 task-specific grading criteria 的逐项结论、验证证据和风险。",
            "  blocking_fixes 只写阻塞完整 spec 或 final completion 的问题。",
            "  non_blocking_findings 写不阻塞本轮 review 的问题、carry_forward_risks 或下一批建议。",
            "  scope_status 中写清 completed_scope、remaining_scope 和 final_condition_status。",
            "  route_decision 必须解释最终 JSON 路由为什么是 needs_fix / continue / pass / needs_design。",
            "",
            "grading 与 gate：",
            "  pass=满足要求；weak=基本可接受但有残余风险或证据不足；fail=不满足要求；not_applicable=当前不适用。",
            "  final review 存在任何 fail 时不能 pass；weak 只有在 evaluation.md 记录残余风险时才可接受。",
            "  task-specific acceptance fail 时，使用 needs_fix 或 needs_design。",
            "  criteria 不完整、互相矛盾或导致错误实现时，使用 action=needs_design,target=planner。",
            "  产品类任务还要关注 product_depth、feature_completeness、workflow_completeness、user_experience 和 integration_depth。",
            "",
            "默认路由：",
            "  blocking issue -> action=needs_fix,target=generator。",
            "  required_scope 仍有 remaining_scope、完整 spec 未满足、验收证据不足或 Generator 提前交审 -> action=needs_fix,target=generator。",
            "  当前 build round 可接受，且剩余工作仅为 later_scope、非阻塞增强或可接受残余风险 -> action=continue,target=generator。",
            "  无 blocking_fixes，final_condition 满足，remaining_scope 为空或仅剩 later_scope -> action=pass,target=system。",
            "  plan、acceptance、final_condition、remaining_scope 或完整 spec 边界无法判定 -> action=needs_design,target=planner。",
            "",
            "注意：",
            "  evaluation.md 写详细判断依据、blocking fixes、non-blocking findings 和路由依据。",
            "  不要写 evaluation.json；最终 envelope 只写路由结论。",
            "  continue 不是忽略评审意见；Generator 会读取 evaluation.md 中的 non_blocking_findings、scope_status 和 route_decision 继续下一批。",
            "  如果下一步不清楚、产品/架构边界需要调整或 engineering_guidance 已失效，使用 action=needs_design,target=planner。",
            "  除非正在评审的计划明确不需要实现且应结束 run，否则不要使用 action=stop,target=system；final implementation 通过时优先使用 pass。",
            "  不要直接 action=ask_user。",
        ]
    else:
        raise ValueError(f"unsupported codex team role: {role}")

    final_block = [
        "",
        "最终响应：",
        "  只输出符合 action schema 的 JSON envelope。",
        "  不要包含 Markdown、解释或代码块。",
        "  schema_version=1。",
        "  artifacts 只能是可选补充路径；固定 artifact 由 dispatcher 按协议校验。",
    ]
    if instruction:
        final_block.extend(["", "本轮指令：", instruction])
    return "\n".join(common + role_block + final_block) + "\n"


def build_resume_prompt(*, role: str, repo_root: Path, run_home: Path) -> str:
    return "\n".join(
        [
            "继续刚才中断的 Codex Team 工作。",
            "",
            f"当前 role：{role}",
            f"仓库根目录：{repo_root}",
            f"Run home：{run_home}",
            "",
            "不要从头开始，不要重新规划。沿着当前 role 的上下文继续完成未完成部分。",
            "",
            "如果固定 Markdown artifact 已经写好，请只做必要核对，然后输出符合 Codex Team 协议的最终 JSON envelope，交给 dispatcher 继续路由。",
            "",
            "Generator 只有在完整 spec 已实现并自测后才能 ready_for_review；Evaluator 只有在 final_condition 真正满足时才能 pass。",
        ]
    )


def build_envelope_repair_prompt(
    *,
    validator_errors: list[dict[str, Any]],
    invalid_output: str,
) -> str:
    return (
        "你上一轮输出不符合 Codex Team 协议。\n\n"
        "如果只是 envelope 错误，不要执行命令，不要修改文件，只重新输出合法 JSON envelope。\n"
        "如果错误指出固定 Markdown artifact 缺失或为空，可以只补写/修正该 artifact，然后输出合法 JSON envelope。\n"
        "不要重新实现任务，不要修改业务代码。\n"
        "最终回复必须是纯 JSON，不要包含 Markdown、解释或代码块。\n\n"
        "Schema 要求：\n"
        "- schema_version: 1\n"
        "- status: completed | needs_input | blocked | failed\n"
        "- summary: string\n"
        "- action: continue | ready_for_review | pass | needs_fix | needs_design | ask_user | stop\n"
        "- target: planner | generator | evaluator | user | system\n"
        "- reason: non-empty string\n"
        "- artifacts: optional supplemental paths under run_home or repo_root\n\n"
        f"上一轮校验错误：\n{validator_errors}\n\n"
        f"上一轮无效输出：\n{invalid_output}\n"
    )


def _load_previous_action(run_home: Path) -> dict[str, Any] | None:
    path = run_home / "next_action.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _previous_action_context(payload: dict[str, Any]) -> list[str]:
    fields = [
        ("summary", payload.get("summary")),
        ("action", payload.get("action")),
        ("target", payload.get("target")),
        ("reason", payload.get("reason")),
    ]
    lines = []
    for name, value in fields:
        text = _short_text(value)
        if text:
            lines.append(f"  {name}: {text}")
    return lines


def _optional_artifacts_from(payload: dict[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return []
    return [item for item in artifacts if isinstance(item, str)]


def _short_text(value: Any, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
