import re
from dataclasses import dataclass
from typing import Any


_GENERIC_IDENTIFIERS = {
    "and", "with", "from", "into", "for", "the", "using", "used", "via",
    "build", "built", "design", "designed", "develop", "developed", "system",
}


@dataclass(frozen=True)
class EvidenceValidation:
    supported: bool
    coverage: float
    unsupported_terms: tuple[str, ...] = ()


def normalize_evidence_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def locate_exact_quote(
    quote: str,
    referenced_chunk_id: str,
    extraction_chunks: dict[str, str],
    canonical_chunks: dict[str, str],
    window_sources: dict[str, list[str]] | None = None,
) -> tuple[str, str]:
    """Resolve an exact model quote to a persisted canonical chunk."""
    normalized_quote = normalize_evidence_text(quote)
    if not normalized_quote or referenced_chunk_id not in extraction_chunks:
        return "", ""

    source_ids = (window_sources or {}).get(referenced_chunk_id, [])
    if canonical_chunks:
        candidates = source_ids or list(canonical_chunks)
        for source_id in candidates:
            source_text = normalize_evidence_text(canonical_chunks.get(source_id, ""))
            if normalized_quote in source_text:
                return source_id, normalized_quote
        return "", ""

    source_text = normalize_evidence_text(extraction_chunks[referenced_chunk_id])
    if normalized_quote in source_text:
        return referenced_chunk_id, normalized_quote
    return "", ""


def _identifiers(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+#./-]{1,}", value)
        if token.lower() not in _GENERIC_IDENTIFIERS
    }


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?(?:\s*[%倍秒毫秒分钟小时天万亿MBGKTPSQ]+)?", value))


def _cjk_bigrams(value: str) -> set[str]:
    characters = "".join(re.findall(r"[\u4e00-\u9fff]", value))
    return {characters[index:index + 2] for index in range(len(characters) - 1)}


def validate_claim_support(claim: str, quotes: list[str], min_coverage: float) -> EvidenceValidation:
    """Apply conservative, domain-neutral grounding checks to a resume claim."""
    normalized_claim = normalize_evidence_text(claim)
    source = normalize_evidence_text(" ".join(quotes))
    if not normalized_claim or not source:
        return EvidenceValidation(False, 0.0)

    source_lower = source.lower()
    unsupported_identifiers = sorted(token for token in _identifiers(normalized_claim) if token not in source_lower)
    unsupported_numbers = sorted(token for token in _numbers(normalized_claim) if token not in source)
    unsupported = tuple(unsupported_identifiers + unsupported_numbers)
    if unsupported:
        return EvidenceValidation(False, 0.0, unsupported)

    claim_bigrams = _cjk_bigrams(normalized_claim)
    source_bigrams = _cjk_bigrams(source)
    if len(claim_bigrams) >= 8 and len(source_bigrams) >= 8:
        coverage = len(claim_bigrams & source_bigrams) / len(claim_bigrams)
        return EvidenceValidation(coverage >= min_coverage, round(coverage, 3))

    # Cross-language documents cannot be compared with CJK n-grams. Exact quotes plus
    # identifier and metric preservation are the safe deterministic checks available.
    return EvidenceValidation(True, 1.0)
