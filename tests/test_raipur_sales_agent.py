from app.services.raipur.sales_agent import SalesAgent, SalesAgentBrief
from app.services.raipur.sales_response_composer import ResponseGoal, SalesResponseBrief


def _brief(message="birthday celebration for 12 people, something lively"):
    return SalesAgentBrief(
        current_message=message,
        compact_context={"active_domain": "celebration"},
        response_brief=SalesResponseBrief(
            ResponseGoal.CELEBRATION_DISCOVERY, "en",
            approved_options=("Party Boat Celebration", "Floating Gazebo"),
        ),
    )


def test_sales_agent_returns_reply_and_validated_understanding():
    agent = SalesAgent(lambda brief: {
        "reply": "Party Boat Celebration is one approved option. How many guests are coming?",
        "intent": "celebration", "occasion": "birthday", "guest_count": 12,
        "preference": "lively_party", "language": "en", "confidence": .97,
    })
    result = agent.respond(_brief())
    assert result.valid and result.understanding is not None
    assert result.understanding.guest_count == 12
    assert result.understanding.preference == "lively_party"


def test_sales_agent_rejects_unsafe_output_without_retry():
    calls = []
    agent = SalesAgent(lambda brief: calls.append(brief) or {
        "reply": "Your booking is confirmed and costs Rs 100.", "confidence": .9,
    })
    result = agent.respond(_brief())
    assert not result.valid and result.reply is None and len(calls) == 1


def test_sales_agent_canonicalizes_service_mention():
    agent = SalesAgent(lambda _brief: {
        "reply": "Party Boat Celebration is an approved option.",
        "intent": "service_question", "service_mention": "party boat",
        "confidence": .95,
    })
    result = agent.respond(_brief("tell me about party boat"))
    assert result.valid and result.understanding.service_code == "party_boat_celebration"
