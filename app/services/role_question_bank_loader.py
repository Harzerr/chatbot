import json
from pathlib import Path
from typing import List


ROLE_QUESTION_BANK_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "role_question_bank.json"


def load_role_question_bank() -> List[dict]:
    with ROLE_QUESTION_BANK_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("role_question_bank.json must contain a top-level list")

    return data
