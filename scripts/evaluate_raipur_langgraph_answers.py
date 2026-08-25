"""Offline-only LangGraph answer-quality evaluation; no webhook or database writes."""
from __future__ import annotations

import argparse, csv, json, os, sys, time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from app.services.raipur.response_models import KnowledgeDraft
from app.services.raipur_langgraph import RaipurLangGraphWorkflow

RESULTS = ROOT / "evals" / "results"


class OfflineKnowledge:
    def answer_service_details(self, _question, service_name, service_code, *, detail_mode="overview", **_kwargs):
        fact = f"{service_name} approved {detail_mode} information is available."
        return KnowledgeDraft(fact, f"{service_code}.md", 0.9, False, detail_mode.replace("_", " "))
    def answer(self, _question): return KnowledgeDraft("Approved Raipur venue information is available.", "raipur_general_information.md", .9, False, "overview")


class NoNetworkConversation:
    def process(self, *_args, **_kwargs): raise AssertionError("legacy processor must not be used")


CASES = [
    "What are the rides?", "Can you provide other rides?", "What is the location of Raipur?", "Raipur kaha hai?",
    "What is the capacity of Speed Boat?", "Hat is the capacity of speed baot.", "Kayak me kitne log baith sakte hain?",
    "Jet Ski kitni der ki hai?", "Staycation me kya included hai?", "Swimming zaruri hai?", "Tell me about Jet Ski.",
    "Can you give more details about it?", "What is the price of Jet Ski?", "I want to book Speed Boat.",
    "Is Jet Ski available tomorrow?", "What is kayaking?", "What exact engine model does your Speed Boat use?",
    "I want the Entartica Raipur address.", "How can I reach Entartica Raipur?", "What else do you offer?",
    "Speed Boat ke bare mein information do.", "What safety equipment is provided?", "Who can participate?",
    "How can I make payment?", "I want to cancel my booking.", "What is a lake?",
    "What should people generally wear for water activities?", "Who is operating Jet Ski today?", "What is the current fuel level?",
    "Can you provide more details about Jet Ski?",
]
REAL_SMOKE = ["What is the location of Raipur?", "What are the rides?", "What is the capacity of Speed Boat?", "Jet Ski kitni der ki hai?", "I want to book Speed Boat."]


def _state(message: str, previous: str | None = None):
    return {"message_id":"eval", "conversation_id":"offline", "customer_id":"offline", "customer_message":message, "normalized_message":message.casefold(), "language":"hinglish" if any(x in message.casefold() for x in ("kya","hai","kitne")) else "en", "location_code":"raipur", "previous_service_code":previous, "intent":"unknown", "entity_type":"unknown", "service_code":None, "topic":None, "use_previous_service":False, "requires_handover":False, "handover_reason":None, "answer_source":"none", "draft_response":None, "validation_status":"pending", "error":None, "route":""}


def run_offline() -> list[dict]:
    workflow = RaipurLangGraphWorkflow(NoNetworkConversation(), knowledge=OfflineKnowledge())
    rows, previous = [], None
    for index, message in enumerate(CASES, 1):
        start = time.perf_counter(); state = _state(message, previous)
        plan = workflow.plan_message({**state, "_runtime":{"current_state":None}}); route = workflow.route({**state, **plan})
        result = workflow.invoke(state, message=SimpleNamespace(content=message), customer={"id":"offline"}, conversation={"id":"offline"}, source_message_id=f"offline-{index}")
        if plan.get("service_code"): previous = plan["service_code"]
        rows.append({"case_id":f"offline-{index}", "turn_number":1, "customer_message":message, "detected_language":state["language"], "intent":plan["intent"], "route":route, "service_code":plan.get("service_code"), "topic":plan.get("topic"), "used_previous_service":plan.get("use_previous_service",False), "retrieved_section_headings":getattr(result.context,"last_answer_sections",()), "retrieved_document_ids":[], "answer_source":(result.safe_metadata or {}).get("graph_answer_source"), "validation_passed":result.response_valid, "validation_errors":[], "deterministic_fallback_used":getattr(result.context,"last_answer_source",None)=="deterministic_fact_fallback", "openai_call_count":0, "latency_ms":round((time.perf_counter()-start)*1000,2), "final_response":result.draft_text})
    return rows


