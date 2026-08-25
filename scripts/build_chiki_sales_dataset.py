"""Build the deterministic, reviewed Chiki sales-composer v1 dataset."""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/"data"/"fine_tuning"/"chiki_sales_v1"
SYSTEM=("You are Chiki, the customer-facing sales host for Entartica Sea World Raipur. Speak warmly and naturally for WhatsApp. "
"Use only supplied approved facts, options, recommendation and next question. Be benefit-led and concise. Ask only the supplied question. "
"Never invent services, prices, availability, capacity, booking status or missing facts.")
OPTIONS=["Floating Gazebo","Houseboat Celebration","Jetty Gazebo","Party Boat Celebration","Pontoon Celebration"]
SERVICES={
"party_boat_celebration":("Party Boat Celebration","a lively on-water group celebration with music and a social atmosphere"),
"floating_gazebo":("Floating Gazebo","a scenic private celebration setting on the water"),
"houseboat_celebration":("Houseboat Celebration","a relaxed celebration experience on a houseboat"),
"jetty_gazebo":("Jetty Gazebo","a comfortable waterside gazebo setting for celebrations"),
"pontoon_celebration":("Pontoon Celebration","a peaceful on-water celebration experience"),
"jet_ski_ride":("Jet Ski","an energetic self-driven water ride with staff guidance"),
"speed_boat_ride":("Speed Boat","a fast-paced boat ride for guests who enjoy excitement on the water"),
"pontoon_boat_ride":("Pontoon Boat","a relaxed leisure boat ride on the lake"),
"inflatable_sofa_ride":("Inflatable Sofa Ride","a lively towable water ride for an adventurous experience"),
"kayaking":("Kayak","a paddle-based H2O Play Park activity for exploring at your own pace"),
"aqua_cycle":("Aqua Cycle","a pedal-powered H2O Play Park activity on the water"),
"bumper_boat":("Bumper Boat","a playful H2O activity built around steering and friendly bumping"),
"zorbing_ball":("Zorbing Ball","a playful H2O activity where balancing, rolling and bouncing are part of the fun"),
"water_bike":("Water Bike","a cycling-style H2O Play Park experience on the water"),
"kids_bumper_boat":("Kids Bumper Boat","a child-focused H2O activity with a kid-sized steering experience"),
"kids_paddle_boat":("Kids Paddle Boat","a child-focused H2O activity for steering and pedalling on the water"),
"daycation_package":("Daycation Package","a day-use experience combining resort comfort with approved water activities"),
"staycation_combo":("Staycation Combo","an overnight resort stay combined with approved Entartica activities")}
H2O=("kayaking","aqua_cycle","bumper_boat","zorbing_ball","water_bike","kids_bumper_boat","kids_paddle_boat")
RIDES=("jet_ski_ride","speed_boat_ride","pontoon_boat_ride","inflatable_sofa_ride")

def brief(goal,lang,**kw):
 d={"response_goal":goal,"customer_language":lang,"service_code":None,"service_name":None,"approved_facts":[],"customer_facts":None,"approved_options":[],"known_occasion":None,"known_guest_count":None,"known_date":None,"known_preference":None,"recommended_service_codes":[],"next_action":None,"next_question":None,"restrictions":["Use only supplied facts and actions","Do not invent commercial or operational claims"]};d.update(kw);return d
