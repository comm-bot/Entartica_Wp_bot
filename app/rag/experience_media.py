"""Typed extraction of approved Experience Media from exact KB documents."""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse


_URL = re.compile(r"https://[^\s<>()]+", re.I)
_APPROVED_HOSTS = {"instagram.com", "www.instagram.com", "youtube.com", "www.youtube.com", "youtu.be"}


@dataclass(frozen=True)
class ExperienceMedia:
    instagram_urls: tuple[str, ...] = ()
    youtube_urls: tuple[str, ...] = ()
    scope: str = "unknown"
    service_code: str | None = None
    category: str | None = None
    source_document: str | None = None

    @property
    def urls(self) -> tuple[str, ...]:
        return (*self.instagram_urls, *self.youtube_urls)


def extract_approved_media(rows: list[dict], *, scope: str, source_document: str, service_code: str | None = None, category: str | None = None) -> ExperienceMedia:
    """Extract allowlisted URLs; Raipur-general scope follows stored document order."""
    ordered = sorted(rows, key=lambda row: int(row.get("chunk_index", 0)))
    candidates: list[str] = []
    for row in ordered:
        heading = str((row.get("metadata") or {}).get("section_heading", ""))
        content = str(row.get("content", ""))
        if heading.casefold() not in {"instagram", "youtube"} and "experience media" not in heading.casefold():
            continue
        candidates.extend(_URL.findall(content))
    candidates = list(dict.fromkeys(url.rstrip(".,") for url in candidates if _approved_url(url)))
    # The shared general document intentionally contains venue media first,
    # followed by water-category media. Preserve that authored scope ordering.
    if source_document.endswith("raipur_general_information.md") and candidates:
        candidates = candidates[:1] if scope == "venue" else candidates[1:] if scope == "activity" else []
    instagram = tuple(url for url in candidates if "instagram.com" in urlparse(url).netloc.casefold())
    youtube = tuple(url for url in candidates if "youtu" in urlparse(url).netloc.casefold())
    return ExperienceMedia(instagram, youtube, scope, service_code, category, source_document)


def _approved_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc.casefold() in _APPROVED_HOSTS
