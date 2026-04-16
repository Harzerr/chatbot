from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.schemas.chat import AnswerEvaluation
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class InterviewEvaluator:
    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )

    def should_evaluate(self, user_answer: str, previous_question: str | None) -> bool:
        normalized = user_answer.strip().lower()
        if not previous_question:
            return False
        if normalized in {"开始面试", "开始", "继续", "开始吧", "可以开始了"}:
            return False
        return len(user_answer.strip()) >= 12

    def _is_coding_question(self, previous_question: str, user_answer: str) -> bool:
        combined = f"{previous_question}\n{user_answer}".lower()
        markers = (
            "手撕代码",
            "代码题",
            "写出核心代码",
            "贴出你的代码",
            "时间复杂度",
            "空间复杂度",
            "实现一个",
            "```",
            "#include",
            "class ",
            "def ",
            "function ",
        )
        return any(marker in combined for marker in markers)

    async def evaluate_answer(
        self,
        previous_question: str,
        user_answer: str,
        interview_role: str | None,
        interview_level: str | None,
        interview_type: str | None,
        target_company: str | None = None,
        jd_content: str | None = None,
    ) -> AnswerEvaluation:
        role = interview_role or "通用软件工程师"
        level = interview_level or "中级"
        interview_kind = interview_type or "技术面"
        company = target_company or "未指定"
        jd = jd_content or "未提供"
        is_coding_question = self._is_coding_question(previous_question, user_answer)
        coding_rules = """
        这是代码题评估，请额外重点检查：
        - 思路是否成立，是否命中正确的数据结构或算法方向
        - 代码或伪代码是否自洽，关键流程能否跑通
        - 时间复杂度和空间复杂度是否合理
        - 是否覆盖边界条件、异常输入、空值、重复值、越界等情况
        - 命名、结构、鲁棒性和可维护性是否达到面试可接受水平
        - 如果候选人只讲思路没写代码，也要判断思路是否足够落地
        """ if is_coding_question else ""

        prompt = f"""
        你是一名严格、专业、客观的技术面试评估官。请根据下面的面试问题和候选人回答进行结构化评分。

        面试岗位：{role}
        面试级别：{level}
        面试类型：{interview_kind}
        目标公司：{company}
        岗位 JD：
        {jd[:3000]}

        面试问题：
        {previous_question}

        候选人回答：
        {user_answer}

        请输出结构化评估，遵循这些规则：
        - 所有分数范围为 0 到 100
        - verdict 只能是：正确、部分正确、错误
        - 如果这是八股题、原理题、场景题或手撕代码题，都要明确判断候选人的回答是否答对核心点
        - correctness_summary：一句话说明为什么判定为正确/部分正确/错误
        - error_analysis：如果回答有问题，列出 2 到 4 条错误点、遗漏点或不严谨之处；不要写空话，要指出具体缺少了什么
        - expected_key_points：给出这道题标准答案应该覆盖的关键点，2 到 5 条
        - correction_suggestion：如果回答不够好，给出更专业的修正建议；如果回答较好，可以给出如何答得更像高水平候选人的建议
        - technical_accuracy：技术内容是否正确、是否有明显事实错误
        - knowledge_depth：是否体现原理理解、工程深度、上下文判断
        - communication_clarity：表达是否清晰、易懂、无明显混乱
        - logical_structure：回答是否有结构、有层次、有主线
        - problem_solving：是否体现分析、取舍、定位问题和决策能力
        - job_match_score：候选人回答与目标岗位/JD/公司要求的匹配度；如果 JD 未提供，则结合岗位、级别和面试类型判断
        - overall_score：综合评分，不要简单平均，要结合岗位和级别判断
        - summary：1 到 2 句话概括本轮回答表现
        - strengths：列出 2 到 4 条亮点
        - improvement_areas：列出 2 到 4 条主要改进点

        评分要严格，避免虚高。如果回答过于空泛、偏题、没有落到真实项目细节，或手撕代码思路不成立，应明显扣分。
        不要因为候选人说了很多字就给高分。内容密度、准确性、证据链、细节完整度，比篇幅更重要。
        如果候选人只是说了正确方向，但没有给出关键机制、边界条件、工程细节或判断依据，应判为“部分正确”而不是“正确”。
        如果候选人的回答与目标岗位/JD要求弱相关、没有体现岗位要求中的关键能力或项目证据，job_match_score 和 overall_score 都要明显扣分。
        如果面试问题属于算法/手撕代码，请重点检查：
        - 是否识别核心数据结构与算法思路
        - 时间复杂度和空间复杂度是否合理
        - 边界条件是否覆盖
        - 伪代码/代码逻辑是否能成立
        {coding_rules}
        """

        chain = self.llm.with_structured_output(AnswerEvaluation)
        result = await chain.ainvoke(prompt)
        return result
