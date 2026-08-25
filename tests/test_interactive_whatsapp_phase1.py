from datetime import UTC, datetime
from types import SimpleNamespace

from app.integrations.exotel import ExotelClient, normalize_exotel_payload
from app.schemas.interactive_messages import celebration_selector, configured_flow, location_selector
from app.services.raipur.interactive_journey import merge_form_response, merge_natural_visit_details, qualification_reply
from app.services.raipur.response_models import ConversationContext, ConversationResult
from app.services.booking_enquiries import BookingDetails
from app.services.raipur_inbound_orchestrator import (
    _context_from_record, _context_to_record, _interactive_gate_result, _offer_celebration_selector,
    _offer_interactive_form,
)


def _context(location=None, **changes):
    base = ConversationContext(
        BookingDetails(None, None, None, None, None, None, None),
        selected_location=location,
    )
    return base.__class__(**{**base.__dict__, **changes})


def _message(text, *, message_type="text", form_response=None):
    return SimpleNamespace(content=text, message_type=message_type, form_response=form_response)


def test_unresolved_customer_gets_four_item_location_list_and_raipur_persists():
    selector = _interactive_gate_result(_message("hi"), None, settings=SimpleNamespace())
    spec = selector.safe_metadata["interactive_message"]
    assert spec["kind"] == "list"
    assert [item["title"] for item in spec["options"]] == ["Raipur", "Coimbatore", "Prayagraj", "Rajsamand"]

    selected = _interactive_gate_result(_message("location_raipur"), selector.context, settings=SimpleNamespace())
    assert selected.context.selected_location == "raipur"
    assert selected.draft_text.startswith("Hello, this is Chiki from Entartica SeaWorld 😊")
    assert "Which location are you coming from?" in selected.draft_text
    assert "How can I help you explore" not in selected.draft_text
    record = _context_to_record(selected.context)
    restored, expired = _context_from_record(record, 120)
    assert not expired and restored.selected_location == "raipur"


def test_inactive_locations_never_continue_to_raipur_and_change_reopens_selector():
    for location in ("coimbatore", "prayagraj", "rajsamand"):
        result = _interactive_gate_result(_message(location), None, settings=SimpleNamespace())
        assert result.context.selected_location == location
        assert "being prepared" in result.draft_text
        blocked = _interactive_gate_result(_message("tell me about jet ski"), result.context, settings=SimpleNamespace())
        assert "being prepared" in blocked.draft_text
    changed = _interactive_gate_result(_message("change location"), _context("raipur"), settings=SimpleNamespace())
    assert changed.context.selected_location is None
    assert changed.safe_metadata["location_selector_sent"] is True


def test_exotel_serializes_location_list_and_flow_without_changing_endpoint_shape():
    client = ExotelClient(account_sid="sid", api_key="key", api_token="token", whatsapp_from="+911111111111")
    list_payload = client.build_interactive_payload(to_number="+912222222222", interactive=location_selector())
    content = list_payload["whatsapp"]["messages"][0]["content"]
    assert content["type"] == "interactive" and content["interactive"]["type"] == "list"
    assert len(content["interactive"]["action"]["sections"][0]["rows"]) == 4

    celebration_payload = client.build_interactive_payload(
        to_number="+912222222222", interactive=celebration_selector("Choose a celebration")
    )
    celebration_ui = celebration_payload["whatsapp"]["messages"][0]["content"]["interactive"]
    rows = celebration_ui["action"]["sections"][0]["rows"]
    assert celebration_ui["type"] == "list"
    assert celebration_ui["action"]["button"] == "Choose Celebration"
    assert [row["id"] for row in rows] == [
        "celebration_floating_gazebo", "celebration_houseboat", "celebration_jetty_gazebo",
        "celebration_party_boat", "celebration_pontoon",
    ]

    flow = configured_flow(flow_type="general_quote", flow_id="configured-flow-id")
    flow_payload = client.build_interactive_payload(to_number="+912222222222", interactive=flow)
    parameters = flow_payload["whatsapp"]["messages"][0]["content"]["interactive"]["action"]["parameters"]
    assert parameters["flow_id"] == "configured-flow-id"
    assert parameters["flow_token"] == "entartica_general_quote"


