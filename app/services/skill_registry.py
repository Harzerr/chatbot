import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from langchain_core.messages import BaseMessage

from app.services.interview_evaluator import InterviewEvaluator
from app.services.interview_skill import InterviewSkill
from app.services.coding_knowledge_store import QdrantCodingKnowledgeStore
from app.services.role_knowledge_store import QdrantRoleKnowledgeStore
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SkillResult:
    response: str
    agent_name: str
    evaluation: dict | None = None
    is_finished: bool = False


class SkillRunner:
    async def run(self, state: Mapping[str, Any]) -> SkillResult:
        raise NotImplementedError


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    triggers: tuple[str, ...]
    skill_dir: Path


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    agent_name: str
    description: str
    triggers: tuple[str, ...]
    runner: SkillRunner
    skill_dir: Path


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        self._skills[definition.name] = definition

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def resolve(self, state: Mapping[str, Any]) -> SkillDefinition | None:
        active_skill = state.get("active_skill")
        if isinstance(active_skill, str) and active_skill:
            return self.get(active_skill)

        # Backward-compatible bridge for the existing interview_mode flag.
        if state.get("interview_mode"):
            return self.get("interview-skills")

        latest_message = _latest_message_text(state).lower()
        if not latest_message:
            return None

        for definition in self._skills.values():
            if any(trigger.lower() in latest_message for trigger in definition.triggers):
                return definition
        return None

    def available_skills_prompt(self) -> str:
        if not self._skills:
            return "No registered skills."
        return "\n".join(
            f"- {skill.name}: {skill.description} Trigger examples: {', '.join(skill.triggers[:5])}"
            for skill in self._skills.values()
        )


class InterviewSkillRunner:
    def __init__(
        self,
        llm,
        evaluator: InterviewEvaluator | None = None,
        role_knowledge_store: QdrantRoleKnowledgeStore | None = None,
    ) -> None:
        resolved_role_knowledge_store = role_knowledge_store
        if resolved_role_knowledge_store is None:
            resolved_role_knowledge_store = _load_optional_dependency(
                "role knowledge store",
                QdrantRoleKnowledgeStore,
            )

        resolved_coding_knowledge_store = _load_optional_dependency(
            "coding knowledge store",
            QdrantCodingKnowledgeStore,
        )

        self._skill = InterviewSkill(
            llm,
            evaluator or InterviewEvaluator(),
            resolved_role_knowledge_store,
            resolved_coding_knowledge_store,
        )

    async def run(self, state: Mapping[str, Any]) -> SkillResult:
        result = await self._skill.run(
            question=_latest_message_text(state),
            previous_interviewer_question=state.get("previous_interviewer_question"),
            relevant_docs=state.get("relevant_docs", []),
            context=state.get("context", ""),
            interview_role=state.get("interview_role"),
            interview_level=state.get("interview_level"),
            interview_type=state.get("interview_type"),
            target_company=state.get("target_company"),
            jd_content=state.get("jd_content"),
            resume_content=state.get("resume_content"),
        )
        return SkillResult(
            response=result["response"],
            agent_name="Interviewer",
            evaluation=result.get("evaluation"),
            is_finished=result.get("is_finished", False),
        )


RunnerFactory = Callable[[Any, SkillSpec], SkillDefinition]


def _load_optional_dependency(name: str, factory: Callable[[], Any]) -> Any | None:
    try:
        return factory()
    except Exception as exc:
        logger.warning(
            "Interview skill %s is unavailable during startup; falling back to local context only: %s",
            name,
            exc,
        )
        return None


def create_default_skill_registry(llm) -> SkillRegistry:
    registry = SkillRegistry()
    runner_factories = build_runner_factories()

    for skill_spec in discover_skill_specs():
        factory = runner_factories.get(skill_spec.name)
        if factory is None:
            logger.warning(
                "Discovered skill '%s' at %s but no runner factory is registered for it yet",
                skill_spec.name,
                skill_spec.skill_dir,
            )
            continue

        definition = factory(llm, skill_spec)
        registry.register(definition)
        logger.info("Registered skill '%s' from %s", definition.name, definition.skill_dir)

    return registry


def build_runner_factories() -> dict[str, RunnerFactory]:
    return {
        "interview-skills": _build_interview_skill_definition,
    }


def discover_skill_specs(root: Path = PROJECT_ROOT) -> list[SkillSpec]:
    skill_specs: list[SkillSpec] = []

    for skill_md in sorted(root.glob("*/SKILL.md")):
        skill_dir = skill_md.parent
        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read skill file %s: %s", skill_md, exc)
            continue

        frontmatter, body = _split_frontmatter(content)
        name = (frontmatter.get("name") or skill_dir.name).strip()
        description = (frontmatter.get("description") or "").strip() or f"{name} skill"
        triggers = _extract_triggers(frontmatter, body)

        skill_specs.append(
            SkillSpec(
                name=name,
                description=description,
                triggers=triggers,
                skill_dir=skill_dir,
            )
        )

    return skill_specs


def _build_interview_skill_definition(llm, spec: SkillSpec) -> SkillDefinition:
    return SkillDefinition(
        name=spec.name,
        agent_name="Interviewer",
        description=spec.description,
        triggers=spec.triggers or (
            "模拟面试",
            "大厂面试",
            "面试官",
            "帮我面试",
            "面试准备",
            "interview practice",
            "mock interview",
        ),
        runner=InterviewSkillRunner(llm),
        skill_dir=spec.skill_dir,
    )


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    stripped = content.lstrip()
    if not stripped.startswith("---\n"):
        return {}, content

    parts = stripped.split("---\n", 2)
    if len(parts) < 3:
        return {}, content

    _, frontmatter_block, body = parts
    return _parse_simple_frontmatter(frontmatter_block), body


def _parse_simple_frontmatter(block: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _extract_triggers(frontmatter: Mapping[str, str], body: str) -> tuple[str, ...]:
    candidates: list[str] = []

    description = frontmatter.get("description", "")
    candidates.extend(_extract_quoted_phrases(description))

    trigger_section_match = re.search(
        r"##\s*触发条件(?P<section>.*?)(?:\n##\s+|\Z)",
        body,
        flags=re.DOTALL,
    )
    if trigger_section_match:
        trigger_section = trigger_section_match.group("section")
        candidates.extend(_extract_quoted_phrases(trigger_section))
        for line in trigger_section.splitlines():
            cleaned = line.strip().lstrip("-").strip()
            if cleaned:
                candidates.extend([part.strip() for part in cleaned.split("/") if part.strip()])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate).strip("`*[]() ")
        if len(cleaned) < 2:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cleaned)

    return tuple(deduped)


def _extract_quoted_phrases(text: str) -> list[str]:
    matches = re.findall(r'"([^"]+)"|“([^”]+)”|\'([^\']+)\'', text)
    phrases: list[str] = []
    for match in matches:
        if isinstance(match, tuple):
            phrases.extend([part for part in match if part])
        elif match:
            phrases.append(match)
    return phrases


def _latest_message_text(state: Mapping[str, Any]) -> str:
    messages = state.get("messages") or []
    if not messages:
        return ""

    latest = messages[-1]
    if isinstance(latest, BaseMessage):
        return str(latest.content)
    return str(getattr(latest, "content", latest))
