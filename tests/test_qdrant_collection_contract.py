from types import SimpleNamespace

import pytest

from app.services.qdrant_collection_contract import (
    QdrantCollectionContractError,
    missing_payload_indexes,
    validate_vector_contract,
)


def _collection_info(size=768, distance="Cosine", payload_schema=None):
    vectors = SimpleNamespace(size=size, distance=distance)
    params = SimpleNamespace(vectors=vectors)
    config = SimpleNamespace(params=params)
    return SimpleNamespace(config=config, payload_schema=payload_schema or {})


def test_vector_contract_accepts_configured_dimension_and_distance():
    validate_vector_contract(
        _collection_info(),
        collection_name="career_evidence",
        expected_size=768,
    )


def test_vector_contract_rejects_dimension_drift_before_runtime_search():
    with pytest.raises(QdrantCollectionContractError, match="actual=1536/cosine"):
        validate_vector_contract(
            _collection_info(size=1536),
            collection_name="career_evidence",
            expected_size=768,
        )


def test_only_missing_payload_indexes_are_returned():
    info = _collection_info(payload_schema={"metadata.tenant_id": {"data_type": "keyword"}})

    missing = missing_payload_indexes(
        info,
        ("metadata.tenant_id", "metadata.user_id", "metadata.document_id"),
    )

    assert missing == ["metadata.user_id", "metadata.document_id"]
