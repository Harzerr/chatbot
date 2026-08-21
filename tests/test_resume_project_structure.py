from app.api.endpoints.career import (
    _enrich_entries_from_evidence,
    _expand_experience_entries,
    _normalize_project_upload_metadata,
)
from app.services.career_fact_jobs import _apply_project_metadata
from app.services.career_studio import CareerStudioService, sanitize_resume_content


def test_project_upload_metadata_is_user_owned_and_overlays_ai_title():
    metadata = _normalize_project_upload_metadata(
        {"title": "车载标定回放平台", "period": "2025.08—2026.03", "company": "示例公司", "role": "算法实习生", "fact_type": "experience"},
        "raw-project.md",
    )
    fact = _apply_project_metadata(
        {
            "fact_type": "project",
            "title": "模型猜测的项目名",
            "content": {"summary": "只保留模型提炼的项目内容", "highlights": ["解析日志。"]},
        },
        metadata,
        {"title": "raw-project"},
    )

    assert fact["title"] == "示例公司"
    assert fact["fact_type"] == "experience"
    assert fact["content"]["period"] == "2025.08—2026.03"
    assert fact["content"]["company"] == "示例公司"
    assert fact["content"]["role"] == "算法实习生"
    assert fact["content"]["metadata_source"] == "user_upload"
    assert fact["content"]["projects"][0]["title"] == "车载标定回放平台"
    assert fact["content"]["projects"][0]["project_key"].startswith("project:")
    assert metadata["project_key"] == fact["content"]["projects"][0]["project_key"]


def test_experience_upload_saves_extracted_content_under_nested_project_highlights():
    fact = _apply_project_metadata(
        {
            "fact_type": "project",
            "title": "模型占位标题",
            "content": {
                "summary": "完成车辆路径记录与回放链路。",
                "engineering_challenge": "定位跳变会污染路径状态。",
                "design_rationale": "通过状态机隔离异常分支。",
                "role_variants": [{"role": "车载 C++", "highlights": ["使用 mutex 保护共享路径状态。"]}],
                "tech_stack": ["C++", "mutex"],
                "highlights": ["使用 mutex 保护共享路径状态。"],
                "evidence_map": [{"claim": "使用 mutex 保护共享路径状态。"}],
            },
            "tags": ["项目经历"],
            "evidence": "原始技术文档",
        },
        {
            "title": "RAPath 路径记录与回放",
            "period": "2025.08—2026.03",
            "company": "示例公司",
            "role": "算法实习生",
            "fact_type": "experience",
        },
        {"title": "RAPath"},
    )

    project = fact["content"]["projects"][0]
    assert fact["fact_type"] == "experience"
    assert fact["title"] == "示例公司"
    assert fact["content"]["period"] == "2025.08—2026.03"
    assert fact["content"]["role_variants"] == []
    assert fact["content"]["highlights"] == []
    assert project["title"] == "RAPath 路径记录与回放"
    assert project["highlights"] == ["使用 mutex 保护共享路径状态。"]


def test_legacy_uploaded_experience_is_migrated_to_project_highlights_on_read():
    content = sanitize_resume_content(
        {
            "metadata_source": "user_upload",
            "summary": "项目摘要。",
            "role": "算法实习生",
            "tech_stack": ["C++"],
            "highlights": ["使用 mutex 保护共享路径状态。"],
        },
        "RAPath 路径记录与回放",
        "experience",
    )

    assert content["highlights"] == []
    assert content["projects"][0]["title"] == "RAPath 路径记录与回放"
    assert content["projects"][0]["highlights"] == ["使用 mutex 保护共享路径状态。"]


def test_project_upload_metadata_falls_back_to_filename_only_for_legacy_callers():
    metadata = _normalize_project_upload_metadata({}, "dlt-calibration.md")

    assert metadata["title"] == "dlt-calibration"
    assert metadata["fact_type"] == "project"
    assert metadata["period"] == ""


