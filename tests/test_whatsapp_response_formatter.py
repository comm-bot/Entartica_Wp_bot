from app.services.whatsapp_response_formatter import format_whatsapp_response, repair_known_mojibake, validate_whatsapp_response


def _format(text, **kwargs):
    return format_whatsapp_response(text=text, intent="service_topic", response_mode="grounded_answer", service_code="water_bike", service_display_name="Water Bike", topic="how_it_works", language="en", **kwargs)


def test_service_facts_become_compact_whatsapp_bullets_without_changes():
    answer = _format("Guests pedal the Water Bike like a bicycle. Dual pontoon floats provide stability. Handlebars are used for steering.")
    assert answer.startswith("*How the Water Bike Works*")
    assert answer.count("•") == 3
    assert "\u00e2\u20ac\u00a2" not in answer
    assert "Dual pontoon floats provide stability." in answer


def test_topic_heading_uses_service_for_duration():
    answer = format_whatsapp_response(text="Sessions generally last around 5 to 10 minutes. Timing depends on weather and operating conditions.", intent="service_topic", response_mode="grounded_answer", service_code="jet_ski_ride", service_display_name="Jet Ski Ride", topic="duration", language="en")
    assert answer.startswith("*Jet Ski Ride Duration*")
    assert "5 to 10 minutes" in answer


def test_greeting_and_gratitude_remain_short_and_context_free():
    assert format_whatsapp_response(text="Hello! How may I help you with Entartica Sea World, Raipur?", intent="greeting", response_mode="conversational_acknowledgement", service_code="water_bike", service_display_name="Water Bike", topic="overview", language="en") == "Hello! How may I help you with Entartica Sea World, Raipur?"
    assert format_whatsapp_response(text="You're welcome!", intent="greeting", response_mode="conversational_acknowledgement", service_code=None, service_display_name=None, topic=None, language="en") == "You're welcome!"


def test_handover_preserves_approved_contact_without_duplicate_block():
    value = format_whatsapp_response(text="For current prices, contact the sales team.\n\nPhone: +91 9429691418\nEmail: sales@entartica.com", intent="pricing", response_mode="human_handover", service_code=None, service_display_name=None, topic=None, language="en", requires_handover=True)
    assert value.startswith("*Price & Booking*")
    assert value.count("+91 9429691418") == 1


def test_structured_location_is_presented_without_inventing_address_or_map():
    value = format_whatsapp_response(text="Entartica Sea World Raipur is located at Sector 24, Jhanjh Lake.\n\nGoogle Maps:\nhttps://maps.example/raipur", intent="location", response_mode="deterministic_location", service_code=None, service_display_name=None, topic=None, language="en")
    assert value.startswith("*Entartica Sea World Raipur*")
    assert "Sector 24, Jhanjh Lake" in value
    assert "https://maps.example/raipur" in value


def test_validator_rejects_internal_metadata_but_not_plain_answer():
    assert validate_whatsapp_response("*Water Bike*\n\n• Guests pedal like a bicycle")[0]
    assert not validate_whatsapp_response("Suggested Chatbot Response: use RAG chunk")[0]


def test_catalogue_bullets_and_known_mojibake_repair_are_unicode_safe():
    catalogue = "*Celebrations*\n\n\u2022 Floating Gazebo\n\u2022 Houseboat Celebration"
    formatted = format_whatsapp_response(
        text=catalogue, intent="service_catalogue", response_mode="grounded_answer",
        service_code=None, service_display_name=None, topic=None, language="en",
    )

    assert "\u2022 Floating Gazebo" in formatted
    assert "\u2022 Houseboat Celebration" in formatted
    assert "\u00e2\u20ac\u00a2" not in formatted
    assert repair_known_mojibake("\u00e2\u20ac\u00a2 \u00e2\u201a\u00b9300") == "\u2022 \u20b9300"


def test_formatter_preserves_hindi_and_unicode_without_reencoding():
    value = "\u0928\u092e\u0938\u094d\u0924\u0947\n\u092a\u0924\u093e \u092d\u0947\u091c\u094b\n\u20b9300\nEntartica Sea World, Raipur\nbirthday celebration"

    assert format_whatsapp_response(
        text=value, intent="service_catalogue", response_mode="grounded_answer",
        service_code=None, service_display_name=None, topic=None, language="hinglish",
    ) == value
