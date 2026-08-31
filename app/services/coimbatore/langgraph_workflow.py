"""Coimbatore-only LangGraph routing with deterministic sales nodes."""
from __future__ import annotations

import re
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class CoimbatoreGraphState(TypedDict, total=False):
    message: Any
    message_text: str
    normalized_message: str
    customer: dict[str, Any]
    conversation: dict[str, Any]
    source_message_id: str
    current_state: Any
    route: str
    response: Any


class CoimbatoreLangGraphWorkflow:
    """Select a bounded Coimbatore action; never sends provider messages."""

    def __init__(self, execute_turn: Callable[..., Any]) -> None:
        self._execute_turn = execute_turn
        graph = StateGraph(CoimbatoreGraphState)
        graph.add_node("normalize", self._normalize)
        graph.add_node("determine_flow", self._determine_flow)
        for route in (
            "qualification", "standard_package", "package_router", "faq",
            "booking", "handoff", "faq_wait", "photos", "availability",
            "payment", "safe_fallback",
        ):
            graph.add_node(route, self._execute_node(route))
        graph.add_edge(START, "normalize")
        graph.add_edge("normalize", "determine_flow")
        graph.add_conditional_edges(
            "determine_flow", lambda state: state["route"],
            {route: route for route in (
                "qualification", "standard_package", "package_router", "faq",
                "booking", "handoff", "faq_wait", "photos", "availability",
                "payment", "safe_fallback",
            )},
        )
        for route in (
            "qualification", "standard_package", "package_router", "faq",
            "booking", "handoff", "faq_wait", "photos", "availability",
            "payment", "safe_fallback",
        ):
            graph.add_edge(route, END)
        self._graph = graph.compile()

    def invoke(self, **values: Any) -> Any:
        state = self._graph.invoke(values)
        result = state["response"]
        metadata = dict(getattr(result, "safe_metadata", {}) or {})
        actual_route = "standard_package" if metadata.get("exact_kb_package_block") else state["route"]
        metadata.update({
            "active_engine": "coimbatore_langgraph",
            "langgraph_enabled": True,
            "graph_route": actual_route,
            "graph_answer_source": f"coimbatore_{actual_route}",
            "raipur_graph_used": False,
        })
        return __import__("dataclasses").replace(result, safe_metadata=metadata)

    @staticmethod
    def _normalize(state: CoimbatoreGraphState) -> dict[str, str]:
        text = getattr(state.get("message"), "content", "")
        text = text if isinstance(text, str) else ""
        return {"message_text": text, "normalized_message": " ".join(text.casefold().split())}

    @staticmethod
    def _determine_flow(state: CoimbatoreGraphState) -> dict[str, str]:
        text = state.get("normalized_message", "")
        if re.search(r"available|availability|slot", text): route = "availability"
        elif re.search(r"payment|paid", text): route = "payment"
        elif "coimbatore_pontoon_book_standard" in text or re.search(r"\bbook now\b", text): route = "booking"
        elif ("coimbatore_pontoon_customize" in text or text == "customize"
              or "coimbatore_pontoon_talk_sales" in text
              or text in {"talk to sales person", "talk to sales", "sales person"}): route = "handoff"
        elif "coimbatore_pontoon_more_photos" in text or "more photos" in text or "photo & video" in text or "photo and video" in text: route = "photos"
        elif "coimbatore_pontoon_ask_question" in text or text == "ask a question": route = "faq_wait"
        elif re.search(r"standard package|5999 package|send package|package details", text): route = "package_router"
        elif re.fullmatch(r"(?:hi+|hello+|hey+)[!.?]*", text) or re.search(r"\d", text): route = "qualification"
        elif text: route = "faq"
        else: route = "safe_fallback"
        return {"route": route}

    def _execute_node(self, route: str):
        def execute(state: CoimbatoreGraphState) -> dict[str, Any]:
            result = self._execute_turn(
                state["message"], customer=state["customer"],
                conversation=state["conversation"],
                source_message_id=state["source_message_id"],
                current_state=state.get("current_state"),
            )
            return {"response": result, "route": route}
        return execute
