from pathlib import Path
import sys
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.coding_knowledge_store import QdrantCodingKnowledgeStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed or rebuild the Qdrant coding question bank")
    parser.add_argument("--rebuild", action="store_true", help="Delete and rebuild the Qdrant coding question collection")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = QdrantCodingKnowledgeStore()
    result = store.rebuild_collection() if args.rebuild else store.append_new_documents()
    print(f"coding knowledge collection: {store.collection_name}")
    print(f"added_count: {result['added_count']}")
    print(f"total_count: {result['total_count']}")
    print("coding question bank seeding finished")


if __name__ == "__main__":
    main()
