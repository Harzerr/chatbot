from __future__ import annotations
import json, sys
from pathlib import Path
from pydantic import ValidationError
from models import ExtractorInput, ExtractorOutput


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split())


def validate_output_data(input_data: dict, output_data: dict) -> list[str]:
    """Validate structure plus cross-references between chunks and evidence."""
    errors: list[str] = []
    try:
        source = ExtractorInput.model_validate(input_data)
    except ValidationError as exc:
        return [f"invalid input: {exc}"]
    try:
        result = ExtractorOutput.model_validate(output_data)
    except ValidationError as exc:
        return [f"invalid output: {exc}"]

    if result.document_id != source.document_id:
        errors.append("document_id does not match input")
    if source.project_mode == "single_project" and len(result.projects) > 1:
        errors.append("single_project input produced multiple projects")

    chunks = {chunk.chunk_id: chunk for chunk in source.chunks}
    project_ids: set[str] = set()
    point_ids: set[str] = set()
    for project in result.projects:
        if project.project_id in project_ids:
            errors.append(f"duplicate project_id: {project.project_id}")
        project_ids.add(project.project_id)
        unknown_project_chunks = set(project.source_chunk_ids) - chunks.keys()
        errors.extend(f"unknown project source chunk: {item}" for item in sorted(unknown_project_chunks))
        for point in project.key_points:
            if point.point_id in point_ids:
                errors.append(f"duplicate point_id: {point.point_id}")
            point_ids.add(point.point_id)
            evidence_ids: set[str] = set()
            for evidence in point.evidence_chunks:
                if evidence.chunk_id not in chunks:
                    errors.append(f"unknown evidence chunk: {evidence.chunk_id}")
                    continue
                evidence_ids.add(evidence.chunk_id)
                quote = _normalized(evidence.quote)
                chunk_text = _normalized(chunks[evidence.chunk_id].text)
                if not quote:
                    errors.append(f"empty evidence quote: {point.point_id}")
                elif quote not in chunk_text:
                    errors.append(f"quote is not contained in chunk {evidence.chunk_id}: {point.point_id}")
            if not evidence_ids:
                errors.append(f"key point has no valid evidence: {point.point_id}")
    return errors

def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print('Usage: python validate_output.py <output.json> [input.json]')
        return 2
    try:
        output_data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result = ExtractorOutput.model_validate(output_data)
        errors = []
        if len(sys.argv) == 3:
            input_data = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
            errors = validate_output_data(input_data, output_data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f'INVALID: {exc}')
        return 1
    if errors:
        print("INVALID: " + "; ".join(errors))
        return 1
    points = sum(len(p.key_points) for p in result.projects)
    evidence = sum(len(k.evidence_chunks) for p in result.projects for k in p.key_points)
    print(f'VALID: {len(result.projects)} projects, {points} key points, {evidence} evidence fragments')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
