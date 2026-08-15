import asyncio
import hashlib
import json
import re
from time import perf_counter

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.chat import AnswerEvaluation, EvidenceItem, LLMAnswerEvaluation, RubricScore
from app.services.interview_assessment import (
    ASSESSMENT_VERSION,
    calculate_confidence,
    classify_question_type,
    confidence_level,
    extract_jd_requirements,
    extract_resume_evidence,
    get_rubric,
    infer_capability_tags,
    rubric_prompt,
    is_non_answer,
)
from app.services.llm_usage import extract_token_usage
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _response_cache_headers() -> dict[str, str] | None:
    if not getattr(settings, "OPENROUTER_RESPONSE_CACHE_ENABLED", False):
        return None
    return {
        "X-OpenRouter-Cache": "true",
        "X-OpenRouter-Cache-TTL": str(getattr(settings, "OPENROUTER_RESPONSE_CACHE_TTL_SECONDS", 86400)),
    }


class InterviewEvaluator:
    def __init__(self) -> None:
        cache_headers = _response_cache_headers()
        reasoning_effort = getattr(settings, "EVALUATION_REASONING_EFFORT", "none")
        self.llm = ChatOpenAI(
            model=settings.EVALUATION_LLM_MODEL,
            temperature=0,
            max_tokens=settings.EVALUATION_LLM_MAX_TOKENS,
            timeout=settings.EVALUATION_LLM_TIMEOUT,
            max_retries=0,
            reasoning_effort=reasoning_effort,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
            default_headers=cache_headers,
        )
        self.compact_llm = ChatOpenAI(
            model=settings.EVALUATION_LLM_MODEL,
            temperature=0,
            max_tokens=getattr(settings, "EVALUATION_COMPACT_LLM_MAX_TOKENS", 1024),
            timeout=getattr(settings, "EVALUATION_COMPACT_LLM_TIMEOUT", 15.0),
            max_retries=0,
            reasoning_effort=reasoning_effort,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
            default_headers=cache_headers,
        )

    def should_evaluate(self, user_answer: str, previous_question: str | None) -> bool:
        normalized = user_answer.strip().lower()
        if not previous_question:
            return False
        if is_non_answer(user_answer):
            return False
        if normalized in {"开始面试", "开始", "继续", "开始吧", "可以开始了"}:
            return False
        return len(user_answer.strip()) >= 12

    @staticmethod
    def _message_text(message) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content or "").strip()

    @classmethod
    def _parse_json_message(cls, message) -> LLMAnswerEvaluation:
        text = cls._message_text(message)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise
            payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            raise ValueError("评估模型未返回 JSON 对象")
        rubric_scores = payload.get("rubric_scores")
        if isinstance(rubric_scores, dict):
            normalized_scores = []
            for dimension, value in rubric_scores.items():
                if isinstance(value, dict):
                    item = {"dimension": dimension, **value}
                else:
                    item = {"dimension": dimension, "score": value}
                item.setdefault("label", dimension)
                item.setdefault("rationale", "")
                normalized_scores.append(item)
            payload["rubric_scores"] = normalized_scores
        return LLMAnswerEvaluation.model_validate(payload)

    async def _invoke_json(self, llm, prompt: str, timeout: float) -> LLMAnswerEvaluation:
        started_at = perf_counter()
        response = None
        try:
            response = await asyncio.wait_for(
                llm.bind(response_format={"type": "json_object"}).ainvoke(prompt),
                timeout=timeout,
            )
        finally:
            self._evaluation_model_latency_ms = getattr(self, "_evaluation_model_latency_ms", 0) + round(
                (perf_counter() - started_at) * 1000
            )
            self._evaluation_attempts = getattr(self, "_evaluation_attempts", 0) + 1
            if response is not None:
                usage = extract_token_usage(response)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    setattr(
                        self,
                        f"_evaluation_{key}",
                        getattr(self, f"_evaluation_{key}", 0) + usage[key],
                    )
        return self._parse_json_message(response)

    def _reset_usage_tracking(self) -> None:
        self._evaluation_model_latency_ms = 0
        self._evaluation_prompt_tokens = 0
        self._evaluation_completion_tokens = 0
        self._evaluation_total_tokens = 0
        self._evaluation_attempts = 0

    def _apply_usage_metadata(self, result: AnswerEvaluation) -> AnswerEvaluation:
        result.evaluation_model_latency_ms = int(getattr(self, "_evaluation_model_latency_ms", 0))
        result.evaluation_prompt_tokens = int(getattr(self, "_evaluation_prompt_tokens", 0))
        result.evaluation_completion_tokens = int(getattr(self, "_evaluation_completion_tokens", 0))
        result.evaluation_total_tokens = int(getattr(self, "_evaluation_total_tokens", 0))
        result.evaluation_attempts = int(getattr(self, "_evaluation_attempts", 0))
        return result

    @staticmethod
    def _retrieved_knowledge_evidence(knowledge_context: str | None) -> tuple[list[str], list[str]]:
        """Extract exact RAG blocks so reports retain provenance if the LLM omits them."""
        context = str(knowledge_context or "").strip()
        start = context.find("[证据ID：")
        if start < 0:
            items = InterviewEvaluator._legacy_knowledge_items(context)
            return InterviewEvaluator._format_knowledge_items(items)
        blocks = re.split(r"\n\n(?=\[证据ID：)", context[start:])
        evidence: list[str] = []
        evidence_ids: list[str] = []
        for block in blocks:
            block = block.strip()
            if not block or not block.startswith("[证据ID："):
                continue
            match = re.match(r"\[证据ID：([^｜\]]+)", block)
            if match:
                evidence_ids.append(match.group(1).strip())
            evidence.append(block[:1100])
        return evidence[:4], evidence_ids[:4]

    @staticmethod
    def _legacy_knowledge_items(context: str) -> list[EvidenceItem]:
        """Parse pre-evidence-pack contexts into stable, user-verifiable evidence items."""
        if not context:
            return []

        markers = list(re.finditer(
            r"\[用户资料[:：]\s*(?P<title>[^｜\]|]+?)\s*[｜|]",
            context,
        ))
        if not markers:
            return []

        items: list[EvidenceItem] = []
        for marker_index, marker in enumerate(markers):
            title = marker.group("title").strip() or "用户上传技术资料"
            body_start = marker.end()
            body_end = markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(context)
            body = context[body_start:body_end].strip()
            body = re.sub(r"^类型[:：][^\n]*\n?", "", body, count=1).strip()
            if not body:
                continue

            heading_matches = list(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", body))
            sections: list[tuple[str, str]] = []
            if heading_matches:
                preface = body[:heading_matches[0].start()].strip()
                if preface:
                    sections.append(("文档开头", preface))
                for index, heading in enumerate(heading_matches):
                    section = heading.group(1).strip()
                    section_start = heading.end()
                    section_end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(body)
                    section_body = body[section_start:section_end].strip()
                    if section_body:
                        sections.append((section, section_body))
            else:
                sections.append(("未标注章节", body))

            for section, section_body in sections:
                paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section_body) if part.strip()]
                if not paragraphs:
                    paragraphs = [section_body]
                for paragraph in paragraphs:
                    normalized = " ".join(paragraph.split())
                    for offset in range(0, len(normalized), 900):
                        quote = normalized[offset:offset + 900].strip()
                        if not quote:
                            continue
                        digest = hashlib.sha256(
                            f"{title}\n{section}\n{quote}".encode("utf-8")
                        ).hexdigest()[:16]
                        evidence_id = f"legacy:{digest}"
                        items.append(EvidenceItem(
                            evidence_id=evidence_id,
                            source_type="career_rag",
                            verification_status="user_provided",
                            quote=quote,
                            document_id=f"legacy-doc:{hashlib.sha256(title.encode('utf-8')).hexdigest()[:12]}",
                            document_title=title,
                            section=section,
                            chunk_id=evidence_id,
                            retrieval_method="legacy_context_compatibility",
                        ))
                        if len(items) >= 4:
                            return items
        return items[:4]

    @staticmethod
    def _format_knowledge_items(items: list[EvidenceItem]) -> tuple[list[str], list[str]]:
        evidence = []
        evidence_ids = []
        for item in items[:4]:
            evidence_ids.append(item.evidence_id)
            evidence.append(
                f"[证据ID：{item.evidence_id}｜职业事实：{item.fact_id or '未关联'}｜"
                f"文档：{item.document_title or '用户上传技术资料'}｜章节：{item.section or '未标注章节'}｜"
                f"检索方式：{item.retrieval_method}]\n{item.quote}"
            )
        return evidence, evidence_ids

    @classmethod
    def extract_knowledge_evidence(cls, knowledge_context: str | None) -> tuple[list[str], list[str], list[EvidenceItem]]:
        items = cls._retrieved_knowledge_items(knowledge_context)
        evidence, evidence_ids = cls._format_knowledge_items(items)
        return evidence, evidence_ids, items

    @staticmethod
    def _retrieved_knowledge_items(knowledge_context: str | None) -> list[EvidenceItem]:
        context = str(knowledge_context or "").strip()
        start = context.find("[证据ID：")
        if start < 0:
            return InterviewEvaluator._legacy_knowledge_items(context)
        blocks = re.split(r"\n\n(?=\[证据ID：)", context[start:])
        items: list[EvidenceItem] = []
        header_pattern = re.compile(
            r"^\[证据ID：(?P<evidence_id>[^｜\]]+)｜职业事实：(?P<fact_id>[^｜\]]+)｜"
            r"文档：(?P<title>[^｜\]]+)｜章节：(?P<section>[^｜\]]+)｜"
            r"版本：(?P<version>[^｜\]]*)｜(?:检索方式：(?P<method>[^｜\]]+)｜)?"
            r"检索分数：(?P<score>[^\]]+)\]"
        )
        legacy_header_pattern = re.compile(
            r"^\[证据ID：(?P<evidence_id>[^｜\]]+)｜职业事实：(?P<fact_id>[^｜\]]+)｜"
            r"文档：(?P<title>[^｜\]]+)｜章节：(?P<section>[^\]]+)\]"
        )
        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue
            match = header_pattern.match(lines[0].strip())
            if not match:
                match = legacy_header_pattern.match(lines[0].strip())
            if not match:
                continue
            score_text = match.groupdict().get("score")
            try:
                score = float(score_text.strip()) if score_text else None
            except ValueError:
                score = None
            evidence_id = match.group("evidence_id").strip()
            items.append(EvidenceItem(
                evidence_id=evidence_id,
                source_type="career_rag",
                verification_status="user_provided",
                quote="\n".join(lines[1:]).strip()[:900],
                fact_id=None if match.group("fact_id").strip() == "未关联" else match.group("fact_id").strip(),
                document_id=evidence_id.split(":", 1)[0],
                document_title=match.group("title").strip(),
                section=match.group("section").strip(),
                chunk_id=evidence_id,
                source_version=(match.groupdict().get("version") or "").strip() or None,
                retrieval_method=(match.groupdict().get("method") or "lexical_bm25_heading_boost").strip(),
                retrieval_score=score,
            ))
        return items[:4]

    def _attach_retrieved_evidence(
        self,
        result: AnswerEvaluation,
        knowledge_context: str | None,
        question_type: str | None = None,
    ) -> AnswerEvaluation:
        if question_type == "代码题":
            return result
        retrieved, evidence_ids, items = self.extract_knowledge_evidence(knowledge_context)
        if not retrieved:
            return result
        existing = list(result.knowledge_evidence or [])
        normalized = {"".join(item.split()) for item in existing}
        for item in retrieved:
            if "".join(item.split()) not in normalized:
                existing.append(item)
        result.knowledge_evidence = existing[:4]
        result.knowledge_evidence_ids = list(dict.fromkeys(
            [*result.knowledge_evidence_ids, *evidence_ids]
        ))[:4]
        result.knowledge_evidence_items = items
        result.knowledge_evidence_source = "career_rag"
        return result

    @staticmethod
    def _validate_rubric_completeness(result: AnswerEvaluation | LLMAnswerEvaluation, rubric) -> None:
        expected = {spec.key for spec in rubric}
        dimensions = [item.dimension for item in result.rubric_scores]
        actual = set(dimensions)
        missing = expected - actual
        duplicated = {dimension for dimension in dimensions if dimensions.count(dimension) > 1}
        unexpected = actual - expected
        if missing or duplicated or unexpected or len(dimensions) != len(expected):
            details = []
            if missing:
                details.append(f"缺少 {sorted(missing)}")
            if duplicated:
                details.append(f"重复 {sorted(duplicated)}")
            if unexpected:
                details.append(f"多余 {sorted(unexpected)}")
            raise ValueError("Rubric 输出不完整或维度不匹配：" + "；".join(details))
        if any(item.score < 0 or item.score > 4 for item in result.rubric_scores):
            raise ValueError("Rubric 分数必须为 0-4")

    @staticmethod
    def _build_compact_prompt(
        *,
        role: str,
        level: str,
        interview_kind: str,
        question_type: str,
        previous_question: str,
        user_answer: str,
        rubric,
        knowledge_context: str | None,
        evidence_feedback: list[dict] | None = None,
    ) -> str:
        """Build a genuinely smaller retry prompt instead of appending to the full prompt."""
        return f"""
你是中文技术面试评估器，只输出结构化 JSON，不输出分析过程。
岗位：{role}；级别：{level}；面试类型：{interview_kind}；题型：{question_type}
问题：{previous_question[:700]}
回答：{user_answer[:1800]}
技术证据：{(knowledge_context or '未提供')[:1200]}
用户核验证据反馈：{json.dumps(evidence_feedback or [], ensure_ascii=False)[:1600]}
Rubric：{rubric_prompt(rubric)}

要求：基础维度和 overall_score 为 0-100；rubric_scores 覆盖全部维度且每项 0-4 分；
只引用回答中出现的证据，不编造事实；数组最多 2 项，每项尽量简短；给出 summary、
correctness_summary、expected_key_points 和 correction_suggestion。若引用技术资料，
knowledge_evidence 必须原样摘录技术资料中的证据片段，并保留其中的证据 ID。
""".strip()

    async def evaluate_answer(
        self,
        previous_question: str,
        user_answer: str,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
        target_company: str | None = None,
        jd_content: str | None = None,
        resume_content: str | None = None,
        code_execution: dict | None = None,
        knowledge_context: str | None = None,
        knowledge_context_cache_hit: bool = False,
        evidence_feedback: list[dict] | None = None,
    ) -> AnswerEvaluation:
        self._reset_usage_tracking()
        role = interview_role or "通用软件工程师"
        level = interview_level or "中级"
        interview_kind = interview_type or "技术面"
        company = target_company or "未指定"
        jd = jd_content or "未提供"
        question_type = classify_question_type(previous_question, interview_kind)
        rubric = get_rubric(question_type)
        capability_tags = infer_capability_tags(previous_question, question_type)
        jd_requirements = extract_jd_requirements(jd_content)
        resume_evidence = extract_resume_evidence(resume_content, previous_question)
        feedback_context = json.dumps(evidence_feedback or [], ensure_ascii=False)

        prompt = f"""
        你是严格、客观的中文面试评估官。只返回 JSON，不要输出分析过程。
        评分必须引用候选人回答中的实际内容；没有出现的事实不得编造。数组最多 3 项，每项尽量简短。

        岗位：{role}；级别：{level}；面试类型：{interview_kind}；公司：{company}
        题型：{question_type}；能力标签：{'、'.join(capability_tags)}
        问题：{previous_question}
        回答：{user_answer}
        JD：{jd[:1800]}
        JD要求：{jd_requirements or ['未提供']}
        简历证据：{resume_evidence or ['未找到直接证据']}
        技术资料证据：{(knowledge_context or '未提供')[:3000]}
        用户核验证据反馈：{feedback_context[:3000]}
        Judge0证据：{json.dumps(code_execution or {}, ensure_ascii=False)}
        Rubric：{rubric_prompt(rubric)}

        输出要求：
        1. 六个基础维度和 overall_score 为 0-100；verdict 只能为“正确/部分正确/错误”。
        2. rubric_scores 必须覆盖每个 Rubric dimension，score 为 0-4；rationale 引用回答依据，missing_points 写缺失点。
        3. 输出 correctness_summary、summary、strengths、improvement_areas、expected_key_points、correction_suggestion。
        4. 代码题若 Judge0 失败，solution_correctness 必须扣分；回答没有证据时使用“证据不足”，不要推断造假。
        5. 评分看准确性、机制深度、工程细节、边界和验证，不按回答长度虚高。
        6. 如果使用技术资料，只能从“技术资料证据”中原样摘录 knowledge_evidence，并保留 [证据ID]、文档和章节信息；不能把资料内容当成候选人已经证明的经历。
        7. 用户核验反馈是对检索证据的纠偏信号，不是候选人能力证明；对标记为 incorrect 的证据不得继续作为支持依据，partial 只能谨慎使用并说明边界。
        """

        try:
            # JSON mode + manual Pydantic validation is more compatible with
            # providers that do not reliably implement tool-call schemas.
            result = await self._invoke_json(self.llm, prompt, settings.EVALUATION_LLM_TIMEOUT)
            result = self._expand_llm_result(result)
            self._validate_rubric_completeness(result, rubric)
        except Exception as exc:
            try:
                compact_prompt = self._build_compact_prompt(
                    role=role,
                    level=level,
                    interview_kind=interview_kind,
                    question_type=question_type,
                    previous_question=previous_question,
                    user_answer=user_answer,
                    rubric=rubric,
                    knowledge_context=knowledge_context,
                    evidence_feedback=evidence_feedback,
                )
                result = await self._invoke_json(
                    self.compact_llm,
                    compact_prompt,
                    getattr(settings, "EVALUATION_COMPACT_LLM_TIMEOUT", 15.0),
                )
                result = self._expand_llm_result(result)
                self._validate_rubric_completeness(result, rubric)
            except Exception as compact_exc:
                failure_reason = (
                    f"主请求 {type(exc).__name__}: {str(exc)[:160]}；"
                    f"紧凑请求 {type(compact_exc).__name__}: {str(compact_exc)[:160]}"
                )
                logger.warning(
                    "Interview evaluation LLM unavailable; using rubric fallback: %s / %s",
                    type(exc).__name__,
                    type(compact_exc).__name__,
                )
                result = self._fallback_evaluation(
                    user_answer=user_answer,
                    question_type=question_type,
                    rubric=rubric,
                    capability_tags=capability_tags,
                    reason=failure_reason,
                )
        if result.evaluation_mode != "fallback":
            result.question_type = question_type
            result.capability_tags = capability_tags
        applied = self._apply_rubric(
            result,
            rubric,
            user_answer,
            bool(jd_requirements),
            bool(resume_evidence),
            code_execution=code_execution,
        )
        if applied.evaluation_mode == "fallback":
            applied.confidence_score = min(applied.confidence_score, 20)
            applied.confidence_level = "低"
        applied = self._attach_retrieved_evidence(applied, knowledge_context, question_type)
        return self._apply_usage_metadata(applied)

    @staticmethod
    def _expand_llm_result(result: LLMAnswerEvaluation | AnswerEvaluation) -> AnswerEvaluation:
        if isinstance(result, AnswerEvaluation):
            return result
        payload = result.model_dump()
        payload["summary"] = payload.get("summary") or "模型未返回简短结论。"
        payload["strengths"] = payload.get("strengths") or []
        payload["improvement_areas"] = payload.get("improvement_areas") or []
        return AnswerEvaluation(**payload)

    @staticmethod
    def _fallback_evaluation(
        *,
        user_answer: str,
        question_type: str,
        rubric,
        capability_tags: list[str],
        reason: str,
    ) -> AnswerEvaluation:
        answer = user_answer.strip()
        answer_length = len(answer)
        signals = InterviewEvaluator._fallback_signals(answer)
        rubric_scores = [
            InterviewEvaluator._fallback_rubric_score(spec, signals)
            for spec in rubric
        ]
        evidence = InterviewEvaluator._fallback_evidence(answer)
        missing_points = InterviewEvaluator._fallback_missing_points(signals)
        weighted_score = round(
            sum(item.score * spec.weight for item, spec in zip(rubric_scores, rubric))
            / (sum(spec.weight for spec in rubric) or 1)
            * 25
        )
        signal_labels = "、".join(signals["labels"]) or "未检测到明确的结构化信号"
        basis = [
            f"评分标准：{ASSESSMENT_VERSION}，题型为“{question_type}”，按该题型 Rubric 权重计算综合分。",
            f"可观察信号：回答 {answer_length} 字；{signal_labels}。",
            "计分规则：每个 Rubric 维度按 0-4 分评估，综合分 = 各维度分数 × 权重 × 25，最终限制为 0-100。",
            "证据边界：只使用回答中出现的文字，不推断未出现的技术事实；远程模型恢复后应重新评估。",
        ]
        strengths = []
        if signals["specific"]:
            strengths.append("回答包含技术名词、实现动作或可核验细节")
        if signals["structure"]:
            strengths.append("回答出现结论、步骤或分层表达")
        if signals["result"]:
            strengths.append("回答提到结果、指标或验证方式")
        strengths = strengths[:3] or ["已记录有效作答内容"]
        improvements = missing_points[:3] or ["补充关键机制、边界条件和验证结果"]
        return AnswerEvaluation(
            technical_accuracy=weighted_score,
            knowledge_depth=weighted_score,
            communication_clarity=weighted_score,
            logical_structure=weighted_score,
            problem_solving=weighted_score,
            job_match_score=weighted_score,
            overall_score=weighted_score,
            verdict="证据不足",
            correctness_summary="未调用远程语义模型，无法确认技术结论；本题仅按可观察信号和 Rubric 给出保守分数。",
            error_analysis=missing_points[:3],
            expected_key_points=[spec.description for spec in rubric[:3]],
            correction_suggestion="远程模型恢复后重新评估，并补充上述 Rubric 维度缺少的技术证据。",
            summary="远程模型暂时不可用，已按可解释的 Rubric 规则降级评估；该结果仅供临时参考。",
            strengths=strengths,
            improvement_areas=improvements,
            assessment_version="rubric-v2-fallback",
            evaluation_mode="fallback",
            question_type=question_type,
            capability_tags=capability_tags,
            rubric_scores=rubric_scores,
            capability_assessments=[
                {
                    "capability": tag,
                    "score": weighted_score,
                    "evidence": evidence[:1],
                    "missing_points": missing_points[:2],
                }
                for tag in capability_tags
            ],
            evidence_warnings=[f"远程评估调用失败：{reason}。"],
            evaluation_basis=basis,
            evidence_grounded=False,
        )

    @staticmethod
    def _fallback_signals(answer: str) -> dict[str, object]:
        structure = bool(re.search(r"(首先|其次|然后|最后|一是|二是|结论|步骤|分为|通过)", answer))
        specific = bool(re.search(r"(Redis|MySQL|PostgreSQL|FastAPI|LangGraph|Qdrant|HTTP|API|SQL|代码|接口|缓存|队列|数据库|模型|算法|服务)", answer, re.IGNORECASE))
        result = bool(re.search(r"(结果|提升|降低|减少|增加|耗时|延迟|成功率|覆盖|通过|指标|验证|命中率|准确率|故障率)", answer))
        boundary = bool(re.search(r"(边界|异常|超时|失败|重试|降级|并发|一致性|空值|重复|极端|监控|告警)", answer))
        labels = []
        if structure:
            labels.append("结构化表达")
        if specific:
            labels.append("技术/实现细节")
        if result:
            labels.append("结果/验证信号")
        if boundary:
            labels.append("边界/异常信号")
        return {
            "answer_length": len(answer),
            "structure": structure,
            "specific": specific,
            "result": result,
            "boundary": boundary,
            "labels": labels,
        }

    @staticmethod
    def _fallback_evidence(answer: str) -> list[str]:
        fragments = [item.strip() for item in re.split(r"[。！？；;\n]+", answer) if item.strip()]
        return [item[:80] for item in fragments[:2]]

    @staticmethod
    def _fallback_missing_points(signals: dict[str, object]) -> list[str]:
        missing = []
        if not signals["specific"]:
            missing.append("缺少可核验的技术名词、实现动作或事实细节")
        if not signals["structure"]:
            missing.append("缺少清晰的结论、步骤或分层结构")
        if not signals["boundary"]:
            missing.append("缺少边界条件、异常处理或风险说明")
        if not signals["result"]:
            missing.append("缺少结果、指标或验证方式")
        return missing

    @staticmethod
    def _fallback_rubric_score(spec, signals: dict[str, object]) -> RubricScore:
        score = 1
        if signals["answer_length"] >= 50:
            score += 1
        if signals["specific"]:
            score += 1
        if signals["structure"] and (signals["boundary"] or signals["result"]):
            score += 1
        score = max(0, min(4, score))
        basis = [f"回答长度 {signals['answer_length']} 字"]
        if signals["specific"]:
            basis.append("检测到技术/实现细节")
        if signals["structure"]:
            basis.append("检测到结构化表达")
        if signals["boundary"]:
            basis.append("检测到边界/异常信号")
        if signals["result"]:
            basis.append("检测到结果/验证信号")
        return RubricScore(
            dimension=spec.key,
            label=spec.label,
            score=score,
            rationale="；".join(basis) + f"；按“{spec.description}”计分。",
            evidence=InterviewEvaluator._fallback_evidence_from_signals(signals),
            missing_points=InterviewEvaluator._fallback_missing_points(signals)[:2],
        )

    @staticmethod
    def _fallback_evidence_from_signals(signals: dict[str, object]) -> list[str]:
        return [f"回答长度 {signals['answer_length']} 字；检测到：{'、'.join(signals['labels']) or '无明确信号'}"]

    @staticmethod
    def _apply_rubric(
        result: AnswerEvaluation,
        rubric,
        user_answer: str,
        has_jd: bool,
        has_resume_evidence: bool,
        code_execution: dict | None = None,
    ) -> AnswerEvaluation:
        provided = {item.dimension: item for item in result.rubric_scores}
        normalized_scores: list[RubricScore] = []
        for spec in rubric:
            item = provided.get(spec.key)
            if item is None:
                raise ValueError(f"评估结果缺少 Rubric 维度：{spec.key}")
            item.label = spec.label
            item.score = max(0, min(4, int(item.score)))
            generic_rationales = {
                "模型按 Rubric 维度给出评分。",
                "模型按Rubric维度给出评分。",
                "",
            }
            if not item.rationale.strip() or item.rationale.strip() in generic_rationales:
                rationale_parts = [f"本维度得分 {item.score}/4，考察重点：{spec.description}。"]
                if item.evidence:
                    rationale_parts.append(f"回答依据：{'；'.join(item.evidence[:2])}。")
                else:
                    rationale_parts.append("当前回答未提供可单独核验的该维度证据。")
                if item.missing_points:
                    rationale_parts.append(f"待补充：{'；'.join(item.missing_points[:2])}。")
                item.rationale = "".join(rationale_parts)
            normalized_scores.append(item)

        if code_execution and any(spec.key == "solution_correctness" for spec in rubric):
            status = str(code_execution.get("status") or "").lower()
            hard_failure_markers = ("compilation error", "runtime error", "time limit", "memory limit", "wrong answer")
            if any(marker in status for marker in hard_failure_markers):
                for item in normalized_scores:
                    if item.dimension == "solution_correctness":
                        item.score = min(item.score, 1)
                        item.missing_points = list(item.missing_points) + ["Judge0 当前运行结果未通过，需先修复可运行性和正确性。"]
                failure_note = f"Judge0 运行状态为 {code_execution.get('status')}，代码正确性已按硬约束下调。"
                if failure_note not in result.error_analysis:
                    result.error_analysis = list(result.error_analysis) + [failure_note]

        total_weight = sum(spec.weight for spec in rubric) or 1
        weighted_score = sum(item.score * spec.weight for item, spec in zip(normalized_scores, rubric)) / total_weight * 25
        result.rubric_scores = normalized_scores
        result.rubric_overall_score = round(weighted_score)
        result.overall_score = result.rubric_overall_score
        result.assessment_version = ASSESSMENT_VERSION
        if result.evaluation_mode == "fallback" and not result.evaluation_basis:
            result.evaluation_basis = [
                f"评分标准：{ASSESSMENT_VERSION}，按题型 Rubric 权重计算综合分。",
                "计分规则：每个 Rubric 维度为 0-4 分，综合分 = 各维度分数 × 权重 × 25。",
                "零分判定：只有所有 Rubric 维度都被明确评为 0 分时才记为 0；缺失或不完整输出会触发重试或规则降级。",
            ]
        result.confidence_score = calculate_confidence(
            user_answer,
            rubric_count=len(normalized_scores),
            has_jd=has_jd,
            has_resume_evidence=has_resume_evidence,
        )
        result.confidence_level = confidence_level(result.confidence_score)
        return result
