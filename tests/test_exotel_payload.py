"""Tests for the confirmed Exotel WhatsApp payload envelope."""

from datetime import UTC, datetime

from app.integrations.exotel import _parse_flow_response_json, normalize_exotel_payload


def _text_message(*, sid: str | None = "message-1") -> dict:
    message = {
        "callback_type": "incoming_message",
        "from": "917700000000",
        "to": "919900000000",
        "timestamp": "2022-10-19T21:48:31+05:30",
        "profile_name": "John",
        "content": {"type": "text", "text": {"body": "Hi"}},
    }
    if sid is not None:
        message["sid"] = sid
    return message


def test_normalizes_incoming_text_payload() -> None:
    """The confirmed dashboard text envelope becomes a normalized message."""

    messages = normalize_exotel_payload({"whatsapp": {"messages": [_text_message()]}})

    assert len(messages) == 1
    assert messages[0].external_message_id == "message-1"
    assert messages[0].message_type == "text"
    assert messages[0].content == "Hi"
    assert messages[0].received_at == datetime(2022, 10, 19, 16, 18, 31, tzinfo=UTC)


def test_normalizes_incoming_flow_payload() -> None:
    """A Flow response stores only its safe display body, not form values."""

    response_json = '{"terms_and_conditions":true,"name":"John Doe"}'
    payload = {
        "whatsapp": {
            "messages": [
                {
                    "callback_type": "incoming_message",
                    "sid": "flow-message-1",
                    "from": "917700000000",
                    "to": "919900000000",
                    "timestamp": "2023-10-22T20:34:40+05:30",
                    "profile_name": "John",
                    "content": {
                        "type": "interactive",
                        "interactive": {
                            "type": "flow",
                            "nfm_reply": {"body": "Sent", "response_json": response_json},
                        },
                    },
                }
            ]
        }
    }

    message = normalize_exotel_payload(payload)[0]

    assert message.message_type == "flow"
    assert message.content == "Sent"
    assert _parse_flow_response_json(payload["whatsapp"]["messages"][0]["content"]) == {
        "terms_and_conditions": True,
        "name": "John Doe",
    }


def test_malformed_flow_response_json_does_not_crash() -> None:
    """Malformed Flow form JSON is ignored without exposing or storing it."""

    content = {
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "nfm_reply": {"body": "Sent", "response_json": "{"},
        },
    }
    payload = {"whatsapp": {"messages": [_text_message()]}}
    payload["whatsapp"]["messages"][0]["content"] = content

    message = normalize_exotel_payload(payload)[0]

    assert message.message_type == "flow"
    assert _parse_flow_response_json(content) is None


def test_missing_sid_uses_deterministic_fallback_id() -> None:
    """The same canonical no-SID message always produces the same hash ID."""

    payload = {"whatsapp": {"messages": [_text_message(sid=None)]}}

    first = normalize_exotel_payload(payload)[0]
    second = normalize_exotel_payload(payload)[0]

    assert first.external_message_id == second.external_message_id
    assert len(first.external_message_id) == 64


def test_unsupported_callback_type_is_ignored() -> None:
    """Only incoming-message callbacks enter the persistence workflow."""

    message = _text_message()
    message["callback_type"] = "delivery_status"

    assert normalize_exotel_payload({"whatsapp": {"messages": [message]}}) == []
