from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.interview_assessment import is_non_answer
from app.services.interview_kit import normalize_interview_round


@dataclass(frozen=True)
class InterviewWorkflowDecision:
    phase: str
    question_mode: str
    completed_questions: int
    follow_up_count: int
    max_follow_ups: int
    should_switch_to_coding: bool
    should_finish: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _phase_for_progress(interview_type: str | None, completed_questions: int, question_limit: int) -> str:
    interview_round = normalize_interview_round(interview_type)
    if completed_questions <= 0:
        return "opening"
    if interview_round == "HR面":
        return "behavioral"

    progress = completed_questions / max(1, question_limit)
    if interview_round == "一面":
        if progress <= 0.3:
            return "foundation"
        if progress <= 0.6:
            return "project_deep_dive"
    else:
        if progress <= 0.5:
            return "project_deep_dive"
    if progress <= 0.8:
        return "coding"
    return "behavioral"


def _latest_workflow_metadata(relevant_docs: list[dict]) -> tuple[str, int]:
    for document in reversed(relevant_docs):
        mode = str(document.get("question_mode") or "").strip()
        if mode:
            try:
                follow_up_count = max(0, int(document.get("follow_up_count") or 0))
            except (TypeError, ValueError):
                follow_up_count = 0
            return mode, follow_up_count
    return "", 0


def decide_interview_workflow(
    *,
    answer: str,
    has_previous_question: bool,
    current_answer_counted: bool,
    completed_questions: int,
    question_limit: int,
    interview_type: str | None,
    relevant_docs: list[dict],
    coding_started: bool,
    max_follow_ups: int,
) -> InterviewWorkflowDecision:
    """Return the deterministic control decision for the next interviewer turn."""
    completed_after_answer = completed_questions + int(current_answer_counted)
    should_finish = completed_after_answer >= question_limit
    phase = "closing" if should_finish else _phase_for_progress(
        interview_type,
        completed_after_answer,
        question_limit,
    )
    previous_mode, previous_follow_ups = _latest_workflow_metadata(relevant_docs)
    max_follow_ups = max(0, max_follow_ups)

    if should_finish:
        question_mode = "finish"
        follow_up_count = 0
    elif has_previous_question and is_non_answer(answer):
        question_mode = "topic_switch"
        follow_up_count = 0
    elif not has_previous_question:
        question_mode = "primary"
        follow_up_count = 0
    elif phase == "coding" and not coding_started:
        question_mode = "coding"
        follow_up_count = 0
    elif current_answer_counted and previous_mode not in {"topic_switch", "finish"} and previous_follow_ups < max_follow_ups:
        question_mode = "follow_up"
        follow_up_count = previous_follow_ups + 1
    else:
        question_mode = "topic_switch"
        follow_up_count = 0

    return InterviewWorkflowDecision(
        phase=phase,
        question_mode=question_mode,
        completed_questions=min(completed_after_answer, question_limit),
        follow_up_count=follow_up_count,
        max_follow_ups=max_follow_ups,
        should_switch_to_coding=question_mode == "coding",
        should_finish=should_finish,
    )


def render_workflow_instruction(decision: InterviewWorkflowDecision) -> str:
    mode_instructions = {
        "primary": "提出当前阶段的一道新主问题，不追问不存在的上一题。",
        "follow_up": "必须围绕上一问回答中的一个具体事实继续深挖，不得换成无关题目。",
        "topic_switch": "必须换一个考察点，不得继续追问上一题，也不得重复历史问题。",
        "coding": "必须进入在线编程题，不得继续普通项目问答。",
        "finish": "停止提问，不得再调用题目生成模型。",
    }
    return (
        "后端工作流门控（优先级高于生成策略）：\n"
        f"- 当前阶段：{decision.phase}\n"
        f"- 下一题模式：{decision.question_mode}\n"
        f"- 已完成有效题数：{decision.completed_questions}\n"
        f"- 连续追问：{decision.follow_up_count}/{decision.max_follow_ups}\n"
        f"- 强制动作：{mode_instructions[decision.question_mode]}"
    )
