"""Tests for the typed outbound Exotel client and disabled send workflow."""

import asyncio
import logging

import httpx
import pytest

from app.config import Settings
from app.integrations.exotel import (
    ExotelAcceptedMessage,
    ExotelAuthenticationError,
    ExotelClient,
    ExotelConnectionError,
    ExotelProviderResponseError,
    ExotelTimeoutError,
    ExotelValidationError,
)
from app.services.outbound_messages import (
    OutboundMessageError,
    OutboundMessageService,
    OutboundMessagingDisabledError,
)
from app.schemas.interactive_messages import InteractiveMessage, InteractiveOption, customer_details_flow
from app.services.coimbatore.pontoon_package import returning_customer_menu
from app.services.latency import LatencyTrace, use_latency_trace


def test_customer_details_flow_payload_uses_published_mode_and_first_screen() -> None:
    interactive = customer_details_flow(
        flow_id="27532617159750529",
        flow_token="opaque-conversation-token",
    )

    payload = _client(lambda request: httpx.Response(202)).build_interactive_payload(
        to_number="+919000000000", interactive=interactive,
    )

    parameters = payload["whatsapp"]["messages"][0]["content"]["interactive"]["action"]["parameters"]
    assert parameters == {
        "mode": "published",
        "flow_message_version": "3",
        "flow_token": "opaque-conversation-token",
        "flow_id": "27532617159750529",
        "flow_cta": "Complete Details",
        "flow_action": "navigate",
        "flow_action_payload": {"screen": "CUSTOMER_DETAILS"},
    }


def test_standard_package_provider_payload_is_one_image_header_body_and_four_row_list() -> None:
    image_url = "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/pontoon_boat_celebration_Coimbtore.jpg"
    body = (
        "Pontoon Boat Celebration Package ✨\n\n"
        "📅 Event Date: 22 Aug 2026\n👥 Guests: 5\n\n"
        "🎉 Inclusions:\n• Red Carpet Welcome\n• 02 Cold Pyro Entry\n• Cake\n"
        "• Music Setup\n• Decoration\n• Cake cutting in the middle of the serene lake\n"
        "• 30 Minutes Premium Boat Ride\n\n💰 Rack Rate: ₹5,999\n"
        "😍 Offer / Discounted Rate: ₹4,999\n🔒 Pay a token of ₹1,000\n\nAPPROVED ADD-ONS"
    )
    interactive = InteractiveMessage(
        kind="list", body=body, fallback_text=body, button_label="Package Actions",
        options=tuple(InteractiveOption(identifier, title) for identifier, title in (
            ("coimbatore_pontoon_book_standard", "Book Now"),
            ("coimbatore_pontoon_ask_question", "Ask a Question"),
            ("coimbatore_pontoon_customize", "Customize"),
            ("coimbatore_pontoon_more_photos", "See Photo & Video"),
        )),
        header_image_url=image_url,
    )
    payload = _client(lambda request: httpx.Response(202)).build_interactive_payload(
        to_number="+919000000000", interactive=interactive,
    )
    messages = payload["whatsapp"]["messages"]
    assert len(messages) == 1
    provider = messages[0]["content"]["interactive"]
    assert messages[0]["content"]["type"] == "interactive"
    assert provider["type"] == "list"
    assert provider["header"] == {"type": "image", "image": {"link": image_url}}
    assert provider["body"]["text"] == body
    assert len(provider["action"]["sections"][0]["rows"]) == 4
    assert provider["body"]["text"] != "What would you like to do next?"


def test_returning_customer_menu_is_one_image_header_message_with_three_buttons() -> None:
    payload = _client(lambda request: httpx.Response(202)).build_interactive_payload(
        to_number="+919000000000", interactive=returning_customer_menu(),
    )

    messages = payload["whatsapp"]["messages"]
    assert len(messages) == 1
    provider = messages[0]["content"]["interactive"]
    assert provider["type"] == "button"
    assert provider["header"] == {"type": "image", "image": {"link": (
        "https://coimbatore-chatbot.s3.ap-south-1.amazonaws.com/"
        "pontoon_boat_celebration_Coimbtore.jpg"
    )}}
    assert [button["reply"]["title"] for button in provider["action"]["buttons"]] == [
        "See Standard Package", "See Couple Package", "Photos & Videos",
    ]


