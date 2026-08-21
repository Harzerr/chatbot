import asyncio
import json
from pathlib import Path

from app.services.career_studio import CareerStudioService, build_role_variants, infer_industrial_roles, sanitize_resume_content, select_role_variant
import pytest


TECHNICAL_DOCUMENT = """# 智能分拣平台

## 项目概述
面向仓储场景建设智能分拣平台，负责后端服务和任务数据链路设计。

## 技术栈
FastAPI、Python、PostgreSQL、Redis、Qdrant

## 核心实现
- 设计 FastAPI 接口接收订单和设备状态，使用 PostgreSQL 保存业务数据。
- 通过 Redis 队列异步处理分拣任务，并为失败任务增加重试和超时兜底。
  将任务状态写回数据库，便于前端查询处理结果。
- 使用 Qdrant 召回相似商品信息，结合元数据过滤减少无关结果。
- 编写接口测试和异常场景测试，验证任务路由、重试和数据一致性。

## 我的角色
负责后端开发与部署。
"""


def test_fallback_keeps_markdown_bullets_and_separates_tech_stack():
    fact = CareerStudioService._fallback_markdown_fact(TECHNICAL_DOCUMENT, "demo.md")
    content = fact["content"]

    assert fact["title"] == "智能分拣平台"
    assert content["role"] == "负责后端开发与部署。"
    assert len(content["highlights"]) == 4
    assert "将任务状态写回数据库" in content["highlights"][1]
    assert content["tech_stack"] == ["FastAPI", "Python", "PostgreSQL", "Redis", "Qdrant"]
    assert content["industrial_roles"] == []
    assert content["role_variants"] == []
    assert all(not item.startswith("围绕") for item in content["highlights"])
    assert len(content["evidence_map"]) == len(content["highlights"])


def test_project_extractor_contract_adapts_multiple_evidence_chunks_to_career_fact():
    extractor_input = {
        "document_id": "source:test",
        "project_mode": "single_project",
        "chunks": [
            {"chunk_id": "source:test:0", "text": "针对目录层级不固定的问题，递归查找 DLT 压缩包中的日志。"},
            {"chunk_id": "source:test:1", "text": "从日志中提取收敛状态，并写入结构化结果。"},
        ],
    }
    payload = {
        "document_id": "source:test",
        "projects": [{
            "project_id": "p1",
            "project_name": "标定回放平台",
            "summary": "建设标定数据回放与结果解析平台。",
            "engineering_challenge": "输入目录层级不固定。",
            "design_rationale": "采用递归查找降低输入结构约束。",
            "tech_stack": ["Python", "DLT"],
            "key_points": [{
                "point_id": "p1-k1",
                "category": "data_processing",
                "title": "DLT 结果解析",
                "normalized_fact": "递归查找日志并提取收敛状态。",
                "resume_bullet": "针对 DLT 压缩包目录层级不固定的问题，递归查找日志并提取收敛状态，写入结构化结果。",
                "confidence": "high",
                "evidence_chunks": [
                    {"chunk_id": "source:test:0", "quote": "针对目录层级不固定的问题，递归查找 DLT 压缩包中的日志。", "support": "说明输入处理机制。"},
                    {"chunk_id": "source:test:1", "quote": "从日志中提取收敛状态，并写入结构化结果。", "support": "说明结果字段和持久化动作。"},
                ],
            }],
        }],
    }

    adapted, warnings = CareerStudioService._adapt_project_extraction_payload(payload, extractor_input)
    content = adapted["facts"][0]["content"]

    assert not warnings
    assert content["highlights"] == [payload["projects"][0]["key_points"][0]["resume_bullet"]]
    assert content["evidence_map"][0]["source_chunk_ids"] == ["source:test:0", "source:test:1"]
    assert len(content["evidence_map"][0]["source_quotes"]) == 2


def test_project_extractor_contract_rejects_unknown_or_inexact_evidence():
    extractor_input = {
        "document_id": "source:test",
        "project_mode": "single_project",
        "chunks": [{"chunk_id": "source:test:0", "text": "实现路径记录。"}],
    }
    payload = {
        "projects": [{
            "project_name": "路径项目",
            "key_points": [{
                "normalized_fact": "实现路径记录。",
                "resume_bullet": "实现路径记录。",
                "evidence_chunks": [{"chunk_id": "missing", "quote": "实现路径记录。", "support": ""}],
            }],
        }],
    }

    with pytest.raises(ValueError, match="不存在的 chunk_id"):
        CareerStudioService._adapt_project_extraction_payload(payload, extractor_input)


