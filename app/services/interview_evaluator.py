import asyncio
import hashlib
import json
import re
from time import perf_counter

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.chat import (
    AnswerEvaluation,
    ConsistencyEvidenceCitation,
    EvidenceItem,
    ExperienceConsistencyCheck,
    LLMAnswerEvaluation,
    RubricScore,
)
from app.schemas.evaluation import EvidencePack
from app.services.interview_assessment import (
    ASSESSMENT_VERSION,
    CONSISTENCY_VERSION,
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

        def as_list(value):
            if value is None:
                return []
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [value] if value.strip() else []
            return [value]

        for field in (
            "error_analysis",
            "expected_key_points",
            "strengths",
            "improvement_areas",
            "consistency_checks",
        ):
            payload[field] = as_list(payload.get(field))
        for field in (
            "technical_accuracy",
            "knowledge_depth",
            "communication_clarity",
            "logical_structure",
            "problem_solving",
            "job_match_score",
            "overall_score",
        ):
            try:
                payload[field] = max(0, min(100, round(float(payload.get(field) or 0))))
            except (TypeError, ValueError):
                payload[field] = 0
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
        else:
            payload["rubric_scores"] = as_list(rubric_scores)
        for item in payload["rubric_scores"]:
            if not isinstance(item, dict):
                continue
            item["evidence"] = as_list(item.get("evidence"))
            item["missing_points"] = as_list(item.get("missing_points"))
        consistency_aliases = {
            "部分一致": "部分一致",
            "基本一致": "部分一致",
            "冲突": "存在冲突",
            "无法判断": "证据不足",
            "insufficient": "证据不足",
            "partial": "部分一致",
            "true": "一致",
            "false": "证据不足",
            "consistent": "一致",
            "conflict": "存在冲突",
        }
        raw_consistency = str(payload.get("resume_consistency") or "不适用").strip()
        payload["resume_consistency"] = consistency_aliases.get(raw_consistency.lower(), raw_consistency)
        check_verdict_aliases = {
            "supported": "支持",
            "support": "支持",
            "consistent": "支持",
            "部分支持": "部分支持",
            "partially_supported": "部分支持",
            "partial_support": "部分支持",
            "partial": "部分支持",
            "conflicted": "冲突",
            "conflict": "冲突",
            "contradiction": "冲突",
            "insufficient": "证据不足",
            "unknown": "证据不足",
        }
        for check in payload.get("consistency_checks") or []:
            if not isinstance(check, dict):
                continue
            check["citations"] = as_list(check.get("citations"))
            raw_verdict = str(check.get("verdict") or "证据不足").strip()
            check["verdict"] = check_verdict_aliases.get(raw_verdict.lower(), raw_verdict)
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
        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue
            header = lines[0].strip()

            def field(name: str) -> str:
                match = re.search(rf"(?:^\[?|｜){re.escape(name)}：([^｜\]]*)", header)
                return match.group(1).strip() if match else ""

            evidence_id = field("证据ID")
            if not evidence_id:
                continue
            score_text = field("检索分数")
            try:
                score = float(score_text.strip()) if score_text else None
            except ValueError:
                score = None
            fact_id = field("职业事实")
            items.append(EvidenceItem(
                evidence_id=evidence_id,
                source_type="career_rag",
                verification_status="user_provided",
                quote="\n".join(lines[1:]).strip()[:900],
                fact_id=None if fact_id in {"", "未关联"} else fact_id,
                document_id=evidence_id.split(":", 1)[0],
                document_title=field("文档"),
                section=field("章节"),
                chunk_id=evidence_id,
                source_version=field("版本") or None,
                retrieval_method=field("检索方式") or "lexical_bm25_heading_boost",
                retrieval_score=score,
            ))
        return items[:4]

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
        evidence_pack: dict | None = None,
        evidence_feedback: list[dict] | None = None,
    ) -> str:
        """Build a genuinely smaller retry prompt instead of appending to the full prompt."""
        return f"""
你是中文技术面试评估器，只输出结构化 JSON，不输出分析过程。
岗位：{role}；级别：{level}；面试类型：{interview_kind}；题型：{question_type}
问题：{previous_question[:700]}
回答：{user_answer[:1800]}
技术证据：{(knowledge_context or '未提供')[:1200]}
EvidencePack：{json.dumps(evidence_pack or {}, ensure_ascii=False)[:1800]}
用户核验证据反馈：{json.dumps(evidence_feedback or [], ensure_ascii=False)[:1600]}
Rubric：{rubric_prompt(rubric)}

要求：基础维度和 overall_score 为 0-100；rubric_scores 覆盖全部维度且每项 0-4 分；
只引用回答中出现的证据，不编造事实；数组最多 2 项，每项尽量简短；给出 summary、
correctness_summary、expected_key_points 和 correction_suggestion。若引用技术资料，
knowledge_evidence 必须原样摘录技术资料中的证据片段，并保留其中的证据 ID。
项目深挖题还必须输出 resume_consistency、consistency_summary、consistency_checks；每个
consistency_check 包含 candidate_claim、claim_type、verdict、citations 和 rationale，candidate_claim
必须逐字来自回答，citation 必须包含 EvidencePack 中的 evidence_id 和逐字 quote。
项目资料可直接支持 project_fact；只有资料或对应要点明确记录候选人的动作/职责时，才能支持
personal_ownership 或 responsibility_scope。若理由认为资料明确一致，verdict 必须为“支持”并给出引用。
一条声明只有部分细节被资料覆盖时使用“部分支持”，并在 rationale 写明未覆盖的边界。
""".strip()

    @staticmethod
    def _prompt_evidence_index(evidence_pack: EvidencePack | None) -> dict:
        """Expose provenance to the model without duplicating chunk bodies."""
        if evidence_pack is None:
            return {}
        return {
            "version": evidence_pack.version,
            "retrieval_method": evidence_pack.retrieval_method,
            "fact_id": evidence_pack.fact_id,
            "evidence_ids": evidence_pack.evidence_ids,
            "chunks": [
                {
                    "evidence_id": chunk.evidence_id,
                    "document_id": chunk.document_id,
                    "title": chunk.title,
                    "section": chunk.section,
                    "project_key": chunk.project_key,
                    "source_version": chunk.source_version,
                    "claim_ids": chunk.claim_ids,
                    "claim_texts": chunk.claim_texts,
                }
                for chunk in evidence_pack.chunks
            ],
        }

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
        evidence_pack: EvidencePack | dict | None = None,
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
        normalized_pack = self._coerce_evidence_pack(evidence_pack, knowledge_context)
        evidence_pack_index = self._prompt_evidence_index(normalized_pack)

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
        结构化 EvidencePack 索引：{json.dumps(evidence_pack_index, ensure_ascii=False)[:2200]}
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
        8. 项目深挖题必须抽取回答中 1-4 条可核验的关键事实，输出 resume_consistency、consistency_summary 和 consistency_checks。
           consistency_checks 每项格式为 {{"candidate_claim":"回答中的逐字声明","claim_type":"project_fact/personal_ownership/metric_result/responsibility_scope","verdict":"支持/部分支持/冲突/证据不足","citations":[{{"evidence_id":"...","quote":"资料逐字引用"}}],"rationale":"..."}}。
           “一致”要求关键声明均有有效支持且不能存在冲突；仅部分声明或部分细节有依据时标记“部分一致/部分支持”；资料没有明确支持或反驳时标记“证据不足”，不得把检索相关性当作事实一致性。
        9. 分开判断“项目中是否存在该技术事实”和“候选人是否亲自负责”。项目资料明确记录某机制时，project_fact 应判“支持”，不能仅因资料未写“我负责”而判证据不足；个人所有权仍需简历要点、对应要点或资料中的动作表述支持。
        10. 若 rationale 中写明“资料明确提到/与回答一致”，verdict 必须为“支持”并提供 EvidencePack 逐字引用，不能输出自相矛盾的“证据不足”。混合了已知事实与新增细节的长句要拆成原文中的多个声明分别判断。
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
                    evidence_pack=evidence_pack_index,
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
        applied = self._apply_experience_consistency(
            applied,
            question_type=question_type,
            previous_question=previous_question,
            user_answer=user_answer,
            evidence_pack=normalized_pack,
            evidence_feedback=evidence_feedback,
            rubric=rubric,
        )
        return self._apply_usage_metadata(applied)

    @classmethod
    def _coerce_evidence_pack(
        cls,
        evidence_pack: EvidencePack | dict | None,
        knowledge_context: str | None,
    ) -> EvidencePack | None:
        if evidence_pack:
            try:
                return evidence_pack if isinstance(evidence_pack, EvidencePack) else EvidencePack.model_validate(evidence_pack)
            except Exception as exc:
                logger.warning("Invalid structured EvidencePack; trying legacy context: %s", exc)

        legacy_items = cls._retrieved_knowledge_items(knowledge_context)
        if not legacy_items:
            return None
        chunks = [
            {
                "evidence_id": item.evidence_id,
                "text": item.quote,
                "document_id": item.document_id or "",
                "title": item.document_title or "",
                "section": item.section or "",
                "fact_id": item.fact_id,
                "source_version": item.source_version or "",
                "retrieval_method": item.retrieval_method,
                "score": item.retrieval_score or 0,
            }
            for item in legacy_items
        ]
        return EvidencePack(
            version="evidence-pack-legacy-adapter",
            retrieval_method="legacy_context_compatibility",
            retrieval_count=len(chunks),
            evidence_ids=[item["evidence_id"] for item in chunks],
            chunks=chunks,
            context=str(knowledge_context or ""),
        )

    @staticmethod
    def _normalized_text(value: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "")).lower()

    @classmethod
    def _quote_belongs_to(cls, quote: str, source: str) -> bool:
        normalized_quote = cls._normalized_text(quote)
        normalized_source = cls._normalized_text(source)
        return len(normalized_quote) >= 6 and normalized_quote in normalized_source

    @staticmethod
    def _consistency_terms(value: str) -> set[str]:
        stopwords = {
            "项目", "系统", "平台", "技术", "实现", "使用", "通过", "进行", "相关", "具体",
            "这个", "一种", "可以", "负责", "工作", "模块", "同时", "实际", "处理", "保证",
        }
        terms = {
            match.group(0).lower()
            for match in re.finditer(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}|\d+(?:\.\d+)?", value or "")
        }
        for sequence in re.findall(r"[\u4e00-\u9fff]{2,}", value or ""):
            terms.update(sequence[index:index + 2] for index in range(len(sequence) - 1))
        return {term for term in terms if term not in stopwords}

    @staticmethod
    def _claim_type_for_text(value: str, supplied_type: str = "project_fact") -> str:
        text = str(value or "")
        if re.search(r"(?:提升|降低|减少|增加|达到|缩短|优化).{0,10}\d", text) or re.search(r"\d+(?:\.\d+)?\s*%", text):
            return "metric_result"
        if any(marker in text for marker in ("我负责", "我主导", "我独立", "我牵头", "本人负责")):
            return "responsibility_scope"
        if any(marker in text for marker in ("我实现", "我开发", "我设计", "我搭建", "我改造", "我增加", "我完成")):
            return "personal_ownership"
        return supplied_type if supplied_type in {
            "project_fact", "personal_ownership", "metric_result", "responsibility_scope"
        } else "project_fact"

    @classmethod
    def _direct_support_for_claim(
        cls,
        claim: str,
        claim_type: str,
        evidence_pack: EvidencePack,
        feedback_by_id: dict[str, str],
    ) -> tuple[list[ConsistencyEvidenceCitation], str, str] | None:
        """Recover auditable full/partial support when a provider omits citations."""
        if any(marker in claim for marker in ("没有", "并未", "未使用", "不采用", "不是", "不依赖")):
            return None
        claim_terms = cls._consistency_terms(claim)
        if len(claim_terms) < 4:
            return None
        resolved_type = cls._claim_type_for_text(claim, claim_type)
        candidate_segments: list[tuple[set[str], ConsistencyEvidenceCitation, int]] = []
        ownership_terms: set[str] = set()
        all_source_numbers: set[str] = set()
        for chunk in evidence_pack.chunks:
            if feedback_by_id.get(chunk.evidence_id) in {"incorrect", "partial"}:
                continue
            source_values = [
                (str(chunk.text or ""), 0),
                *[(str(item), 1) for item in chunk.claim_texts if str(item).strip()],
            ]
            all_source_numbers.update(re.findall(r"\d+(?:\.\d+)?", " ".join(value for value, _ in source_values)))
            ownership_terms.update(cls._consistency_terms(" ".join(chunk.claim_texts)))

            segments = [
                (segment.strip(), source_priority)
                for source, source_priority in source_values
                for segment in re.split(r"(?<=[。！？；])|\n+", source)
                if len(cls._normalized_text(segment)) >= 6
            ] or source_values
            for segment, source_priority in segments:
                source_terms = cls._consistency_terms(segment)
                overlap = claim_terms & source_terms
                if len(overlap) < 2:
                    continue
                candidate_segments.append((overlap, ConsistencyEvidenceCitation(
                    evidence_id=chunk.evidence_id,
                    quote=segment[:1200],
                ), source_priority))

        if resolved_type in {"personal_ownership", "responsibility_scope"}:
            ownership_overlap = len(claim_terms & ownership_terms) / max(len(claim_terms), 1)
            if ownership_overlap < 0.32:
                return None

        covered: set[str] = set()
        citations: list[ConsistencyEvidenceCitation] = []
        remaining = list(candidate_segments)
        while remaining and len(citations) < 3:
            remaining.sort(key=lambda item: len(item[0] - covered) + item[2] * 3, reverse=True)
            terms, citation, _ = remaining.pop(0)
            if len(terms - covered) < 2:
                break
            covered.update(terms)
            citations.append(citation)

        coverage = len(covered) / max(len(claim_terms), 1)
        ascii_claim = {term for term in claim_terms if re.search(r"[a-z0-9]", term)}
        ascii_covered = ascii_claim & covered
        chinese_covered = {term for term in covered if re.fullmatch(r"[\u4e00-\u9fff]{2}", term)}
        if len(covered) < 4 or (not ascii_covered and len(chinese_covered) < 5):
            return None

        claim_numbers = set(re.findall(r"\d+(?:\.\d+)?", claim))
        numbers_complete = claim_numbers.issubset(all_source_numbers)
        identifiers_complete = ascii_claim.issubset(covered)
        if coverage >= 0.58 and numbers_complete and identifiers_complete:
            return citations, resolved_type, "支持"
        if coverage >= 0.16 and len(covered) >= 6:
            return citations[:2], resolved_type, "部分支持"
        return None

    @classmethod
    def _recover_direct_support_checks(
        cls,
        checks: list[ExperienceConsistencyCheck],
        *,
        user_answer: str,
        evidence_pack: EvidencePack,
        feedback_by_id: dict[str, str],
        recoverable_claims: set[str],
        allow_generate: bool,
    ) -> list[ExperienceConsistencyCheck]:
        candidates = list(checks)
        if not candidates and allow_generate:
            clauses = [
                clause.strip(" \t-•")
                for clause in re.split(r"(?<=[。！？；])|\n+", user_answer)
                if 10 <= len(clause.strip()) <= 500
            ]
            candidates = [
                ExperienceConsistencyCheck(
                    candidate_claim=clause,
                    claim_type=cls._claim_type_for_text(clause),
                    verdict="证据不足",
                    rationale="本条仅依据已上传资料进行直接文本核验；本次未取得完整模型评估结果。",
                )
                for clause in clauses[:6]
            ]
            recoverable_claims = {check.candidate_claim for check in candidates}

        recovered: list[ExperienceConsistencyCheck] = []
        for check in candidates:
            if check.verdict != "证据不足" or check.candidate_claim not in recoverable_claims:
                recovered.append(check)
                continue
            atomic_claims = [
                item.strip(" \t-•，,；;。")
                for item in re.split(r"[，,；;。]+", check.candidate_claim)
                if len(item.strip(" \t-•，,；;。")) >= 8
            ]
            if len(atomic_claims) > 1:
                atomic_checks: list[ExperienceConsistencyCheck] = []
                for atomic_claim in atomic_claims:
                    atomic_type = cls._claim_type_for_text(atomic_claim, check.claim_type)
                    atomic_support = cls._direct_support_for_claim(
                        atomic_claim,
                        atomic_type,
                        evidence_pack,
                        feedback_by_id,
                    )
                    if atomic_support is None:
                        atomic_checks.append(check.model_copy(update={
                            "candidate_claim": atomic_claim,
                            "claim_type": atomic_type,
                            "verdict": "证据不足",
                            "citations": [],
                            "rationale": "现有资料不足以支持或反驳这条拆分后的完整声明。",
                        }))
                        continue
                    atomic_citations, atomic_type, atomic_verdict = atomic_support
                    atomic_checks.append(check.model_copy(update={
                        "candidate_claim": atomic_claim,
                        "claim_type": atomic_type,
                        "verdict": atomic_verdict,
                        "citations": atomic_citations,
                        "rationale": (
                            "该项拆分声明与已上传资料存在高强度直接文本匹配。"
                            if atomic_verdict == "支持"
                            else "资料覆盖该项拆分声明的核心方向，但未覆盖全部实现边界。"
                        ),
                    }))
                if any(item.verdict in {"支持", "部分支持"} for item in atomic_checks):
                    recovered.extend(atomic_checks)
                    continue
            support = cls._direct_support_for_claim(
                check.candidate_claim,
                check.claim_type,
                evidence_pack,
                feedback_by_id,
            )
            if support is None:
                recovered.append(check)
                continue
            citations, claim_type, verdict = support
            recovered.append(check.model_copy(update={
                "claim_type": claim_type,
                "verdict": verdict,
                "citations": citations,
                "rationale": (
                    "回答中的该项事实与用户上传项目资料存在高强度直接文本匹配。"
                    if verdict == "支持"
                    else "资料支持该声明的核心方向，但未完整覆盖其中的全部实现细节或量化边界。"
                ),
            }))
        return recovered[:4]

    @classmethod
    def _apply_experience_consistency(
        cls,
        result: AnswerEvaluation,
        *,
        question_type: str,
        previous_question: str = "",
        user_answer: str,
        evidence_pack: EvidencePack | None,
        evidence_feedback: list[dict] | None,
        rubric,
    ) -> AnswerEvaluation:
        result.consistency_version = CONSISTENCY_VERSION
        if question_type != "项目深挖题":
            result.resume_consistency = "不适用"
            result.consistency_summary = "该题不是项目或实习经历深挖题，不执行经历一致性核验。"
            result.consistency_checks = []
            return result

        if evidence_pack is None or not evidence_pack.chunks:
            result.resume_consistency = "证据不足"
            result.consistency_summary = "未检索到可用于核验该回答的个人项目资料。"
            result.consistency_checks = []
            result.confidence_score = min(result.confidence_score, 60)
            result.confidence_level = confidence_level(result.confidence_score)
            return result

        chunks_by_id = {chunk.evidence_id: chunk for chunk in evidence_pack.chunks}
        feedback_by_id = {
            str(item.get("evidence_id")): str(item.get("verdict"))
            for item in (evidence_feedback or [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        valid_checks: list[ExperienceConsistencyCheck] = []
        recoverable_claims: set[str] = set()
        cited_ids: list[str] = []
        warnings = list(result.evidence_warnings or [])

        for check in result.consistency_checks:
            if not cls._quote_belongs_to(check.candidate_claim, user_answer):
                warnings.append("一致性判断包含无法在候选人回答中定位的声明，已丢弃。")
                continue
            if check.verdict == "证据不足":
                rationale = check.rationale
                if any(marker in rationale for marker in ("明确描述", "明确提到", "与候选人", "一致", "相符", "支持")):
                    rationale = "资料包含相关背景，但当前引用不足以支持或反驳这条完整声明。"
                valid_checks.append(check.model_copy(update={"citations": [], "rationale": rationale}))
                recoverable_claims.add(check.candidate_claim)
                continue
            if not check.citations:
                warnings.append("支持、部分支持或冲突判断缺少 EvidencePack 引用，已降级为证据不足。")
                valid_checks.append(check.model_copy(update={
                    "verdict": "证据不足",
                    "citations": [],
                    "rationale": "模型没有提供可核验的 EvidencePack 引用，无法据此确认该声明。",
                }))
                recoverable_claims.add(check.candidate_claim)
                continue

            citations_valid = True
            accepted_citations = []
            for citation in check.citations:
                chunk = chunks_by_id.get(citation.evidence_id)
                feedback_verdict = feedback_by_id.get(citation.evidence_id)
                chunk_source = "\n".join([chunk.text, *chunk.claim_texts]) if chunk is not None else ""
                if (
                    chunk is None
                    or feedback_verdict in {"incorrect", "partial"}
                    or not cls._quote_belongs_to(citation.quote, chunk_source)
                ):
                    citations_valid = False
                    break
                accepted_citations.append(citation)
            if not citations_valid:
                warnings.append("一致性判断引用了未知、非逐字或已被用户否定的证据，已降级为证据不足。")
                valid_checks.append(check.model_copy(update={
                    "verdict": "证据不足",
                    "citations": [],
                    "rationale": "模型给出的 Evidence ID 或原文引用未通过后端校验，不能据此确认该声明。",
                }))
                recoverable_claims.add(check.candidate_claim)
                continue
            valid_checks.append(check.model_copy(update={"citations": accepted_citations}))
            cited_ids.extend(citation.evidence_id for citation in accepted_citations)

        valid_checks = cls._recover_direct_support_checks(
            valid_checks,
            user_answer=user_answer,
            evidence_pack=evidence_pack,
            feedback_by_id=feedback_by_id,
            recoverable_claims=recoverable_claims,
            allow_generate=not bool(result.consistency_checks),
        )
        cited_ids = [
            citation.evidence_id
            for check in valid_checks
            if check.verdict in {"支持", "部分支持", "冲突"}
            for citation in check.citations
        ]

        has_conflict = any(check.verdict == "冲突" for check in valid_checks)
        has_support = any(check.verdict == "支持" for check in valid_checks)
        has_partial_support = any(check.verdict == "部分支持" for check in valid_checks)
        has_insufficient = any(check.verdict == "证据不足" for check in valid_checks)
        if has_conflict:
            consistency = "存在冲突"
            summary = "回答中的至少一项关键经历声明与用户上传资料存在可追踪冲突。"
        elif has_support and not has_partial_support and not has_insufficient:
            consistency = "一致"
            summary = "回答中的关键项目事实或个人职责均获得用户上传资料的可追踪支持，未发现可核验冲突。"
        elif has_support or has_partial_support:
            consistency = "部分一致"
            summary = "资料支持回答中的部分项目事实，但尚未覆盖全部实现细节、个人职责或量化边界。"
        else:
            consistency = "证据不足"
            summary = "现有资料不足以支持或反驳回答中的关键经历声明。"

        result.resume_consistency = consistency
        result.consistency_summary = summary
        result.consistency_checks = valid_checks[:4]
        result.evidence_warnings = list(dict.fromkeys(warnings))

        cited_id_set = set(cited_ids)
        cited_chunks = [chunk for chunk in evidence_pack.chunks if chunk.evidence_id in cited_id_set]
        accepted_quotes_by_id: dict[str, list[str]] = {}
        for check in valid_checks:
            if check.verdict not in {"支持", "部分支持", "冲突"}:
                continue
            for citation in check.citations:
                accepted_quotes_by_id.setdefault(citation.evidence_id, [])
                if citation.quote not in accepted_quotes_by_id[citation.evidence_id]:
                    accepted_quotes_by_id[citation.evidence_id].append(citation.quote)
        result.knowledge_evidence_ids = [chunk.evidence_id for chunk in cited_chunks]
        result.knowledge_evidence = [
            quote
            for chunk in cited_chunks
            for quote in accepted_quotes_by_id.get(chunk.evidence_id, [])
        ]
        result.knowledge_evidence_items = [
            EvidenceItem(
                evidence_id=chunk.evidence_id,
                source_type="career_rag",
                verification_status="user_provided",
                quote=(accepted_quotes_by_id.get(chunk.evidence_id) or [chunk.text])[0][:900],
                fact_id=str(chunk.fact_id) if chunk.fact_id is not None else None,
                document_id=chunk.document_id,
                document_title=chunk.title,
                section=chunk.section,
                chunk_id=chunk.evidence_id,
                source_version=chunk.source_version,
                retrieval_method=chunk.retrieval_method,
                retrieval_score=chunk.score,
            )
            for chunk in cited_chunks
        ]
        result.knowledge_evidence_source = "evidence_pack_v2" if cited_chunks else "none"

        if consistency == "存在冲突":
            for score in result.rubric_scores:
                if score.dimension == "personal_ownership":
                    score.score = min(score.score, 1)
                    score.missing_points = list(dict.fromkeys([
                        *score.missing_points,
                        "回答中的项目所有权声明与个人资料存在冲突，需要澄清责任边界。",
                    ]))
            total_weight = sum(spec.weight for spec in rubric) or 1
            result.rubric_overall_score = round(
                sum(score.score * spec.weight for score, spec in zip(result.rubric_scores, rubric))
                / total_weight
                * 25
            )
            result.overall_score = result.rubric_overall_score
            result.confidence_score = min(result.confidence_score, 40)
        elif consistency == "部分一致":
            result.confidence_score = min(result.confidence_score, 70)
        elif consistency == "证据不足":
            result.confidence_score = min(result.confidence_score, 60)
        result.confidence_level = confidence_level(result.confidence_score)
        logger.info(
            "Experience consistency applied: question_chars=%s pack_chunks=%s checks=%s supports=%s conflicts=%s insufficient=%s",
            len(previous_question or ""),
            len(evidence_pack.chunks),
            len(valid_checks),
            sum(check.verdict == "支持" for check in valid_checks),
            sum(check.verdict == "冲突" for check in valid_checks),
            sum(check.verdict in {"部分支持", "证据不足"} for check in valid_checks),
        )
        return result

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
            correctness_summary="本次未取得完整模型评估结果，无法确认全部技术结论；当前仅按可观察信号和 Rubric 给出低置信度临时分数。",
            error_analysis=missing_points[:3],
            expected_key_points=[spec.description for spec in rubric[:3]],
            correction_suggestion="可稍后重新评估，并补充上述 Rubric 维度缺少的技术证据。",
            summary="完整模型评估本次未成功，系统已按可解释的 Rubric 规则生成低置信度临时结果。",
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
