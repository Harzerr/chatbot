from __future__ import annotations

import re
from dataclasses import dataclass


ASSESSMENT_VERSION = "rubric-v2"

NON_ANSWER_MARKERS = (
    "不知道",
    "不清楚",
    "不了解",
    "不太了解",
    "没了解过",
    "没接触过",
    "没有接触过",
    "没做过",
    "没有做过",
    "不熟悉",
    "不太会",
    "不会",
    "答不上来",
    "无法回答",
    "不记得",
    "想不起来",
    "没有相关经验",
    "无相关经验",
)


def is_non_answer(answer: str | None) -> bool:
    """Return whether the candidate explicitly declines or cannot answer."""
    normalized = "".join(str(answer or "").lower().split())
    if not normalized:
        return True
    markers = [marker for marker in NON_ANSWER_MARKERS if marker in normalized]
    if not markers:
        return False
    for marker in markers:
        suffix = normalized[normalized.find(marker) + len(marker):]
        if len(suffix) >= 8 and any(conjunction in suffix for conjunction in ("但是", "不过", "但我", "同时", "我会", "可以")):
            continue
        return True
    return False


def is_countable_answer(answer: str | None, *, has_previous_question: bool = True) -> bool:
    """Use one deterministic rule for interview counters, evaluation and reports."""
    normalized = "".join(str(answer or "").lower().split())
    if not has_previous_question or not normalized:
        return False
    if normalized in {"开始面试", "开始", "继续", "开始吧", "可以开始了", "继续面试"}:
        return False
    return not is_non_answer(normalized)


def count_countable_answers(chat_messages: list[dict]) -> int:
    return sum(
        1
        for message in chat_messages
        if (
            bool(message["answer_counted"])
            if message.get("answer_counted") is not None
            else is_countable_answer(message.get("user_message"))
        )
    )


@dataclass(frozen=True)
class RubricDimensionSpec:
    key: str
    label: str
    weight: float
    fallback_field: str
    description: str


RUBRICS: dict[str, tuple[RubricDimensionSpec, ...]] = {
    "技术原理题": (
        RubricDimensionSpec("technical_correctness", "技术正确性", 0.35, "technical_accuracy", "机制、结论和术语是否正确"),
        RubricDimensionSpec("mechanism_depth", "原理深度", 0.25, "knowledge_depth", "是否解释原因、边界和关键机制"),
        RubricDimensionSpec("engineering_context", "工程落地", 0.20, "problem_solving", "是否能说明实践场景、风险和处理方式"),
        RubricDimensionSpec("answer_structure", "表达结构", 0.20, "logical_structure", "是否结论先行、层次清晰"),
    ),
    "项目深挖题": (
        RubricDimensionSpec("fact_grounding", "事实与证据", 0.25, "technical_accuracy", "是否给出可回溯的项目、职责、数据或细节"),
        RubricDimensionSpec("personal_ownership", "个人贡献", 0.25, "problem_solving", "是否说清本人决策、推动和负责边界"),
        RubricDimensionSpec("technical_depth", "技术深度", 0.25, "knowledge_depth", "是否讲清方案、机制、异常和优化"),
        RubricDimensionSpec("tradeoff_reflection", "取舍与复盘", 0.15, "problem_solving", "是否说明方案比较、限制和复盘"),
        RubricDimensionSpec("answer_structure", "表达结构", 0.10, "logical_structure", "是否按场景、行动、结果、复盘组织"),
    ),
    "系统设计题": (
        RubricDimensionSpec("requirements_clarification", "需求澄清", 0.15, "problem_solving", "是否识别目标、约束、规模和边界"),
        RubricDimensionSpec("architecture_design", "架构设计", 0.30, "technical_accuracy", "核心模块、数据流和接口是否合理"),
        RubricDimensionSpec("tradeoff_reliability", "取舍与可靠性", 0.25, "knowledge_depth", "是否覆盖一致性、扩展性、可用性与风险"),
        RubricDimensionSpec("implementation_plan", "落地方案", 0.15, "problem_solving", "是否有分阶段实现、验证和排障思路"),
        RubricDimensionSpec("answer_structure", "表达结构", 0.15, "logical_structure", "方案描述是否完整且易追踪"),
    ),
    "行为面试题": (
        RubricDimensionSpec("star_structure", "STAR 完整度", 0.30, "logical_structure", "是否交代情境、任务、行动和结果"),
        RubricDimensionSpec("ownership_reflection", "责任与复盘", 0.25, "problem_solving", "是否体现个人承担、复盘和成长"),
        RubricDimensionSpec("collaboration", "协作沟通", 0.20, "communication_clarity", "是否体现协作、冲突处理和影响他人"),
        RubricDimensionSpec("job_alignment", "岗位动机", 0.15, "job_match_score", "是否自然关联目标岗位与能力"),
        RubricDimensionSpec("answer_authenticity", "具体可信度", 0.10, "technical_accuracy", "是否避免空泛套话，给出具体事实"),
    ),
    "代码题": (
        RubricDimensionSpec("algorithm_choice", "算法与数据结构", 0.25, "technical_accuracy", "是否选择正确的算法方向和数据结构"),
        RubricDimensionSpec("solution_correctness", "解法正确性", 0.30, "technical_accuracy", "代码或伪代码是否自洽、关键流程可运行"),
        RubricDimensionSpec("complexity", "复杂度", 0.15, "knowledge_depth", "时间和空间复杂度是否合理"),
        RubricDimensionSpec("edge_cases", "边界覆盖", 0.20, "problem_solving", "是否覆盖空值、重复、越界和异常输入"),
        RubricDimensionSpec("code_quality", "代码质量", 0.10, "communication_clarity", "命名、结构、可维护性是否合格"),
    ),
    "通用技术题": (
        RubricDimensionSpec("technical_correctness", "技术正确性", 0.35, "technical_accuracy", "结论和实现方向是否正确"),
        RubricDimensionSpec("knowledge_depth", "知识深度", 0.25, "knowledge_depth", "是否包含机制、边界和工程细节"),
        RubricDimensionSpec("problem_solving", "问题解决", 0.20, "problem_solving", "是否体现分析、取舍和验证"),
        RubricDimensionSpec("answer_structure", "表达结构", 0.20, "logical_structure", "是否有清晰主线"),
    ),
}


