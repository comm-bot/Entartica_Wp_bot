# Raipur LangGraph Migration Plan

## Current dual-engine architecture

`/webhooks/exotel/inbound` persists a normalized message and invokes
`RaipurInboundOrchestrator`.  With `RAIPUR_LANGGRAPH_ENABLED=true`, the
orchestrator uses `RaipurLangGraphWorkflow`; otherwise it retains the
deprecated `RaipurConversationService` compatibility engine.  Both engines
continue to use the same approved knowledge provider, service repository,
conversation context, draft lifecycle, and safety restrictions.

## Phase 1: shared category handling

`app/services/raipur/category_handler.py` is the engine-neutral owner of
approved celebration, package, and activity-catalogue recognition and
templates.  It returns `RaipurCategoryHandlerResult` with `handled`, `route`,
`intent`, `service_code`, `topic`, `answer_source`, `response_text`, and
`fallback_reason`.  It has no persistence, provider, or send capability.

`RaipurLangGraphWorkflow` calls this handler directly.  The legacy service
also calls it while retaining compatibility aliases for historical private
test imports.  This phase intentionally leaves its broader orchestration
unchanged.

## Remaining legacy responsibilities

- Legacy sequencing in `RaipurConversationService.process()`.
- Context mutation and booking-enquiry orchestration.
- Service/topic follow-up resolution and legacy deterministic branches.
- Legacy response persistence and draft creation adapters.
- `ConversationContext`, `ConversationResult`, and `KnowledgeDraft` models
  still imported by LangGraph and other components.

## Legacy function classification (Phase 1 inventory)

| Classification | Functions / members |
| --- | --- |
| Legacy-only orchestration | `RaipurConversationService.__init__`, `process`, `_pricing`, `_booking`, `_booking_sales_handover`, `_save` |
| Reusable service/topic resolution | `_active_approved_services`, `_active_service`, `_active_celebration_services`, `_active_package_services`, `_service_detail`, `_generic_service_definition`, `_fallback_excerpts`, `_is_service_follow_up`, `_is_venue_overview_question`, `_is_service_full_overview_request`, `_is_more_details_request`, `_with_service`, `_service_detail_retrieval_query`, `_is_service_confirmation_question`, `_is_service_definition_question`, `_service_response_addresses_topic` |
| Reusable category logic | **Moved:** `handle_raipur_category_request`, catalogue/celebration/package detection, and their templates to `raipur.category_handler`; compatibility-private template helpers remain legacy-only until Phase 2 cleanup |
| Reusable business guardrail | `_is_availability_request`, `_is_live_availability_request`, `_is_follow_up_availability_request`, `_eligibility_response_addresses_subject`, `_participation_eligibility_fallback`, `_safe_clarification_needed`, `_structured_metadata`, `_service_detail_metadata`, `_pricing_text`, `_verify`, `_available`, `_not_available`, `_availability_text` |
| Reusable response template | `_language_changed`, `_greeting`, `_service_question_fallback`, `_structured_location_answer`, `_service_detail_fallback`, `_generic_definition_fallback`, `_daycation_definition`, `_definition_follow_up`, `_self_introduction`, `_current_information`, `_destination_scope_question`, `_raipur_city_travel`, `_raipur_city_geography`, `_raipur_city_repair`, `_repair`, `_h2o_unavailable`, `_clarification`, `_ask`, `_handover` |
| Reusable context/normalization utility | `_language`, `_requested_language`, `_is_service_repair_request`, `_is_location_question`, `_is_direct_contact_request`, `_is_location_follow_up`, `_is_location_correction`, `_is_pending_location_map_action`, `_is_raipur_city_geography_question`, `_normalize_intent_text`, `_location_context`, `_clear_booking_state`, `_catalogue_context`, `_safe_summary`, `_clean_response_script`, `_apply_known_text`, `_apply_reply`, `_date`, `_time` |
| Test-only dependency/protocol | `KnowledgeAnswerProvider.answer`, `DraftRepository.create_outbound_draft` |
| Obsolete compatibility candidates | `_is_package_list_question`, `_service_list_answer`, `_celebration_service_list_answer`, `_package_service_list_answer`, `_all_approved_services`; retained only until callers/tests are migrated deliberately |

## LangGraph-owned responsibilities

- Feature-flagged production route selection and typed graph state.
- Deterministic graph planning, graph answer nodes, retrieval composition,
  response validation, and route telemetry.

## Phase 2: shared response and context models

