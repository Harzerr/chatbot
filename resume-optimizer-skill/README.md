# Resume Project Extractor Skill

A compact Agent Skill for extracting **project experience key points from chunked uploaded documents**.

## Core design

```text
Project
  -> Key Point
      -> Evidence Chunk 1
      -> Evidence Chunk 2
      -> Evidence Chunk N
```

This specifically supports long-document chunking: one project fact may be scattered across multiple chunks.

## Directory

```text
resume-optimizer-skill/
├── SKILL.md
├── README.md
├── schemas/
│   ├── input_schema.json
│   └── output_schema.json
├── src/
│   ├── models.py
│   └── validate_output.py
├── references/
│   └── extraction-rules.md
└── examples/
    ├── input_chunks.json
    └── output.json
```

## Integration flow

```text
Uploaded PDF/DOCX
      ↓
Parser / OCR
      ↓
Long-text chunking
      ↓
chunks[{chunk_id, text, ...}]
      ↓
resume-project-extractor
      ↓
projects[]
  └─ key_points[]
       └─ evidence_chunks[]
      ↓
Interview Agent / Evidence Review / Resume Deep Dive
```

The application now builds the canonical chunks before invoking the Skill and validates every
evidence chunk ID and quote before adapting the result into the CareerFact schema.

## Suggested invocation

> Extract project experiences from these canonical chunks. In single_project mode keep one uploaded
> document as one project. Merge evidence across chunks when several fragments support the same key
> point. Return JSON following the output schema.

## Python models and validation

`src/models.py` contains reusable Pydantic models for FastAPI/LangGraph backends. The application
builds the runtime prompt from `SKILL.md`; `src/validate_output.py` cross-checks evidence references
against the input chunks without maintaining a second prompt implementation.

## Validate sample output

```bash
pip install pydantic
python src/validate_output.py examples/output.json examples/input_chunks.json
```