def test_extraction_windows_remap_evidence_to_canonical_chunks():
    markdown = "\n\n".join(
        f"## 模块 {index}\n针对边界 {index}，使用处理器 {index} 完成状态校验和结果保存。"
        for index in range(30)
    )
    extractor_input = CareerStudioService._build_project_extractor_input(
        markdown,
        "platform.md",
        True,
    )
    canonical_chunks = extractor_input["_canonical_chunks"]
    target_chunk = canonical_chunks[5]
    quote = f"针对边界 5，使用处理器 5 完成状态校验和结果保存。"
    window = next(item for item in extractor_input["chunks"] if quote in item["text"])
    payload = {
        "projects": [{
            "project_id": "p1",
            "project_name": "平台项目",
            "key_points": [{
                "point_id": "p1-k1",
                "category": "implementation",
                "title": "边界处理",
                "normalized_fact": quote,
                "resume_bullet": "针对边界状态不一致问题，通过处理器完成校验并保存结果。",
                "confidence": "high",
                "evidence_chunks": [{
                    "chunk_id": window["chunk_id"],
                    "quote": quote,
                    "support": "证明校验与保存机制。",
                }],
            }],
        }],
    }

    adapted, _ = CareerStudioService._adapt_project_extraction_payload(payload, extractor_input)
    evidence = adapted["facts"][0]["content"]["evidence_map"][0]

    assert len(extractor_input["chunks"]) < len(canonical_chunks)
    assert evidence["source_chunk_ids"] == [target_chunk["chunk_id"]]


def test_extraction_uses_exact_quote_when_model_selects_wrong_window():
    markdown = "\n\n".join(
        f"## 模块 {index}\n针对边界 {index}，使用处理器 {index} 完成状态校验和结果保存。"
        for index in range(120)
    )
    extractor_input = CareerStudioService._build_project_extractor_input(markdown, "platform.md", True)
    quote = "针对边界 119，使用处理器 119 完成状态校验和结果保存。"
    correct_window = next(item for item in extractor_input["chunks"] if quote in item["text"])
    wrong_window = next(item for item in extractor_input["chunks"] if item["chunk_id"] != correct_window["chunk_id"])
    payload = {
        "projects": [{
            "project_id": "p1",
            "project_name": "平台项目",
            "key_points": [{
                "resume_bullet": "针对状态边界问题，使用处理器完成校验并保存结果。",
                "confidence": "high",
                "evidence_chunks": [{
                    "chunk_id": wrong_window["chunk_id"],
                    "quote": quote,
                    "support": "证明边界处理机制。",
                }],
            }],
        }],
    }

    adapted, warnings = CareerStudioService._adapt_project_extraction_payload(payload, extractor_input)
    evidence = adapted["facts"][0]["content"]["evidence_map"][0]

    assert not warnings
    assert evidence["source_chunk_ids"] == [extractor_input["_canonical_chunks"][-1]["chunk_id"]]


def test_extraction_recovers_paraphrased_quote_with_lower_confidence():
    markdown = "## 任务链路\n针对压缩包目录层级不固定的问题，递归查找 DLT 日志并提取收敛状态。"
    extractor_input = CareerStudioService._build_project_extractor_input(markdown, "calibration.md", True)
    window = extractor_input["chunks"][0]
    payload = {
        "projects": [{
            "project_id": "p1",
            "project_name": "标定平台",
            "key_points": [{
                "resume_bullet": "针对 DLT 压缩包层级不固定的问题，设计递归检索链路并解析收敛状态。",
                "confidence": "high",
                "evidence_chunks": [{
                    "chunk_id": window["chunk_id"],
                    "quote": "递归处理不同目录中的日志并解析标定结果。",
                    "support": "说明日志解析机制。",
                }],
            }],
        }],
    }

    adapted, warnings = CareerStudioService._adapt_project_extraction_payload(payload, extractor_input)
    evidence = adapted["facts"][0]["content"]["evidence_map"][0]

    assert evidence["source_quote"] == "针对压缩包目录层级不固定的问题，递归查找 DLT 日志并提取收敛状态。"
    assert evidence["confidence"] == 0.65
    assert warnings == ["1 条要点已回对到最相关的原文证据，请重点核对。"]


