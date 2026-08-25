"""Deterministic, train-only few-shot selection for Chiki sales composition."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


TRAIN_PATH = Path(__file__).resolve().parents[3] / "data" / "fine_tuning" / "chiki_sales_v1" / "train.jsonl"
CELEBRATION_CODES = {
    "floating_gazebo", "houseboat_celebration", "jetty_gazebo",
    "party_boat_celebration", "pontoon_celebration",
}
H2O_CODES = {
    "kayaking", "aqua_cycle", "bumper_boat", "zorbing_ball", "water_bike",
    "kids_bumper_boat", "kids_paddle_boat",
}
RIDE_CODES = {"jet_ski_ride", "speed_boat_ride", "pontoon_boat_ride", "inflatable_sofa_ride"}


@dataclass(frozen=True)
class GoldExample:
    case_id: str
    response_goal: str
    language: str
    service_code: str | None
    category: str
    next_action: str | None
    intent_kind: str
    brief: dict[str, Any]
    response: str


def _category(code: str | None) -> str:
    if code in CELEBRATION_CODES:
        return "celebration"
    if code in H2O_CODES:
        return "h2o"
    if code in RIDE_CODES:
        return "one_time_ride"
    return "other"


def _intent_kind(brief: dict[str, Any]) -> str:
    facts = " ".join(str(item) for item in brief.get("approved_facts") or ()).casefold()
    if "requested detail unavailable" in facts:
        return "unknown_fact"
    if "individual turn duration" in facts:
        return "h2o_individual_turn"
    if "full-day access" in facts:
        return "h2o_access"
    goal = str(brief.get("response_goal") or "")
    if "discovery" in goal:
        return "discovery"
    if "recommendation" in goal:
        return "recommendation"
    if goal == "factual_answer":
        return "factual"
    return "overview"


@lru_cache(maxsize=1)
def load_train_gold_examples() -> tuple[GoldExample, ...]:
    examples: list[GoldExample] = []
    for line in TRAIN_PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        brief = json.loads(row["messages"][1]["content"])
        examples.append(GoldExample(
            case_id=row["metadata"]["case_id"],
            response_goal=brief["response_goal"],
            language=brief["customer_language"],
            service_code=brief.get("service_code"),
            category=_category(brief.get("service_code")),
            next_action=brief.get("next_action"),
            intent_kind=_intent_kind(brief),
            brief=brief,
            response=row["messages"][2]["content"],
        ))
    return tuple(examples)


class GoldExampleSelector:
    """Rank reviewed TRAIN demonstrations without embeddings or model calls."""

    def __init__(self, examples: tuple[GoldExample, ...] | None = None, limit: int = 4) -> None:
        self.examples = examples if examples is not None else load_train_gold_examples()
        self.limit = max(3, min(limit, 5))

    def select(self, brief: Any) -> tuple[GoldExample, ...]:
        current = {
            "response_goal": brief.response_goal.value,
            "customer_language": brief.customer_language,
            "service_code": brief.service_code,
            "next_action": brief.next_action,
            "approved_facts": brief.approved_facts,
        }
        goal = current["response_goal"]
        language = current["customer_language"]
        category = _category(current["service_code"])
        intent_kind = _intent_kind(current)

        def score(example: GoldExample) -> tuple[int, str]:
            value = 0
            value += 100 if example.response_goal == goal else 0
            value += 35 if example.language == language else 0
            intent_weight = 80 if intent_kind in {"h2o_access", "h2o_individual_turn", "unknown_fact"} else 25
            value += intent_weight if example.intent_kind == intent_kind else 0
            value += 18 if category != "other" and example.category == category else 0
            value += 12 if current["service_code"] and example.service_code == current["service_code"] else 0
            value += 10 if current["next_action"] and example.next_action == current["next_action"] else 0
            return (-value, example.case_id)

        ranked = sorted(self.examples, key=score)
        chosen: list[GoldExample] = []
        response_shapes: set[str] = set()
        for example in ranked:
            shape = " ".join(example.response.casefold().split())[:80]
            if shape in response_shapes:
                continue
            chosen.append(example)
            response_shapes.add(shape)
            if len(chosen) == self.limit:
                break
        return tuple(chosen)


def compact_gold_examples(examples: tuple[GoldExample, ...]) -> str:
    blocks: list[str] = []
    keys = ("response_goal", "customer_language", "service_code", "service_name", "approved_facts", "approved_options", "next_action", "next_question")
    for number, example in enumerate(examples, 1):
        compact = {key: example.brief.get(key) for key in keys if example.brief.get(key) not in (None, [], "")}
        blocks.append(
            f"EXAMPLE {number}\nBrief: {json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}"
            f"\nIdeal Chiki response: {example.response}"
        )
    return "\n\n".join(blocks)