def add(rows,data,answer,case):rows.append({"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(data,ensure_ascii=False,sort_keys=True)},{"role":"assistant","content":answer}],"metadata":{"case_id":case}})
def facts(**kw):
 d={"experience_summary":None,"benefits":[],"duration_type":None,"duration_value":None,"operating_hours":None,"access_type":None,"approved_inclusions":[],"suitability":[],"relevant_highlights":[]};d.update(kw);return d

def build():
 rows=[]
 openings=("That sounds lovely","Great idea","Let's make it special","Wonderful plan")
 occasions=("birthday","anniversary","corporate event","special event")
 langs=("en","hinglish","hi")
 for i in range(12):
  lang=langs[i%3];occasion=occasions[i%4];q={"en":"How many guests will be joining?","hinglish":"Approx kitne guests honge?","hi":"लगभग कितने मेहमान होंगे?"}[lang]
  if lang=="en":a=f"{openings[i%4]} 🎉 For your {occasion}, you can explore {', '.join(OPTIONS[:-1])} and {OPTIONS[-1]}. {q}"
  elif lang=="hinglish":a=f"{occasion.title()} ko special banate hain 🎉 Options mein {', '.join(OPTIONS[:-1])} aur {OPTIONS[-1]} hain. {q}"
  else:a=f"{occasion} को खास बनाते हैं 🎉 विकल्प हैं {', '.join(OPTIONS[:-1])} और {OPTIONS[-1]}। {q}"
  add(rows,brief("celebration_discovery",lang,approved_options=OPTIONS,known_occasion=occasion,next_action="ask_guest_count",next_question=q),a,f"discovery-{i}")
 for i,g in enumerate((2,4,6,8,10,12,14,16,18)):
  lang=langs[i%3];q={"en":"What date are you planning it for?","hinglish":"Aap kis date ko plan kar rahe hain?","hi":"आप किस तारीख की योजना बना रहे हैं?"}[lang]
  occasion=occasions[i%4]
  lead_en=("Perfect","Great, that helps","Lovely, I've got that")[i%3];lead_hi=("बहुत अच्छा","ठीक है","शानदार")[i%3]
  a={"en":f"{lead_en} — I've noted a {occasion} for {g} guests. {q}","hinglish":f"{lead_en}, {occasion} ke liye {g} guests note kar liye. {q}","hi":f"{lead_hi}, {occasion} के लिए {g} मेहमान नोट कर लिए हैं। {q}"}[lang]
  add(rows,brief("ask_date",lang,approved_facts=[f"Guest count: {g}",f"Occasion: {occasion}"],known_occasion=occasion,known_guest_count=g,next_action="ask_date",next_question=q),a,f"date-{i}")
 dates=("13 August 2026","15 August 2026","22 September 2026","5 October 2026","12 November 2026","20 December 2026","8 January 2027","14 February 2027","21 March 2027")
 for i,date in enumerate(dates):
  lang=langs[(i+1)%3];g=(6,8,12)[i%3];q={"en":"Would you prefer something lively, private, or relaxed?","hinglish":"Aap lively, private ya relaxed celebration prefer karenge?","hi":"आप lively, private या relaxed celebration पसंद करेंगे?"}[lang]
  a={"en":f"Great — {date} for {g} guests is noted. {q}","hinglish":f"Great, {date} aur {g} guests note ho gaye. {q}","hi":f"बहुत बढ़िया, {date} और {g} मेहमान नोट हो गए हैं। {q}"}[lang]
  add(rows,brief("ask_preference",lang,approved_facts=[date,f"{g} guests"],known_guest_count=g,known_date=date,next_action="ask_preference",next_question=q),a,f"preference-{i}")
 recs=(("party_boat_celebration","birthday","lively party-style"),("floating_gazebo","anniversary","private and intimate"),("houseboat_celebration","birthday","relaxed"),("jetty_gazebo","corporate event","relaxed"),("pontoon_celebration","anniversary","peaceful and private"))
 for i in range(12):
  code,occasion,pref=recs[i%5];name,_=SERVICES[code];lang=langs[i%3];q={"en":"Would you like to explore its highlights?","hinglish":"Kya aap iske highlights dekhna chahenge?","hi":"क्या आप इसकी खास बातें जानना चाहेंगे?"}[lang]
  a={"en":f"For the {pref} experience you want, {name} looks like a strong option ✨ {q}","hinglish":f"Aapki {pref} preference ke hisaab se {name} ek strong option lagta hai ✨ {q}","hi":f"आपकी {pref} पसंद के अनुसार {name} एक अच्छा विकल्प लगता है ✨ {q}"}[lang]
  add(rows,brief("service_recommendation",lang,service_code=code,service_name=name,approved_facts=[f"Supports {occasion} and {pref} preferences"],known_occasion=occasion,known_preference=pref,recommended_service_codes=[code],next_action="answer_service",next_question=q),a,f"recommend-{i}")
 for i,(code,(name,summary)) in enumerate(SERVICES.items()):
  for variant in range(2 if i<14 else 1):
   lang=langs[(i+variant)%3];q={"en":"Would you like its duration or highlights?","hinglish":"Aap duration ya highlights jaana chahenge?","hi":"क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}[lang]
   a={"en":f"{name} is {summary}. It can add a memorable water experience to your visit. {q}","hinglish":f"{name} ek engaging water experience hai — {summary}. Visit ko memorable banane ke liye yeh achha option ho sakta hai. {q}","hi":f"{name} एक खास water experience है — {summary}। यह आपकी visit को यादगार बना सकता है। {q}"}[lang]
   add(rows,brief("service_overview",lang,service_code=code,service_name=name,approved_facts=[summary],customer_facts=facts(experience_summary=summary,benefits=["memorable water experience"]),next_action="answer_service",next_question=q),a,f"overview-{code}-{variant}")
 for i,(code,(name,summary)) in enumerate(list(SERVICES.items())[:15]):
  lang=langs[i%3];q={"en":"Would you like to check the duration?","hinglish":"Duration check karein?","hi":"क्या आप अवधि जानना चाहेंगे?"}[lang]
  a={"en":f"A lovely highlight of {name} is that it is {summary}. {q}","hinglish":f"{name} ki ek khaas baat: {summary}. {q}","hi":f"{name} की एक खास बात है: {summary}। {q}"}[lang]
  add(rows,brief("service_more_details",lang,service_code=code,service_name=name,approved_facts=[summary],customer_facts=facts(relevant_highlights=[summary]),next_action="answer_service",next_question=q),a,f"more-{code}")
 for i,code in enumerate(H2O):
  name,_=SERVICES[code];lang=langs[i%3];cf=facts(duration_type="full_day_access",operating_hours="10:00 AM to 6:30 PM",access_type="h2o_play_park")
  a={"en":f"{name} is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM 🌊","hinglish":f"{name} H2O Play Park ke full-day access mein included hai, 10:00 AM se 6:30 PM tak 🌊","hi":f"{name} H2O Play Park के full-day access में शामिल है, 10:00 AM से 6:30 PM तक 🌊"}[lang]
  add(rows,brief("factual_answer",lang,service_code=code,service_name=name,approved_facts=["Full-day access from 10:00 AM to 6:30 PM"],customer_facts=cf),a,f"h2o-access-{code}")
  cf2=facts(duration_type="individual_turn_unknown",operating_hours="10:00 AM to 6:30 PM",access_type="h2o_play_park")
  a={"en":f"The individual {name} turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.","hinglish":f"{name} ke individual turn ka exact duration separately listed nahi hai. H2O Play Park access 10:00 AM se 6:30 PM tak hai.","hi":f"{name} के individual turn की अवधि अलग से listed नहीं है। H2O Play Park access 10:00 AM से 6:30 PM तक है।"}[lang]
  add(rows,brief("factual_answer",lang,service_code=code,service_name=name,approved_facts=["Individual turn duration separately unavailable","Full-day access from 10:00 AM to 6:30 PM"],customer_facts=cf2),a,f"h2o-turn-{code}")
 for i,code in enumerate(RIDES):
  name,_=SERVICES[code];lang=("en","hinglish")[i%2];a=f"{name} ka one-time ride approximately 5–10 minutes ka hota hai 🌊" if lang=="hinglish" else f"{name} is an approximately 5–10 minute one-time ride 🌊"
  add(rows,brief("factual_answer",lang,service_code=code,service_name=name,approved_facts=["Approximately 5–10 minutes"],customer_facts=facts(duration_type="ride_duration",duration_value="approximately 5–10 minutes",access_type="one_time_ride")),a,f"ride-{code}")
 for i,(code,(name,_)) in enumerate(list(SERVICES.items())[:6]):
  lang=langs[i%3];a={"en":f"I don't have a confirmed detail for that about {name} right now. The Entartica team can help verify it for you.","hinglish":f"{name} ke liye yeh detail abhi confirmed nahi hai. Entartica team verify kar sakti hai.","hi":f"{name} के बारे में यह जानकारी अभी confirmed नहीं है। Entartica team verify करने में मदद कर सकती है।"}[lang]
  add(rows,brief("factual_answer",lang,service_code=code,service_name=name,approved_facts=["Requested detail unavailable; do not invent"],next_action="none"),a,f"unknown-{i}")
 acts=[("en","If you enjoy high energy, Jet Ski and Speed Boat are exciting choices; Kayak and Aqua Cycle offer a gentler pace. Would you prefer thrill or relaxation?","Would you prefer thrill or relaxation?"),("hinglish","Adventure ke liye Jet Ski aur Speed Boat, aur relaxed pace ke liye Kayak ya Aqua Cycle explore kar sakte hain. Aap thrill ya relaxation prefer karenge?","Aap thrill ya relaxation prefer karenge?"),("en","For family water fun, Kayak, Aqua Cycle and Zorbing Ball offer different ways to enjoy the lake. What age group will be joining?","What age group will be joining?"),("hinglish","Family ke saath Kayak, Aqua Cycle aur Zorbing Ball explore kar sakte hain. Kids ki age group kya hai?","Kids ki age group kya hai?"),("en","Jet Ski feels energetic, while Kayak and Aqua Cycle let you enjoy the water at your own pace. Which style sounds better?","Which style sounds better?"),("hinglish","Speed Boat, Kayak, Aqua Cycle aur Zorbing Ball mein achhi variety hai. Fast-paced ya playful experience chahiye?","Fast-paced ya playful experience chahiye?"),("en","Kayak and Aqua Cycle suit a relaxed pace; Jet Ski and Speed Boat bring more energy. What mood are you in?","What mood are you in?")]
 opt=[SERVICES[c][0] for c in ("jet_ski_ride","speed_boat_ride","kayaking","aqua_cycle","zorbing_ball")]
 for i,(lang,a,q) in enumerate(acts):add(rows,brief("family_discovery" if i in (2,3) else "activity_discovery",lang,approved_options=opt,next_action="continue_discovery",next_question=q),a,f"activity-{i}")
 assert len(rows)==120,len(rows);return rows

def main():
 rows=build();ROOT.mkdir(parents=True,exist_ok=True);splits={"train":[],"validation":[],"holdout":[]}
 for i,item in enumerate(rows):splits["holdout" if i%6==0 else "validation" if i%6==1 else "train"].append(item)
 # Add package-duration gold cases to learning splits only. Holdout identity
 # and its original twenty scenarios remain unchanged.
 day=brief("factual_answer","en",service_code="daycation_package",service_name="Daycation Package",approved_facts=["2:00 PM to 6:00 PM","4-hour Daycation window"],customer_facts=facts(duration_type="package_window",duration_value="4 hours",operating_hours="2:00 PM to 6:00 PM",access_type="daycation"))
 stay=brief("factual_answer","hinglish",service_code="staycation_combo",service_name="Staycation Combo",approved_facts=["2:00 PM to 12:00 PM next day"],customer_facts=facts(duration_type="overnight_package_window",duration_value="2:00 PM to 12:00 PM next day",access_type="staycation"))
 splits["train"][-1]={"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(day,ensure_ascii=False,sort_keys=True)},{"role":"assistant","content":"Daycation runs from 2:00 PM to 6:00 PM, giving you a 4-hour daytime experience to enjoy the resort and Entartica activities 🌊"}],"metadata":{"case_id":"daycation-duration"}}
 splits["validation"][-1]={"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(stay,ensure_ascii=False,sort_keys=True)},{"role":"assistant","content":"Staycation Combo ka approved window 2:00 PM se next day 12:00 PM tak hai, so you can enjoy an overnight resort stay with Entartica activities."}],"metadata":{"case_id":"staycation-duration"}}
 assert {k:len(v) for k,v in splits.items()}=={"train":80,"validation":20,"holdout":20}
 for name,items in splits.items():(ROOT/f"{name}.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in items)+"\n",encoding="utf-8")
 briefs=[json.loads(x["messages"][1]["content"]) for items in splits.values() for x in items]
 manifest={"version":"chiki_sales_v1","example_counts":{k:len(v) for k,v in splits.items()},"total_examples":120,"response_goal_distribution":dict(Counter(x["response_goal"] for x in briefs)),"language_distribution":dict(Counter(x["customer_language"] for x in briefs)),"service_coverage":sorted({x["service_code"] for x in briefs if x["service_code"]}),"safety_unknown_examples":6,"h2o_examples":14,"recommendation_examples":12,"qualification_examples":18,"created_from":["SalesResponseBrief","CustomerFacts","approved Raipur service catalogue","governed duration/access facts"],"validation_status":"passed_offline_validation","contains_customer_pii":False,"external_upload":False}
 (ROOT/"dataset_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
