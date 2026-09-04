import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_vector_store
from app.db.session import get_db
from app.models.career import CareerFact, JobPosting
from app.models.training import TrainingAttempt, TrainingItem
from app.services.role_question_bank_loader import load_role_question_bank
from app.agent.evaluation_agent import EvaluationAgent

router = APIRouter()


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)


class StatusRequest(BaseModel):
    status: str = Field(pattern="^(active|mastered|snoozed|archived)$")


class PlanRequest(BaseModel):
    job_id: int | None = None


def _item_response(item: TrainingItem) -> dict:
    try:
        focus = json.loads(item.focus_json or "[]")
    except json.JSONDecodeError:
        focus = []
    return {
        "id": item.id, "source_type": item.source_type, "source_label": item.source_label,
        "question": item.question, "focus_points": focus, "reference_answer": item.reference_answer,
        "original_answer": item.original_answer, "priority": item.priority, "status": item.status,
        "attempts": item.attempts, "last_score": item.last_score, "due_at": item.due_at, "job_id": item.job_id,
        "created_at": item.created_at, "updated_at": item.updated_at,
    }


def _fact_question(fact: CareerFact) -> tuple[str, list[str], str]:
    title = fact.title
    if fact.fact_type in {"project", "experience"}:
        return (
            f"请围绕「{title}」完整说明背景、你的个人职责、关键技术选择、遇到的难点，以及可量化的结果。",
            ["背景与目标", "个人贡献", "技术决策", "难点与解决", "结果量化"],
            "按背景、任务、行动、结果展开；清楚区分团队成果和个人贡献，并用事实或指标支撑。",
        )
    if fact.fact_type == "skill":
        return (
            f"简历中写到「{title}」，请说明你在哪个真实项目或任务中使用过它、为什么这样选，以及如何验证效果。",
            ["真实使用场景", "核心原理", "技术取舍", "效果验证"],
            "先说明业务场景，再解释关键原理和具体做法，最后给出效果、边界或复盘。",
        )
    if fact.fact_type in {"award", "certificate"}:
        return (
            f"请介绍「{title}」的获得背景、评选或考核要求、你完成的工作/作品，以及这项成果能证明什么能力。",
            ["获得背景", "评选或考核要求", "个人工作或作品", "可验证成果", "能力沉淀"],
            "说明奖项或证书的来源与规则，重点讲你完成的实际工作、可核验结果，以及它与应聘岗位的关联。",
        )
    if fact.fact_type == "language":
        return (
            f"简历中写到「{title}」，请说明你的具体水平、真实使用场景，以及它如何支持学习、协作或工作交付。",
            ["具体水平", "真实使用场景", "产出或证明", "岗位关联"],
            "避免只报分数；用阅读资料、技术沟通、文档写作或项目实践说明实际能力。",
        )
    if fact.fact_type == "education":
        return (
            f"请结合「{title}」说明一段与目标岗位最相关的学习经历、你解决过的问题，以及形成了哪些可迁移能力。",
            ["学习内容", "实践或问题", "方法与结果", "岗位关联"],
            "把教育经历转化为能力证据，避免只复述学校、专业或课程名称。",
        )
    return (
        f"请展开说明简历中的「{title}」：它的背景是什么、你在其中的角色或投入是什么，以及能提供哪些事实证据。",
        ["背景", "个人角色", "事实证据", "能力关联"],
        "围绕可验证事实说明背景、个人参与和结果，明确它与目标岗位的关系。",
    )


def _score(answer: str, focus_points: list[str]) -> tuple[float, str]:
    normalized = answer.lower()
    hit = [point for point in focus_points if point.lower() in normalized]
    score = min(100.0, round(42 + min(len(answer.strip()) / 4, 30) + len(hit) * 7, 1))
    missing = [point for point in focus_points if point not in hit]
    feedback = "回答已覆盖：" + ("、".join(hit) if hit else "尚未识别到明确考察点")
    if missing:
        feedback += "。下次补充：" + "、".join(missing[:3])
    return score, feedback


@router.get("/items")
async def list_items(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user),
):
    rows = await db.scalars(
        select(TrainingItem).where(TrainingItem.user_id == current_user.id).order_by(
            TrainingItem.status.asc(), TrainingItem.priority.desc(), TrainingItem.updated_at.desc()
        )
    )
    return [_item_response(item) for item in rows.all()]


