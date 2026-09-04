from __future__ import annotations

from statistics import mean

from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.chat import (
    CompetencySummary,
    EvidenceItem,
    InterviewReportResponse,
    JDRequirementMatch,
    RecommendedResource,
    VoiceInterviewReportRequest,
)
from app.services.interview_kit import get_recommended_resources
from app.services.interview_assessment import get_rubric, is_countable_answer
from app.services.interview_evaluator import InterviewEvaluator


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
            model=settings.INTERVIEW_LLM_MODEL,
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

    def _dimension_score(self, evaluation: dict, field: str, evaluations: list[dict]) -> int | None:
        """Ignore legacy default zeros when only the overall score was saved."""
        raw_value = evaluation.get(field)
        if raw_value is None:
            return None
        try:
            value = self._clamp_score(int(raw_value))
        except (TypeError, ValueError):
            return None

        dimension_fields = (
            "technical_accuracy",
            "knowledge_depth",
            "communication_clarity",
            "logical_structure",
            "problem_solving",
            "job_match_score",
        )
        dimension_values = []
        for dimension in dimension_fields:
            try:
                dimension_values.append(int(evaluation.get(dimension, 0)))
            except (TypeError, ValueError):
                dimension_values.append(0)

        is_legacy_default = (
            self._score(evaluation, "overall_score") > 0
            and all(item == 0 for item in dimension_values)
            and any(self._score(item, "overall_score") > 0 for item in evaluations)
        )
        return None if is_legacy_default else value

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

    @staticmethod
    def _dedupe_text(items: list[str], limit: int = 3) -> list[str]:
        result: list[str] = []
        seen = set()
        for item in items:
            text = str(item or "").strip()
            key = "".join(text.split())
            if text and key not in seen:
                seen.add(key)
                result.append(text)
        return result[:limit]

    def _build_competency_assessments(self, evaluations: list[dict]) -> list[CompetencySummary]:
        buckets: dict[str, dict] = {}
        for evaluation in evaluations:
            assessments = evaluation.get("capability_assessments") or []
            if not assessments:
                assessments = [
                    {
                        "capability": tag,
                        "score": self._score(evaluation, "overall_score"),
                        "evidence": [],
                        "missing_points": evaluation.get("improvement_areas") or [],
                    }
                    for tag in (evaluation.get("capability_tags") or [])
                ]
            for item in assessments:
                if not isinstance(item, dict):
                    continue
                capability = str(item.get("capability") or "综合能力").strip()
                bucket = buckets.setdefault(capability, {"scores": [], "evidence": [], "evidence_items": [], "missing": []})
                try:
                    bucket["scores"].append(self._clamp_score(int(item.get("score", 0))))
                except (TypeError, ValueError):
                    continue
                bucket["evidence"].extend(item.get("evidence") or [])
                bucket["evidence"].extend(evaluation.get("resume_evidence") or [])
                bucket["evidence"].extend(evaluation.get("knowledge_evidence") or [])
                bucket["evidence_items"].extend(evaluation.get("knowledge_evidence_items") or [])
                candidate_answer = str(evaluation.get("_candidate_answer") or "").strip()
                if (
                    not item.get("evidence")
                    and not evaluation.get("knowledge_evidence")
                    and candidate_answer
                ):
                    excerpt = " ".join(candidate_answer.split())[:180]
                    bucket["evidence"].append(f"作答摘录（待核验）：{excerpt}")
                bucket["missing"].extend(item.get("missing_points") or [])

        summaries: list[CompetencySummary] = []
        for capability, bucket in buckets.items():
            count = len(bucket["scores"])
            confidence = "高" if count >= 3 else "中" if count >= 2 else "低"
            summaries.append(
                CompetencySummary(
                    capability=capability,
                    score=self._clamp_score(round(mean(bucket["scores"]))) if count else 0,
                    confidence=confidence,
                    covered_questions=count,
                    evidence=self._dedupe_text(bucket["evidence"]),
                    evidence_items=[EvidenceItem.model_validate(item) for item in bucket["evidence_items"][:4]],
                    missing_points=self._dedupe_text(bucket["missing"]),
                )
            )
        return sorted(summaries, key=lambda item: (-item.covered_questions, item.score, item.capability))[:8]

    def _build_jd_requirement_matches(self, evaluations: list[dict]) -> list[JDRequirementMatch]:
        priority = {"已体现": 3, "部分体现": 2, "未体现": 1, "不适用": 0}
        buckets: dict[str, dict] = {}
        for evaluation in evaluations:
            for item in evaluation.get("jd_requirement_matches") or []:
                if not isinstance(item, dict):
                    continue
                requirement = str(item.get("requirement") or "").strip()
                if not requirement:
                    continue
                bucket = buckets.setdefault(requirement, {"status": "不适用", "evidence": [], "gaps": []})
                status = str(item.get("status") or "不适用")
                if priority.get(status, 0) > priority.get(bucket["status"], 0):
                    bucket["status"] = status
                bucket["evidence"].extend(item.get("evidence") or [])
                gap = str(item.get("gap") or "").strip()
                if gap:
                    bucket["gaps"].append(gap)

        return [
            JDRequirementMatch(
                requirement=requirement,
                status=bucket["status"] if bucket["status"] in priority else "不适用",
                evidence=self._dedupe_text(bucket["evidence"], limit=2),
                gap="；".join(self._dedupe_text(bucket["gaps"], limit=2)),
            )
            for requirement, bucket in list(buckets.items())[:8]
        ]

    @staticmethod
    def _normalize_evaluation_for_display(evaluation: dict | None) -> dict | None:
        """Make legacy compact Rubric responses readable without changing stored data."""
        if not isinstance(evaluation, dict):
            return evaluation
        normalized = dict(evaluation)
        rubric_items = []
        specs = {spec.key: spec for spec in get_rubric(evaluation.get("question_type") or "通用技术题")}
        generic = {
            "模型按 Rubric 维度给出评分。",
            "模型按Rubric维度给出评分。",
            "",
        }
        for raw_item in evaluation.get("rubric_scores") or []:
            item = dict(raw_item) if isinstance(raw_item, dict) else {}
            rationale = str(item.get("rationale") or "").strip()
            if not rationale or rationale in generic:
                spec = specs.get(str(item.get("dimension") or ""))
                description = spec.description if spec else "该评分维度的回答表现"
                score = item.get("score", "-")
                evidence = [str(value).strip() for value in item.get("evidence") or [] if str(value).strip()]
                missing = [str(value).strip() for value in item.get("missing_points") or [] if str(value).strip()]
                rationale = f"本维度得分 {score}/4，考察重点：{description}。"
                rationale += f"回答依据：{'；'.join(evidence[:2])}。" if evidence else "当前回答未提供可单独核验的该维度证据。"
                if missing:
                    rationale += f"待补充：{'；'.join(missing[:2])}。"
                item["rationale"] = rationale
            rubric_items.append(item)
        if rubric_items:
            normalized["rubric_scores"] = rubric_items
        return normalized

    @staticmethod
    def _coverage_status(total_answers: int, competencies: list[CompetencySummary]) -> str:
        if not competencies:
            return "当前尚未形成可用的能力覆盖数据。"
        stable = [item.capability for item in competencies if item.confidence == "高"]
        preliminary = [item.capability for item in competencies if item.confidence == "中"]
        if stable:
            return f"已完成 {total_answers} 条作答，{ '、'.join(stable) } 已被至少 3 题覆盖，可作为相对稳定结论。"
        if preliminary:
            return f"已完成 {total_answers} 条作答，{ '、'.join(preliminary) } 已有初步覆盖；其余结论仍需更多题目验证。"
        return f"已完成 {total_answers} 条作答，但每项能力目前仅由单题支撑，应将结论视为低置信度观察。"

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

        if not parts and isinstance(evaluation, dict) and evaluation.get("evaluation_mode") == "fallback":
            rubric_scores = evaluation.get("rubric_scores") or []
            fallback_points = []
            for item in rubric_scores[:4]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("dimension") or "评分维度").strip()
                missing = [str(value).strip() for value in (item.get("missing_points") or []) if str(value).strip()]
                fallback_points.append(f"{label}：" + ("；".join(missing[:2]) if missing else "应结合问题给出可核验的技术解释。"))
            if fallback_points:
                parts.append("参考要点（规则降级生成）：\n- " + "\n- ".join(fallback_points))

        return "\n\n".join(parts).strip()

    def _generate_reference_answers(self, questions: list[str]) -> list[str]:
        if not questions:
            return []
        if not getattr(self, "llm", None):
            return ["暂时无法生成参考答案。"] * len(questions)

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

        chain = self.llm.with_structured_output(ReferenceAnswerBundle, method="json_mode")
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

    def _build_interview_questions_from_chat_messages(
        self,
        chat_messages: list[dict],
        include_reference_answers: bool = True,
    ) -> list[dict]:
        items: list[dict] = []
        missing: list[tuple[int, str]] = []
        pending_question = ""
        pending_question_grounding: dict = {}

        for msg in chat_messages:
            candidate_answer = (msg.get("user_message") or "").strip()
            assistant_message = (msg.get("assistant_message") or "").strip()
            evaluation = self._normalize_evaluation_for_display(msg.get("evaluation"))
            if evaluation:
                retrieved, evidence_ids, evidence_items = InterviewEvaluator.extract_knowledge_evidence(
                    msg.get("knowledge_context")
                )
                if (
                    evidence_items
                    and evaluation.get("question_type") != "代码题"
                    and not evaluation.get("knowledge_evidence_items")
                    and not evaluation.get("consistency_summary")
                ):
                    evaluation["knowledge_evidence"] = list(dict.fromkeys([
                        *(evaluation.get("knowledge_evidence") or []),
                        *retrieved,
                    ]))[:4]
                    evaluation["knowledge_evidence_ids"] = list(dict.fromkeys([
                        *(evaluation.get("knowledge_evidence_ids") or []),
                        *evidence_ids,
                    ]))[:4]
                    evaluation["knowledge_evidence_items"] = [
                        item.model_dump(mode="json") for item in evidence_items
                    ]
                    evaluation["knowledge_evidence_source"] = "career_rag"

            # 当前用户回答对应上一轮面试官问题，确保抓取全程问答，不依赖 evaluation 是否存在。
            answer_counted = msg.get("answer_counted")
            is_valid_answer = (
                is_countable_answer(candidate_answer)
                if answer_counted is None
                else bool(answer_counted) and is_countable_answer(candidate_answer)
            )
            # Reports aggregate effective answers only. The transcript remains in
            # Qdrant for audit, while explicit non-answers cannot distort scoring.
            if pending_question and candidate_answer and is_valid_answer:
                reference_answer = self._format_reference_answer_from_evaluation(evaluation) if evaluation else ""
                if not reference_answer:
                    missing.append((len(items), pending_question))
                    reference_answer = "暂时无法生成参考答案。"

                items.append(
                    {
                        "point_id": str(msg.get("id")) if msg.get("id") else None,
                        "question": pending_question,
                        "candidate_answer": candidate_answer,
                        "reference_answer": reference_answer,
                        "evaluation": evaluation,
                        "evaluation_status": msg.get("evaluation_status"),
                        "evaluation_error": msg.get("evaluation_error"),
                        "answer_counted": is_valid_answer,
                        "question_grounded": bool(pending_question_grounding.get("question_grounded", False)),
                        "question_grounding_version": pending_question_grounding.get("question_grounding_version"),
                        "question_evidence_ids": pending_question_grounding.get("question_evidence_ids", []),
                        "question_evidence_items": pending_question_grounding.get("question_evidence_items", []),
                        "evidence_feedback": msg.get("evidence_feedback") or [],
                    }
                )

            # assistant_message 视为下一轮面试官问题
            if assistant_message:
                pending_question = assistant_message
                pending_question_grounding = {
                    "question_grounded": msg.get("question_grounded", False),
                    "question_grounding_version": msg.get("question_grounding_version"),
                    "question_evidence_ids": msg.get("question_evidence_ids") or [],
                    "question_evidence_items": msg.get("question_evidence_items") or [],
                }

        if missing and include_reference_answers:
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
            dimension: score
            for dimension, score in {
                "technical_accuracy": averages["technical_accuracy"],
                "knowledge_depth": averages["knowledge_depth"],
                "communication_clarity": averages["communication_clarity"],
                "logical_structure": averages["logical_structure"],
                "problem_solving": averages["problem_solving"],
                "job_match_score": averages["job_match_score"],
            }.items()
            if score is not None
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

    def build(
        self,
        chat_id: str,
        chat_messages: list[dict],
        include_reference_answers: bool = True,
    ) -> InterviewReportResponse:
        evaluations = []
        for msg in chat_messages:
            if not msg.get("evaluation"):
                continue
            evaluation = dict(msg["evaluation"])
            evaluation["_candidate_answer"] = str(msg.get("user_message") or "").strip()
            evaluations.append(evaluation)
        latest = chat_messages[-1] if chat_messages else {}

        interview_questions = self._build_interview_questions_from_chat_messages(
            chat_messages,
            include_reference_answers=include_reference_answers,
        )
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
                overall_score=None,
                technical_accuracy=None,
                knowledge_depth=None,
                communication_clarity=None,
                logical_structure=None,
                problem_solving=None,
                job_match_score=None,
                summary="当前有效作答样本不足，暂时无法生成完整评估。",
                content_analysis="请先完成至少一轮有内容的面试问答，再生成评估。",
                strengths=[],
                improvement_areas=["请提供更完整的作答内容，系统才能进行有效评估。"],
                recommendations=["至少完成一轮详细作答后，再重新生成报告。"],
                recommended_resources=[],
                interview_questions=interview_questions,
                assessment_version="rubric-v2",
            )

        averages = {
            "overall_score": self._clamp_score(
                round(mean([self._score(evaluation, "overall_score") for evaluation in evaluations]))
            )
        }
        for field in self.SCORE_FIELDS:
            if field == "overall_score":
                continue
            values = [
                score
                for evaluation in evaluations
                if (score := self._dimension_score(evaluation, field, evaluations)) is not None
            ]
            averages[field] = self._clamp_score(round(mean(values))) if values else None

        dimension_scores = {
            dimension: score
            for dimension, score in {
                "technical_accuracy": averages["technical_accuracy"],
                "knowledge_depth": averages["knowledge_depth"],
                "communication_clarity": averages["communication_clarity"],
                "logical_structure": averages["logical_structure"],
                "problem_solving": averages["problem_solving"],
                "job_match_score": averages["job_match_score"],
            }.items()
            if score is not None
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
        competency_assessments = self._build_competency_assessments(evaluations)
        jd_requirement_matches = self._build_jd_requirement_matches(evaluations)
        coverage_status = self._coverage_status(total_answers, competency_assessments)

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
            content_analysis=f"{narrative.content_analysis} {coverage_status}",
            strengths=narrative.strengths,
            improvement_areas=narrative.improvement_areas,
            recommendations=narrative.recommendations,
            recommended_resources=resources,
            interview_questions=interview_questions,
            assessment_version="rubric-v2" if any(item.get("assessment_version") == "rubric-v2" for item in evaluations) else "legacy",
            coverage_status=coverage_status,
            competency_assessments=competency_assessments,
            jd_requirement_matches=jd_requirement_matches,
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
