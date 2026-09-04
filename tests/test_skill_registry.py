import asyncio
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from app.services.career_studio import CareerStudioService
from app.services.skill_registry import (
    LazySkillRunner,
    SkillResult,
    SkillRunner,
    create_default_skill_registry,
)


class RecordingLLM:
    def __init__(self, content: str = '{"facts": []}') -> None:
        self.content = content
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        self.prompts.append(str(messages[0].content))
        return SimpleNamespace(content=self.content)


def test_resume_optimizer_is_registered_from_skill_frontmatter():
    llm = RecordingLLM()
    registry = create_default_skill_registry(llm, skill_names={"resume-project-extractor"})

    definition = registry.get("resume-project-extractor")

    assert definition is not None
    assert definition.agent_name == "ResumeOptimizer"
    assert definition.skill_dir.name == "resume-optimizer-skill"
    assert isinstance(definition.runner, LazySkillRunner)
    assert definition.runner.is_loaded is False


def test_resume_optimizer_runs_through_registry_and_injects_instructions():
    llm = RecordingLLM()
    registry = create_default_skill_registry(llm, skill_names={"resume-project-extractor"})

    result = asyncio.run(
        registry.run(
            "resume-project-extractor",
            {"prompt": "只返回 JSON，提炼这个项目：处理任务队列。"},
        )
    )

    assert result.agent_name == "ResumeOptimizer"
    assert result.response == '{"facts": []}'
    assert len(llm.prompts) == 1
    assert "简历优化 Skill 指令" in llm.prompts[0]
    assert "Resume Project Extractor" in llm.prompts[0]
    assert "运行时输出 Schema" in llm.prompts[0]


def test_career_studio_uses_registry_for_markdown_json_invocation():
    class RecordingRegistry:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def run(self, name, state, **options):
            self.calls.append((name, state, options))
            return SkillResult(response='{"facts": []}', agent_name="ResumeOptimizer")

    service = CareerStudioService.__new__(CareerStudioService)
    service._skill_registry = RecordingRegistry()
    service._llm = None
    service._model = "test-model"
    service._resume_llm = None

    result = asyncio.run(service._invoke_json("提炼项目内容", skill_name="resume-project-extractor"))

    assert result == {"facts": []}
    assert service._skill_registry.calls == [
        ("resume-project-extractor", {"prompt": "提炼项目内容"}, {})
    ]


def _write_instruction_skill(
    root,
    *,
    directory: str = "runtime-skill",
    name: str = "runtime-skill",
    version: str = "v1",
    chat_enabled: bool = True,
):
    skill_dir = root / directory
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Runtime test skill {version}",
                "triggers: runtime test, 动态技能",
                f"chat-enabled: {'true' if chat_enabled else 'false'}",
                "agent-name: RuntimeAgent",
                "---",
                f"# Runtime Skill {version}",
                "Return the requested result without adding unrelated content.",
            ]
        ),
        encoding="utf-8",
    )
    return skill_dir


def test_registry_hot_add_update_and_remove_instruction_skill(tmp_path):
    llm = RecordingLLM(content="runtime-result")
    registry = create_default_skill_registry(
        llm,
        root=tmp_path,
        refresh_interval_seconds=3600,
    )
    assert registry.list() == []

    skill_dir = _write_instruction_skill(tmp_path, version="v1")
    first_definition = registry.get("runtime-skill")
    assert first_definition is not None
    assert isinstance(first_definition.runner, LazySkillRunner)
    assert first_definition.runner.is_loaded is False

    first_result = asyncio.run(registry.run("runtime-skill", {"prompt": "run it"}))
    assert first_result.response == "runtime-result"
    assert first_result.agent_name == "RuntimeAgent"
    assert first_definition.runner.is_loaded is True
    assert "Runtime Skill v1" in llm.prompts[-1]

    _write_instruction_skill(tmp_path, version="v2")
    assert registry.refresh(force=True) is True
    second_definition = registry.get("runtime-skill")
    assert second_definition is not None
    assert second_definition is not first_definition
    assert isinstance(second_definition.runner, LazySkillRunner)
    assert second_definition.runner.is_loaded is False

    asyncio.run(registry.run("runtime-skill", {"prompt": "run it again"}))
    assert "Runtime Skill v2" in llm.prompts[-1]

    (skill_dir / "SKILL.md").unlink()
    assert registry.refresh(force=True) is True
    assert registry.get("runtime-skill") is None


def test_registry_dynamically_routes_chat_enabled_skills(tmp_path):
    llm = RecordingLLM(content="ok")
    registry = create_default_skill_registry(
        llm,
        root=tmp_path,
        chat_only=True,
        refresh_interval_seconds=0,
    )
    _write_instruction_skill(tmp_path, name="chat-skill", directory="chat")
    _write_instruction_skill(
        tmp_path,
        name="workflow-skill",
        directory="workflow",
        chat_enabled=False,
    )

    resolved = registry.resolve({"messages": [HumanMessage(content="请执行动态技能")]})

    assert resolved is not None
    assert resolved.name == "chat-skill"
    assert registry.get("workflow-skill") is None


def test_lazy_runner_initializes_once_under_concurrency():
    load_count = 0

    class CountingRunner(SkillRunner):
        async def run(self, state):
            await asyncio.sleep(0)
            return SkillResult(response=str(state["value"]), agent_name="Counting")

    def load_runner():
        nonlocal load_count
        load_count += 1
        return CountingRunner()

    runner = LazySkillRunner(load_runner)

    async def invoke_twice():
        return await asyncio.gather(
            runner.run({"value": 1}),
            runner.run({"value": 2}),
        )

    results = asyncio.run(invoke_twice())

    assert load_count == 1
    assert [result.response for result in results] == ["1", "2"]
