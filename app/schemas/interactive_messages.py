"""Provider-neutral outbound WhatsApp interactive message descriptions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class InteractiveOption:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class InteractiveMessage:
    kind: Literal["list", "flow", "buttons"]
    body: str
    fallback_text: str
    button_label: str
    options: tuple[InteractiveOption, ...] = ()
    flow_id: str | None = None
    flow_token: str | None = None
    flow_cta: str | None = None
    flow_screen_id: str | None = None
    flow_type: Literal["general_quote", "celebration", "pontoon_celebration", "customer_details"] | None = None
    header_image_url: str | None = None

    def as_metadata(self) -> dict[str, object]:
        return asdict(self)


def location_selector() -> InteractiveMessage:
    return InteractiveMessage(
        kind="list",
        body="Welcome to Entartica Sea World 🌊\nPlease choose the location you'd like to explore.",
        fallback_text="Please choose your location:\n1. Raipur\n2. Coimbatore\n3. Prayagraj\n4. Rajsamand",
        button_label="Choose Location",
        options=tuple(
            InteractiveOption(f"location_{name.casefold()}", name)
            for name in ("Raipur", "Coimbatore", "Prayagraj", "Rajsamand")
        ),
    )


def celebration_selector(body: str) -> InteractiveMessage:
    """Expose the five canonical Raipur celebration services as one list."""
    return InteractiveMessage(
        kind="list",
        body=body,
        fallback_text=body,
        button_label="Choose Celebration",
        options=(
            InteractiveOption("celebration_floating_gazebo", "Floating Gazebo"),
            InteractiveOption("celebration_houseboat", "Houseboat Celebration"),
            InteractiveOption("celebration_jetty_gazebo", "Jetty Gazebo"),
            InteractiveOption("celebration_party_boat", "Party Boat Celebration"),
            InteractiveOption("celebration_pontoon", "Pontoon Boat Celebration"),
        ),
    )


def configured_flow(*, flow_type: Literal["general_quote", "celebration", "pontoon_celebration"], flow_id: str | None) -> InteractiveMessage:
    if flow_type == "general_quote":
        body, cta = "Kindly share the below details for the best quote.", "Plan My Visit"
    elif flow_type == "celebration":
        body, cta = "Please share your celebration details 🎉", "Share Celebration Details"
    else:
        body, cta = "Pontoon Celebration Details\n\nEvent Date\nNumber of Persons", "Share Celebration Details"
    fallback = body + " You can share the details naturally here."
    return InteractiveMessage(
        kind="flow" if flow_id else "list",
        body=body,
        fallback_text=fallback,
        button_label=cta,
        flow_id=flow_id,
        flow_token=f"entartica_{flow_type}",
        flow_cta=cta,
        flow_type=flow_type,
    )


def customer_details_flow(*, flow_id: str, flow_token: str) -> InteractiveMessage:
    """Open the published two-field customer-details form inside WhatsApp."""
    return InteractiveMessage(
        kind="flow",
        body=("Hi 👋 Welcome to Entartica Coimbatore!\n\n"
              "Before we start, please share your details so I can assist you better. 😊"),
        fallback_text="Please tap Complete Details to continue.",
        button_label="Complete Details",
        flow_id=flow_id,
        flow_token=flow_token,
        flow_cta="Complete Details",
        flow_screen_id="CUSTOMER_DETAILS",
        flow_type="customer_details",
    )
