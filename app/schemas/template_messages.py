"""Provider-neutral, durable WhatsApp template description."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TemplateMessage:
    name: str
    language: str
    header_image_url: str
    flow_id: str
    flow_cta: str
    service_code: str
    package_source_file: str
    approved_package: bool = True

    def as_metadata(self) -> dict[str, object]:
        return asdict(self)
