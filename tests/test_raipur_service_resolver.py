from app.services.raipur.service_resolver import resolve_service


def test_resolves_official_names_aliases_and_common_misspellings():
    assert resolve_service("jet ski").service_code == "jet_ski_ride"
    assert resolve_service("jetski").matched_alias is True
    assert resolve_service("bumber boat").service_code == "bumper_boat"
    assert resolve_service("water bike").service_code == "water_bike"
    for alias in ("houseboat", "house boat", "houseboat celebration", "house boat celebration", "housboat", "house bot", "\u0939\u093e\u0909\u0938 \u092c\u094b\u091f"):
        assert resolve_service(alias).service_code == "houseboat_celebration"


def test_explicit_service_overrides_a_stored_context_and_no_match_fails_closed():
    switched = resolve_service(
        "now tell me about Jet Ski",
        context_service_code="water_bike",
        context_service_name="Water Bike",
        allow_context=True,
    )
    assert switched.explicit_service and not switched.context_service_used
    assert switched.service_code == "jet_ski_ride"
    assert not resolve_service("unrelated question").matched


def test_context_is_used_only_when_explicitly_allowed():
    result = resolve_service(
        "isme kitna log aa sakte hain?",
        context_service_code="bumper_boat",
        context_service_name="Bumper Boat",
        allow_context=True,
    )
    assert result.matched and result.context_service_used
    assert result.service_code == "bumper_boat"


def test_common_typos_resolve_to_correct_services():
    assert resolve_service("Tell me about party baot").service_code == "party_boat_celebration"
    assert resolve_service("kayk ka duration kya hai").service_code == "kayaking"
    assert resolve_service("aqua cyle ki details").service_code == "aqua_cycle"
    assert resolve_service("bumber boat").service_code == "bumper_boat"
