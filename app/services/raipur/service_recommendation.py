"""Approved-evidence recommendation policy for Raipur celebrations only."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from app.services.raipur.capacity_governance import CapacityCompatibility, assess_capacity
from app.services.raipur_services import approved_service_from_message, knowledge_service_code


_ALLOWED_SECTIONS = {
    "experience overview", "what makes this experience special", "best for",
    "experience highlights", "capacity", "celebration inclusions",
    "customisation options", "duration",
}
_PREFERENCE_TERMS = {
    "private_intimate": ("intimate", "private celebration", "private setting", "romantic", "personal setting"),
    "lively_party": ("lively", "energetic", "party atmosphere", "music adds energy"),
    "relaxed": ("relaxed", "peaceful", "calm"),
    "couple": ("couple", "romantic", "intimate"),
    "family": ("family", "group gathering", "family and friends"),
}


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class RecommendationEvidence:
    service_code: str
    section: str
    text: str
    source_document_id: str | None = None


@dataclass(frozen=True)
class RecommendationDecision:
    recommended_service_codes: tuple[str, ...] = ()
    strength: str = "none"
    evidence: tuple[RecommendationEvidence, ...] = ()
    reason: str = "insufficient_approved_evidence"
    insufficient_evidence: bool = True
    capacity_compatibility: tuple[CapacityCompatibility, ...] = ()
    occasion_evidence_used: bool = False
    preference_evidence_used: bool = False


class RecommendationEvidenceProvider(Protocol):
    def recommendation_evidence(self, service_code: str) -> list[dict[str, Any]]: ...


class CelebrationRecommendationPolicy:
    """Rank only supplied active candidates using their own approved facts."""

    def __init__(self, evidence_provider: RecommendationEvidenceProvider | None) -> None:
        self._provider = evidence_provider

    def recommend(
        self,
        *,
        candidates: list[dict[str, Any]],
        occasion: str | None,
        preference: str | None,
        guest_count: int | None,
    ) -> RecommendationDecision:
        if self._provider is None:
            return RecommendationDecision()
        preference_terms = _PREFERENCE_TERMS.get(_normalized(preference).replace(" ", "_"), ())
        occasion_terms = self._occasion_terms(occasion)
        if not preference_terms and not occasion_terms:
            return RecommendationDecision()

        ranked: list[tuple[int, int, str, tuple[RecommendationEvidence, ...], CapacityCompatibility | None]] = []
        for row in candidates:
            name = row.get("name") if isinstance(row, dict) else None
            approved = approved_service_from_message(name)
            if approved is None or approved.category != "floating_celebration":
                continue
            code = knowledge_service_code(approved)
            capacity = assess_capacity(code, guest_count)
            if capacity is not None and capacity.compatible is False:
                continue
            facts = self._facts_for(code)
            preference_matches = tuple(fact for fact in facts if self._contains_any(fact.text, preference_terms))
            occasion_matches = tuple(fact for fact in facts if self._contains_any(fact.text, occasion_terms))
            if preference_terms and not preference_matches:
                continue
            if occasion_terms and not occasion_matches:
                continue
            selected = tuple(dict.fromkeys((*preference_matches, *occasion_matches)))
            if not selected:
                continue
            score = (2 if preference_matches else 0) + (2 if occasion_matches else 0) + min(len(selected), 3)
            ranked.append((score, len(selected), code, selected[:3], capacity))

        if not ranked:
            return RecommendationDecision()
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        winners = ranked[:3]
        codes = tuple(item[2] for item in winners)
        evidence = tuple(fact for item in winners for fact in item[3])
        capacity_compatibility = tuple(item[4] for item in winners if item[4] is not None)
        strength = "strong" if preference_terms and occasion_terms else "moderate"
        return RecommendationDecision(
            recommended_service_codes=codes,
            strength=strength,
            evidence=evidence,
            reason="approved_service_specific_evidence_match",
            insufficient_evidence=False,
            capacity_compatibility=capacity_compatibility,
            occasion_evidence_used=bool(occasion_terms),
            preference_evidence_used=bool(preference_terms),
        )

    def _facts_for(self, service_code: str) -> tuple[RecommendationEvidence, ...]:
        try:
            rows = self._provider.recommendation_evidence(service_code)
        except Exception:
            return ()
        facts = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("service_code") != service_code:
                continue
            section = row.get("section")
            text = row.get("text")
            if _normalized(section) not in _ALLOWED_SECTIONS or not isinstance(text, str) or not text.strip():
                continue
            facts.append(RecommendationEvidence(service_code, str(section), text.strip(), row.get("source_document_id")))
        return tuple(facts)

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        value = text.casefold()
        return bool(terms) and any(term in value for term in terms)

    @staticmethod
    def _occasion_terms(occasion: str | None) -> tuple[str, ...]:
        value = _normalized(occasion)
        if not value or value in {"special event", "celebration"}:
            return ()
        if "corporate" in value or "client" in value or "team" in value:
            return ("corporate", "client", "team celebration")
        if "birthday" in value:
            return ("birthday",)
        if "anniversary" in value:
            return ("anniversary", "anniversaries")
        if "proposal" in value:
            return ("proposal",)
        return (value,)
