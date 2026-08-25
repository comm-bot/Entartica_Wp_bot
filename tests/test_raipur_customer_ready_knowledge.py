"""Customer-ready service answers never render KB governance prose."""
from types import SimpleNamespace

from app.rag.customer_ready_knowledge import build_customer_ready_service_answer
from app.rag.raipur_knowledge_provider import RaipurKnowledgeProvider
from app.services.raipur_services import APPROVED_RAIPUR_SERVICES
from app.services.raipur_langgraph import RaipurLangGraphWorkflow
from app.services.whatsapp_response_formatter import format_whatsapp_response


FORBIDDEN = (
    "published configuration", "should not be assumed", "current entartica pages",
    "different durations", "customer-ready format", "conflict", "facts to verify",
    "not established", "production value",
)


class _Response:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, client, table): self.client, self.table_name = client, table
    def select(self, *_args): return self
    def eq(self, *_args): return self
    def execute(self): return _Response(self.client.docs if self.table_name == "knowledge_documents" else self.client.chunks)


class _Client:
    docs = [{"id":"party-doc","source_file":"party_boat_celebration.md","is_active":True,"metadata":{"location_code":"raipur","service_code":"party_boat_celebration","approval_status":"approved","customer_facing":True}}]
    chunks = [
        {"knowledge_document_id":"party-doc","content":"The Party Boat Celebration is an on-water group celebration designed for music, socialising, and special occasions together. It offers an energetic group atmosphere for birthdays and corporate gatherings.","metadata":{"section_heading":"Experience Overview"}},
        {"knowledge_document_id":"party-doc","content":"- Creates a group celebration setting directly on the water.\n- Music adds energy to the onboard atmosphere.\n- Suitable for social and corporate occasions.","metadata":{"section_heading":"What Makes This Experience Special"}},
        {"knowledge_document_id":"party-doc","content":"- Large-group format\n- Music available on board\n- Lively celebration atmosphere","metadata":{"section_heading":"Experience Highlights"}},
        {"knowledge_document_id":"party-doc","content":"Starting celebration duration:\n\n**2 hours**\n\nExtensions may be possible only after confirmation and are not automatically included.\n\nOther current Entartica pages display different Party Boat durations or ride formats. These do not replace the approved 2-hour starting duration.","metadata":{"section_heading":"Duration"}},
        {"knowledge_document_id":"party-doc","content":"Approved celebration-service operating hours:\n\n**10:00 AM to 9:00 PM**\n\nAll timings remain subject to weather and operational conditions.","metadata":{"section_heading":"Operating Hours"}},
        {"knowledge_document_id":"party-doc","content":"Party Boat Celebration is a group-oriented celebration experience. Private charter arrangements are published as available, but exclusive use should not be assumed.","metadata":{"section_heading":"Access Type"}},
    ]
    def table(self, name): return _Query(self, name)


class _Services:
    def list_active_for_location(self, _location):
        return [{"name": item.name, "slug": item.slug, "is_active": True} for item in APPROVED_RAIPUR_SERVICES]


def _state(message):
    return {"message_id":"m","conversation_id":"c","customer_id":"u","customer_message":message,"normalized_message":message.casefold(),"language":"en","location_code":"raipur","previous_service_code":None,"previous_topic":None,"intent":None,"entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"selected_route":None,"answer_source":None,"validation_errors":[],"plan_consistency_repaired":False,"invocation_id":"i","draft_response":None,"validation_status":"pending","error":None,"route":None}


def _turn(workflow, message, context=None):
    result = workflow.invoke(_state(message), message=SimpleNamespace(content=message), customer={"id":"u"}, conversation={"id":"c","location_id":"raipur"}, source_message_id="m", current_state=context)
    metadata = result.safe_metadata or {}
    formatted = format_whatsapp_response(
        text=result.draft_text, intent=result.detected_intent, response_mode=metadata.get("response_mode"),
        service_code=metadata.get("service_code"), service_display_name=result.context.last_service_name,
        topic=metadata.get("topic"), language=result.response_language,
        requires_handover=result.human_handover_required,
    )
    return result, formatted


def _assert_customer_ready(text):
    lowered = text.casefold()
    assert all(term not in lowered for term in FORBIDDEN)


def test_party_boat_three_turn_path_uses_customer_ready_sections_only():
    provider = RaipurKnowledgeProvider(_Client(), SimpleNamespace(raipur_knowledge_min_confidence=.65), embed_query_fn=lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    workflow = RaipurLangGraphWorkflow(knowledge=provider, services=_Services())

    overview, overview_text = _turn(workflow, "can you tell me about party baot clebration")
    more, more_text = _turn(workflow, "can you tell me more about it", overview.context)
    duration, duration_text = _turn(workflow, "how long can I access it?", more.context)
    timings, timings_text = _turn(workflow, "what are its timings?", duration.context)

    assert overview.context.last_service_code == "party_boat_celebration"
    assert overview.safe_metadata["selected_section_heading"] == "Experience Overview"
    assert "group celebration" in overview_text.casefold()
    assert more.context.last_service_code == "party_boat_celebration"
    assert "music" in more_text.casefold() and more_text != overview_text
    assert duration.context.last_service_code == "party_boat_celebration"
    assert "2 hours" in duration_text.casefold()
    assert timings.context.last_service_code == "party_boat_celebration"
    assert "10:00 am to 9:00 pm" in timings_text.casefold()
    for text in (overview_text, more_text, duration_text, timings_text): _assert_customer_ready(text)


def test_customer_ready_overviews_for_other_services_drop_governance_sentences():
    services = (
        ("floating_gazebo", "Floating Gazebo"),
        ("houseboat_celebration", "Houseboat Celebration"),
        ("pontoon_celebration", "Pontoon Celebration"),
    )
    for code, name in services:
        ready = build_customer_ready_service_answer([
            ("Experience Overview", f"{name} offers a scenic customer celebration experience. Current Entartica pages display different internal arrangements."),
        ], service_name=name, service_code=code, detail_mode="overview")
        assert ready.text and name in ready.text
        _assert_customer_ready(ready.text)


def test_formatter_defensively_blocks_governance_without_customer_ready_error_text():
    value = format_whatsapp_response(
        text="The production value has a conflict in the knowledge document.",
        intent="service_topic", response_mode="grounded_answer", service_code="party_boat_celebration",
        service_display_name="Party Boat Celebration", topic="duration", language="en",
    )
    _assert_customer_ready(value)
    assert "approved overview" in value.casefold()