def test_list_reply_and_flow_submission_are_normalized_structurally():
    base = {
        "callback_type": "incoming_message", "sid": "m1", "from": "+912222222222", "to": "+911111111111",
        "timestamp": "2026-08-17T10:00:00+05:30", "profile_name": "Customer",
    }
    list_payload = {"whatsapp": {"messages": [{**base, "content": {"type": "interactive", "interactive": {
        "type": "list_reply", "list_reply": {"id": "location_raipur", "title": "Raipur"},
    }}}]}}
    normalized = normalize_exotel_payload(list_payload)[0]
    assert normalized.message_type == "text" and normalized.content == "location_raipur"

    list_payload["whatsapp"]["messages"][0]["sid"] = "m-celebration"
    list_reply = list_payload["whatsapp"]["messages"][0]["content"]["interactive"]["list_reply"]
    list_reply.update(id="celebration_floating_gazebo", title="Floating Gazebo")
    normalized = normalize_exotel_payload(list_payload)[0]
    assert normalized.message_type == "text" and normalized.content == "Floating Gazebo"

    list_payload["whatsapp"]["messages"][0]["sid"] = "m-pontoon"
    list_reply.update(id="celebration_pontoon", title="Pontoon Boat Celebration")
    normalized = normalize_exotel_payload(list_payload)[0]
    assert normalized.content == "Pontoon Boat Celebration"

    flow_payload = {"whatsapp": {"messages": [{**base, "sid": "m2", "content": {"type": "interactive", "interactive": {
        "type": "nfm_reply", "nfm_reply": {"body": "Sent", "response_json": '{"flow_type":"general_quote","adults":2,"kids":1}'},
    }}}]}}
    normalized = normalize_exotel_payload(flow_payload)[0]
    assert normalized.message_type == "flow"
    assert normalized.form_response == {"flow_type": "general_quote", "adults": 2, "kids": 1}


def test_general_and_celebration_forms_validate_merge_and_never_confirm_booking():
    general, errors = merge_form_response(_context("raipur"), {
        "flow_type": "general_quote", "check_in_date": "2026-08-20", "check_out_date": "2026-08-21",
        "adults": 2, "kids": 1, "kids_age": "8",
    })
    assert not errors and general.form_status == "submitted"
    assert general.details.adults_count == 2 and general.details.children_count == 1
    assert general.form_values["kids_ages"] == [8]

    celebration, errors = merge_form_response(_context("raipur"), {
        "flow_type": "celebration", "name": "Guest", "number_of_persons": 12,
        "date_of_visiting": "2026-08-25", "hanging": "provided detail", "put_on_cake": "Happy Birthday",
    })
    assert not errors and celebration.details.total_guests == 12
    assert celebration.form_values["hanging"] == "provided detail"
    assert celebration.form_values["cake_text"] == "Happy Birthday"


def test_pontoon_selection_offers_dedicated_flow_only_when_configured():
    result = ConversationResult(
        action="answer_information", detected_intent="service_overview", draft_text="What date and how many persons?",
        reason_code="test", detected_location="raipur", response_language="en", human_handover_required=False,
        context=_context("raipur", last_service_code="pontoon_celebration", active_journey="celebration"),
        safe_metadata={
            "pontoon_media_attached": True,
            "package_source_file": "active/services/pontoon_celebration.md",
            "media_message": {"type": "image", "url": "https://example.test/pontoon.jpg", "caption": "Approved package"},
        },
    )
    missing = _offer_interactive_form(result, "Pontoon Boat Celebration", SimpleNamespace(raipur_pontoon_celebration_flow_id=None))
    assert "interactive_message" not in missing.safe_metadata
    assert missing.draft_text == "What date and how many persons?"

    flow_only = _offer_interactive_form(result, "Pontoon Boat Celebration", SimpleNamespace(
        raipur_pontoon_celebration_flow_id="flow-1", raipur_pontoon_celebration_template_id=None,
    ))
    assert "template_message" not in flow_only.safe_metadata
    assert "interactive_message" not in flow_only.safe_metadata

    offered = _offer_interactive_form(result, "Pontoon Boat Celebration", SimpleNamespace(
        raipur_pontoon_celebration_flow_id="flow-1", raipur_pontoon_celebration_template_id="template-1",
    ))
    assert offered.safe_metadata["template_message"]["name"] == "template-1"
    assert offered.safe_metadata["template_message"]["flow_id"] == "flow-1"
    assert offered.safe_metadata["template_message"]["flow_cta"] == "Share Event Details"
    assert "media_message" not in offered.safe_metadata
    assert "interactive_message" not in offered.safe_metadata
    assert offered.safe_metadata["flow_type"] == "pontoon_celebration"
    assert offered.context.active_form == "pontoon_celebration"