def test_markdown_extraction_uses_registry_and_preserves_skill_bullets(monkeypatch):
    markdown = "# 路径记录模块\n\n按定位结果计算并保存路径点。"
    extractor_input = CareerStudioService._build_project_extractor_input(
        markdown,
        "path.md",
        True,
        {"title": "用户填写的路径项目", "period": "2025"},
    )
    chunk = extractor_input["chunks"][0]

    class RecordingSkillRegistry:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def run(self, name, state, **options):
            self.calls.append((name, state, options))
            return type("Result", (), {
                "response": json.dumps({
                    "document_id": extractor_input["document_id"],
                    "projects": [{
                        "project_id": "p1",
                        "project_name": "路径记录模块",
                        "summary": "实现路径记录。",
                        "key_points": [{
                            "point_id": "p1-k1",
                            "category": "implementation",
                            "title": "记录路径",
                            "normalized_fact": "记录路径点。",
                            "resume_bullet": "针对路径点需要连续记录的问题，按定位结果计算并保存路径点，完成路径数据链路。",
                            "confidence": "high",
                            "evidence_chunks": [{
                                "chunk_id": chunk["chunk_id"],
                                "quote": "按定位结果计算并保存路径点。",
                                "support": "说明路径点处理机制。",
                            }],
                        }],
                    }],
                }, ensure_ascii=False),
            })()

    service = CareerStudioService.__new__(CareerStudioService)
    service._skill_registry = RecordingSkillRegistry()
    service._llm = None
    service._model = "test-model"
    resume_llm = object()
    service._resume_llm = resume_llm
    monkeypatch.setattr(
        "app.services.career_studio.build_role_variants",
        lambda *_args: [{"role": "后端 / 平台工程师", "summary": "岗位摘要", "highlights": ["岗位改写。"], "evidence_map": []}],
    )

    result = asyncio.run(
        service.extract_fact_from_markdown(
            markdown,
            "path.md",
            project_metadata={"title": "用户填写的路径项目", "period": "2025"},
        )
    )

    assert service._skill_registry.calls[0][0] == "resume-project-extractor"
    prompt = service._skill_registry.calls[0][1]["prompt"]
    assert service._skill_registry.calls[0][2]["llm_override"] is resume_llm
    assert '"project_mode": "single_project"' in prompt
    assert f'"chunk_id": "{chunk["chunk_id"]}"' in prompt
    assert '"_canonical_chunks"' not in prompt
    fact = result["facts"][0]
    assert fact["content"]["highlights"]
    assert fact["content"]["highlights"] == ["针对路径点需要连续记录的问题，按定位结果计算并保存路径点，完成路径数据链路。"]
    assert fact["content"]["role_variants"][0]["highlights"] == ["岗位改写。"]
    assert fact["content"]["evidence_map"][0]["source_chunk_ids"] == [
        extractor_input["_canonical_chunks"][0]["chunk_id"]
    ]


def test_markdown_upload_rejects_non_skill_payload_without_fallback():
    service = CareerStudioService.__new__(CareerStudioService)

    class LegacySkillRegistry:
        async def run(self, _name, _state):
            return type("Result", (), {"response": json.dumps({"facts": [{"title": "旧格式"}]})})()

    service._skill_registry = LegacySkillRegistry()
    service._llm = None
    service._model = "test-model"
    service._resume_llm = None

    with pytest.raises(ValueError, match="未生成可用的项目要点"):
        asyncio.run(service.extract_fact_from_markdown("# 项目\n\n实现接口。", "project.md", allow_fallback=False))


def test_markdown_upload_returns_reviewable_fallback_when_skill_times_out():
    service = CareerStudioService.__new__(CareerStudioService)
    service._skill_registry = None
    service._llm = None
    service._model = "test-model"
    service._resume_llm = None

    async def timed_out_invoke(*_args, **_kwargs):
        raise TimeoutError("model deadline exceeded")

    service._invoke_json = timed_out_invoke
    result = asyncio.run(
        service.extract_fact_from_markdown(
            "# 任务平台\n\n## 核心实现\n\n- 使用任务队列执行后台作业并保存状态。",
            "task-platform.md",
            allow_fallback=True,
        )
    )

    assert result["facts"][0]["content"]["highlights"]
    assert result["_quality"]["used_fallback"] is True
    assert result["_quality"]["requires_review"] is True


