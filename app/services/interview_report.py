from __future__ import annotations

from statistics import mean

from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.chat import (
    InterviewReportResponse,
    RecommendedResource,
    VoiceInterviewReportRequest,
)
from app.services.interview_kit import get_recommended_resources


class ReportNarrative(BaseModel):
    summary: str
    content_analysis: str = ""
    strengths: list[str]
    improvement_areas: list[str]
    recommendations: list[str]


class TranscriptReportAssessment(BaseModel):
    technical_accuracy: int
    knowledge_depth: int
    communication_clarity: int
    logical_structure: int
    problem_solving: int
    job_match_score: int
    overall_score: int
    summary: str
    content_analysis: str = ""
    strengths: list[str]
    improvement_areas: list[str]
    recommendations: list[str]


class ReferenceAnswerItem(BaseModel):
    index: int
    reference_answer: str


class ReferenceAnswerBundle(BaseModel):
    items: list[ReferenceAnswerItem]


class InterviewReportBuilder:
    SCORE_FIELDS = [
        "technical_accuracy",
        "knowledge_depth",
        "communication_clarity",
        "logical_structure",
        "problem_solving",
        "job_match_score",
        "overall_score",
    ]

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0.2,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )

    @staticmethod
    def _clamp_score(value: int) -> int:
        return max(0, min(100, int(value)))

    def _score(self, evaluation: dict, field: str) -> int:
        value = evaluation.get(field, 0)
        try:
            return self._clamp_score(int(value))
        except (TypeError, ValueError):
            return 0

    def _dimension_label(self, dimension: str) -> str:
        labels = {
            "technical_accuracy": "技术准确性",
            "knowledge_depth": "知识深度",
            "communication_clarity": "表达清晰度",
            "logical_structure": "逻辑结构",
            "problem_solving": "问题解决能力",
            "job_match_score": "岗位匹配度",
        }
        return labels.get(dimension, dimension)

    def _recommendation_for(self, dimension: str) -> str:
        mapping = {
            "technical_accuracy": "回答前先校验关键技术细节，减少概念性和事实性错误。",
            "knowledge_depth": "补充原理、边界条件与取舍分析，提升答案深度。",
            "communication_clarity": "用“结论先行 + 分点说明”的方式，让表达更清楚。",
            "logical_structure": "使用 STAR 或 PREP 结构组织答案，避免跳跃叙述。",
            "problem_solving": "明确问题拆解、方案比较和最终决策依据。",
            "job_match_score": "把回答和岗位职责、业务目标、可量化结果主动关联。",
        }
        return mapping.get(dimension, "针对薄弱维度继续做专项练习。")

    @staticmethod
    def _build_summary(overall_score: int, strengths: list[str], improvement_areas: list[str]) -> str:
        if overall_score >= 85:
            level_text = "整体表现较强，已经接近目标岗位面试要求。"
        elif overall_score >= 70:
            level_text = "整体表现稳定，但仍有可提升空间。"
        else:
            level_text = "当前核心能力还需补强，建议继续进行针对性训练。"

        strength_text = "、".join(strengths) if strengths else "暂未形成稳定优势"
        improvement_text = "、".join(improvement_areas) if improvement_areas else "暂无明显短板"
        return f"{level_text} 当前优势：{strength_text}。优先改进：{improvement_text}。"

    def _format_reference_answer_from_evaluation(self, evaluation: dict | object) -> str:
        expected_key_points = []
        correction_suggestion = None

        if isinstance(evaluation, dict):
            expected_key_points = evaluation.get("expected_key_points") or []
            correction_suggestion = evaluation.get("correction_suggestion")
        else:
            expected_key_points = getattr(evaluation, "expected_key_points", None) or []
            correction_suggestion = getattr(evaluation, "correction_suggestion", None)

        lines: list[str] = []
        for item in expected_key_points:
            if item is None:
                continue
            stripped = str(item).strip()
            if stripped:
                lines.append(f"- {stripped}")

        parts: list[str] = []
        if lines:
            parts.append("参考要点：\n" + "\n".join(lines))
        if correction_suggestion and str(correction_suggestion).strip():
            parts.append("改进建议：\n" + str(correction_suggestion).strip())

        return "\n\n".join(parts).strip()

    def _generate_reference_answers(self, questions: list[str]) -> list[str]:
        if not questions:
            return []

        numbered = "\n".join(
            f"{idx}. {q.strip()[:800]}" for idx, q in enumerate(questions, start=1)
        )
        prompt = f"""
你是一位资深技术面试官。
请针对下面每一道问题给出简洁、可执行的中文参考答案。

问题列表：
{numbered}

输出规则：
- 返回一个对象，字段名为 items（数组）。
- 每个元素包含：index（题号）和 reference_answer（字符串）。
- 每一道题都必须有答案。
- 每条 reference_answer 控制在 200 字以内。
""".strip()

        chain = self.llm.with_structured_output(ReferenceAnswerBundle)
        try:
            result = chain.invoke(prompt)
        except Exception:
            return ["暂时无法生成参考答案。"] * len(questions)

        by_index: dict[int, str] = {}
        for item in getattr(result, "items", []) or []:
            try:
                by_index[int(item.index)] = (item.reference_answer or "").strip()
            except Exception:
                continue

        answers: list[str] = []
        for idx in range(1, len(questions) + 1):
            ans = (by_index.get(idx) or "").strip()
            answers.append(ans or "暂时无法生成参考答案。")
        return answers

    def _build_interview_questions_from_chat_messages(self, chat_messages: list[dict]) -> list[dict]:
        items: list[dict] = []
        missing: list[tuple[int, str]] = []
        pending_question = ""

        for msg in chat_messages:
            candidate_answer = (msg.get("user_message") or "").strip()
            assistant_message = (msg.get("assistant_message") or "").strip()
            evaluation = msg.get("evaluation")

            # 当前用户回答对应上一轮面试官问题，确保抓取全程问答，不依赖 evaluation 是否存在。
            if pending_question and candidate_answer:
                reference_answer = self._format_reference_answer_from_evaluation(evaluation) if evaluation else ""
                if not reference_answer:
                    missing.append((len(items), pending_question))
                    reference_answer = "暂时无法生成参考答案。"

                items.append(
                    {
                        "question": pending_question,
                        "candidate_answer": candidate_answer,
                        "reference_answer": reference_answer,
                    }
                )

            # assistant_message 视为下一轮面试官问题
            if assistant_message:
                pending_question = assistant_message

        if missing:
            generated = self._generate_reference_answers([q for _, q in missing])
            for (pos, _), ans in zip(missing, generated):
                if ans and ans.strip():
                    items[pos]["reference_answer"] = ans.strip()

        return items

    def _build_interview_questions_from_transcript(self, transcript: list) -> list[dict]:
        question_answer_pairs: list[tuple[str, str]] = []
        pending_question: str | None = None

        for turn in transcript:
            role = getattr(turn, "role", None)
            text = (getattr(turn, "text", "") or "").strip()
            if not text:
                continue

            if role == "interviewer":
                pending_question = text
                continue

            if role == "candidate" and pending_question:
                question_answer_pairs.append((pending_question, text))
                pending_question = None

        questions = [question for question, _ in question_answer_pairs]
        answers = self._generate_reference_answers(questions)
        return [
            {"question": question, "candidate_answer": candidate_answer, "reference_answer": reference_answer}
            for (question, candidate_answer), reference_answer in zip(question_answer_pairs, answers)
        ]

    def _build_narrative(
        self,
        latest: dict,
        averages: dict,
        chat_messages: list[dict],
        evaluations: list[dict],
        total_answers: int | None = None,
    ) -> ReportNarrative:
        _ = latest, chat_messages, evaluations
        dimension_scores = {
            "technical_accuracy": averages["technical_accuracy"],
            "knowledge_depth": averages["knowledge_depth"],
            "communication_clarity": averages["communication_clarity"],
            "logical_structure": averages["logical_structure"],
            "problem_solving": averages["problem_solving"],
            "job_match_score": averages["job_match_score"],
        }
        sorted_dims = sorted(dimension_scores.items(), key=lambda item: item[1], reverse=True)
        top_dims = [self._dimension_label(dim) for dim, score in sorted_dims[:2] if score >= 70]
        low_dims = [self._dimension_label(dim) for dim, _ in sorted_dims[-2:]]
        answer_count = total_answers if total_answers is not None else len(evaluations)

        return ReportNarrative(
            summary=self._build_summary(
                overall_score=averages["overall_score"],
                strengths=top_dims,
                improvement_areas=low_dims,
            ),
            content_analysis=(
                f"本次共记录 {answer_count} 条有效作答，参与评分 {len(evaluations)} 条，"
                f"综合均分约为 {averages['overall_score']} 分。"
            ),
            strengths=top_dims or ["作答完整度"],
            improvement_areas=low_dims or ["整体稳定性"],
            recommendations=[self._recommendation_for(dim) for dim, _ in sorted_dims[-2:]],
        )

    def _build_transcript_assessment(
        self,
        *,
        request: VoiceInterviewReportRequest,
        transcript: list,
    ) -> TranscriptReportAssessment:
        _ = request
        candidate_turns = [turn for turn in transcript if turn.role == "candidate" and turn.text.strip()]
        avg_len = int(mean([len(turn.text.strip()) for turn in candidate_turns])) if candidate_turns else 0

        base = 60
        if len(candidate_turns) >= 3:
            base += 6
        if len(candidate_turns) >= 6:
            base += 6
        if avg_len >= 80:
            base += 6
        if avg_len >= 160:
            base += 6

        technical_accuracy = self._clamp_score(base)
        knowledge_depth = self._clamp_score(base - 2)
        communication_clarity = self._clamp_score(base + 3)
        logical_structure = self._clamp_score(base)
        problem_solving = self._clamp_score(base - 1)
        job_match_score = self._clamp_score(base - 1)
        overall_score = self._clamp_score(
            round(
                (
                    technical_accuracy
                    + knowledge_depth
                    + communication_clarity
                    + logical_structure
                    + problem_solving
                    + job_match_score
                )
                / 6
            )
        )

        dim_scores = {
            "technical_accuracy": technical_accuracy,
            "knowledge_depth": knowledge_depth,
            "communication_clarity": communication_clarity,
            "logical_structure": logical_structure,
            "problem_solving": problem_solving,
            "job_match_score": job_match_score,
        }
        sorted_dims = sorted(dim_scores.items(), key=lambda item: item[1], reverse=True)
        top_dims = [self._dimension_label(dim) for dim, score in sorted_dims[:2] if score >= 70]
        low_dims = [self._dimension_label(dim) for dim, _ in sorted_dims[-2:]]

        return TranscriptReportAssessment(
            technical_accuracy=technical_accuracy,
            knowledge_depth=knowledge_depth,
            communication_clarity=communication_clarity,
            logical_structure=logical_structure,
            problem_solving=problem_solving,
            job_match_score=job_match_score,
            overall_score=overall_score,
            summary=self._build_summary(overall_score, top_dims, low_dims),
            content_analysis=(
                f"基于 {len(candidate_turns)} 条候选人作答进行评估，"
                f"平均回答长度约 {avg_len} 字。"
            ),
            strengths=top_dims or ["作答积极性"],
            improvement_areas=low_dims or ["稳定性"],
            recommendations=[self._recommendation_for(dim) for dim, _ in sorted_dims[-2:]],
        )

    def build(self, chat_id: str, chat_messages: list[dict]) -> InterviewReportResponse:
        evaluations = [msg["evaluation"] for msg in chat_messages if msg.get("evaluation")]
        latest = chat_messages[-1] if chat_messages else {}

        interview_questions = self._build_interview_questions_from_chat_messages(chat_messages)
        effective_answer_count = sum(
            1 for item in interview_questions if str(item.get("candidate_answer") or "").strip()
        )
        scored_answer_count = len(evaluations)
        total_answers = max(scored_answer_count, effective_answer_count)
        if not evaluations:
            return InterviewReportResponse(
                chat_id=chat_id,
                interview_role=latest.get("interview_role"),
                interview_level=latest.get("interview_level"),
                interview_type=latest.get("interview_type"),
                target_company=latest.get("target_company"),
                total_answers=total_answers,
                overall_score=0,
                technical_accuracy=0,
                knowledge_depth=0,
                communication_clarity=0,
                logical_structure=0,
                problem_solving=0,
                job_match_score=0,
                summary="当前有效作答样本不足，暂时无法生成完整评估。",
                content_analysis="请先完成至少一轮有内容的面试问答，再生成评估。",
                strengths=[],
                improvement_areas=["请提供更完整的作答内容，系统才能进行有效评估。"],
                recommendations=["至少完成一轮详细作答后，再重新生成报告。"],
                recommended_resources=[],
                interview_questions=interview_questions,
            )

        averages = {
            field: self._clamp_score(round(mean([self._score(evaluation, field) for evaluation in evaluations])))
            for field in self.SCORE_FIELDS
        }

        dimension_scores = {
            "technical_accuracy": averages["technical_accuracy"],
            "knowledge_depth": averages["knowledge_depth"],
            "communication_clarity": averages["communication_clarity"],
            "logical_structure": averages["logical_structure"],
            "problem_solving": averages["problem_solving"],
            "job_match_score": averages["job_match_score"],
        }
        sorted_dims = sorted(dimension_scores.items(), key=lambda item: item[1], reverse=True)
        low_dim_keys = [dim for dim, _ in sorted_dims[-2:]]

        narrative = self._build_narrative(
            latest=latest,
            averages=averages,
            chat_messages=chat_messages,
            evaluations=evaluations,
            total_answers=total_answers,
        )
        resources = [RecommendedResource(**item) for item in get_recommended_resources(low_dim_keys)]

        return InterviewReportResponse(
            chat_id=chat_id,
            interview_role=latest.get("interview_role"),
            interview_level=latest.get("interview_level"),
            interview_type=latest.get("interview_type"),
            target_company=latest.get("target_company"),
            total_answers=total_answers,
            overall_score=averages["overall_score"],
            technical_accuracy=averages["technical_accuracy"],
            knowledge_depth=averages["knowledge_depth"],
            communication_clarity=averages["communication_clarity"],
            logical_structure=averages["logical_structure"],
            problem_solving=averages["problem_solving"],
            job_match_score=averages["job_match_score"],
            summary=narrative.summary,
            content_analysis=narrative.content_analysis,
            strengths=narrative.strengths,
            improvement_areas=narrative.improvement_areas,
            recommendations=narrative.recommendations,
            recommended_resources=resources,
            interview_questions=interview_questions,
        )

    def build_from_transcript(
        self,
        *,
        chat_id: str,
        request: VoiceInterviewReportRequest,
    ) -> InterviewReportResponse:
        transcript = [
            turn for turn in request.transcript
            if turn.text and turn.text.strip()
        ]
        interview_questions = self._build_interview_questions_from_transcript(transcript)
        candidate_turns = [turn for turn in transcript if turn.role == "candidate"]

        if not candidate_turns:
            return InterviewReportResponse(
                chat_id=chat_id,
                interview_role=request.interview_role,
                interview_level=request.interview_level,
                interview_type=request.interview_type,
                target_company=request.target_company,
                total_answers=0,
                overall_score=0,
                technical_accuracy=0,
                knowledge_depth=0,
                communication_clarity=0,
                logical_structure=0,
                problem_solving=0,
                job_match_score=0,
                summary="当前有效语音作答不足，暂时无法生成完整评估。",
                content_analysis="请先完成至少一轮有效语音作答，再重新生成评估。",
                strengths=[],
                improvement_areas=["转写记录里至少需要一轮完整问答。"],
                recommendations=["建议继续进行一轮语音面试后再生成报告。"],
                recommended_resources=[],
                interview_questions=interview_questions,
            )

        assessment = self._build_transcript_assessment(request=request, transcript=transcript)
        dimension_scores = {
            "technical_accuracy": assessment.technical_accuracy,
            "knowledge_depth": assessment.knowledge_depth,
            "communication_clarity": assessment.communication_clarity,
            "logical_structure": assessment.logical_structure,
            "problem_solving": assessment.problem_solving,
            "job_match_score": assessment.job_match_score,
        }
        sorted_dims = sorted(dimension_scores.items(), key=lambda item: item[1], reverse=True)
        low_dim_keys = [dim for dim, _ in sorted_dims[-2:]]
        resources = [RecommendedResource(**item) for item in get_recommended_resources(low_dim_keys)]

        return InterviewReportResponse(
            chat_id=chat_id,
            interview_role=request.interview_role,
            interview_level=request.interview_level,
            interview_type=request.interview_type,
            target_company=request.target_company,
            total_answers=len(candidate_turns),
            overall_score=assessment.overall_score,
            technical_accuracy=assessment.technical_accuracy,
            knowledge_depth=assessment.knowledge_depth,
            communication_clarity=assessment.communication_clarity,
            logical_structure=assessment.logical_structure,
            problem_solving=assessment.problem_solving,
            job_match_score=assessment.job_match_score,
            summary=assessment.summary,
            content_analysis=assessment.content_analysis,
            strengths=assessment.strengths,
            improvement_areas=assessment.improvement_areas,
            recommendations=assessment.recommendations,
            recommended_resources=resources,
            interview_questions=interview_questions,
        )