Completed: `Action`, `KnowledgeDraft`, `ConversationContext`, and
`ConversationResult` now live in `app.services.raipur.response_models`.
The field order, annotations, defaults, frozen dataclass equality, repr, and
standard dataclass serialization are unchanged.  LangGraph, the inbound
orchestrator, and the knowledge provider now import the neutral models.
`raipur_conversation` re-exports those exact objects for compatibility; it
does not define a second class.

Remaining `raipur_conversation` imports are classified as follows:

- **Legitimate compatibility-engine dependency:**
  `RaipurInboundOrchestrator` imports `RaipurConversationService` while the
  legacy feature-flag path remains supported.
- **Helper dependency for a future phase:** `RaipurLangGraphWorkflow` imports
  `_greeting`, `_is_location_question`, `_language`, and
  `_structured_location_answer`; these are outside this model-only phase.
- **Test-only legacy dependency:** legacy conversation/service tests and pilot
  scripts import the compatibility service.  Model-only tests have migrated
  to `raipur.response_models`; one parity test deliberately imports legacy
  re-exports.

No production import remains that obtains one of the three models from the
legacy module.

## Phase 3: shared service and topic resolution

Completed: `app.services.raipur.service_resolver` provides `ServiceResolution`
and `resolve_service`; `app.services.raipur.topic_resolver` provides
`TopicResolution`, `resolve_topic`, and `topic_for_graph`.  They return only
structured routing information and contain no customer-facing text, provider,
persistence, booking, or guardrail behaviour.

The resolver delegates official names and approved aliases to the existing
`raipur_services` manifest helpers, which remains the single authoritative
catalogue and service-code mapping.  A narrow `bumber boat` normalization is
performed before that approved lookup.  An explicit current-message service
always wins over optional stored context.

`RaipurConversationService` and `RaipurLangGraphWorkflow` now resolve the
current explicit service through the shared resolver.  The dialogue planner's
`_service_question_topic` is retained as a compatibility wrapper over the
shared topic resolver.  LangGraph uses `topic_for_graph` to preserve its
existing `swimming` state spelling while the legacy planner retains
`swimming_requirement`; both values derive from the same matched phrase.

Parity coverage includes aliases, misspellings, context service use, capacity,
duration, swimming, how-it-works, inclusions, and no-match results, alongside
the existing structured-routing, LangGraph, inbound-orchestrator, provider,
and webhook tests.

### Phase 3 inventory

| Classification | Current owner |
| --- | --- |
| Reusable service resolution | `raipur_services` approved manifest and aliases; `raipur.service_resolver` structured decision/context selection |
| Reusable topic resolution | `raipur.topic_resolver` canonical phrase matching and graph spelling adapter |
| LangGraph-only orchestration | `_deterministic_plan`, `_repair_plan_consistency`, graph state/context clearing |
| Legacy-only orchestration | `RaipurConversationService.process`, booking/persistence branches, legacy context mutation |
| Knowledge-provider responsibility | exact-section lookup, metadata filtering, heading ranking, RAG retrieval/composition |
| Business guardrail | pricing, booking, availability, payment, cancellation/refund, medical and handover decisions (unchanged) |
| Response formatting | greeting/location/structured templates and WhatsApp formatter (unchanged) |

Remaining legacy helper imports in LangGraph are `_greeting`,
`_is_location_question`, `_language`, and `_structured_location_answer`; none
are service or topic resolution imports.  They remain future-phase candidates.

Rollback: restore the two engine calls to their former resolver helpers and
retain the same feature-flagged legacy engine.  This phase does not affect
documents, schema, providers, drafts, or send state.

## Phase 4: deterministic language, greeting, and location helpers

Completed: shared `raipur.language`, `raipur.greeting_handler`, and
`raipur.location_handler` modules now own deterministic language detection,
greeting/gratitude rendering, and approved structured-location rendering.
LangGraph no longer imports `_greeting`, `_is_location_question`, `_language`,
or `_structured_location_answer` from the legacy module.  Legacy names remain
thin forwarding compatibility helpers; the legacy location matcher retains its
existing scoped fallback conditions for parity.

Language detection is deterministic (`en`, `hi`, `hinglish`); location
rendering consumes only the existing structured approved location record and
does not add address facts.  Greeting/gratitude remain distinct at the graph
route level.  No guardrail, provider, formatter, persistence, or booking code
was moved.

Remaining production legacy imports are now limited to the compatibility
service in the inbound orchestrator and legacy-only helper use outside this
phase.  Recommended Phase 5: assess whether deterministic context mutation
helpers can be safely separated, before any guardrail or booking extraction.

