from types import SimpleNamespace

from app.services.raipur_sales_contact import SalesContact, approved_safe_fallback, controlled_sales_handover, direct_human_handover


def test_handover_text_has_approved_contact_without_collection_prompts():
    contact = SalesContact.from_settings(SimpleNamespace(entartica_sales_phone="+919429691418", entartica_sales_email="sales@entartica.com"))
    for answer in (approved_safe_fallback(contact, "en"), controlled_sales_handover(contact, "en"), direct_human_handover(contact, "en")):
        assert "+91 94296 91418" in answer and "sales@entartica.com" in answer
        lowered = answer.casefold()
        assert all(term not in lowered for term in ("visit date", "guest count", "what date", "what time", "your name"))
