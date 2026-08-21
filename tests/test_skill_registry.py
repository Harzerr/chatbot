import asyncio
from types import SimpleNamespace

from app.services.career_studio import CareerStudioService
from app.services.skill_registry import SkillResult, create_default_skill_registry


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
