"""Deterministic, non-sending customer presentation for typed Raipur outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

class RaipurResponseLanguage(StrEnum): ENGLISH="english"; HINDI="hindi"; HINGLISH="hinglish"
class RaipurResponseTemplateKey(StrEnum): FIELD="booking_field"; COMPLETE="booking_complete"; AVAILABILITY="availability"; PRICING="pricing"; HANDOVER="handover"; INFORMATION="information"
@dataclass(frozen=True)
class RaipurResponseRequest:
 action:str; language:str; reason_code:str=""; grounded_answer:str|None=None; availability_status:str|None=None; next_required_field:str|None=None; human_handover_required:bool=False
@dataclass(frozen=True)
class RaipurResponse:
 text:str; language:RaipurResponseLanguage; template_key:RaipurResponseTemplateKey; response_valid:bool; safe_validation_reason:str
def detect_language(text:str,previous:str|None=None)->RaipurResponseLanguage:
 if any("\u0900"<=c<="\u097f" for c in text):return RaipurResponseLanguage.HINDI
 if any(x in text.casefold() for x in (" kya"," kaise"," kal"," aaj"," chahiye","karni hai"," kitna"," batao"," nahi","booking karni")):return RaipurResponseLanguage.HINGLISH
 return RaipurResponseLanguage(previous) if previous in {x.value for x in RaipurResponseLanguage} and len(text.split())<=3 else RaipurResponseLanguage.ENGLISH
def present(request:RaipurResponseRequest)->RaipurResponse:
 lang=detect_language("",request.language);field=request.next_required_field
 if request.grounded_answer:
  key=RaipurResponseTemplateKey.FIELD if field else RaipurResponseTemplateKey.PRICING if request.action=="pricing_sales_handover" else RaipurResponseTemplateKey.AVAILABILITY if request.availability_status else RaipurResponseTemplateKey.INFORMATION
  return RaipurResponse(request.grounded_answer,lang,key,True,"grounded")
 if field:
  prompts={"requested_service_text":("Which activity would you like to enquire about?","आप किस गतिविधि के लिए पूछताछ करना चाहते हैं?","Aap kis activity ke liye enquiry karna chahte hain?"),"preferred_date":("What date would you prefer?","आप किस तारीख को आना चाहेंगे?","Aap kis date ko aana chahenge?"),"preferred_time":("What time would you prefer? Please include AM or PM.","आप किस समय आना चाहेंगे? कृपया AM या PM भी बताएं।","Aap kis time aana chahenge? Please AM ya PM bhi batayein."),"adults_count":("How many adults will be joining?","कितने वयस्क शामिल होंगे?","Kitne adults join karenge?"),"children_count":("How many children will be joining?","कितने बच्चे शामिल होंगे?","Kitne children join karenge?"),"total_guests":("What is the total number of guests?","कुल कितने अतिथि होंगे?","Total kitne guests honge?"),"special_requirements":("Do you have any special requirements? You can reply 'No' if there are none.","क्या आपकी कोई विशेष आवश्यकता है? नहीं हो तो 'नहीं' लिखें।","Koi special requirement hai? Nahi ho to 'No' reply karein.")};text=prompts.get(field,("Please share the next detail.",)*3)[list(RaipurResponseLanguage).index(lang)];return RaipurResponse(text,lang,RaipurResponseTemplateKey.FIELD,True,"safe")
 if request.action=="pricing_sales_handover":text=("Pricing is provided by our sales team based on your requirements. This is not a final booking confirmation.","मूल्य की जानकारी हमारी बिक्री टीम देगी। यह अंतिम बुकिंग पुष्टि नहीं है।","Pricing hamari sales team aapki requirements ke basis par batayegi. Yeh final booking confirmation nahi hai.")[list(RaipurResponseLanguage).index(lang)];return RaipurResponse(text,lang,RaipurResponseTemplateKey.PRICING,True,"safe")
 if request.availability_status in {"available","limited","not_available","verification_required","stale","provider_error"}:
  text="The requested slot requires team verification. This is not a final booking confirmation." if request.availability_status not in {"available","limited"} else "The requested slot currently appears available. This is not a final booking confirmation. Our team will verify the details.";return RaipurResponse(text,lang,RaipurResponseTemplateKey.AVAILABILITY,True,"safe")
 if request.grounded_answer:return RaipurResponse(request.grounded_answer,lang,RaipurResponseTemplateKey.INFORMATION,True,"grounded")
 return RaipurResponse("Our team will assist you with this request.",lang,RaipurResponseTemplateKey.HANDOVER,True,"safe")
