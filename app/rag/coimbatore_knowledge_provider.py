"""Structured, Coimbatore-only customer evidence and answer contracts."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any

from app.rag.retrieval import embed_query, retrieve_candidates_for_location

_INTERNAL = ("question bank", "future expansion", "faq collection template", "readiness", "next knowledge build", "current status")
_PENDING = ("pending business input", "awaiting business", "known website conflicts", "validation queue",
            "historical", "superseded", "old capacity", "old food")

@dataclass(frozen=True)
class CoimbatoreAnswer:
    topic: str
    text: str
    source_heading: str
    authority: str = "approved_current"
    customer_facing: bool = True
    requires_live_data: bool = False
    handoff_required: bool = False
    package_id: str | None = None

@dataclass(frozen=True)
class CoimbatoreEvidence:
    chunks: tuple[dict[str, Any], ...]
    query: str

class CoimbatoreKnowledgeProvider:
    def __init__(self, client: Any, settings: Any): self._client, self._settings = client, settings

    def answer(self, question: str, *, guest_count: int | None = None, package_id: str | None = None) -> CoimbatoreAnswer | None:
        topic = resolve_topic(question)
        if topic is None: return None
        answer = compose_approved_answer(topic, guest_count=guest_count, package_id=package_id)
        if answer is None: return None
        query = _AUTHORITY_QUERY.get(topic, question)
        vector = embed_query(query, self._settings)
        rows = retrieve_candidates_for_location(self._client, vector, location_code="coimbatore", limit=30)
        minimum = float(getattr(self._settings, "coimbatore_knowledge_min_similarity", 0.30))
        eligible = [row for row in rows if _eligible(row) and float(row.get("confidence", 0.0)) >= minimum]
        preferred = sorted(eligible, key=lambda row: (_heading_score(topic, row), row.get("confidence", 0.0)), reverse=True)
        if not preferred: return None
        heading = str((preferred[0].get("metadata") or {}).get("section_heading") or "Coimbatore Master Knowledge")
        return CoimbatoreAnswer(topic, answer.text, heading, answer.authority, True, answer.requires_live_data, answer.handoff_required, package_id)

    def retrieve_evidence(self, question: str, *, topic: str | None = None, attribute: str | None = None,
                          package_id: str | None = None, limit: int = 5) -> CoimbatoreEvidence:
        """Retrieve approved content for the real question without requiring a legacy topic."""
        context = " ".join(part for part in (
            question,
            f"Current package: {package_id.replace('_', ' ')}" if package_id else "",
            f"Requested topic: {topic}" if topic else "",
            f"Requested attribute: {attribute}" if attribute else "",
        ) if part)
        vector = embed_query(context, self._settings)
        rows = retrieve_candidates_for_location(self._client, vector, location_code="coimbatore", limit=30)
        minimum = float(getattr(self._settings, "coimbatore_knowledge_min_similarity", 0.30))
        eligible = [row for row in rows if _eligible(row) and float(row.get("confidence", 0.0)) >= minimum]
        preferred = sorted(eligible, key=lambda row: (
            _standard_authority_score(package_id, topic, attribute, row), _heading_score(topic or "", row), row.get("confidence", 0.0)
        ), reverse=True)
        chunks = tuple({
            "content": str(row.get("content", "")),
            "section_heading": str((row.get("metadata") or {}).get("section_heading") or "Coimbatore Master Knowledge"),
            "location_code": "coimbatore",
            "confidence": float(row.get("confidence", 0.0)),
        } for row in preferred[:max(1, limit)] if isinstance(row.get("content"), str) and row["content"].strip())
        return CoimbatoreEvidence(chunks, context)

def _eligible(row: dict[str, Any]) -> bool:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    heading = str(metadata.get("section_heading", "")).casefold()
    return metadata.get("location_code") == "coimbatore" and metadata.get("customer_output_allowed") is not False and not any(x in heading for x in _INTERNAL + _PENDING)

def _heading_score(topic: str, row: dict[str, Any]) -> int:
    heading = str((row.get("metadata") or {}).get("section_heading", "")).casefold()
    terms = _HEADING_TERMS.get(topic, ())
    return sum(20 for term in terms if term in heading) + (10 if any(x in heading for x in ("approved", "operational rules v2", "package specific", "permission matrix")) else 0)

def _standard_authority_score(package_id: str | None, topic: str | None, attribute: str | None, row: dict[str, Any]) -> int:
    if package_id != "coimbatore_pontoon_standard": return 0
    heading = str((row.get("metadata") or {}).get("section_heading", "")).casefold()
    subject = (topic or "").casefold(); detail = (attribute or "").casefold()
    if subject in {"cake", "duration", "pyro", "inclusions", "music", "decoration"}:
        if "standard package inclusions" in heading: return 300
        if "approved standard package add-ons" in heading and detail in {"extra", "add-on", "addon", "price", "customized"}: return 280
    if subject in {"price", "token", "refund", "cancellation", "package"} and "standard package commercial terms" in heading:
        return 300
    return 100 if any(term in heading for term in (
        "standard package identity", "standard package inclusions", "standard package commercial terms",
        "approved standard package add-ons", "standard package authority rule",
    )) else 0

def recommended_package(guests: int | None) -> str | None:
    if guests == 2: return "couple_romance"
    if isinstance(guests, int) and 3 <= guests <= 10: return "family_friends"
    return None

def resolve_topic(text: object) -> str | None:
    value = text.casefold() if isinstance(text, str) else ""
    rules = (
        ("discount", r"discount|best price|kam kar"), ("payment", r"payment link|i paid|payment status|send payment|token amount|how much token"),
        ("availability", r"available|availability|slot"), ("park_timing", r"park.*tim|opening|closing|operating hours"),
        ("booking_window", r"what time.*book|booking window|kitne baje"), ("location", r"where.*(?:entartica|located)|location bhejo|address|map"),
        ("pregnancy", r"pregnan"), ("own_cake", r"bring.*(?:own )?cake|own cake"), ("own_decoration", r"own decoration|bring.*decoration"),
        ("cake", r"cake"), ("inclusions", r"what(?:'s| is)? included|what do i get|inclusions?"),
        ("food", r"food|khana"), ("photoshoot", r"photoshoot|photo shoot"), ("drone", r"drone"),
        ("singer", r"singer"), ("duration", r"how long|duration|kitni der"), ("cancellation", r"cancel|refund|reschedul"),
        ("occasion", r"\b(?:birthday|anniversary)\b"),
        ("parking", r"parking"), ("washroom", r"washroom|toilet"), ("changing_room", r"changing room|locker"),
        ("price", r"how much|price+|cost|rates?|kitna|kitne ka"),
        ("overview", r"^(?:show\s+|tell me\s+|which\s+|what\s+)?(?:pontoon\s+)?packages?(?:\s+details?)?$|what packages do you have|what is pontoon|about pontoon|pontoon celebration kya"),
    )
    return next((topic for topic, pattern in rules if re.search(pattern, value)), None)

def compose_approved_answer(topic: str, *, guest_count: int | None, package_id: str | None) -> CoimbatoreAnswer | None:
    if package_id == "coimbatore_pontoon_standard":
        from app.services.coimbatore.pontoon_package import load_standard_package, resolve_standard_package_pricing
        package = load_standard_package()
        pricing = resolve_standard_package_pricing(guest_count)
        if topic == "overview":
            if pricing is None:
                text = ("The maximum capacity of the Pontoon Boat is 10 guests 😊 Please send the correct number of guests from 1 to 10."
                        if isinstance(guest_count, int) and guest_count > 10
                        else "The Standard Pontoon Celebration price depends on the guest count. How many guests will be joining?")
                return CoimbatoreAnswer(topic, text, "Standard Package Identity", package_id=package_id,
                                        handoff_required=False)
            return CoimbatoreAnswer(topic, f"The Standard Package offer for {guest_count} guests is ₹{pricing.offer_price:,}/- (original price ₹{pricing.regular_price:,}/-).", "Standard Package Identity", package_id=package_id)
        if topic == "price":
            if pricing is None:
                text = ("The maximum capacity of the Pontoon Boat is 10 guests 😊 Please send the correct number of guests from 1 to 10."
                        if isinstance(guest_count, int) and guest_count > 10
                        else "Please share the guest count so I can show the approved Standard Package price.")
                return CoimbatoreAnswer(topic, text, "Standard Package Commercial Terms", package_id=package_id,
                                        handoff_required=False)
            return CoimbatoreAnswer(topic, f"For {guest_count} guests, the Standard Package offer price is ₹{pricing.offer_price:,}/-; the original price is ₹{pricing.regular_price:,}/-.", "Standard Package Commercial Terms", package_id=package_id)
        if topic == "inclusions":
            return CoimbatoreAnswer(topic, "The Standard Package includes Red Carpet Welcome, 02 Cold Pyro Entry, Cake, Music Setup, Decoration, lake cake-cutting and a 30 Minutes Premium Boat Ride.", "Standard Package Inclusions", package_id=package_id)
        if topic == "cake":
            return CoimbatoreAnswer(topic, "Yes 😊 Cake is included in the Standard Package and can be provided in any available flavour.", "Standard Package Inclusions", package_id=package_id)
        if topic == "duration":
            return CoimbatoreAnswer(topic, "The Standard Package includes a 30-minute Premium Boat Ride.", "Standard Package Inclusions", package_id=package_id)
        if topic == "cancellation":
            return CoimbatoreAnswer(topic, package.refund_rule, "Standard Package Commercial Terms", package_id=package_id)
    if package_id == "coimbatore_pontoon_couple_romance":
        from app.services.coimbatore.pontoon_package import load_couple_package
        package = load_couple_package()
        if topic == "overview": return CoimbatoreAnswer(topic, package.message_template, "ACTIVE COUPLE ROMANCE PONTOON PACKAGE — CUSTOMER PRESENTATION", package_id=package_id)
        if topic == "price": return CoimbatoreAnswer(topic, "The Couple Romance Package is ₹3,999 for 2 guests.", "CUSTOMER_PACKAGE_MESSAGE", package_id=package_id)
        if topic == "inclusions": return CoimbatoreAnswer(topic, "The Couple Romance Package includes Red Carpet Entry, Basic Boat Decoration, 250 g Cake, Music, 02 Cold Pyros and a 20 Minutes Private Pontoon Boat Ride.", "CUSTOMER_PACKAGE_MESSAGE", package_id=package_id)
        if topic == "cake": return CoimbatoreAnswer(topic, "The Couple Romance Package includes a 250 g cake in any available flavour.", "PACKAGE RULES", package_id=package_id)
        if topic == "duration": return CoimbatoreAnswer(topic, "The Couple Romance Package includes a 20-minute private Pontoon Boat Ride.", "PACKAGE RULES", package_id=package_id)
    family_price = "₹6,000" if guest_count and guest_count <= 6 else "₹7,500" if guest_count and guest_count <= 9 else "₹9,000"
    if topic == "overview":
        if package_id == "couple_romance":
            return _package_answer(guest_count or 2, package_id)
        if package_id == "family_friends" and guest_count is not None:
            return _package_answer(guest_count, package_id)
        return CoimbatoreAnswer(topic, "We have two Pontoon Celebration options 😊\n• Couple Romance — ₹3,999\n• Standard Pontoon Celebration — ₹5,999\n\nWhich one would you like to see?", "Active Package Presentations")
    if topic == "price":
        if guest_count and guest_count > 10: return CoimbatoreAnswer(topic, "The maximum capacity of the Pontoon Boat is 10 guests 😊 Please send the correct number of guests from 1 to 10.", "Guest & Capacity Rules", handoff_required=False)
        if package_id == "couple_romance": return _package_answer(2, package_id)
        if package_id == "family_friends": return _package_answer(guest_count or 3, package_id)
        return CoimbatoreAnswer(topic, "Couple Romance is ₹3,999. The Standard Pontoon Celebration is ₹5,999. Which package would you like?", "Active Package Presentations")
    if topic == "inclusions":
        if package_id == "couple_romance": return CoimbatoreAnswer(topic, "The Couple Romance Celebration includes a 20-minute private Pontoon ride, 250 g cake, basic boat decoration, music, red carpet entry and 2 cold pyros.", "Pontoon FAQ — Package Specific", package_id=package_id)
        if package_id == "family_friends": return CoimbatoreAnswer(topic, "The Family & Friends Celebration includes a 30-minute ride, 500 g cake, boat decoration, music, red carpet and pyro entry.", "Pontoon FAQ — Package Specific", package_id=package_id)
        return CoimbatoreAnswer(topic, "We have Couple Romance and Standard Pontoon Celebration packages. Which one would you like to know about?", "Active Package Presentations")
    if topic == "cake": return CoimbatoreAnswer(topic, "Yes 😊 A 250 g cake is included in the Couple package." if package_id == "couple_romance" else "Yes 😊 A 500 g cake is included in the Family & Friends package.", "Is cake included?", package_id=package_id)
    if topic == "duration": return CoimbatoreAnswer(topic, "The Couple Romance ride is 20 minutes." if package_id == "couple_romance" else "The Family & Friends ride is 30 minutes.", "Pontoon FAQ — Package Specific", package_id=package_id)
    if topic == "occasion": return CoimbatoreAnswer(topic, "Lovely 🎉 A Pontoon Celebration is a great way to celebrate that occasion.", "Celebration Types", package_id=package_id)
    answers = {
        "pregnancy":"Pregnant guests are not allowed to participate in the Pontoon ride.",
        "own_cake":"Yes, you may bring your own cake. Customized cakes can also be arranged from ₹1,000 depending on the cake.",
        "own_decoration":"Outside decoration is not allowed; decoration must be arranged through Entartica.",
        "food":"Food is not included in either standard package. It can be arranged based on your requirement; current options and prices need confirmation from our team.",
        "photoshoot":"The photoshoot add-on is ₹10,000 and includes 1 Reel plus 25 Photos. Delivery is expected within 2 weeks.",
        "drone":"Drone coverage is available for an additional ₹5,000 with the photoshoot package.",
        "singer":"The approved singer add-on is ₹8,000.",
        "booking_window":"Pontoon Celebration can be requested between 6:00 AM and 9:00 PM, subject to live availability.",
        "location":"Entartica SeaWorld is at Periyakulam Lake Boat House, Ukkadam, Coimbatore, Tamil Nadu 641001.\nhttps://www.google.com/maps/search/?api=1&query=Entartica+Sea+World+Periyakulam+Lake+Boat+House+Ukkadam+Coimbatore+Tamil+Nadu+641001",
        "parking":"Yes, parking is available at Entartica Coimbatore.", "washroom":"Yes, washrooms are available.",
        "changing_room":"Changing rooms and lockers are not available.",
        "park_timing":"The current official sources show slightly different closing times, so I’d like to have the current operating hours confirmed for your visit.",
    }
    if topic in answers: return CoimbatoreAnswer(topic, answers[topic], _DEFAULT_HEADINGS[topic])
    if topic == "availability": return CoimbatoreAnswer(topic, "That time may be within the booking window, but actual availability must be checked. I can have the team verify it for you.", "Availability Rules", requires_live_data=True, handoff_required=True)
    if topic == "payment": return CoimbatoreAnswer(topic, "Bookings require 100% advance payment, but I can’t verify payment status or create a payment link yet. Our team will assist with the secure next step.", "Payment Rules", requires_live_data=True, handoff_required=True)
    if topic == "discount": return CoimbatoreAnswer(topic, "Our team will help you with any available discount or special quotation.", "AI Permission Matrix — Confirmed", handoff_required=True)
    if topic == "cancellation": return CoimbatoreAnswer(topic, "Confirmed bookings are generally non-refundable, and late arrival or no-show is not refundable. Rescheduling is subject to availability and possible price revision. Our team must approve any cancellation or rescheduling request.", "Cancellation, Rescheduling, Refund & Weather Rules", handoff_required=True)
    return None


def _package_answer(guest_count: int, package_id: str) -> CoimbatoreAnswer:
    if package_id == "couple_romance":
        text = ("Perfect ❤️ For 2 guests, the Pontoon Couple Romance Celebration is a great fit.\n\n"
                "₹3,999\n• 20-minute private Pontoon ride\n• 250 g cake\n• Basic boat decoration\n"
                "• Music\n• Red carpet entry\n• 2 cold pyros")
        return CoimbatoreAnswer("price", text, "Couple Romance Celebration — Approved Package Master", package_id=package_id)
    price = "₹6,000" if guest_count <= 6 else "₹7,500" if guest_count <= 9 else "₹9,000"
    text = (f"For {guest_count} guests, the Pontoon Family & Friends Celebration is {price} 😊\n\n"
            "It includes a 30-minute ride, 500 g cake, decoration, music, red carpet and pyro entry.")
    return CoimbatoreAnswer("price", text, "Family & Friends Celebration — Approved Package Master", package_id=package_id)

_AUTHORITY_QUERY = {"location":"Official Location Google Maps Periyakulam Lake Boat House Ukkadam", "price":"Pontoon approved package master price", "cake":"Pontoon FAQ package cake included", "duration":"Pontoon package ride duration", "pregnancy":"Pontoon operational rules pregnant guests"}
_HEADING_TERMS = {"location":("official location","location & on-site"), "price":("approved package master","package specific","package selection"), "cake":("cake","package specific"), "duration":("package specific","commercial details"), "pregnancy":("pregnant guests","operational rules")}
_DEFAULT_HEADINGS = {"pregnancy":"Pregnant Guests","own_cake":"Food, Cake & Outside Items","own_decoration":"Fireworks, Pyro & Themes","food":"Food, Cake & Outside Items","photoshoot":"Photography & Media","drone":"Photography & Media","singer":"Approved Add-Ons","booking_window":"Pontoon FAQ — Package Specific","location":"Official Location","parking":"Location & On-Site Customer Journey","washroom":"Location & On-Site Customer Journey","changing_room":"Location & On-Site Customer Journey","park_timing":"Known Website Conflicts — Validation Queue"}
