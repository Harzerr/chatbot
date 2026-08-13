from app.services.career_studio import CareerStudioService


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
    assert len(content["evidence_map"]) == len(content["highlights"])


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
    assert entry["items"][0]["text"] == "使用 Redis 队列处理任务"