def test_mocked_two_second_exotel_delay_is_attributed_to_http_stage() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(202, json={"response":{"whatsapp":{"messages":[
            {"code":202, "status":"success", "data":{"sid":"delayed-provider-sid"}}
        ]}}})

    trace = LatencyTrace(request_id="delayed-exotel")
    with use_latency_trace(trace):
        result = asyncio.run(_client(handler).send_text_message("+919000000000", "Approved text"))
    assert result.provider_message_id == "delayed-provider-sid"
    assert 1900 <= trace.stages_ms["Exotel_HTTP_request"] < 2600


def _client(handler) -> ExotelClient:
    return ExotelClient(
        account_sid="account",
        api_key="key",
        api_token="token",
        whatsapp_from="+919900000000",
        transport=httpx.MockTransport(handler),
    )


def test_send_text_message_accepts_202_and_parses_sid(caplog) -> None:
    """The client submits the documented JSON envelope and returns its SID."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/accounts/account/messages"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["authorization"] == "Basic a2V5OnRva2Vu"
        payload = __import__("json").loads(request.content)
        assert payload["status_callback"] == "https://example.test/status"
        assert payload["whatsapp"]["messages"][0]["content"]["type"] == "text"
        return httpx.Response(
            202,
            json={
                "http_code": 202,
                "response": {
                    "whatsapp": {
                        "messages": [
                            {"code": 202, "status": "success", "data": {"sid": "provider-1"}}
                        ]
                    }
                },
            },
        )

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(
            _client(handler).send_text_message(
                "+919000000000", "private message", "https://example.test/status", "internal-1"
            )
        )

    assert result == ExotelAcceptedMessage(provider_message_id="provider-1")
    assert "+919000000000" not in caplog.text
    assert "private message" not in caplog.text
    assert "token" not in caplog.text


def test_send_text_message_keeps_unicode_catalogue_text_as_json_string(caplog) -> None:
    text = "\u2022 Floating Gazebo\n\u2022 Houseboat Celebration\n\u20b9 \u0928\u092e\u0938\u094d\u0924\u0947"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"] == "application/json"
        assert isinstance(request.content, bytes)
        body = request.content.decode("utf-8")
        assert "\u2022 Floating Gazebo" in body
        assert "\u00e2\u20ac\u00a2" not in body
        assert __import__("json").loads(body)["whatsapp"]["messages"][0]["content"]["text"]["body"] == text
        return httpx.Response(202, json={"response": {"whatsapp": {"messages": [{"code": 202, "status": "success", "data": {"sid": "provider-1"}}]}}})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = asyncio.run(_client(handler).send_text_message("+919000000000", text))

    assert result.provider_message_id == "provider-1"
    trace = next(message for message in caplog.messages if "event=outbound_unicode_trace" in message)
    assert "contains_mojibake=False" in trace
    assert "contains_unicode_bullet=True" in trace


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(400, ExotelValidationError), (401, ExotelAuthenticationError), (503, ExotelProviderResponseError)],
)
def test_send_text_message_maps_http_errors(status_code: int, error_type: type[Exception]) -> None:
    """Provider HTTP failures map to safe typed errors."""

    with pytest.raises(error_type):
        asyncio.run(
            _client(lambda request: httpx.Response(status_code)).send_text_message(
                "+919000000000", "test", "https://example.test/status", "internal-1"
            )
        )


def test_rejected_send_logs_only_safe_metadata(caplog) -> None:
    """A provider validation response never writes request or error values to logs."""

    response = {
        "http_code": 400,
        "whatsapp": {
            "messages": [
                {
                    "code": "INVALID_FROM",
                    "status": "failed",
                    "validation_field": "from",
                    "description": "private provider explanation",
                }
            ]
        },
    }
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelValidationError):
            asyncio.run(
                _client(
                    lambda request: httpx.Response(
                        400,
                        json=response,
                        headers={"content-type": "application/json", "x-request-id": "request-12345678"},
                    )
                ).send_text_message(
                    "+919000000000",
                    "private customer message",
                    "https://private.example.test/webhooks/exotel/status",
                    "private-custom-data",
                )
            )

    diagnostic = caplog.messages[-1]
    assert "operation=exotel_send" in diagnostic
    assert "outcome_category=definite_rejection" in diagnostic
    assert "request_started=true" in diagnostic
    assert "http_status=400" in diagnostic
    assert "provider_http_code=400" in diagnostic
    assert "provider_message_code=INVALID_FROM" in diagnostic
    assert "provider_status=failed" in diagnostic
    assert "provider_field=from" in diagnostic
    assert "from_e164_valid=True" in diagnostic
    assert "to_e164_valid=True" in diagnostic
    for secret_or_personal_value in (
        "token",
        "account",
        "+919900000000",
        "+919000000000",
        "private customer message",
        "private.example.test",
        "private-custom-data",
        "private provider explanation",
        "request-12345678",
    ):
        assert secret_or_personal_value not in diagnostic
    for field in ("request_url_shape_valid=True", "authentication_present=True", "sender_present=True", "recipient_present=True", "callback_present=True", "payload_schema=whatsapp.messages.text"):
        assert field in diagnostic


@pytest.mark.parametrize(
    ("response", "schema", "category", "field"),
    [
        (
            {"RestException": {"Status": 400, "Message": "Sender +919000000000 is invalid"}},
            "RestException",
            "invalid_sender",
            "from",
        ),
        (
            {"error": {"parameter": "content", "message": "private provider text"}},
            "error",
            "unknown_validation_error",
            "content",
        ),
        (
            {"errors": [{"field": "to", "message": "private provider text"}]},
            "errors",
            "unknown_validation_error",
            "to",
        ),
        (
            {
                "http_code": 400,
                "response": {"whatsapp": {"messages": [{"code": "INVALID", "status": "failed"}]}},
            },
            "response.whatsapp",
            "unknown_validation_error",
            "unknown",
        ),
    ],
)
def test_rejected_send_fingerprints_supported_error_shapes(
    caplog, response: dict, schema: str, category: str, field: str
) -> None:
    """Supported rejection schemas expose structure and categories, not values."""

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelValidationError):
            asyncio.run(
                _client(lambda request: httpx.Response(400, json=response)).send_text_message(
                    "+919000000000", "private message", "https://private.example/status", "private-data"
                )
            )

    diagnostic = caplog.messages[-1]
    assert f"response_schema={schema}" in diagnostic
    assert f"error_category={category}" in diagnostic
    assert f"provider_field={field}" in diagnostic
    assert "response_top_keys=" in diagnostic
    assert "response_nested_keys=" in diagnostic
    assert "response_value_types=" in diagnostic
    assert "+919000000000" not in diagnostic
    assert "private provider text" not in diagnostic
    assert "private message" not in diagnostic
    assert "private.example" not in diagnostic
    assert "private-data" not in diagnostic


@pytest.mark.parametrize(
    ("error_data", "application_code", "category", "field", "data_type"),
    [
        (
            {
                "code": "WA_1001",
                "message": "Sender +919000000000 is not registered",
                "field": "from",
                "phone": "+919000000000",
                "callback_url": "https://private.example/status",
            },
            "WA_1001",
            "sender_not_registered",
            "from",
            "dict",
        ),
        (
            [{"code": "WA_1002", "message": "private content"}],
            "unknown",
            "unknown_validation_error",
            "unknown",
            "list",
        ),
        (
            {
                "error": {
                    "error_code": "WA_2001",
                    "reason": "Template is required for this message",
                }
            },
            "WA_2001",
            "template_required",
            "unknown",
            "dict",
        ),
    ],
)
def test_error_data_diagnostics_are_safe_and_use_inner_application_code(
    caplog, error_data, application_code: str, category: str, field: str, data_type: str
) -> None:
    """Nested provider errors expose only safe shape and categorization data."""

    response = {
        "http_code": 400,
        "response": {
            "whatsapp": {
                "messages": [
                    {"code": 400, "status": "failure", "data": {}, "error_data": error_data}
                ]
            }
        },
    }
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelValidationError):
            asyncio.run(
                _client(lambda request: httpx.Response(400, json=response)).send_text_message(
                    "+919000000000", "private message", "https://private.example/status", "private-data"
                )
            )

    diagnostic = caplog.messages[-1]
    assert "provider_message_code=400" in diagnostic
    assert f"error_data_type={data_type}" in diagnostic
    assert "error_data_keys=" in diagnostic
    assert "error_data_nested_keys=" in diagnostic
    assert f"provider_application_code={application_code}" in diagnostic
    assert f"provider_error_category={category}" in diagnostic
    assert f"provider_error_field={field}" in diagnostic
    for private_value in (
        "+919000000000",
        "private.example",
        "private message",
        "private-data",
        "Sender",
        "Template is required",
    ):
        assert private_value not in diagnostic


def test_numeric_application_code_takes_priority_over_error_text(caplog) -> None:
    """Known numeric WhatsApp codes override potentially misleading error text."""

    response = {
        "http_code": 400,
        "response": {
            "whatsapp": {
                "messages": [
                    {
                        "code": 400,
                        "status": "failure",
                        "error_data": {
                            "code": 1001,
                            "description": "missing mandatory parameter",
                        },
                    }
                ]
            }
        },
    }
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelValidationError):
            asyncio.run(
                _client(lambda request: httpx.Response(400, json=response)).send_text_message(
                    "+919000000000", "private message"
                )
            )

    diagnostic = caplog.messages[-1]
    assert "provider_application_code=1001" in diagnostic
    assert "provider_error_category=whatsapp_not_enabled" in diagnostic
    assert "provider_error_category=missing_parameter" not in diagnostic
    assert "missing mandatory parameter" not in diagnostic


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (httpx.ReadTimeout("timeout"), ExotelTimeoutError),
        (httpx.ConnectError("connection"), ExotelConnectionError),
    ],
)
def test_send_text_message_maps_transport_errors(error: Exception, error_type: type[Exception]) -> None:
    """Timeout and connection failures never leak transport details."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(error_type):
        asyncio.run(
            _client(handler).send_text_message(
                "+919000000000", "test", "https://example.test/status", "internal-1"
            )
        )