def test_role_variant_builder_preserves_evidence_wording_without_technology_rewrites():
    source = {
        "summary": "围绕服务接口与任务数据链路，平台将任务创建、数据回放、标定计算、结果验证、日志解析和报告归档串成后台作业。",
        "highlights": [
            "围绕服务接口与任务数据链路，Django/DRF 在线回放任务接口与数据库模型。",
            "围绕服务接口与任务数据链路，DLT 压缩包上传、解压、递归查找和解析。",
            "围绕服务接口与任务数据链路，从 DLT 中提取传感器安装参数、delta、阈值和收敛状态。",
            "围绕服务接口与任务数据链路，使用 PostgreSQL JSONB 保存半结构化结果。",
            "围绕服务接口与任务数据链路，使用 SQL 和 Superset 制作统计图表。",
            "围绕服务接口与任务数据链路，理解并参与 SWA FSM Agent 的任务调度、回放和结果归档链路。",
        ],
        "industrial_roles": [{"role": "后端 / 平台工程师"}],
    }

    variant = build_role_variants("标定任务回放与结果分析平台", source)[0]

    assert variant["highlights"]
    assert all(not item.startswith("围绕") for item in variant["highlights"])
    assert all("围绕服务接口与任务数据链路" not in item for item in variant["highlights"])
    assert any(item.startswith("Django/DRF 在线回放任务接口") for item in variant["highlights"])
    assert all("设计在线" not in item for item in variant["highlights"])


def test_project_is_mapped_to_enterprise_role_tracks_from_evidence():
    tracks = infer_industrial_roles(
        "标定任务回放平台",
        {
            "summary": "提供 Django 任务接口和 DLT 回放处理",
            "tech_stack": ["Django", "PostgreSQL", "Python", "DLT"],
            "highlights": ["递归解析压缩包并保存 JSONB 结果"],
        },
    )

    roles = [track["role"] for track in tracks]
    assert "后端 / 平台工程师" in roles
    assert "数据处理 / 自动化工具链工程师" in roles
    assert all(track["fit_reason"] and track["evidence"] for track in tracks)
    assert all(0 < track["confidence"] < 1 for track in tracks)


def test_tailoring_selects_role_specific_variant_from_job_requirements():
    variant = select_role_variant(
        {"title": "后端平台工程师", "required_skills": ["Django", "PostgreSQL"]},
        {
            "role_variants": [
                {"role": "车载 C++ / 自动驾驶软件工程师", "summary": "强调状态机", "highlights": ["状态流转"]},
                {"role": "后端 / 平台工程师", "summary": "强调任务接口", "highlights": ["Django 任务接口"]},
            ]
        },
    )

    assert variant["role"] == "后端 / 平台工程师"
    assert variant["highlights"] == ["Django 任务接口。"]


def test_fallback_does_not_infer_projects_from_question_only_headings():
    source = """# 算法实习技术文档

## 实习所在系统解决什么业务问题
## RAPath 如何记录、校验、保存和发送车辆路径
## mutex、atomic 分别保护什么数据
## 路径点如何从定位结果中计算出来
## 倒车偏轨、定位跳变和超长路径如何处理
## OnboardMapping 和地图管理模块如何协同
## Recall/Recompute 集成时为什么会出现头文件冲突
## 标定平台如何创建任务、回放数据、解析 DLT、保存结果和展示报表
"""

    facts = CareerStudioService._fallback_markdown_facts(source, "internship.md")

    assert facts == []


def test_fallback_does_not_turn_resume_metadata_into_project_highlights():
    source = """# 算法实习\n\n> 实习时间：2025.08—2026.03。\n> 技术方向：车载 C++、自动化标定。\n> 主要技术：C++、Python、PostgreSQL。\n\n## 标定平台\n实现平台将任务创建和数据回放串成后台作业。工作内容包括：\n- Django/DRF 在线回放任务接口与数据库模型；\n- 使用 PostgreSQL JSONB 保存半结构化结果；\n"""

    facts = CareerStudioService._fallback_markdown_facts(source, "internship.md")
    highlights = facts[0]["content"]["highlights"]

    assert all("实习时间" not in item and "技术方向" not in item and "主要技术" not in item for item in highlights)
    assert all(not item.startswith("实现>") for item in highlights)
    assert all(not item.endswith("；。") for item in highlights)


