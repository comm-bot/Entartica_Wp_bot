from app.services.booking_enquiries import BookingDetails
from app.services.raipur.context_state import clear_for_non_service_turn, clear_pending_celebration, resolve_service_turn, set_catalogue_context, set_celebration_occasion_pending
from app.services.raipur.response_models import ConversationContext

def _context(code="water_bike", name="Water Bike"):
 return ConversationContext(BookingDetails(None,None,None,None,None,None,None),last_service_code=code,last_service_name=name,active_topic="overview")

def test_followup_retains_and_explicit_service_switches_context():
 retained=resolve_service_turn(_context(),service_code=None,service_name=None,topic="how_it_works",explicit_service=False)
 assert retained.context_service_used and retained.updated_context.active_topic=="how_it_works"
 switched=resolve_service_turn(_context(),service_code="jet_ski_ride",service_name="Jet Ski Ride",topic="overview",explicit_service=True)
 assert switched.explicit_service_switch and switched.updated_context.last_service_code=="jet_ski_ride"

def test_location_greeting_or_category_clear_stale_service_subject():
 value=clear_for_non_service_turn(_context(),reason="location")
 assert value.clear_service_context and value.updated_context.last_service_code is None and value.updated_context.active_topic is None

def test_catalogue_context_clears_service_but_persists_approved_category():
 value=set_catalogue_context(_context(),"activity")
 assert value.updated_context.last_service_code is None
 assert value.updated_context.active_topic=="activity_catalogue"
 assert value.updated_context.active_entity_type=="catalogue"
 assert value.updated_context.active_entity_name=="activity"

def test_acknowledgement_is_distinct_from_greeting_so_clear_path_is_not_applied():
 from app.services.raipur.greeting_handler import is_acknowledgement, is_greeting
 assert is_acknowledgement("thank you") and is_acknowledgement("theek hai")
 assert not is_greeting("thank you")
 assert is_greeting("hello") and not is_acknowledgement("hello")

def test_set_celebration_occasion_pending_persists_celebration_context():
 value=set_celebration_occasion_pending(_context())
 updated=value.updated_context
 assert value.reason=="celebration_occasion_pending"
 assert updated.active_topic=="celebration_catalogue"
 assert updated.active_entity_type=="catalogue"
 assert updated.active_entity_name=="celebration"
 assert updated.last_service_code is None
 assert updated.pending_clarification is True
 assert updated.pending_clarification_type=="celebration_occasion"
 assert updated.pending_clarification_options==("anniversary","birthday","corporate")
 assert updated.pending_action=="celebration_occasion"

def test_clear_pending_celebration_resets_pending_and_active_context():
 ctx=set_celebration_occasion_pending(_context()).updated_context
 value=clear_pending_celebration(ctx,reason="celebration_cancel")
 updated=value.updated_context
 assert value.clear_topic_context
 assert updated.active_topic is None
 assert updated.active_entity_name is None
 assert updated.last_service_code is None
 assert updated.pending_clarification is False
 assert updated.pending_clarification_type is None
 assert updated.pending_clarification_options==()
 assert updated.pending_action is None
 assert updated.pending_entity_name is None
