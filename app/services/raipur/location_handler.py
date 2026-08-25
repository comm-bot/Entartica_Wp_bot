"""Deterministic approved location helpers."""
import re
def is_location_question(text: str) -> bool:
    value=text.casefold(); phrases=("location bhejo","address batao","address bhejo","map link","google maps","location send","where is it","where are you located","directions","pata","pata batao","kahan hai","kaha hai","address","adress","addres","location","locaton","map","पता","पता भेजो","लोकेशन")
    return any(item in value or item in text for item in phrases) or bool(
        re.search(r"\bwhere\s+is\s+(?:entartica(?:\s+raipur)?|sea\s+world)\b", value)
    )
def structured_location_answer(location: dict | None, language: str) -> str | None:
    if not isinstance(location,dict): return None
    metadata=location.get("metadata") if isinstance(location.get("metadata"),dict) else {}; name=metadata.get("location_name",location.get("name")); address=metadata.get("address_line",location.get("address")); landmark=metadata.get("landmark"); maps_url=metadata.get("maps_url")
    if not all(isinstance(v,str) and v.strip() for v in (name,address,landmark,maps_url)): return None
    landmark_name=re.sub(r"^near\s+","",landmark.strip(),flags=re.I)
    if language=="hi": return f"{name.strip()}, {address.strip()} में, {landmark_name} के पास स्थित है।\n\nGoogle Maps:\n{maps_url.strip()}"
    if language=="hinglish": return f"{name.strip()}, {address.strip()} mein, {landmark_name} ke paas located hai.\n\nGoogle Maps:\n{maps_url.strip()}"
    return f"{name.strip()} is located at {address.strip()}, near {landmark_name}.\n\nGoogle Maps:\n{maps_url.strip()}"
