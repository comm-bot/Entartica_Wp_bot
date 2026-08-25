"""Short deterministic greeting helpers."""
import re

_GREETING = re.compile(r"(?:hi+|hello|hey|namaste|bye|goodbye)", re.I)
_ACKNOWLEDGEMENT = re.compile(
    r"(?:thanks?|thank\s+you|okay\s+thanks|shukriya|dhanyavaad|achha|thik\s+hai|theek\s+hai|ok|okay|great|understood|got\s+it|alright|fine|धन्यवाद|शुक्रिया)",
    re.I,
)


def _whole_message(text: object, pattern: re.Pattern) -> bool:
    """Match only a short standalone message, ignoring trailing punctuation."""
    if not isinstance(text, str):
        return False
    cleaned = re.sub(r"\s*[.!?]+\s*$", "", text.strip())
    return bool(pattern.fullmatch(cleaned))


def is_greeting(text: object) -> bool:
    return _whole_message(text, _GREETING)


def is_acknowledgement(text: object) -> bool:
    return _whole_message(text, _ACKNOWLEDGEMENT)


def is_gratitude(text: str) -> bool:
    return bool(re.search(r"\b(?:thanks?|thank\s+you|shukriya|dhanyavaad)\b", text, re.I))
def greeting_response(language: str) -> str:
    if language == "hi": return "नमस्ते! मैं Chiki हूँ, Entartica Sea World से। मैं Raipur की rides, celebration options, timings और booking enquiries में मदद कर सकता हूँ।"
    if language == "hinglish": return "Namaste! Main Chiki hoon, Entartica Sea World se. Main Raipur ki rides, celebration options, timings aur booking enquiries mein madad kar sakta hoon."
    return "Hello! I'm Chiki from Entartica Sea World. I can help you with Raipur rides, celebration options, timings, and booking enquiries."
def acknowledgement_response(language: str) -> str:
    if language == "hi": return "धन्यवाद! मैं आपकी और मदद के लिए यहाँ हूँ।"
    if language == "hinglish": return "Shukriya! Main aapki aur help ke liye yahin hoon."
    return "You're welcome! I am here to help."
