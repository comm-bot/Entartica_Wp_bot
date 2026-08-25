"""Deterministic greeting-versus-acknowledgement distinction tests."""
import pytest

from app.services.raipur.greeting_handler import acknowledgement_response, greeting_response, is_acknowledgement, is_greeting


@pytest.mark.parametrize("text", [
    "thank you", "thanks", "okay thanks", "ok", "okay", "great",
    "understood", "got it", "alright", "fine",
    "achha", "thik hai", "theek hai", "dhanyavaad", "shukriya",
    "धन्यवाद", "शुक्रिया",
    "Thank You!", "okay.", "Theek hai",
])
def test_acknowledgement_phrases_are_detected(text):
    assert is_acknowledgement(text)


@pytest.mark.parametrize("text", [
    "hi", "hii", "hello", "hey", "namaste", "bye", "goodbye", "Hello!",
])
def test_greeting_phrases_are_detected(text):
    assert is_greeting(text)


def test_acknowledgement_is_not_misclassified_as_greeting():
    for text in ("thank you", "okay", "thik hai", "got it", "shukriya", "धन्यवाद"):
        assert not is_greeting(text)


def test_greeting_is_not_misclassified_as_acknowledgement():
    for text in ("hi", "hello", "hey", "namaste"):
        assert not is_acknowledgement(text)


@pytest.mark.parametrize("text", [
    "What is included?", "How long is it?", "Tell me about Jet Ski.",
    "Can pregnant women ride Jet Ski?", "thank you for the details",
    "Please book Jet Ski for tomorrow",
])
def test_service_questions_are_never_acknowledgements_or_greetings(text):
    assert not is_acknowledgement(text)
    assert not is_greeting(text)


@pytest.mark.parametrize("language", ["en", "hinglish", "hi"])
def test_greeting_uses_chiki_identity_without_virtual_assistant(language):
    response = greeting_response(language)
    assert "chiki" in response.casefold()
    assert "entartica sea world" in response.casefold()
    assert "virtual assistant" not in response.casefold()


def test_acknowledgement_response_is_unchanged():
    response = acknowledgement_response("en")
    assert "virtual assistant" not in response.casefold()
    assert response.casefold().strip().startswith("you're welcome")