def classify_question_type(question: str, interview_type: str | None = None) -> str:
    normalized = (question or "").lower()
    if any(marker in normalized for marker in ("手撕代码", "代码题", "实现一个", "时间复杂度", "空间复杂度", "```", "#include", "def ", "class ")):
        return "代码题"
    if any(marker in normalized for marker in ("项目", "实习", "你负责", "你的职责", "你做过", "怎么优化", "遇到什么问题", "成果", "指标")):
        return "项目深挖题"
    if any(marker in normalized for marker in ("设计一个", "系统设计", "架构", "如何设计", "高并发", "高可用", "扩展性", "容量")):
        return "系统设计题"
    if interview_type == "HR面" or any(marker in normalized for marker in ("为什么", "冲突", "协作", "压力", "失败", "缺点", "职业规划", "离职", "团队")):
        return "行为面试题"
    if any(marker in normalized for marker in ("原理", "区别", "为什么", "如何保证", "机制", "是什么", "怎么实现")):
        return "技术原理题"
    return "通用技术题"


def get_rubric(question_type: str) -> tuple[RubricDimensionSpec, ...]:
    return RUBRICS.get(question_type, RUBRICS["通用技术题"])


def infer_capability_tags(question: str, question_type: str) -> list[str]:
    normalized = (question or "").lower()
    tags: list[str] = []
    candidates = {
        "缓存与一致性": ("redis", "缓存", "一致性"),
        "数据库与事务": ("mysql", "数据库", "事务", "索引", "sql"),
        "并发与线程": ("并发", "线程", "锁", "线程池", "协程"),
        "系统设计": ("架构", "高并发", "高可用", "系统设计", "扩展"),
        "工程排障": ("排查", "故障", "监控", "线上", "异常"),
        "算法与编码": ("算法", "代码", "复杂度", "数组", "链表", "树", "图"),
        "项目实践": ("项目", "实习", "职责", "优化", "成果"),
        "行为与协作": ("冲突", "协作", "团队", "压力", "失败", "规划"),
    }
    for tag, markers in candidates.items():
        if any(marker in normalized for marker in markers):
            tags.append(tag)
    type_tag = {
        "技术原理题": "技术基础",
        "项目深挖题": "项目表达与所有权",
        "系统设计题": "系统设计",
        "行为面试题": "行为表达",
        "代码题": "算法与编码",
    }.get(question_type)
    if type_tag and type_tag not in tags:
        tags.append(type_tag)
    return tags[:4] or ["综合能力"]


def extract_jd_requirements(jd_content: str | None, limit: int = 6) -> list[str]:
    if not jd_content:
        return []
    lines = [
        re.sub(r"^[\s•·\-*\d.、]+", "", line).strip()
        for line in re.split(r"[\r\n。；;]+", jd_content)
    ]
    requirement_markers = ("要求", "熟悉", "掌握", "能力", "经验", "优先", "负责", "精通", "了解")
    selected = [line for line in lines if 8 <= len(line) <= 180 and any(marker in line for marker in requirement_markers)]
    if not selected:
        selected = [line for line in lines if 8 <= len(line) <= 120]
    deduped: list[str] = []
    seen = set()
    for line in selected:
        key = re.sub(r"\s+", "", line)
        if key and key not in seen:
            seen.add(key)
            deduped.append(line)
    return deduped[:limit]


def extract_resume_evidence(resume_content: str | None, question: str, limit: int = 6) -> list[str]:
    if not resume_content:
        return []
    question_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9+#._-]{1,}|[\u4e00-\u9fff]{2,}", question or ""))
    stop_terms = {"请你", "介绍", "一下", "如何", "什么", "为什么", "这个", "问题", "项目", "经历"}
    question_terms = {term.lower() for term in question_terms if term not in stop_terms}
    candidates: list[tuple[int, str]] = []
    for line in resume_content.splitlines():
        normalized = re.sub(r"\s+", " ", line.strip(" •·-*\t"))
        if not 10 <= len(normalized) <= 220:
            continue
        lowered = normalized.lower()
        score = sum(1 for term in question_terms if len(term) >= 2 and term in lowered)
        if re.search(r"负责|主导|设计|实现|优化|搭建|解决|提升|降低|项目|实习", normalized):
            score += 1
        if score:
            candidates.append((score, normalized))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    evidence: list[str] = []
    seen = set()
    for _, line in candidates:
        if line not in seen:
            seen.add(line)
            evidence.append(line)
    return evidence[:limit]


def rubric_prompt(rubric: tuple[RubricDimensionSpec, ...]) -> str:
    return "\n".join(
        f"- {item.key}（{item.label}，权重 {int(item.weight * 100)}%）：{item.description}；按 0-4 分打分。"
        for item in rubric
    )


def calculate_confidence(answer: str, rubric_count: int, has_jd: bool, has_resume_evidence: bool) -> int:
    length = len((answer or "").strip())
    score = 40
    if length >= 60:
        score += 15
    if length >= 160:
        score += 10
    if rubric_count >= 4:
        score += 10
    if has_jd:
        score += 5
    if has_resume_evidence:
        score += 5
    return min(85, score)


def confidence_level(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 60:
        return "中"
    return "低"