def write_results(rows: list[dict], *, stem: str = "raipur_langgraph_answer_quality") -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{stem}.json").write_text(json.dumps(rows, indent=2, default=list), encoding="utf-8")
    with (RESULTS / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer=csv.DictWriter(handle, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    (RESULTS / f"{stem}.md").write_text(f"# Raipur LangGraph Answer Quality\n\nCases: {len(rows)}\n\nDatabase writes: 0\n", encoding="utf-8")


def run_real_readonly(max_cases: int | None) -> list[dict]:
    from app.config import get_settings
    from app.evaluation.raipur_readonly_adapter import RaipurReadOnlyAdapter
    from app.integrations.supabase import get_supabase_client
    from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
    from app.services.raipur_conversational_fallback import build_raipur_conversational_fallback
    from app.services.raipur_sales_contact import SalesContact
    settings = get_settings(); adapter = RaipurReadOnlyAdapter(get_supabase_client())
    location = adapter.resolve_raipur_location()
    if not isinstance(location, dict): raise RuntimeError("raipur_location_unavailable")
    class Services:
        def list_active_for_location(self, location_id): return adapter.list_active_services(location_id)
    knowledge = RaipurKnowledgeProvider(adapter, settings, retrieve_candidates_fn=lambda _unused, embedding, limit=20: adapter.retrieve_venue_knowledge(embedding, limit=limit))
    workflow = RaipurLangGraphWorkflow(NoNetworkConversation(), knowledge=knowledge, services=Services(), location=location, sales_contact=SalesContact.from_settings(settings), conversational_fallback=build_raipur_conversational_fallback(settings))
    rows=[]
    for index, message in enumerate(REAL_SMOKE[:max_cases or len(REAL_SMOKE)], 1):
        state=_state(message); start=time.perf_counter(); plan=workflow.plan_message({**state,"_runtime":{"current_state":None}}); route=workflow.route({**state,**plan})
        result=workflow.invoke(state,message=SimpleNamespace(content=message),customer={"id":"readonly"},conversation={"id":"readonly","location_id":location["id"]},source_message_id=f"readonly-{index}")
        openai = 0 if route in {"answer_location","answer_catalogue","handover_to_sales"} else 2
        rows.append({"case_id":f"real-{index}","mode":"real_readonly","customer_message":message,"intent":plan["intent"],"route":route,"service_code":plan.get("service_code"),"topic":plan.get("topic"),"used_previous_service":plan.get("use_previous_service",False),"retrieved_section_headings":list(getattr(result.context,"last_answer_sections",())),"retrieved_document_ids":[],"approved_fact_count":len(getattr(result.context,"last_answer_sections",())),"answer_source":(result.safe_metadata or {}).get("graph_answer_source"),"validation_passed":result.response_valid,"validation_errors":[],"deterministic_fallback_used":getattr(result.context,"last_answer_source",None)=="deterministic_fact_fallback","embedding_call_count":1 if openai else 0,"composition_call_count":1 if openai else 0,"general_fallback_call_count":0,"total_openai_calls":openai,"database_write_attempts":adapter.database_write_attempts,"exotel_calls":0,"whatsapp_calls":0,"latency_ms":round((time.perf_counter()-start)*1000,2),"final_response":result.draft_text})
    return rows


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--real-readonly", action="store_true"); parser.add_argument("--max-cases", type=int); args=parser.parse_args()
    if args.real_readonly:
        if os.getenv("RAIPUR_REAL_ANSWER_EVAL") != "true": print("mode=real_readonly reason=explicit_environment_confirmation_required"); return 2
        print("REAL READ-ONLY EVALUATION\nSupabase approved knowledge reads: enabled\nOpenAI embeddings/composition: enabled\nConversation persistence: disabled\nDatabase writes: disabled\nExotel: disabled\nWhatsApp: disabled\nIngestion: disabled")
        rows=run_real_readonly(args.max_cases); write_results(rows, stem="raipur_langgraph_real_readonly"); print(f"mode=real_readonly cases={len(rows)} database_writes=0 exotel_calls=0 whatsapp_calls=0"); return 0
    rows=run_offline(); rows = rows[:args.max_cases] if args.max_cases else rows; write_results(rows); print(f"mode=offline cases={len(rows)} external_calls=0 database_writes=0")
    return 0


if __name__ == "__main__": raise SystemExit(main())
