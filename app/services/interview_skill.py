import re
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.coding_question_bank_loader import load_coding_question_bank
from app.services.coding_knowledge_store import QdrantCodingKnowledgeStore
from app.services.interview_kit import (
    build_company_jd_resume_context,
    get_interview_question_limit,
    get_question_bank_context,
    get_role_knowledge_context,
    normalize_interview_round,
    normalize_interview_role,
)
from app.services.role_knowledge_store import QdrantRoleKnowledgeStore

MANUAL_FINISH_COMMAND = "__SYSTEM_END_INTERVIEW_AND_EXPORT_REPORT__"
INTERVIEW_SKILL_ROOT = Path(__file__).resolve().parents[2] / "interview-skills"
ROLE_FOUNDATION_KEYWORDS = {
    "Java后端工程师": ["Java", "JVM", "多线程", "Spring", "Spring Boot", "MySQL", "Redis"],
    "C++开发工程师": ["C++", "STL", "Qt", "Linux", "多线程", "内存管理", "Docker"],
    "测试工程师": ["测试", "接口测试", "自动化", "Python", "MySQL", "Docker", "CI"],
    "Web前端工程师": ["JavaScript", "TypeScript", "Vue", "React", "CSS", "浏览器", "前端工程化"],
    "Python算法工程师": ["Python", "机器学习", "深度学习", "PyTorch", "模型训练", "特征工程", "数据处理"],
}