def test_pontoon_flow_submission_maps_structured_fields_and_natural_acknowledgement():
    context = _context(
        "raipur", last_service_code="pontoon_celebration", active_journey="celebration",
        active_form="pontoon_celebration", pending_slots={"pontoon_media_sent": "true"},
    )
    result = _interactive_gate_result(_message(
        "Sent", message_type="flow", form_response={"event_date": "2026-08-25", "number_of_persons": 6},
    ), context, settings=SimpleNamespace())
    assert result.context.details.preferred_date.isoformat() == "2026-08-25"
    assert result.context.details.total_guests == 6
    assert result.context.form_values == {"guest_count": 6, "planned_date": "2026-08-25"}
    assert result.context.last_service_code == "pontoon_celebration"
    assert result.context.pending_slots["pontoon_media_sent"] == "true"
    assert "25 August" in result.draft_text and "6 guests" in result.draft_text
    assert "noted the celebration details" not in result.draft_text


def test_pontoon_flow_past_date_retains_valid_guests_and_requests_only_date():
    context = _context(
        "raipur", last_service_code="pontoon_celebration", active_journey="celebration",
        active_form="pontoon_celebration", pending_slots={"pontoon_media_sent": "true"},
    )
    result = _interactive_gate_result(_message(
        "Sent", message_type="flow", form_response={"event_date": "2026-08-15", "number_of_persons": 6},
    ), context, settings=SimpleNamespace())
    assert result.context.details.preferred_date is None
    assert result.context.details.total_guests == 6
    assert result.context.form_values == {"guest_count": 6}
    assert "future date" in result.draft_text.casefold()
    assert "number of persons" not in result.draft_text.casefold()


def test_natural_visit_details_merge_without_erasing_existing_values():
    merged = merge_natural_visit_details(_context("raipur"), "2 adults and 2 kids, ages 5 and 9")
    assert merged.details.total_guests == 4
    assert merged.form_values["kids_ages"] == [5, 9]


def test_post_raipur_multifield_reply_extracts_date_guests_and_customer_origin():
    context = _context("raipur", active_journey="visit_qualification")
    merged = merge_natural_visit_details(context, "20 August, 4 persons, Ahmedabad")
    assert merged.details.preferred_date is not None
    assert merged.details.total_guests == 4
    assert merged.form_values["customer_location"] == "Ahmedabad"
    assert qualification_reply(merged).startswith("Great 😊 I have your visit details")


def test_post_raipur_adult_child_reply_derives_total_and_origin():
    context = _context("raipur", active_journey="visit_qualification")
    merged = merge_natural_visit_details(context, "23 Aug, 2 adults and 1 kid from Bhilai")
    assert merged.details.adults_count == 2 and merged.details.children_count == 1
    assert merged.details.total_guests == 3
    assert merged.form_values["customer_location"] == "Bhilai"


def test_post_raipur_partial_date_asks_only_for_missing_details():
    context = _context("raipur", active_journey="visit_qualification")
    merged = merge_natural_visit_details(context, "20 August")
    reply = qualification_reply(merged)
    assert merged.details.preferred_date is not None
    assert "how many persons" in reply and "which city" in reply
    assert "which date" not in reply


def test_broad_celebration_result_gets_one_five_item_list_but_specific_service_does_not():
    broad = ConversationResult(
        action="answer_information", detected_intent="celebration_service_list",
        draft_text="Approved celebration options", reason_code="test", detected_location="raipur",
        response_language="en", human_handover_required=False,
        context=_context("raipur", active_journey="celebration"), safe_metadata={},
    )
    offered = _offer_celebration_selector(broad)
    interactive = offered.safe_metadata["interactive_message"]
    assert interactive["kind"] == "list" and len(interactive["options"]) == 5
    assert offered.draft_text == "Approved celebration options"

    specific = ConversationResult(
        action="answer_information", detected_intent="service_overview",
        draft_text="Floating Gazebo approved detail", reason_code="test", detected_location="raipur",
        response_language="en", human_handover_required=False,
        context=_context("raipur", last_service_code="floating_gazebo"), safe_metadata={},
    )
    assert _offer_celebration_selector(specific) is specific