## Phase 5: shared deterministic context state

Completed: `raipur.context_state` provides pure `ContextResolutionResult`,
`resolve_service_turn`, and `clear_for_non_service_turn` helpers.  It has no
database, provider, send, or persistence dependency. LangGraph delegates its
non-service context clear operation to this module; the legacy engine consults
the same explicit-service context decision while retaining its sequencing and
persistence. Booking, guardrail, and repository code remain outside the
module. Rollback is limited to restoring the former local context operations.

Recommended Phase 6 boundary: inventory remaining legacy response/persistence
adapters only; do not extract guardrails without separate approval.

## Future phases

1. Extract shared deterministic location/language/rendering helpers that
   LangGraph still imports from the legacy module, with route-order parity
   tests; do not move guardrails.
2. Extract business guardrails and response templates only after exact
   LangGraph parity is demonstrated.
3. Move persistence adapters behind explicit protocols, then remove legacy
   engine selection only after a controlled rollout.

## Phase 6: LangGraph default and production-path parity audit

Completed in repository: `RAIPUR_LANGGRAPH_ENABLED` now defaults to `true`.
An explicit `false` value is the emergency compatibility mode and selects only
`RaipurConversationService.process()`.  The inbound orchestrator selects
exactly one engine per inbound message and has no exception path that retries
the same message through legacy after a LangGraph failure.  Startup emits one
safe `raipur_conversation_engine_selected` event with the selected engine,
effective flag, compatibility mode, and application environment.

| Responsibility | LangGraph / production owner | Classification |
| --- | --- | --- |
| Greeting, gratitude, location, catalogue, service overview/topic, Hindi/Hinglish, service switching, stale-context override | `RaipurLangGraphWorkflow` plus neutral helpers | LangGraph complete |
| Celebration and package category routing | shared `raipur.category_handler`, invoked by LangGraph | LangGraph complete |
| Pricing, booking, payment, availability, cancellation/refund, medical/safety guardrails | LangGraph routes and shared sales/guardrail services | LangGraph complete |
| Customer/inbound/conversation/context persistence, drafts, claims, duplicate protection, formatting, audit logs, status callbacks | webhook, repositories, draft sender, formatter, callback route | shared outside both engines |
| Legacy full conversation processor | `RaipurConversationService.process()` | explicit compatibility only |

Parity evidence is fake-only: engine-selection tests prove that enabled
LangGraph never invokes `RaipurConversationService.process()` and explicit
compatibility mode invokes only legacy. Existing graph/orchestrator/webhook
tests cover the route, context, restriction, duplicate, formatting, and
background acknowledgement boundaries. They are not live WhatsApp acceptance.

`RaipurLangGraphWorkflow` still receives the compatibility service instance at
construction time as a transitional dependency source for optional knowledge,
service, location, sales-contact, and fallback attributes. It does not import
or invoke the legacy processor. This is a Phase 7 deletion blocker: replace
that constructor dependency with an explicit neutral dependency object only
after a separately approved parity task.

### Phase 7 deletion blockers

- Live allowlisted WhatsApp acceptance is not recorded.
- No reviewed Git rollback tag has been created.
- The LangGraph constructor still accepts the compatibility service for
  transitional dependency values.
- Multi-replica ordering and durable background processing remain operational
  risks outside engine selection.

Rollback: set `RAIPUR_LANGGRAPH_ENABLED=false`, restart the application, and
verify the startup engine-selection event. Do not fall back per message.

## Test migration plan

Keep shared-handler unit tests, LangGraph workflow tests, legacy conversation
tests, inbound-orchestrator tests, and webhook tests in the required suite.
For each later extraction, add parity tests using the same fake inputs and
compare route, intent, service/topic, source, response, and fallback reason.

## Rollback plan

The feature flag still selects the legacy compatibility engine.  Revert only
the shared-module imports/calls if parity fails; no documents, schemas,
provider configuration, draft states, or outbound send controls change in this
phase.

## Deletion criteria for `RaipurConversationService`

Delete it only after all reusable models and logic are owned by neutral
modules, LangGraph is the only runtime engine through a controlled rollout,
legacy-only scripts/tests are migrated or retired deliberately, and full
parity plus rollback acceptance has been recorded.

## Remaining risks

- Several consumers still import legacy response/context models.
- The compatibility engine contains broad historical routing branches.
- In-process background work and feature-flag configuration remain runtime
  deployment concerns outside this extraction.
