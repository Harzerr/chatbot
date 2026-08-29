from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class QdrantCollectionContractError(RuntimeError):
    """Raised when an existing collection cannot serve the configured embeddings."""


def validate_vector_contract(
    collection_info: Any,
    *,
    collection_name: str,
    expected_size: int,
    expected_distance: str = "cosine",
) -> None:
    """Fail fast when an existing collection uses an incompatible vector schema."""
    vectors = collection_info.config.params.vectors
    if isinstance(vectors, Mapping):
        raise QdrantCollectionContractError(
            f"Qdrant collection {collection_name!r} uses named vectors, but this service expects one unnamed vector."
        )

    actual_size = int(getattr(vectors, "size", 0) or 0)
    actual_distance = str(getattr(vectors, "distance", "") or "").split(".")[-1].lower()
    if actual_size != int(expected_size) or actual_distance != expected_distance.lower():
        raise QdrantCollectionContractError(
            "Qdrant collection contract mismatch: "
            f"collection={collection_name!r}, actual={actual_size}/{actual_distance or 'unknown'}, "
            f"expected={expected_size}/{expected_distance.lower()}. "
            "Reindex into a new collection instead of writing vectors with a different embedding contract."
        )


def missing_payload_indexes(collection_info: Any, required_fields: tuple[str, ...]) -> list[str]:
    payload_schema = getattr(collection_info, "payload_schema", None) or {}
    existing = set(payload_schema)
    return [field for field in required_fields if field not in existing]
