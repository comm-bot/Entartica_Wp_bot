"""Offline Promptfoo provider: validates routing only, never calls external services."""
from app.services.raipur_langgraph import RaipurLangGraphWorkflow


class _Result:
    response_valid = True
    draft_text = "approved test response"


class _Conversation:
    def process(self, *_args, **_kwargs): return _Result()


def call_api(prompt, options, context):
    text = str(prompt)
    workflow = RaipurLangGraphWorkflow(_Conversation())
    state = {"message_id":"fake","conversation_id":"fake","customer_id":"fake","customer_message":text,"normalized_message":text.casefold(),"language":"en","location_code":"raipur","previous_service_code":None,"intent":"unknown","entity_type":"unknown","service_code":None,"topic":None,"use_previous_service":False,"requires_handover":False,"handover_reason":None,"answer_source":"none","draft_response":None,"validation_status":"pending","error":None,"route":""}
    # Plan without invoking production services; this is an offline route probe.
    update = workflow.plan_message({**state, "_runtime": {"current_state": None}})
    route = workflow.route({**state, **update})
    metadata = {
        "intent": update["intent"], "service_code": update.get("service_code"),
        "topic": update.get("topic"), "route": route,
        "answer_source": "offline_route_probe", "used_previous_service": bool(update.get("use_previous_service")),
    }
    return {"output": f"route={route}; intent={update['intent']}; service_code={update.get('service_code') or 'none'}", "metadata": metadata}