def test_markdown_tables_and_document_metadata_do_not_leak_into_resume_highlights():
    source = """# 标定结果分析平台

## 核心实现
| 目标 | 说明 |
| --- | --- |
| 数据可视化 | 通过 Apache Superset 仪表盘展示标定结果趋势 |
覆盖项目: bctpybackend（管理侧 Django 后端）+ swafsmagent（执行侧 HSM Agent）。
文档版本: v1.0。
生成日期: 2026-03-05。
| EOL Delta 计算 | 计算在线标定与出厂基准的角度偏差（roll/pitch/yaw） |
"""

    content = CareerStudioService._fallback_markdown_fact(source, "calibration.md")["content"]
    highlights = content["highlights"]

    assert any("通过 Apache Superset 仪表盘展示标定结果趋势" in item for item in highlights)
    assert any("计算在线标定与出厂基准的角度偏差" in item for item in highlights)
    assert all("|" not in item for item in highlights)
    assert all("覆盖项目" not in item and "文档版本" not in item and "生成日期" not in item for item in highlights)


def test_sanitize_stored_fact_content_cleans_role_variants_and_nested_projects():
    content = sanitize_resume_content(
        {
            "highlights": ["| 目标 | 说明 |", "| --- | --- |", "| 日志解析 | 自动提取 DLT 结果 |", "生成日期: 2026-03-05。"],
            "role_variants": [{"role": "工具链", "highlights": ["| 结果归档 | 写入 PostgreSQL JSONB |"]}],
            "projects": [{"title": "日志解析", "highlights": ["文档版本: v1.0。", "递归查找 DLT 日志"]}],
        },
        "标定平台",
    )

    assert content["highlights"] == ["自动提取 DLT 结果。"]
    assert content["role_variants"][0]["highlights"] == ["写入 PostgreSQL JSONB。"]
    assert content["projects"][0]["highlights"] == ["递归查找 DLT 日志。"]


def test_evidence_alignment_covers_model_rephrasing():
    highlights = ["使用 Redis 队列异步处理分拣任务并增加失败重试"]
    evidence = CareerStudioService._align_evidence_map(highlights, TECHNICAL_DOCUMENT, [])

    assert len(evidence) == 1
    assert evidence[0]["source_quote"] in " ".join(TECHNICAL_DOCUMENT.split())
    assert evidence[0]["confidence"] > 0


def test_tailored_resume_fallback_preserves_fact_structure():
    result = CareerStudioService._fallback_tailored_resume(
        {"title": "后端开发", "summary": "负责服务端开发", "required_skills": ["Python"]},
        [{
            "id": 7,
            "fact_type": "project",
            "title": "任务平台",
            "content": {
                "summary": "建设任务处理平台",
                "engineering_challenge": "任务失败需要重试且状态必须可追踪",
                "design_rationale": "选择 Redis 队列解耦任务创建与异步处理",
                "role": "后端开发",
                "tech_stack": ["FastAPI", "Redis"],
                "highlights": ["使用 Redis 队列处理任务"],
            },
            "evidence": "项目原文",
        }],
    )

    entry = result["sections"][0]["entries"][0]
    assert result["headline"] == "后端开发"
    assert result["sections"][0]["heading"] == "项目经历"
    assert entry["fact_ids"] == [7]
    assert entry["subtitle"] == "后端开发"
    assert entry["engineering_challenge"] == "任务失败需要重试且状态必须可追踪"
    assert entry["design_rationale"] == "选择 Redis 队列解耦任务创建与异步处理"
    assert entry["items"][0]["text"] == "使用 Redis 队列处理任务"
    assert result["match_analysis"]["role_alignment"][0]["fact_id"] == 7


def test_skill_requires_industrial_technical_mechanisms():
    skill = Path("resume-optimizer-skill/SKILL.md").read_text(encoding="utf-8")

    assert "Resume Project Extractor" in skill
    assert "Project -> Key Point -> One or More Evidence Chunks" in skill
    assert "resume_bullet" in skill
    assert "chunk_id" in skill
    assert "industrial" in skill.lower()