class InterviewSkill:
    def __init__(
        self,
        llm,
        evaluator,
        role_knowledge_store: QdrantRoleKnowledgeStore | None = None,
        coding_knowledge_store: QdrantCodingKnowledgeStore | None = None,
    ):
        self._llm = llm
        self._evaluator = evaluator
        self._role_knowledge_store = role_knowledge_store
        self._coding_knowledge_store = coding_knowledge_store
        self._skill_bundle = self._load_skill_bundle()

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _load_skill_bundle(self) -> dict[str, str]:
        skill_md = self._read_text(INTERVIEW_SKILL_ROOT / "SKILL.md")
        question_design = self._read_text(INTERVIEW_SKILL_ROOT / "references" / "question-design.md")
        company_profiles = self._read_text(INTERVIEW_SKILL_ROOT / "references" / "company-profiles.md")
        jd_parser = self._read_text(INTERVIEW_SKILL_ROOT / "references" / "jd-parser.md")
        resume_parser = self._read_text(INTERVIEW_SKILL_ROOT / "references" / "resume-parser.md")
        bei_framework = self._read_text(INTERVIEW_SKILL_ROOT / "references" / "bei-framework.md")

        return {
            "skill_md": skill_md[:5000],
            "question_design": question_design[:3500],
            "company_profiles": company_profiles[:3500],
            "jd_parser": jd_parser[:2500],
            "resume_parser": resume_parser[:2500],
            "bei_framework": bei_framework[:2500],
        }

    def _build_skill_instruction_context(self) -> str:
        skill_md = self._skill_bundle.get("skill_md") or "未找到 interview-skills/SKILL.md"
        question_design = self._skill_bundle.get("question_design") or "未找到 question-design.md"
        company_profiles = self._skill_bundle.get("company_profiles") or "未找到 company-profiles.md"
        jd_parser = self._skill_bundle.get("jd_parser") or "未找到 jd-parser.md"
        resume_parser = self._skill_bundle.get("resume_parser") or "未找到 resume-parser.md"
        bei_framework = self._skill_bundle.get("bei_framework") or "未找到 bei-framework.md"

        return f"""
INTERVIEW SKILL INSTRUCTIONS:
请将下列内容视为面试官 skill 的结构化主指令来源。你当前在执行一套“大厂模拟面试官 skill”，提问和追问时优先遵循这些规则。

[主流程 / SKILL.md]
{skill_md}

[阶段1：JD 解析规则]
{jd_parser}

[阶段2：简历解析规则]
{resume_parser}

[阶段3：公司画像与风格匹配]
{company_profiles}

[阶段4：面试题设计规则]
{question_design}

[阶段5：行为面试与追问框架]
{bei_framework}
"""

    def _get_role_knowledge_context(
        self,
        interview_role: str | None,
        interview_type: str | None,
        question: str | None,
        jd_content: str | None,
        resume_content: str | None,
    ) -> str:
        query = "\n".join(
            part
            for part in [
                normalize_interview_role(interview_role),
                interview_type or "",
                question or "",
                (jd_content or "")[:1200],
                (resume_content or "")[:1200],
            ]
            if part
        )

        if self._role_knowledge_store:
            try:
                docs = self._role_knowledge_store.search_role_knowledge(
                    interview_role=interview_role,
                    query=query,
                    top_k=4,
                )
                if docs:
                    doc_blocks = []
                    for doc in docs:
                        focus_points = "、".join(doc.get("focus_points", []))
                        doc_blocks.append(
                            f"- 面试题：{doc.get('title')}\n"
                            f"  岗位：{doc.get('role')}\n"
                            f"  题型：{doc.get('category')}\n"
                            f"  考察点：{focus_points}\n"
                            f"  回答方向：{doc.get('answer_framework')}\n"
                            f"  内容摘要：{doc.get('content')}"
                        )
                    return "ROLE KNOWLEDGE BASE RETRIEVAL:\n" + "\n".join(doc_blocks)
            except Exception:
                pass

        return get_role_knowledge_context(
            interview_role=interview_role,
            interview_type=interview_type,
            question=question,
            jd_content=jd_content,
            resume_content=resume_content,
        )

    def _analyze_jd(self, jd_content: str | None) -> str:
        if not jd_content or not jd_content.strip():
            return "未提供 JD。请结合岗位类型、级别和目标公司推断面试重点。"
        return (
            "JD 分析重点：\n"
            "- 请提炼岗位核心职责、必须能力、加分项、业务场景与隐含要求。\n"
            "- 优先围绕 JD 中出现频率高、要求明确、区分度强的能力提问。\n"
            f"- JD 摘要：\n{jd_content.strip()[:1200]}"
        )

    def _analyze_resume(self, resume_content: str | None) -> str:
        if not resume_content or not resume_content.strip():
            return "未提供简历。请使用合理的目标候选人基线，但不要编造具体项目。"
        return (
            "候选人背景分析：\n"
            "- 请识别候选人的项目经历、技术栈、业务场景、职责边界、成果指标与可能薄弱点。\n"
            "- 一面先看岗位基础是否扎实，后续轮次再逐步加大对真实经历和项目深挖的权重。\n"
            f"- 简历摘要：\n{resume_content.strip()[:1200]}"
        )

    def _extract_resume_highlights(self, resume_content: str | None) -> list[str]:
        if not resume_content or not resume_content.strip():
            return []

        raw_lines = [line.strip("•·-* \t") for line in resume_content.splitlines()]
        lines = [line for line in raw_lines if line]
        highlights_with_score: list[tuple[int, str]] = []

        ignored_markers = ("候选人个人档案", "候选人简历内容")
        section_patterns = {
            "project": re.compile(r"(项目|实习|工作经历|工作经验|实践经历|校园经历)"),
            "research": re.compile(r"(科研|论文|课题|实验室|研究方向|发表)"),
            "competition": re.compile(r"(竞赛|比赛|获奖|奖项|挑战杯|数学建模)"),
            "skills": re.compile(r"(技能|技术栈|专业能力|擅长|编程语言|工具)"),
        }
        action_pattern = re.compile(
            r"(负责|主导|设计|实现|优化|搭建|参与|推进|完成|解决|改进|开发|落地|重构|维护|研究)"
        )
        metric_pattern = re.compile(r"(\d+[%mskKwW万千百篇项个次]|top\s*\d+|SOTA)", re.IGNORECASE)
        tech_token_pattern = re.compile(r"\b[A-Za-z][A-Za-z0-9.+#/_-]{1,}\b")
        project_name_pattern = re.compile(r"(《[^》]+》|“[^”]+”|\"[^\"]+\")")

        current_section = ""

        for index, line in enumerate(lines):
            if len(line) < 6:
                continue
            if any(marker in line for marker in ignored_markers):
                continue

            lowered = line.lower()
            for section, pattern in section_patterns.items():
                if pattern.search(lowered):
                    current_section = section
                    break

            score = 0
            if current_section in {"project", "research", "competition"}:
                score += 3
            elif current_section == "skills":
                score += 1

            if action_pattern.search(line):
                score += 3
            if metric_pattern.search(line):
                score += 2

            tech_tokens = tech_token_pattern.findall(line)
            if len(tech_tokens) >= 2:
                score += 2
            elif len(tech_tokens) == 1:
                score += 1

            if project_name_pattern.search(line):
                score += 2
            if any(sep in line for sep in ("：", ":", "|", "/", "->", "→")):
                score += 1
            if re.search(r"\b20\d{2}\b", line):
                score += 1
            if 12 <= len(line) <= 120:
                score += 2
            elif len(line) <= 160:
                score += 1

            previous_line = lines[index - 1] if index > 0 else ""
            if previous_line and any(pattern.search(previous_line.lower()) for pattern in section_patterns.values()):
                score += 1

            if score >= 4:
                highlights_with_score.append((score, line))

        if not highlights_with_score:
            for line in lines:
                if any(marker in line for marker in ignored_markers):
                    continue
                if 12 <= len(line) <= 120:
                    highlights_with_score.append((1, line))

        deduped: list[str] = []
        seen = set()
        for _, item in sorted(highlights_with_score, key=lambda x: (-x[0], len(x[1]))):
            normalized = re.sub(r"\s+", " ", item)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized[:140])

        return deduped[:8]

    def _has_started_coding_round(self, relevant_docs: list[dict]) -> bool:
        coding_markers = ("手撕代码", "代码题", "写出核心代码", "贴出你的代码", "实现这个函数")
        for doc in relevant_docs:
            assistant_message = (doc.get("assistant_message") or "").lower()
            if any(marker.lower() in assistant_message for marker in coding_markers):
                return True
        return False

    def _looks_like_code_submission(self, question: str) -> bool:
        normalized = question.strip()
        if "```" in normalized:
            return True

        code_patterns = (
            r"\bclass\s+\w+",
            r"\bpublic\s+class\b",
            r"\bdef\s+\w+\s*\(",
            r"\bfunction\s+\w+\s*\(",
            r"#include\s*<",
            r"\bint\s+main\s*\(",
            r"\bstd::",
            r"\breturn\b.+;",
            r"\bconst\s+\w+",
        )
        return any(re.search(pattern, normalized) for pattern in code_patterns)

    def _should_switch_to_coding_round(
        self,
        relevant_docs: list[dict],
        interview_type: str | None,
    ) -> bool:
        if self._has_started_coding_round(relevant_docs):
            return False

        interview_round = normalize_interview_round(interview_type)
        required_completed_rounds = {
            "一面": 2,
            "二面": 1,
            "三面": 2,
            "HR面": 999,
        }
        return len(relevant_docs) >= required_completed_rounds.get(interview_round, 999)

    def _pick_coding_question(
        self,
        interview_role: str | None,
        interview_type: str | None,
        relevant_docs: list[dict],
    ) -> dict | None:
        role = normalize_interview_role(interview_role)
        interview_round = normalize_interview_round(interview_type)
        if self._coding_knowledge_store:
            try:
                query = f"{role} {interview_round} 手撕代码 面试题"
                docs = self._coding_knowledge_store.search_coding_questions(
                    interview_role=role,
                    interview_type=interview_type,
                    query=query,
                    top_k=8,
                )
                if docs:
                    index = len(relevant_docs) % len(docs)
                    selected = docs[index]
                    return {
                        "role": selected.get("role"),
                        "rounds": selected.get("rounds", []),
                        "title": selected.get("title"),
                        "difficulty": selected.get("difficulty", "中等"),
                        "topic": selected.get("topic", ""),
                        "source_basis": selected.get("source_basis", "Qdrant coding knowledge"),
                        "prompt": selected.get("prompt") or selected.get("content", ""),
                        "input_spec": selected.get("input_spec", ""),
                        "output_spec": selected.get("output_spec", ""),
                        "examples": selected.get("examples", []),
                        "evaluation_focus": selected.get("evaluation_focus", []),
                    }
            except Exception:
                pass

        candidates = [
            item for item in load_coding_question_bank()
            if item.get("role") in {role, "通用软件工程师"} and interview_round in item.get("rounds", [])
        ]
        if not candidates:
            return None

        role_specific = [item for item in candidates if item.get("role") == role]
        generic = [item for item in candidates if item.get("role") == "通用软件工程师"]
        ordered_candidates = role_specific + generic
        index = len(relevant_docs) % len(ordered_candidates)
        return ordered_candidates[index]

    def _render_coding_question_prompt(self, coding_question: dict) -> str:
        title = coding_question.get("title", "代码题")
        difficulty = coding_question.get("difficulty", "中等")
        prompt = coding_question.get("prompt", "")
        input_spec = coding_question.get("input_spec", "")
        output_spec = coding_question.get("output_spec", "")
        examples = coding_question.get("examples", [])

        parts = [
            f"我们切一道手撕代码题。请你实现“{title}”，难度大致是{difficulty}。",
            prompt,
        ]
        if input_spec:
            parts.append(f"输入要求是：{input_spec}")
        if output_spec:
            parts.append(f"输出要求是：{output_spec}")
        if examples:
            parts.append(f"例如：{'；'.join(examples[:2])}")
        parts.append("你可以先讲思路，再贴代码；如果你愿意，也可以直接给出完整实现。")
        return " ".join(part for part in parts if part)

    def _build_coding_round_context(
        self,
        interview_role: str | None,
        interview_type: str | None,
        relevant_docs: list[dict],
        question: str,
    ) -> str:
        if self._looks_like_code_submission(question):
            return """
当前处于代码作答评审阶段：
- 候选人刚提交的内容很可能包含代码或伪代码
- 请先用一句话指出一个做得对的点或一个明显风险点，再继续像真人面试官一样追问
- 优先追问时间复杂度、空间复杂度、边界条件、异常输入、线程安全或可读性
- 如果代码思路明显有问题，要自然指出关键漏洞，并要求候选人修正，不要直接给标准答案
"""

        if not self._should_switch_to_coding_round(relevant_docs, interview_type):
            return ""

        coding_question = self._pick_coding_question(interview_role, interview_type, relevant_docs)
        if not coding_question:
            return ""

        examples = "\n".join(f"- {item}" for item in coding_question.get("examples", []))
        focuses = "\n".join(f"- {item}" for item in coding_question.get("evaluation_focus", []))

        return f"""
当前回合需要切换到手撕代码场景：
- 这是一个真实技术面试中的代码题回合，现在必须出一道手撕代码题
- 请围绕下面这道题自然发问，不要换题，不要改成纯项目题或纯八股题
- 你可以先用一句自然过渡，然后把题意、输入输出要求、一个或两个示例说清楚
- 需要明确告诉候选人：可以先讲思路，再贴代码；如果愿意，也可以直接贴完整代码
- 题目标题：{coding_question.get('title')}
- 难度：{coding_question.get('difficulty')}
- 题目要求：{coding_question.get('prompt')}
- 输入要求：{coding_question.get('input_spec')}
- 输出要求：{coding_question.get('output_spec')}
- 示例：
{examples or "- 无"}
- 评审重点：
{focuses or "- 代码正确性"}
"""

    def _is_opening_turn(self, question: str, relevant_docs: list[dict]) -> bool:
        if not relevant_docs:
            return True

        normalized = question.strip().lower()
        opening_phrases = {"开始面试", "开始", "开始吧", "可以开始了", "继续面试", "继续"}
        return normalized in opening_phrases

    def _build_opening_strategy(
        self,
        question: str,
        relevant_docs: list[dict],
        resume_highlights: list[str],
        resume_content: str | None,
        interview_role: str | None,
        interview_type: str | None,
    ) -> str:
        if not self._is_opening_turn(question, relevant_docs):
            return ""

        interview_round = normalize_interview_round(interview_type)
        normalized_role = normalize_interview_role(interview_role)
        role_keywords = ROLE_FOUNDATION_KEYWORDS.get(normalized_role, [])
        resume_text = resume_content or ""
        matched_keywords = [keyword for keyword in role_keywords if keyword.lower() in resume_text.lower()]

        if interview_round == "一面":
            keyword_bullets = "\n".join(f"- {item}" for item in matched_keywords[:5])
            return f"""
开场题硬性要求：
- 当前是一面，第一题优先考核岗位相关基础知识，而不是直接深挖项目
- 第一题必须优先覆盖该岗位的核心基础：概念理解、原理机制、常见工程边界或基础设计判断
- 如果简历中明确写了与岗位相关的技能，请优先从候选人已经写在简历里的技能切入基础题
{keyword_bullets if keyword_bullets else f"- 若简历中没有明显岗位技能关键词，也必须先从 {normalized_role} 的高频基础知识切入，再逐步过渡到项目。"}
- 对于 {normalized_role}，第一题应该像真实一面技术筛选，先判断基础是否扎实，再决定后续是否深挖项目
- 除非候选人完全没有岗位相关技能信息，否则不要把第一题设计成科研项目或竞赛项目深挖题
"""

        if resume_highlights:
            bullets = "\n".join(f"- {item}" for item in resume_highlights[:5])
            return f"""
开场题硬性要求：
- 这是面试开场轮，第一题应明确锚定到候选人简历中的具体经历，不能先问泛化的“你有什么经验”
- 下面是从简历中抽取的优先追问线索，请至少点名其中一项来发问：
{bullets}
- 问题里必须出现明确的经历锚点，例如项目名、科研课题、竞赛经历、承担工作、技术栈或具体模块
- 如果 JD 要求与简历不完全对齐，也要从候选人真实经历切入，再追问其如何迁移到目标岗位，而不是直接假设候选人有某项经验
"""

        if resume_content and resume_content.strip():
            return """
开场题硬性要求：
- 这是面试开场轮，第一题必须引用简历中的真实内容切入
- 不允许直接问泛化的自我介绍式项目题
- 如果简历与 JD 不完全匹配，请围绕简历中最接近的经历追问其能力迁移
"""

        return ""

    def _get_company_style(self, company: str | None) -> str:
        if not company:
            return "通用互联网公司技术面试风格：重视真实经验、技术判断、问题拆解与表达质量。"

        normalized = company.lower()

        if "字节" in normalized or "bytedance" in normalized:
            return "字节风格：节奏快，强调项目 impact、细节深挖、复杂度分析、真实 ownership 和快速反应。"
        if "阿里" in normalized:
            return "阿里风格：强调系统设计、业务理解、稳定性、高并发场景与跨团队推进能力。"
        if "腾讯" in normalized:
            return "腾讯风格：强调工程实践、底层原理、稳定性、设计合理性和边界意识。"
        if "美团" in normalized:
            return "美团风格：强调业务落地、工程效率、性能优化、结果导向和复盘能力。"
        if "华为" in normalized:
            return "华为风格：强调基础扎实、系统能力、严谨性、复杂问题拆解和工程规范。"

        return "通用互联网公司技术面试风格：重视真实经验、技术判断、问题拆解与表达质量。"

    def _build_prompt(
        self,
        question: str,
        context: str,
        skill_instruction_context: str,
        jd_analysis: str,
        resume_analysis: str,
        opening_strategy: str,
        company_style: str,
        question_bank_context: str,
        role_knowledge_context: str,
        coding_round_context: str,
        company_jd_resume_context: str,
        history_messages: list,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
    ) -> list:
        role = normalize_interview_role(interview_role)
        level = interview_level or "中级"
        interview_kind = normalize_interview_round(interview_type)

        return [
            SystemMessage(
                content=f"""
你是一个专业、严格、真实的 AI 面试官，请严格按照真实技术面试流程进行提问与追问。

Skill 运行时上下文：
{skill_instruction_context}

面试设定：
- 岗位：{role}
- 级别：{level}
- 面试类型：{interview_kind}

核心目标：
- 生成高质量、高区分度、足够专业的面试问题
- 通过连续追问判断候选人是否真正做过、是否理解原理、是否具备工程判断
- 区分弱、中、强候选人，而不是生成泛泛而谈的聊天式问题
- 你当前不是自由发挥的通用助手，而是在执行 interview-skills 这套面试官 skill
- 出题结构、公司风格、JD/简历解析思路优先遵循 skill 文档
- 将本轮面试理解为一个结构化流程：JD解析 -> 简历解析 -> 公司风格匹配 -> 题目设计 -> 行为追问
- 如果岗位知识库检索到了具体面试题，则优先把它们视为题库候选，而不是重新发明与岗位无关的问题

公司风格：
{company_style}

JD 分析：
{jd_analysis}

简历分析：
{resume_analysis}

开场策略：
{opening_strategy or "当前不是开场轮，按上一轮回答继续深挖。"}

岗位能力方向：
{question_bank_context or "未提供额外题库方向，请根据岗位与面试类型动态生成问题。"}

岗位知识库检索结果：
{role_knowledge_context or "未命中岗位知识库，请结合岗位、JD、简历进行常识性推断。"}

代码题上下文：
{coding_round_context or "当前不是代码题回合，按常规技术面试逻辑出题。"}

公司 / JD / 简历补充上下文：
{company_jd_resume_context}

对话上下文：
{context}

面试规则：
- 一次只问一个主问题
- 优先基于 JD、简历和候选人的上一轮回答提问
- 优先使用 interview-skills 中定义的出题框架：JD 驱动、简历锚点、由浅入深、追问预设
- 优先使用岗位化题库与岗位知识库中的能力模型、考点和优秀回答范式来约束提问深度
- 如果代码题上下文要求当前切到手撕代码场景，就必须执行，不要继续普通项目问答
- 至少让部分问题显式锚定到 skill 中的分阶段设计：破冰、专业基础、项目深挖、行为追问、收尾
- 问题必须具体，不能空泛，不能像教程提纲
- 如果候选人已经回答过某个方向，就继续深挖细节、取舍、指标、边界、故障、复杂度，而不是换个说法重复问
- 如果候选人回答比较空泛，立刻缩小范围，要求说清一个真实项目、一个模块、一次线上问题、一个技术决策或一个关键指标
- 如果这是开场轮且是一面，禁止一上来就深挖科研或竞赛项目；应优先从岗位基础知识切入，必要时结合简历里明确写过的技能来发问
- 如果这是开场轮且不是一面，禁止问“介绍一下你的项目经验/介绍一下你的 C++ 经验”这类泛化问题，必须基于简历中的某一条经历发问
- 一面优先核验岗位基础知识、原理理解、常见边界和表达清晰度，项目真实性放在基础核验之后
- 二面优先深挖项目决策、复杂场景、系统设计或编码实现能力
- 三面优先考察综合判断、复杂问题拆解、跨团队协作和成长潜力
- HR面优先考察动机匹配、稳定性、沟通协作、价值观和职业规划
- 如果当前是代码题回合，默认先判断候选人的思路是否成立，再追问复杂度、边界条件和代码质量
- 无论是哪一轮，问题都要符合当前标准岗位的核心技术栈和高频考点，不能问错岗位
- 不要一次抛多个问题
- 不要自问自答
- 不要长篇解释概念，除非用户明确要求讲解
- 不要使用“你的回答很好”这类弱化面试强度的话术，除非马上接更尖锐的追问

输出要求：
- 你对外输出时只能像真人面试官一样自然说话，不要输出报告格式
- 严禁输出诸如“Q1”“题目：”“考察点：”“难度：”“参考答案提示：”“追问方向：”这类栏目名
- 严禁输出分隔线、卡片样式、标题模板、emoji 或题库展示格式
- 如果这是开场轮，最多用一句很自然的开场过渡，然后立刻进入第一道问题
- 如果用户刚回答了上一题，先给一句非常简短的判断，然后自然地继续追问或切换到下一题
- 单次回复默认控制在 1 到 3 句，不要长篇铺垫
- 问题要像真实面试官临场提问，例如“你简历里提到……，当时为什么这么做？”这种自然口语
- 不要用“好的，我们开始面试”“下面是第一题”这类主持词口吻，除非用户明确要求仪式化开场
- 即使你内部参考了 skill 文档中的输出模板，也不要把模板原样展示给用户
- 优先输出真正能筛人的自然提问，而不是教科书目录或面试报告
"""
            ),
            *history_messages,
            HumanMessage(content=question),
        ]

    def _build_history_messages(self, relevant_docs: list[dict]) -> list:
        history = []
        for doc in relevant_docs[-6:]:
            if doc.get("user_message"):
                history.append(HumanMessage(content=doc["user_message"]))
            if doc.get("assistant_message"):
                history.append(AIMessage(content=doc["assistant_message"], name="Interviewer"))
        return history

    async def run(
        self,
        question: str,
        previous_interviewer_question: str | None,
        relevant_docs: list[dict],
        context: str,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
        target_company: str | None = None,
        jd_content: str | None = None,
        resume_content: str | None = None,
    ) -> dict:
        question_limit = get_interview_question_limit(interview_type)
        normalized_question = (question or "").strip()

        if normalized_question == MANUAL_FINISH_COMMAND:
            completed_questions = min(len(relevant_docs), question_limit)
            return {
                "response": (
                    f"本场面试已结束。你已完成 {completed_questions}/{question_limit} 题。"
                    "系统已记录本次作答数据，请查看综合报告并导出 PDF。"
                ),
                "evaluation": None,
                "is_finished": True,
            }

        if relevant_docs and len(relevant_docs) >= question_limit:
            return {
                "response": f"本场面试已结束。你已完成 {question_limit}/{question_limit} 题。系统已记录本次作答数据，请查看右侧综合报告。",
                "evaluation": None,
                "is_finished": True,
            }

        jd_analysis = self._analyze_jd(jd_content)
        resume_analysis = self._analyze_resume(resume_content)
        resume_highlights = self._extract_resume_highlights(resume_content)
        normalized_role = normalize_interview_role(interview_role)
        skill_instruction_context = self._build_skill_instruction_context()
        opening_strategy = self._build_opening_strategy(
            question=question,
            relevant_docs=relevant_docs,
            resume_highlights=resume_highlights,
            resume_content=resume_content,
            interview_role=normalized_role,
            interview_type=interview_type,
        )
        company_style = self._get_company_style(target_company)
        history_messages = self._build_history_messages(relevant_docs)
        question_bank_context = get_question_bank_context(normalized_role, interview_type)
        role_knowledge_context = self._get_role_knowledge_context(
            interview_role=normalized_role,
            interview_type=interview_type,
            question=question,
            jd_content=jd_content,
            resume_content=resume_content,
        )
        coding_round_context = self._build_coding_round_context(
            interview_role=normalized_role,
            interview_type=interview_type,
            relevant_docs=relevant_docs,
            question=question,
        )

        if self._should_switch_to_coding_round(relevant_docs, interview_type) and not self._looks_like_code_submission(question):
            coding_question = self._pick_coding_question(
                interview_role=normalized_role,
                interview_type=interview_type,
                relevant_docs=relevant_docs,
            )
            if coding_question:
                return {
                    "response": self._render_coding_question_prompt(coding_question),
                    "evaluation": None,
                    "is_finished": False,
                }

        company_jd_resume_context = build_company_jd_resume_context(
            target_company,
            jd_content,
            resume_content,
        )

        messages = self._build_prompt(
            question=question,
            context=context,
            skill_instruction_context=skill_instruction_context,
            jd_analysis=jd_analysis,
            resume_analysis=resume_analysis,
            opening_strategy=opening_strategy,
            company_style=company_style,
            question_bank_context=question_bank_context,
            role_knowledge_context=role_knowledge_context,
            coding_round_context=coding_round_context,
            company_jd_resume_context=company_jd_resume_context,
            history_messages=history_messages,
            interview_role=normalized_role,
            interview_level=interview_level,
            interview_type=interview_type,
        )

        response = await self._llm.ainvoke(messages)
        response_text = response.content if hasattr(response, "content") else str(response)

        evaluation = None
        try:
            if self._evaluator.should_evaluate(question, previous_interviewer_question):
                evaluation = await self._evaluator.evaluate_answer(
                    previous_question=previous_interviewer_question,
                    user_answer=question,
                    interview_role=normalized_role,
                    interview_level=interview_level,
                    interview_type=interview_type,
                    target_company=target_company,
                    jd_content=jd_content,
                )
        except Exception:
            evaluation = None

        return {
            "response": response_text,
            "evaluation": evaluation.model_dump() if evaluation else None,
            "is_finished": False,
        }
