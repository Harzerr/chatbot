"""Migrate flattened internship bullets into nested project entries."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.api.endpoints.career import _expand_experience_entries
from app.db.session import AsyncSessionLocal, async_engine
from app.models.career import CareerFact, ResumeDocument


async def migrate(user_id: int | None = None) -> int:
    async with AsyncSessionLocal() as db:
        query = select(ResumeDocument).order_by(ResumeDocument.id)
        if user_id is not None:
            query = query.where(ResumeDocument.user_id == user_id)
        resumes = (await db.scalars(query)).all()
        updated = 0
        for resume in resumes:
            content = json.loads(resume.content_json or "{}")
            if not isinstance(content, dict):
                continue
            fact_rows = (await db.scalars(
                select(CareerFact).where(
                    CareerFact.user_id == resume.user_id,
                )
            )).all()
            facts_by_id = {fact.id: fact for fact in fact_rows}
            fact_payload = [
                {
                    "id": fact.id,
                    "fact_type": fact.fact_type,
                    "title": fact.title,
                    "content": json.loads(fact.content_json or "{}"),
                    "evidence": fact.evidence,
                }
                for fact in fact_rows
            ]
            before = json.dumps(content, ensure_ascii=False, sort_keys=True)
            _expand_experience_entries(content, fact_payload)
            after = json.dumps(content, ensure_ascii=False, sort_keys=True)
            changed = before != after
            for section in content.get("sections", []):
                if not isinstance(section, dict) or section.get("heading") != "实习经历":
                    continue
                for entry in section.get("entries", []):
                    if not isinstance(entry, dict) or not isinstance(entry.get("projects"), list):
                        continue
                    fact_ids = entry.get("fact_ids") if isinstance(entry.get("fact_ids"), list) else []
                    if len(fact_ids) != 1 or fact_ids[0] not in facts_by_id or len(entry["projects"]) < 2:
                        continue
                    fact = facts_by_id[fact_ids[0]]
                    fact_content = json.loads(fact.content_json or "{}")
                    if not isinstance(fact_content, dict):
                        fact_content = {}
                    existing_projects = fact_content.get("projects") if isinstance(fact_content.get("projects"), list) else []
                    if len(existing_projects) >= len(entry["projects"]) and all(
                        isinstance(project, dict) and project.get("highlights")
                        for project in existing_projects[:len(entry["projects"])]
                    ):
                        continue
                    source_highlights = fact_content.get("highlights") if isinstance(fact_content.get("highlights"), list) else []
                    fact_content["projects"] = [
                        {
                            "title": project.get("title", ""),
                            "summary": project.get("summary", ""),
                            "engineering_challenge": project.get("engineering_challenge", ""),
                            "design_rationale": project.get("design_rationale", ""),
                            "tech_stack": project.get("tech_stack", []),
                            "highlights": [
                                item.get("text", "") for item in project.get("items", [])
                                if isinstance(item, dict) and item.get("text")
                            ] or [
                                highlight for highlight in source_highlights
                                if str(project.get("title", "")).replace(" ", "")[:8] in str(highlight).replace(" ", "")
                            ][:1],
                            "evidence_map": project.get("evidence_map", []),
                        }
                        for project in entry["projects"]
                        if isinstance(project, dict) and project.get("title")
                    ]
                    fact.content_json = json.dumps(fact_content, ensure_ascii=False)
                    changed = True
            if changed:
                resume.content_json = json.dumps(content, ensure_ascii=False)
                resume.status = "edited"
                updated += 1
        await db.commit()
    await async_engine.dispose()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args()
    print(f"updated_resumes={asyncio.run(migrate(args.user_id))}")


if __name__ == "__main__":
    main()