def test_transport_failure_logs_only_safe_request_shape(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelConnectionError):
            asyncio.run(
                _client(lambda request: (_ for _ in ()).throw(httpx.ConnectError("private"))).send_text_message(
                    "+919000000000", "private message", "https://private.example/status"
                )
            )
    diagnostic = caplog.messages[-1]
    assert "request_url_shape_valid=True" in diagnostic and "authentication_present=True" in diagnostic
    assert "outcome_category=ambiguous_provider_outcome" in diagnostic and "request_started=true" in diagnostic
    assert "+919000000000" not in diagnostic and "private message" not in diagnostic and "private.example" not in diagnostic


def test_send_text_message_rejects_202_without_provider_sid() -> None:
    """A malformed accepted response is not treated as a successful send."""

    with pytest.raises(ExotelProviderResponseError):
        asyncio.run(
            _client(lambda request: httpx.Response(202, json={})).send_text_message(
                "+919000000000", "test", "https://example.test/status", "internal-1"
            )
        )


def test_malformed_success_is_logged_as_an_ambiguous_outcome(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        with pytest.raises(ExotelProviderResponseError):
            asyncio.run(
                _client(lambda request: httpx.Response(202, json={"whatsapp": {"messages": [{}]}})).send_text_message(
                    "+919000000000", "private message", "https://private.example/status"
                )
            )
    diagnostic = caplog.messages[-1]
    assert "outcome_category=ambiguous_provider_outcome" in diagnostic
    assert "request_started=true" in diagnostic
    assert "+919000000000" not in diagnostic and "private message" not in diagnostic and "private.example" not in diagnostic


def test_minimal_diagnostic_payload_omits_optional_fields() -> None:
    """The controlled diagnostic variant sends only the required message fields."""

    payload = _client(lambda request: httpx.Response(202)).build_text_payload(
        to_number="+919000000000", text="diagnostic"
    )

    assert set(payload) == {"whatsapp"}
    messages = payload["whatsapp"]["messages"]
    assert len(messages) == 1
    assert set(messages[0]) == {"from", "to", "content"}
    assert messages[0]["content"]["type"] == "text"
    assert messages[0]["content"]["text"]["body"] == "diagnostic"
    assert "status_callback" not in payload
    assert "custom_data" not in messages[0]


def test_image_payload_uses_exotel_image_content_with_link_and_caption() -> None:
    payload = _client(lambda request: httpx.Response(202)).build_image_payload(
        to_number="+919000000000",
        image_url="https://example.test/pontoon.jpg",
        caption="Approved Pontoon package",
        status_callback="https://example.test/status",
        custom_data="draft-safe",
    )

    message = payload["whatsapp"]["messages"][0]
    assert message["content"] == {
        "type": "image",
        "image": {"link": "https://example.test/pontoon.jpg", "caption": "Approved Pontoon package"},
    }
    assert message["custom_data"] == "draft-safe"
    assert payload["status_callback"] == "https://example.test/status"


def test_document_payload_uses_exotel_pdf_content_with_filename_and_caption() -> None:
    payload = _client(lambda request: httpx.Response(202)).build_document_payload(
        to_number="+919000000000", document_url="https://signed.example/confirmation.pdf",
        caption="Booking confirmed", filename="Entartica-CBE-1.pdf",
        status_callback="https://example.test/status", custom_data="draft-safe-document",
    )
    message = payload["whatsapp"]["messages"][0]
    assert message["content"] == {"type":"document", "document":{
        "link":"https://signed.example/confirmation.pdf", "caption":"Booking confirmed",
        "filename":"Entartica-CBE-1.pdf",
    }}
    assert message["custom_data"] == "draft-safe-document"


def test_pontoon_template_payload_uses_one_template_with_dynamic_image_header() -> None:
    from app.schemas.template_messages import TemplateMessage

    template = TemplateMessage(
        name="approved_pontoon_template", language="en",
        header_image_url="https://example.test/pontoon.jpg", flow_id="approved-flow",
        flow_cta="Share Event Details", service_code="pontoon_celebration",
        package_source_file="active/services/pontoon_celebration.md",
    )
    payload = _client(lambda request: httpx.Response(202)).build_template_payload(
        to_number="+919000000000", template=template,
    )
    message = payload["whatsapp"]["messages"][0]
    assert message["content"]["type"] == "template"
    assert message["content"]["template"] == {
        "name": "approved_pontoon_template",
        "language": {"code": "en", "policy": "deterministic"},
        "components": [{
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": "https://example.test/pontoon.jpg"}}],
        }],
    }
    assert "interactive" not in message["content"]


def test_outbound_service_is_disabled_by_default() -> None:
    """No repository or provider activity occurs unless explicitly enabled."""

    service = OutboundMessageService(
        object(), settings=Settings(exotel_outbound_enabled=False)
    )

    with pytest.raises(OutboundMessagingDisabledError):
        asyncio.run(service.send_text_message(to_number="+919000000000", text="test"))


class _Customers:
    def get_by_whatsapp_number(self, value: str) -> dict[str, str]:
        return {"id": "customer-1"}


class _Conversations:
    def get_open(self, value: str) -> dict[str, str]:
        return {"id": "conversation-1"}


class _Messages:
    def __init__(self) -> None:
        self.failed_code: str | None = None
        self.accepted_sid: str | None = None

    def create_outbound_pending(self, **kwargs) -> dict[str, str]:
        return {"id": "message-1"}

    def mark_outbound_accepted(self, message_id: str, provider_message_id: str) -> None:
        self.accepted_sid = provider_message_id

    def mark_outbound_failed(self, message_id: str, failure_code: str) -> None:
        self.failed_code = failure_code


class _AcceptedClient:
    async def send_text_message(self, *args) -> ExotelAcceptedMessage:
        return ExotelAcceptedMessage(provider_message_id="provider-1")


class _FailedClient:
    async def send_text_message(self, *args) -> ExotelAcceptedMessage:
        raise ExotelTimeoutError


def _enabled_service(exotel_client) -> tuple[OutboundMessageService, _Messages]:
    settings = Settings(
        exotel_outbound_enabled=True,
        exotel_account_sid="account",
        exotel_api_key="key",
        exotel_api_token="token",
        exotel_whatsapp_from="+919900000000",
        public_base_url="https://example.test",
    )
    service = OutboundMessageService(object(), settings=settings, exotel_client=exotel_client)
    messages = _Messages()
    service._customers = _Customers()
    service._conversations = _Conversations()
    service._messages = messages
    return service, messages


def test_outbound_service_marks_pending_message_accepted() -> None:
    """A provider acceptance updates the durable pending record."""

    service, messages = _enabled_service(_AcceptedClient())

    result = asyncio.run(service.send_text_message(to_number="+919000000000", text="test"))

    assert result.provider_message_id == "provider-1"
    assert messages.accepted_sid == "provider-1"


def test_outbound_service_retains_failed_pending_message() -> None:
    """A provider failure updates the pending record to failed."""

    service, messages = _enabled_service(_FailedClient())

    with pytest.raises(OutboundMessageError):
        asyncio.run(service.send_text_message(to_number="+919000000000", text="test"))

    assert messages.failed_code == "timeout"
