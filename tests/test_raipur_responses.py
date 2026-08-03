from app.services.raipur_responses import RaipurResponseRequest,detect_language,present
def test_languages_and_safe_booking_templates():
 assert detect_language("मुझे जानकारी चाहिए").value=="hindi";assert detect_language("kal booking karni hai").value=="hinglish"
 response=present(RaipurResponseRequest("check_availability","english",availability_status="available"));assert "final booking confirmation" in response.text.casefold() and "confirmed" not in response.text.casefold()
 assert "No" in present(RaipurResponseRequest("ask","hinglish",next_required_field="special_requirements")).text