@router.post("/plans/default", status_code=status.HTTP_201_CREATED)
async def create_default_plan(
    payload: PlanRequest,
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user), vector_store=Depends(get_vector_store),
):
    facts = (await db.scalars(select(CareerFact).where(
        CareerFact.user_id == current_user.id, CareerFact.is_archived.is_(False)
    ).order_by(CareerFact.updated_at.desc()))).all()
    jobs = (await db.scalars(select(JobPosting).where(JobPosting.user_id == current_user.id).order_by(JobPosting.updated_at.desc()))).all()
    job = next((item for item in jobs if item.id == payload.job_id), None) if payload.job_id else (jobs[0] if jobs else None)
    if payload.job_id and not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    role = current_user.target_role or (job.title if job else "通用软件工程师")
    bank = [entry for entry in load_role_question_bank() if entry.get("role") == role] or load_role_question_bank()
    normalized = json.loads(job.normalized_json or "{}") if job else {}
    keywords = [str(value).lower() for value in (normalized.get("required_skills", []) + normalized.get("preferred_skills", []))]
    bank.sort(key=lambda entry: sum(word in (entry["question"] + " ".join(entry.get("focus_points", []))).lower() for word in keywords), reverse=True)
    existing_questions = set((await db.scalars(select(TrainingItem.question).where(TrainingItem.user_id == current_user.id, TrainingItem.status != "archived"))).all())
    created: list[TrainingItem] = []

    def add(source_type, source_ref, label, question, focus, framework, original="", priority=50):
        if question in existing_questions:
            return
        item = TrainingItem(user_id=current_user.id, source_type=source_type, source_ref=source_ref,
            source_label=label, question=question, focus_json=json.dumps(focus, ensure_ascii=False),
            reference_answer=framework, original_answer=original, priority=priority, job_id=job.id if job else None)
        db.add(item); created.append(item)

    # 4 resume/fact questions.
    for fact in facts[:4]:
        question, focus, framework = _fact_question(fact)
        add("resume", str(fact.id), f"简历事实 · {fact.title}", question, focus, framework, priority=85)

    # 2 real interviewer questions from prior mock interviews.
    history = vector_store.get_chats_by_user_id(str(current_user.id), current_user.tenant_id, limit=200, offset=0)
    history.sort(key=lambda item: item.get("timestamp", ""))
    pending = ""
    for msg in history:
        answer = (msg.get("user_message") or "").strip()
        if pending and answer and len(created) < 6:
            evaluation = msg.get("evaluation") or {}
            focus = evaluation.get("expected_key_points") or ["回答结构", "技术准确性", "岗位匹配"]
            framework = evaluation.get("correction_suggestion") or "结合反馈重新组织答案，先说明结论，再给出依据和结果。"
            add("interview", msg.get("chat_id"), "模拟面试复盘 · 面试官真实提问", pending, focus, framework, answer, priority=95)
        if msg.get("assistant_message"):
            pending = msg["assistant_message"].strip()
        if len(created) >= 6:
            break

    # 3 JD-related new questions and exactly 1 role-general challenge; use role bank, never old user answers.
    for index, entry in enumerate(bank):
        if sum(1 for item in created if item.source_type in {"jd", "general"}) >= 4:
            break
        source_type = "general" if index == 3 else "jd"
        label = "岗位通用挑战" if source_type == "general" else f"目标 JD 新题 · {job.title if job else role}"
        add(source_type, None, label, entry["question"], entry.get("focus_points", []), entry.get("answer_framework", ""), priority=70 if source_type == "general" else 78)

    await db.commit()
    for item in created:
        await db.refresh(item)
    return {"items": [_item_response(item) for item in created], "distribution": {"resume": min(4, len(facts)), "interview": sum(1 for x in created if x.source_type == "interview"), "jd": 3, "general": 1}}


@router.post("/items/{item_id}/answer")
async def answer_item(item_id: int, payload: AnswerRequest, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    item = await db.scalar(select(TrainingItem).where(TrainingItem.id == item_id, TrainingItem.user_id == current_user.id))
    if not item: raise HTTPException(status_code=404, detail="Training item not found")
    focus = json.loads(item.focus_json or "[]")
    job = await db.scalar(select(JobPosting).where(JobPosting.id == item.job_id, JobPosting.user_id == current_user.id)) if item.job_id else None
    try:
        evaluation = await EvaluationAgent().evaluate_answer(item.question, payload.answer, current_user.target_role, None, "训练", job.company if job else None, job.raw_content if job else None)
        evaluation_data = evaluation.model_dump()
        score = evaluation.overall_score
        feedback = f"{evaluation.correctness_summary} {evaluation.correction_suggestion or evaluation.summary}"
    except Exception:
        score, feedback = _score(payload.answer, focus)
        evaluation_data = {}
    db.add(TrainingAttempt(training_item_id=item.id, user_id=current_user.id, answer=payload.answer.strip(), score=score, feedback=feedback, evaluation_json=json.dumps(evaluation_data, ensure_ascii=False)))
    item.attempts += 1; item.last_score = score
    await db.commit(); await db.refresh(item)
    return {"item": _item_response(item), "score": score, "feedback": feedback}


@router.patch("/items/{item_id}/status")
async def update_item_status(item_id: int, payload: StatusRequest, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    item = await db.scalar(select(TrainingItem).where(TrainingItem.id == item_id, TrainingItem.user_id == current_user.id))
    if not item: raise HTTPException(status_code=404, detail="Training item not found")
    item.status = payload.status
    item.due_at = datetime.utcnow() + timedelta(days=3) if payload.status == "snoozed" else None
    await db.commit(); await db.refresh(item)
    return _item_response(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await db.execute(delete(TrainingAttempt).where(TrainingAttempt.training_item_id == item_id, TrainingAttempt.user_id == current_user.id))
    result = await db.execute(delete(TrainingItem).where(TrainingItem.id == item_id, TrainingItem.user_id == current_user.id))
    if not result.rowcount: raise HTTPException(status_code=404, detail="Training item not found")
    await db.commit()
