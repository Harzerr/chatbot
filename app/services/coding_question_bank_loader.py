import json
from functools import lru_cache
from pathlib import Path

from app.knowledge.coding_question_bank_data import CODING_QUESTION_BANK

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODING_QUESTION_BANK_PATH = PROJECT_ROOT / "app" / "knowledge" / "coding_question_bank.json"


@lru_cache(maxsize=1)
def load_coding_question_bank() -> list[dict]:
    bank = list(CODING_QUESTION_BANK)

    if CODING_QUESTION_BANK_PATH.exists():
        bank.extend(json.loads(CODING_QUESTION_BANK_PATH.read_text(encoding="utf-8")))

    return bank
