"""Deterministic Raipur language classification."""
import re
def detect_language(text: str) -> str:
    if re.search(r"[\u0900-\u097f]", text): return "hi"
    if re.search(r"\b(kal|hai|kya|mein|ka|karna|karni|mujhe|kro|bhejo|nmbr)\b", text, re.I): return "hinglish"
    return "en"
