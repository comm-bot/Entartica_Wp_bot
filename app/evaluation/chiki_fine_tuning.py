"""Offline validation and holdout contract for Chiki composer datasets."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any

from app.rag.customer_ready_knowledge import contains_governance_language
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES, knowledge_service_code

ALLOWED_SERVICE_CODES = {knowledge_service_code(item) for item in APPROVED_RAIPUR_SERVICES}
ALLOWED_SERVICE_NAMES = {item.name for item in APPROVED_RAIPUR_SERVICES}
FORBIDDEN = re.compile(r"\b(?:facts to verify|source conflict|current pages disagree|customer-ready format|production value|governance|evidence status|supported|explicit|unknown|conflict)\b", re.I)
PHONE_OR_PII = re.compile(r"(?:\+?\d[\d\s-]{8,}\d|\b[A-Z][a-z]+\s+[A-Z][a-z]+\b\s*(?:phone|number|email))")
UNSAFE_CLAIM = re.compile(r"\b(?:booking is confirmed|payment is confirmed|available (?:today|tomorrow|now)|₹|\binr\b|\brs\.?\s*\d)\b", re.I)
METRICS = ("sales_tone", "fact_grounding", "next_action_compliance", "conciseness", "language_match", "unsupported_claim_rate", "governance_leakage", "service_name_accuracy")


@dataclass(frozen=True)
class DatasetValidation:
    valid: bool
    example_count: int
    errors: tuple[str, ...]
    goal_distribution: dict[str, int]
    language_distribution: dict[str, int]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try: rows.append(json.loads(line))
        except json.JSONDecodeError as exc: raise ValueError(f"{path.name}:{number}:invalid_json") from exc
    return rows


def validate_dataset(root: Path) -> DatasetValidation:
    errors: list[str] = []; all_rows = []; goals: Counter[str] = Counter(); languages: Counter[str] = Counter()
    split_outputs: dict[str, list[str]] = {}
    for split in ("train", "validation", "holdout"):
        path = root / f"{split}.jsonl"
        try: rows = load_jsonl(path)
        except (OSError, ValueError) as exc: errors.append(str(exc)); continue
        split_outputs[split] = []
        for index, row in enumerate(rows, 1):
            prefix = f"{split}:{index}"
            messages = row.get("messages") if isinstance(row, dict) else None
            if not isinstance(messages, list) or [item.get("role") for item in messages] != ["system", "user", "assistant"]:
                errors.append(f"{prefix}:invalid_messages"); continue
            try: brief = json.loads(messages[1]["content"])
            except (KeyError, TypeError, json.JSONDecodeError): errors.append(f"{prefix}:invalid_brief"); continue
            answer = messages[2].get("content", "")
            if not isinstance(answer, str) or not answer.strip(): errors.append(f"{prefix}:empty_answer"); continue
            goals[str(brief.get("response_goal"))] += 1; languages[str(brief.get("customer_language"))] += 1
            if FORBIDDEN.search(answer) or contains_governance_language(answer): errors.append(f"{prefix}:governance")
            if PHONE_OR_PII.search(answer) or PHONE_OR_PII.search(messages[1]["content"]): errors.append(f"{prefix}:pii")
            if UNSAFE_CLAIM.search(answer): errors.append(f"{prefix}:unsafe_claim")
            code = brief.get("service_code")
            if code is not None and code not in ALLOWED_SERVICE_CODES: errors.append(f"{prefix}:invalid_service_code")
            supplied_names = set(brief.get("approved_options") or ())
            if brief.get("service_name"): supplied_names.add(brief["service_name"])
            for name in ALLOWED_SERVICE_NAMES:
                if name.casefold() in answer.casefold() and not any(name.casefold() in supplied.casefold() for supplied in supplied_names):
                    errors.append(f"{prefix}:unsupported_service:{name}")
            supplied = json.dumps(brief, ensure_ascii=False).casefold()
            for number in re.findall(r"\b\d+(?::\d+)?\b", answer):
                if number not in supplied: errors.append(f"{prefix}:unsupported_number:{number}")
            question = brief.get("next_question")
            if question and answer.count("?") != 1: errors.append(f"{prefix}:next_question_count")
            if len(answer) > 900: errors.append(f"{prefix}:too_long")
            split_outputs[split].append(answer)
            all_rows.append(row)
    for left, right in (("train", "validation"), ("train", "holdout"), ("validation", "holdout")):
        for a in split_outputs.get(left, ()):
            for b in split_outputs.get(right, ()):
                if SequenceMatcher(None, a.casefold(), b.casefold()).ratio() >= .97:
                    errors.append(f"near_duplicate:{left}:{right}")
    return DatasetValidation(not errors, len(all_rows), tuple(dict.fromkeys(errors)), dict(goals), dict(languages))


def holdout_evaluation_contract() -> dict[str, Any]:
    return {"metrics": METRICS, "external_evaluation": False, "comparison": ("base_sales_composer", "fine_tuned_chiki"), "input": "holdout.jsonl"}


def deterministic_output_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    """Score objective output properties; tone deliberately remains unscored."""
    totals=Counter(); count=len(rows)
    for row in rows:
        brief=json.loads(row["messages"][1]["content"]); answer=row["messages"][2]["content"]
        supplied=json.dumps(brief,ensure_ascii=False).casefold()
        totals["grounded"] += not any(number not in supplied for number in re.findall(r"\b\d+(?::\d+)?\b",answer))
        name=brief.get("service_name"); totals["service"] += not name or name.casefold() in answer.casefold()
        question=brief.get("next_question"); totals["question"] += not question or answer.count("?")==1
        totals["safe"] += not bool(UNSAFE_CLAIM.search(answer))
        totals["governance"] += not bool(FORBIDDEN.search(answer) or contains_governance_language(answer))
        totals["concise"] += len(answer)<=900
        language=brief.get("customer_language"); totals["language"] += language=="en" or (language=="hinglish" and bool(re.search(r"\b(?:hai|hain|aap|ke|ki|kar|karein|liye|khaas)\b",answer,re.I))) or (language=="hi" and bool(re.search(r"[\u0900-\u097f]",answer)))
    rate=lambda key:round(100*totals[key]/count,2) if count else 0.0
    return {"examples":count,"factual_grounding":rate("grounded"),"service_name_accuracy":rate("service"),"next_question_compliance":rate("question"),"unsupported_claim_free":rate("safe"),"governance_leakage_free":rate("governance"),"language_match":rate("language"),"conciseness":rate("concise"),"sales_tone_quality":"requires_human_or_model_evaluation","raw_kb_like_rate":"requires_human_or_model_evaluation"}