def test_multi_project_internship_is_preserved_as_nested_projects():
    facts = [{
        "id": 38,
        "fact_type": "experience",
        "title": "博世算法实习生",
        "content": {
            "highlights": [
                "RAPath 路径记录与回放模块",
                "车载标定自动回放平台",
                "DLT 日志分析工具链",
            ]
        },
    }]
    generated = {
        "sections": [{
            "heading": "实习经历",
            "entries": [{
                "fact_ids": [38],
                "title": "博世汽车部件（苏州）有限公司",
                "items": [
                    {"fact_ids": [38], "label": "RAPath 路径记录与回放模块", "text": "路径学习"},
                    {"fact_ids": [38], "label": "车载标定自动回放平台", "text": "自动回放"},
                    {"fact_ids": [38], "label": "DLT 日志分析工具链", "text": "日志解析"},
                ],
            }],
        }]
    }

    _expand_experience_entries(generated, facts)

    entry = generated["sections"][0]["entries"][0]
    assert [project["title"] for project in entry["projects"]] == [
        "RAPath 路径记录与回放模块",
        "车载标定自动回放平台",
        "DLT 日志分析工具链",
    ]
    assert entry["items"] == []


def test_internship_markdown_is_stored_as_parent_with_project_children():
    markdown = """# 博世汽车部件（苏州）有限公司算法实习\n\n## 实习工作全景\n\n### RAPath 路径记录与回放模块\n实现路径记录与回放。\n\n### 车载标定自动回放平台\n实现标定数据自动回放。\n"""
    projects = [
        {"fact_type": "project", "title": "RAPath 路径记录与回放模块", "content": {"summary": "实现路径记录与回放。", "engineering_challenge": "定位跳变会污染路径状态。", "design_rationale": "采用状态机隔离异常分支。", "highlights": ["实现路径记录与回放。"]}},
        {"fact_type": "project", "title": "车载标定自动回放平台", "content": {"summary": "实现标定数据自动回放。", "engineering_challenge": "压缩包目录层级不固定。", "design_rationale": "采用递归查找降低输入结构约束。", "highlights": ["实现标定数据自动回放。"]}},
    ]

    grouped = CareerStudioService._group_project_facts_as_experience(projects, markdown, "bosch.md")

    assert grouped["fact_type"] == "experience"
    assert grouped["title"] == "博世汽车部件（苏州）有限公司"
    assert [item["title"] for item in grouped["content"]["projects"]] == [
        "RAPath 路径记录与回放模块",
        "车载标定自动回放平台",
    ]
    assert grouped["content"]["projects"][0]["engineering_challenge"] == "定位跳变会污染路径状态。"
    assert grouped["content"]["projects"][1]["design_rationale"] == "采用递归查找降低输入结构约束。"
    assert "状态机" in grouped["content"]["design_rationale"]
    assert "递归查找" in grouped["content"]["design_rationale"]
    assert grouped["content"]["projects"][0]["industrial_roles"]
    assert grouped["content"]["projects"][0]["role_variants"]
    assert grouped["content"]["industrial_roles"]


def test_experience_project_normalization_accepts_legacy_string_candidates():
    fact = {
        "id": 41,
        "fact_type": "experience",
        "content": {"highlights": ["路径记录模块：处理定位跳变"]},
    }
    entry = {"items": []}

    from app.api.endpoints.career import _experience_projects

    projects = _experience_projects(fact, entry)

    assert projects[0]["title"] == "路径记录模块"
    assert projects[0]["summary"] == "处理定位跳变"
    assert projects[0]["engineering_challenge"] == ""


def test_tailored_resume_uses_role_specific_variant_instead_of_generic_bullets():
    generated = {
        "sections": [{
            "heading": "项目经历",
            "entries": [{"fact_ids": [52], "title": "任务平台", "items": []}],
        }]
    }
    facts = [{
        "id": 52,
        "fact_type": "project",
        "title": "任务平台",
        "content": {
            "summary": "通用项目摘要",
            "role_variants": [
                {"role": "后端 / 平台工程师", "summary": "后端岗位摘要", "highlights": ["Django 任务接口与状态持久化"]},
                {"role": "车载 C++ / 自动驾驶软件工程师", "summary": "车载岗位摘要", "highlights": ["状态机与并发保护"]},
            ],
        },
        "evidence": "项目原文",
    }]

    _enrich_entries_from_evidence(
        generated,
        facts,
        {"title": "后端平台工程师", "required_skills": ["Django"]},
    )

    entry = generated["sections"][0]["entries"][0]
    assert entry["summary"] == "后端岗位摘要"
    assert entry["items"][0]["text"] == "Django 任务接口与状态持久化。"
