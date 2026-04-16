from pathlib import Path
import sys
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.role_knowledge_store import QdrantRoleKnowledgeStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed or rebuild the Qdrant role question bank")
    parser.add_argument("--rebuild", action="store_true", help="Delete and rebuild the Qdrant role question collection")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = QdrantRoleKnowledgeStore()
    result = store.rebuild_collection() if args.rebuild else store.append_new_documents()
    print(f"role knowledge collection: {store.collection_name}")
    print(f"added_count: {result['added_count']}")
    print(f"total_count: {result['total_count']}")
    print("role question bank seeding finished")


if __name__ == "__main__":
    main()
