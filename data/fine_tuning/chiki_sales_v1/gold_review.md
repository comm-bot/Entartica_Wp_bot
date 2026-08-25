# Chiki Sales v1 — Gold Response Review

Reviewed: 120 | Revised: 34 | Needs human review: 0

Holdout membership and all 20 holdout scenario inputs are unchanged. Tone scoring of live model output was not run because that requires external OpenAI calls.

## train · discovery-2

- Response goal: `celebration_discovery`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "corporate event", "next_action": "ask_guest_count", "next_question": "लगभग कितने मेहमान होंगे?"}`

> corporate event को खास बनाते हैं 🎉 विकल्प हैं Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration और Pontoon Celebration। लगभग कितने मेहमान होंगे?

## train · discovery-3

- Response goal: `celebration_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "special event", "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

> Wonderful plan 🎉 For your special event, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

## train · discovery-4

- Response goal: `celebration_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "birthday", "next_action": "ask_guest_count", "next_question": "Approx kitne guests honge?"}`

> Birthday ko special banate hain 🎉 Options mein Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration aur Pontoon Celebration hain. Approx kitne guests honge?

## train · discovery-5

- Response goal: `celebration_discovery`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "anniversary", "next_action": "ask_guest_count", "next_question": "लगभग कितने मेहमान होंगे?"}`

> anniversary को खास बनाते हैं 🎉 विकल्प हैं Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration और Pontoon Celebration। लगभग कितने मेहमान होंगे?

## train · discovery-8

- Response goal: `celebration_discovery`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "birthday", "next_action": "ask_guest_count", "next_question": "लगभग कितने मेहमान होंगे?"}`

> birthday को खास बनाते हैं 🎉 विकल्प हैं Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration और Pontoon Celebration। लगभग कितने मेहमान होंगे?

## train · discovery-9

- Response goal: `celebration_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "anniversary", "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

> Great idea 🎉 For your anniversary, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

## train · discovery-10

- Response goal: `celebration_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "corporate event", "next_action": "ask_guest_count", "next_question": "Approx kitne guests honge?"}`

> Corporate Event ko special banate hain 🎉 Options mein Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration aur Pontoon Celebration hain. Approx kitne guests honge?

## train · discovery-11

- Response goal: `celebration_discovery`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "special event", "next_action": "ask_guest_count", "next_question": "लगभग कितने मेहमान होंगे?"}`

> special event को खास बनाते हैं 🎉 विकल्प हैं Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration और Pontoon Celebration। लगभग कितने मेहमान होंगे?

## train · date-2

- Response goal: `ask_date`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 6", "Occasion: corporate event"], "known_occasion": "corporate event", "known_guest_count": 6, "next_action": "ask_date", "next_question": "आप किस तारीख की योजना बना रहे हैं?"}`

> शानदार, corporate event के लिए 6 मेहमान नोट कर लिए हैं। आप किस तारीख की योजना बना रहे हैं?

## train · date-3

- Response goal: `ask_date`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 8", "Occasion: special event"], "known_occasion": "special event", "known_guest_count": 8, "next_action": "ask_date", "next_question": "What date are you planning it for?"}`

> Perfect — I've noted a special event for 8 guests. What date are you planning it for?

## train · date-4

- Response goal: `ask_date`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 10", "Occasion: birthday"], "known_occasion": "birthday", "known_guest_count": 10, "next_action": "ask_date", "next_question": "Aap kis date ko plan kar rahe hain?"}`

> Great, that helps, birthday ke liye 10 guests note kar liye. Aap kis date ko plan kar rahe hain?

## train · date-5

- Response goal: `ask_date`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 12", "Occasion: anniversary"], "known_occasion": "anniversary", "known_guest_count": 12, "next_action": "ask_date", "next_question": "आप किस तारीख की योजना बना रहे हैं?"}`

> शानदार, anniversary के लिए 12 मेहमान नोट कर लिए हैं। आप किस तारीख की योजना बना रहे हैं?

## train · date-8

- Response goal: `ask_date`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 18", "Occasion: birthday"], "known_occasion": "birthday", "known_guest_count": 18, "next_action": "ask_date", "next_question": "आप किस तारीख की योजना बना रहे हैं?"}`

> शानदार, birthday के लिए 18 मेहमान नोट कर लिए हैं। आप किस तारीख की योजना बना रहे हैं?

## train · preference-0

- Response goal: `ask_preference`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["13 August 2026", "6 guests"], "known_guest_count": 6, "known_date": "13 August 2026", "next_action": "ask_preference", "next_question": "Aap lively, private ya relaxed celebration prefer karenge?"}`

> Great, 13 August 2026 aur 6 guests note ho gaye. Aap lively, private ya relaxed celebration prefer karenge?

## train · preference-1

- Response goal: `ask_preference`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["15 August 2026", "8 guests"], "known_guest_count": 8, "known_date": "15 August 2026", "next_action": "ask_preference", "next_question": "आप lively, private या relaxed celebration पसंद करेंगे?"}`

> बहुत बढ़िया, 15 August 2026 और 8 मेहमान नोट हो गए हैं। आप lively, private या relaxed celebration पसंद करेंगे?

## train · preference-2

- Response goal: `ask_preference`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["22 September 2026", "12 guests"], "known_guest_count": 12, "known_date": "22 September 2026", "next_action": "ask_preference", "next_question": "Would you prefer something lively, private, or relaxed?"}`

> Great — 22 September 2026 for 12 guests is noted. Would you prefer something lively, private, or relaxed?

## train · preference-5

- Response goal: `ask_preference`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["20 December 2026", "12 guests"], "known_guest_count": 12, "known_date": "20 December 2026", "next_action": "ask_preference", "next_question": "Would you prefer something lively, private, or relaxed?"}`

> Great — 20 December 2026 for 12 guests is noted. Would you prefer something lively, private, or relaxed?

## train · preference-6

- Response goal: `ask_preference`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["8 January 2027", "6 guests"], "known_guest_count": 6, "known_date": "8 January 2027", "next_action": "ask_preference", "next_question": "Aap lively, private ya relaxed celebration prefer karenge?"}`

> Great, 8 January 2027 aur 6 guests note ho gaye. Aap lively, private ya relaxed celebration prefer karenge?

## train · preference-7

- Response goal: `ask_preference`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["14 February 2027", "8 guests"], "known_guest_count": 8, "known_date": "14 February 2027", "next_action": "ask_preference", "next_question": "आप lively, private या relaxed celebration पसंद करेंगे?"}`

> बहुत बढ़िया, 14 February 2027 और 8 मेहमान नोट हो गए हैं। आप lively, private या relaxed celebration पसंद करेंगे?

## train · preference-8

- Response goal: `ask_preference`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["21 March 2027", "12 guests"], "known_guest_count": 12, "known_date": "21 March 2027", "next_action": "ask_preference", "next_question": "Would you prefer something lively, private, or relaxed?"}`

> Great — 21 March 2027 for 12 guests is noted. Would you prefer something lively, private, or relaxed?

## train · recommend-2

- Response goal: `service_recommendation`
- Language: `hi`
- Service: `Houseboat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports birthday and relaxed preferences"], "known_occasion": "birthday", "known_preference": "relaxed", "recommended_service_codes": ["houseboat_celebration"], "next_action": "answer_service", "next_question": "क्या आप इसकी खास बातें जानना चाहेंगे?"}`

> आपकी relaxed पसंद के अनुसार Houseboat Celebration एक अच्छा विकल्प लगता है ✨ क्या आप इसकी खास बातें जानना चाहेंगे?

## train · recommend-3

- Response goal: `service_recommendation`
- Language: `en`
- Service: `Jetty Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports corporate event and relaxed preferences"], "known_occasion": "corporate event", "known_preference": "relaxed", "recommended_service_codes": ["jetty_gazebo"], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

> For the relaxed experience you want, Jetty Gazebo looks like a strong option ✨ Would you like to explore its highlights?

## train · recommend-4

- Response goal: `service_recommendation`
- Language: `hinglish`
- Service: `Pontoon Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports anniversary and peaceful and private preferences"], "known_occasion": "anniversary", "known_preference": "peaceful and private", "recommended_service_codes": ["pontoon_celebration"], "next_action": "answer_service", "next_question": "Kya aap iske highlights dekhna chahenge?"}`

> Aapki peaceful and private preference ke hisaab se Pontoon Celebration ek strong option lagta hai ✨ Kya aap iske highlights dekhna chahenge?

## train · recommend-5

- Response goal: `service_recommendation`
- Language: `hi`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports birthday and lively party-style preferences"], "known_occasion": "birthday", "known_preference": "lively party-style", "recommended_service_codes": ["party_boat_celebration"], "next_action": "answer_service", "next_question": "क्या आप इसकी खास बातें जानना चाहेंगे?"}`

> आपकी lively party-style पसंद के अनुसार Party Boat Celebration एक अच्छा विकल्प लगता है ✨ क्या आप इसकी खास बातें जानना चाहेंगे?

## train · recommend-8

- Response goal: `service_recommendation`
- Language: `hi`
- Service: `Jetty Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports corporate event and relaxed preferences"], "known_occasion": "corporate event", "known_preference": "relaxed", "recommended_service_codes": ["jetty_gazebo"], "next_action": "answer_service", "next_question": "क्या आप इसकी खास बातें जानना चाहेंगे?"}`

> आपकी relaxed पसंद के अनुसार Jetty Gazebo एक अच्छा विकल्प लगता है ✨ क्या आप इसकी खास बातें जानना चाहेंगे?

## train · recommend-9

- Response goal: `service_recommendation`
- Language: `en`
- Service: `Pontoon Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports anniversary and peaceful and private preferences"], "known_occasion": "anniversary", "known_preference": "peaceful and private", "recommended_service_codes": ["pontoon_celebration"], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

> For the peaceful and private experience you want, Pontoon Celebration looks like a strong option ✨ Would you like to explore its highlights?

## train · recommend-10

- Response goal: `service_recommendation`
- Language: `hinglish`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports birthday and lively party-style preferences"], "known_occasion": "birthday", "known_preference": "lively party-style", "recommended_service_codes": ["party_boat_celebration"], "next_action": "answer_service", "next_question": "Kya aap iske highlights dekhna chahenge?"}`

> Aapki lively party-style preference ke hisaab se Party Boat Celebration ek strong option lagta hai ✨ Kya aap iske highlights dekhna chahenge?

## train · recommend-11

- Response goal: `service_recommendation`
- Language: `hi`
- Service: `Floating Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports anniversary and private and intimate preferences"], "known_occasion": "anniversary", "known_preference": "private and intimate", "recommended_service_codes": ["floating_gazebo"], "next_action": "answer_service", "next_question": "क्या आप इसकी खास बातें जानना चाहेंगे?"}`

> आपकी private and intimate पसंद के अनुसार Floating Gazebo एक अच्छा विकल्प लगता है ✨ क्या आप इसकी खास बातें जानना चाहेंगे?

## train · overview-floating_gazebo-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Floating Gazebo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a scenic private celebration setting on the water"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Floating Gazebo ek engaging water experience hai — a scenic private celebration setting on the water. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## train · overview-floating_gazebo-1

- Response goal: `service_overview`
- Language: `hi`
- Service: `Floating Gazebo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a scenic private celebration setting on the water"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Floating Gazebo एक खास water experience है — a scenic private celebration setting on the water। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-houseboat_celebration-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Houseboat Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a relaxed celebration experience on a houseboat"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Houseboat Celebration एक खास water experience है — a relaxed celebration experience on a houseboat। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-houseboat_celebration-1

- Response goal: `service_overview`
- Language: `en`
- Service: `Houseboat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a relaxed celebration experience on a houseboat"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Houseboat Celebration is a relaxed celebration experience on a houseboat. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## train · overview-pontoon_celebration-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Pontoon Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a peaceful on-water celebration experience"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Pontoon Celebration ek engaging water experience hai — a peaceful on-water celebration experience. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## train · overview-pontoon_celebration-1

- Response goal: `service_overview`
- Language: `hi`
- Service: `Pontoon Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a peaceful on-water celebration experience"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Pontoon Celebration एक खास water experience है — a peaceful on-water celebration experience। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-jet_ski_ride-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Jet Ski`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["an energetic self-driven water ride with staff guidance"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Jet Ski एक खास water experience है — an energetic self-driven water ride with staff guidance। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-jet_ski_ride-1

- Response goal: `service_overview`
- Language: `en`
- Service: `Jet Ski`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["an energetic self-driven water ride with staff guidance"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Jet Ski is an energetic self-driven water ride with staff guidance. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## train · overview-pontoon_boat_ride-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Pontoon Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a relaxed leisure boat ride on the lake"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Pontoon Boat ek engaging water experience hai — a relaxed leisure boat ride on the lake. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## train · overview-pontoon_boat_ride-1

- Response goal: `service_overview`
- Language: `hi`
- Service: `Pontoon Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a relaxed leisure boat ride on the lake"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Pontoon Boat एक खास water experience है — a relaxed leisure boat ride on the lake। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-inflatable_sofa_ride-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Inflatable Sofa Ride`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a lively towable water ride for an adventurous experience"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Inflatable Sofa Ride एक खास water experience है — a lively towable water ride for an adventurous experience। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-inflatable_sofa_ride-1

- Response goal: `service_overview`
- Language: `en`
- Service: `Inflatable Sofa Ride`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a lively towable water ride for an adventurous experience"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Inflatable Sofa Ride is a lively towable water ride for an adventurous experience. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## train · overview-aqua_cycle-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Aqua Cycle`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a pedal-powered H2O Play Park activity on the water"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Aqua Cycle ek engaging water experience hai — a pedal-powered H2O Play Park activity on the water. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## train · overview-aqua_cycle-1

- Response goal: `service_overview`
- Language: `hi`
- Service: `Aqua Cycle`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a pedal-powered H2O Play Park activity on the water"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Aqua Cycle एक खास water experience है — a pedal-powered H2O Play Park activity on the water। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-bumper_boat-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Bumper Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a playful H2O activity built around steering and friendly bumping"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Bumper Boat एक खास water experience है — a playful H2O activity built around steering and friendly bumping। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-bumper_boat-1

- Response goal: `service_overview`
- Language: `en`
- Service: `Bumper Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a playful H2O activity built around steering and friendly bumping"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Bumper Boat is a playful H2O activity built around steering and friendly bumping. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## train · overview-water_bike-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Water Bike`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a cycling-style H2O Play Park experience on the water"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Water Bike ek engaging water experience hai — a cycling-style H2O Play Park experience on the water. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## train · overview-water_bike-1

- Response goal: `service_overview`
- Language: `hi`
- Service: `Water Bike`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a cycling-style H2O Play Park experience on the water"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Water Bike एक खास water experience है — a cycling-style H2O Play Park experience on the water। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-kids_bumper_boat-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Kids Bumper Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a child-focused H2O activity with a kid-sized steering experience"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Kids Bumper Boat एक खास water experience है — a child-focused H2O activity with a kid-sized steering experience। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## train · overview-kids_paddle_boat-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Kids Paddle Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a child-focused H2O activity for steering and pedalling on the water"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Kids Paddle Boat is a child-focused H2O activity for steering and pedalling on the water. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## train · more-party_boat_celebration

- Response goal: `service_more_details`
- Language: `en`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a lively on-water group celebration with music and a social atmosphere"], "next_action": "answer_service", "next_question": "Would you like to check the duration?"}`

> A lovely highlight of Party Boat Celebration is that it is a lively on-water group celebration with music and a social atmosphere. Would you like to check the duration?

## train · more-floating_gazebo

- Response goal: `service_more_details`
- Language: `hinglish`
- Service: `Floating Gazebo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a scenic private celebration setting on the water"], "next_action": "answer_service", "next_question": "Duration check karein?"}`

> Floating Gazebo ki ek khaas baat: a scenic private celebration setting on the water. Duration check karein?

## train · more-houseboat_celebration

- Response goal: `service_more_details`
- Language: `hi`
- Service: `Houseboat Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a relaxed celebration experience on a houseboat"], "next_action": "answer_service", "next_question": "क्या आप अवधि जानना चाहेंगे?"}`

> Houseboat Celebration की एक खास बात है: a relaxed celebration experience on a houseboat। क्या आप अवधि जानना चाहेंगे?

## train · more-jetty_gazebo

- Response goal: `service_more_details`
- Language: `en`
- Service: `Jetty Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a comfortable waterside gazebo setting for celebrations"], "next_action": "answer_service", "next_question": "Would you like to check the duration?"}`

> A lovely highlight of Jetty Gazebo is that it is a comfortable waterside gazebo setting for celebrations. Would you like to check the duration?

## train · more-speed_boat_ride

- Response goal: `service_more_details`
- Language: `en`
- Service: `Speed Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a fast-paced boat ride for guests who enjoy excitement on the water"], "next_action": "answer_service", "next_question": "Would you like to check the duration?"}`

> A lovely highlight of Speed Boat is that it is a fast-paced boat ride for guests who enjoy excitement on the water. Would you like to check the duration?

## train · more-pontoon_boat_ride

- Response goal: `service_more_details`
- Language: `hinglish`
- Service: `Pontoon Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a relaxed leisure boat ride on the lake"], "next_action": "answer_service", "next_question": "Duration check karein?"}`

> Pontoon Boat ki ek khaas baat: a relaxed leisure boat ride on the lake. Duration check karein?

## train · more-inflatable_sofa_ride

- Response goal: `service_more_details`
- Language: `hi`
- Service: `Inflatable Sofa Ride`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a lively towable water ride for an adventurous experience"], "next_action": "answer_service", "next_question": "क्या आप अवधि जानना चाहेंगे?"}`

> Inflatable Sofa Ride की एक खास बात है: a lively towable water ride for an adventurous experience। क्या आप अवधि जानना चाहेंगे?

## train · more-kayaking

- Response goal: `service_more_details`
- Language: `en`
- Service: `Kayak`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a paddle-based H2O Play Park activity for exploring at your own pace"], "next_action": "answer_service", "next_question": "Would you like to check the duration?"}`

> A lovely highlight of Kayak is that it is a paddle-based H2O Play Park activity for exploring at your own pace. Would you like to check the duration?

## train · more-zorbing_ball

- Response goal: `service_more_details`
- Language: `en`
- Service: `Zorbing Ball`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a playful H2O activity where balancing, rolling and bouncing are part of the fun"], "next_action": "answer_service", "next_question": "Would you like to check the duration?"}`

> A lovely highlight of Zorbing Ball is that it is a playful H2O activity where balancing, rolling and bouncing are part of the fun. Would you like to check the duration?

## train · more-water_bike

- Response goal: `service_more_details`
- Language: `hinglish`
- Service: `Water Bike`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a cycling-style H2O Play Park experience on the water"], "next_action": "answer_service", "next_question": "Duration check karein?"}`

> Water Bike ki ek khaas baat: a cycling-style H2O Play Park experience on the water. Duration check karein?

## train · more-kids_bumper_boat

- Response goal: `service_more_details`
- Language: `hi`
- Service: `Kids Bumper Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a child-focused H2O activity with a kid-sized steering experience"], "next_action": "answer_service", "next_question": "क्या आप अवधि जानना चाहेंगे?"}`

> Kids Bumper Boat की एक खास बात है: a child-focused H2O activity with a kid-sized steering experience। क्या आप अवधि जानना चाहेंगे?

## train · h2o-access-kayaking

- Response goal: `factual_answer`
- Language: `en`
- Service: `Kayak`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Kayak is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM 🌊

## train · h2o-turn-aqua_cycle

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Aqua Cycle`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> Aqua Cycle ke individual turn ka exact duration separately listed nahi hai. H2O Play Park access 10:00 AM se 6:30 PM tak hai.

## train · h2o-access-bumper_boat

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Bumper Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Bumper Boat H2O Play Park के full-day access में शामिल है, 10:00 AM से 6:30 PM तक 🌊

## train · h2o-turn-bumper_boat

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Bumper Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> Bumper Boat के individual turn की अवधि अलग से listed नहीं है। H2O Play Park access 10:00 AM से 6:30 PM तक है।

## train · h2o-access-zorbing_ball

- Response goal: `factual_answer`
- Language: `en`
- Service: `Zorbing Ball`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Zorbing Ball is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM 🌊

## train · h2o-turn-water_bike

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Water Bike`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> Water Bike ke individual turn ka exact duration separately listed nahi hai. H2O Play Park access 10:00 AM se 6:30 PM tak hai.

## train · h2o-access-kids_bumper_boat

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Kids Bumper Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Kids Bumper Boat H2O Play Park के full-day access में शामिल है, 10:00 AM से 6:30 PM तक 🌊

## train · h2o-turn-kids_bumper_boat

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Kids Bumper Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> Kids Bumper Boat के individual turn की अवधि अलग से listed नहीं है। H2O Play Park access 10:00 AM से 6:30 PM तक है।

## train · h2o-access-kids_paddle_boat

- Response goal: `factual_answer`
- Language: `en`
- Service: `Kids Paddle Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Kids Paddle Boat is included with H2O Play Park full-day access from 10:00 AM to 6:30 PM 🌊

## train · ride-speed_boat_ride

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Speed Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Approximately 5–10 minutes"]}`

> Speed Boat ka one-time ride approximately 5–10 minutes ka hota hai 🌊

## train · ride-pontoon_boat_ride

- Response goal: `factual_answer`
- Language: `en`
- Service: `Pontoon Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Approximately 5–10 minutes"]}`

> Pontoon Boat is an approximately 5–10 minute one-time ride 🌊

## train · ride-inflatable_sofa_ride

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Inflatable Sofa Ride`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Approximately 5–10 minutes"]}`

> Inflatable Sofa Ride ka one-time ride approximately 5–10 minutes ka hota hai 🌊

## train · unknown-0

- Response goal: `factual_answer`
- Language: `en`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> I don't have a confirmed detail for that about Party Boat Celebration right now. The Entartica team can help verify it for you.

## train · unknown-3

- Response goal: `factual_answer`
- Language: `en`
- Service: `Jetty Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> I don't have a confirmed detail for that about Jetty Gazebo right now. The Entartica team can help verify it for you.

## train · unknown-4

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Pontoon Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> Pontoon Celebration ke liye yeh detail abhi confirmed nahi hai. Entartica team verify kar sakti hai.

## train · unknown-5

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Jet Ski`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> Jet Ski के बारे में यह जानकारी अभी confirmed नहीं है। Entartica team verify करने में मदद कर सकती है।

## train · activity-0

- Response goal: `activity_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Would you prefer thrill or relaxation?"}`

> If you enjoy high energy, Jet Ski and Speed Boat are exciting choices; Kayak and Aqua Cycle offer a gentler pace. Would you prefer thrill or relaxation?

## train · activity-3

- Response goal: `family_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Kids ki age group kya hai?"}`

> Family ke saath Kayak, Aqua Cycle aur Zorbing Ball explore kar sakte hain. Kids ki age group kya hai?

## train · activity-4

- Response goal: `activity_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Which style sounds better?"}`

> Jet Ski feels energetic, while Kayak and Aqua Cycle let you enjoy the water at your own pace. Which style sounds better?

## train · activity-5

- Response goal: `activity_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Fast-paced ya playful experience chahiye?"}`

> Speed Boat, Kayak, Aqua Cycle aur Zorbing Ball mein achhi variety hai. Fast-paced ya playful experience chahiye?

## train · daycation-duration

- Response goal: `factual_answer`
- Language: `en`
- Service: `Daycation Package`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["2:00 PM to 6:00 PM", "4-hour Daycation window"]}`

> Daycation runs from 2:00 PM to 6:00 PM, giving you a 4-hour daytime experience to enjoy the resort and Entartica activities 🌊

## validation · discovery-1

- Response goal: `celebration_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "anniversary", "next_action": "ask_guest_count", "next_question": "Approx kitne guests honge?"}`

> Anniversary ko special banate hain 🎉 Options mein Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration aur Pontoon Celebration hain. Approx kitne guests honge?

## validation · discovery-7

- Response goal: `celebration_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "special event", "next_action": "ask_guest_count", "next_question": "Approx kitne guests honge?"}`

> Special Event ko special banate hain 🎉 Options mein Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration aur Pontoon Celebration hain. Approx kitne guests honge?

## validation · date-1

- Response goal: `ask_date`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 4", "Occasion: anniversary"], "known_occasion": "anniversary", "known_guest_count": 4, "next_action": "ask_date", "next_question": "Aap kis date ko plan kar rahe hain?"}`

> Great, that helps, anniversary ke liye 4 guests note kar liye. Aap kis date ko plan kar rahe hain?

## validation · date-7

- Response goal: `ask_date`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 16", "Occasion: special event"], "known_occasion": "special event", "known_guest_count": 16, "next_action": "ask_date", "next_question": "Aap kis date ko plan kar rahe hain?"}`

> Great, that helps, special event ke liye 16 guests note kar liye. Aap kis date ko plan kar rahe hain?

## validation · preference-4

- Response goal: `ask_preference`
- Language: `hi`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["12 November 2026", "8 guests"], "known_guest_count": 8, "known_date": "12 November 2026", "next_action": "ask_preference", "next_question": "आप lively, private या relaxed celebration पसंद करेंगे?"}`

> बहुत बढ़िया, 12 November 2026 और 8 मेहमान नोट हो गए हैं। आप lively, private या relaxed celebration पसंद करेंगे?

## validation · recommend-1

- Response goal: `service_recommendation`
- Language: `hinglish`
- Service: `Floating Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports anniversary and private and intimate preferences"], "known_occasion": "anniversary", "known_preference": "private and intimate", "recommended_service_codes": ["floating_gazebo"], "next_action": "answer_service", "next_question": "Kya aap iske highlights dekhna chahenge?"}`

> Aapki private and intimate preference ke hisaab se Floating Gazebo ek strong option lagta hai ✨ Kya aap iske highlights dekhna chahenge?

## validation · recommend-7

- Response goal: `service_recommendation`
- Language: `hinglish`
- Service: `Houseboat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports birthday and relaxed preferences"], "known_occasion": "birthday", "known_preference": "relaxed", "recommended_service_codes": ["houseboat_celebration"], "next_action": "answer_service", "next_question": "Kya aap iske highlights dekhna chahenge?"}`

> Aapki relaxed preference ke hisaab se Houseboat Celebration ek strong option lagta hai ✨ Kya aap iske highlights dekhna chahenge?

## validation · overview-party_boat_celebration-1

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Party Boat Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a lively on-water group celebration with music and a social atmosphere"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Party Boat Celebration ek engaging water experience hai — a lively on-water group celebration with music and a social atmosphere. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## validation · overview-jetty_gazebo-1

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Jetty Gazebo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a comfortable waterside gazebo setting for celebrations"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Jetty Gazebo ek engaging water experience hai — a comfortable waterside gazebo setting for celebrations. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## validation · overview-speed_boat_ride-1

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Speed Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a fast-paced boat ride for guests who enjoy excitement on the water"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Speed Boat ek engaging water experience hai — a fast-paced boat ride for guests who enjoy excitement on the water. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## validation · overview-kayaking-1

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Kayak`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a paddle-based H2O Play Park activity for exploring at your own pace"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Kayak ek engaging water experience hai — a paddle-based H2O Play Park activity for exploring at your own pace. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## validation · overview-zorbing_ball-1

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Zorbing Ball`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a playful H2O activity where balancing, rolling and bouncing are part of the fun"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Zorbing Ball ek engaging water experience hai — a playful H2O activity where balancing, rolling and bouncing are part of the fun. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## validation · overview-staycation_combo-0

- Response goal: `service_overview`
- Language: `hi`
- Service: `Staycation Combo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["an overnight resort stay combined with approved Entartica activities"], "next_action": "answer_service", "next_question": "क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?"}`

> Staycation Combo एक खास water experience है — an overnight resort stay combined with approved Entartica activities। यह आपकी visit को यादगार बना सकता है। क्या आप इसकी अवधि या खास बातें जानना चाहेंगे?

## validation · more-jet_ski_ride

- Response goal: `service_more_details`
- Language: `hi`
- Service: `Jet Ski`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["an energetic self-driven water ride with staff guidance"], "next_action": "answer_service", "next_question": "क्या आप अवधि जानना चाहेंगे?"}`

> Jet Ski की एक खास बात है: an energetic self-driven water ride with staff guidance। क्या आप अवधि जानना चाहेंगे?

## validation · more-bumper_boat

- Response goal: `service_more_details`
- Language: `hi`
- Service: `Bumper Boat`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a playful H2O activity built around steering and friendly bumping"], "next_action": "answer_service", "next_question": "क्या आप अवधि जानना चाहेंगे?"}`

> Bumper Boat की एक खास बात है: a playful H2O activity built around steering and friendly bumping। क्या आप अवधि जानना चाहेंगे?

## validation · h2o-access-aqua_cycle

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Aqua Cycle`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Aqua Cycle H2O Play Park ke full-day access mein included hai, 10:00 AM se 6:30 PM tak 🌊

## validation · h2o-access-water_bike

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Water Bike`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Full-day access from 10:00 AM to 6:30 PM"]}`

> Water Bike H2O Play Park ke full-day access mein included hai, 10:00 AM se 6:30 PM tak 🌊

## validation · ride-jet_ski_ride

- Response goal: `factual_answer`
- Language: `en`
- Service: `Jet Ski`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Approximately 5–10 minutes"]}`

> Jet Ski is an approximately 5–10 minute one-time ride 🌊

## validation · unknown-2

- Response goal: `factual_answer`
- Language: `hi`
- Service: `Houseboat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> Houseboat Celebration के बारे में यह जानकारी अभी confirmed नहीं है। Entartica team verify करने में मदद कर सकती है।

## validation · staycation-duration

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Staycation Combo`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["2:00 PM to 12:00 PM next day"]}`

> Staycation Combo ka approved window 2:00 PM se next day 12:00 PM tak hai, so you can enjoy an overnight resort stay with Entartica activities.

## holdout · discovery-0

- Response goal: `celebration_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "birthday", "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

> That sounds lovely 🎉 For your birthday, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

## holdout · discovery-6

- Response goal: `celebration_discovery`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "known_occasion": "corporate event", "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

> Let's make it special 🎉 For your corporate event, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

## holdout · date-0

- Response goal: `ask_date`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 2", "Occasion: birthday"], "known_occasion": "birthday", "known_guest_count": 2, "next_action": "ask_date", "next_question": "What date are you planning it for?"}`

> Perfect — I've noted a birthday for 2 guests. What date are you planning it for?

## holdout · date-6

- Response goal: `ask_date`
- Language: `en`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Guest count: 14", "Occasion: corporate event"], "known_occasion": "corporate event", "known_guest_count": 14, "next_action": "ask_date", "next_question": "What date are you planning it for?"}`

> Perfect — I've noted a corporate event for 14 guests. What date are you planning it for?

## holdout · preference-3

- Response goal: `ask_preference`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["5 October 2026", "6 guests"], "known_guest_count": 6, "known_date": "5 October 2026", "next_action": "ask_preference", "next_question": "Aap lively, private ya relaxed celebration prefer karenge?"}`

> Great, 5 October 2026 aur 6 guests note ho gaye. Aap lively, private ya relaxed celebration prefer karenge?

## holdout · recommend-0

- Response goal: `service_recommendation`
- Language: `en`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports birthday and lively party-style preferences"], "known_occasion": "birthday", "known_preference": "lively party-style", "recommended_service_codes": ["party_boat_celebration"], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

> For the lively party-style experience you want, Party Boat Celebration looks like a strong option ✨ Would you like to explore its highlights?

## holdout · recommend-6

- Response goal: `service_recommendation`
- Language: `en`
- Service: `Floating Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Supports anniversary and private and intimate preferences"], "known_occasion": "anniversary", "known_preference": "private and intimate", "recommended_service_codes": ["floating_gazebo"], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

> For the private and intimate experience you want, Floating Gazebo looks like a strong option ✨ Would you like to explore its highlights?

## holdout · overview-party_boat_celebration-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Party Boat Celebration`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a lively on-water group celebration with music and a social atmosphere"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Party Boat Celebration is a lively on-water group celebration with music and a social atmosphere. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## holdout · overview-jetty_gazebo-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Jetty Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a comfortable waterside gazebo setting for celebrations"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Jetty Gazebo is a comfortable waterside gazebo setting for celebrations. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## holdout · overview-speed_boat_ride-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Speed Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a fast-paced boat ride for guests who enjoy excitement on the water"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Speed Boat is a fast-paced boat ride for guests who enjoy excitement on the water. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## holdout · overview-kayaking-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Kayak`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a paddle-based H2O Play Park activity for exploring at your own pace"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Kayak is a paddle-based H2O Play Park activity for exploring at your own pace. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## holdout · overview-zorbing_ball-0

- Response goal: `service_overview`
- Language: `en`
- Service: `Zorbing Ball`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["a playful H2O activity where balancing, rolling and bouncing are part of the fun"], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

> Zorbing Ball is a playful H2O activity where balancing, rolling and bouncing are part of the fun. It can add a memorable water experience to your visit. Would you like its duration or highlights?

## holdout · overview-daycation_package-0

- Response goal: `service_overview`
- Language: `hinglish`
- Service: `Daycation Package`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a day-use experience combining resort comfort with approved water activities"], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

> Daycation Package ek engaging water experience hai — a day-use experience combining resort comfort with approved water activities. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

## holdout · more-pontoon_celebration

- Response goal: `service_more_details`
- Language: `hinglish`
- Service: `Pontoon Celebration`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a peaceful on-water celebration experience"], "next_action": "answer_service", "next_question": "Duration check karein?"}`

> Pontoon Celebration ki ek khaas baat: a peaceful on-water celebration experience. Duration check karein?

## holdout · more-aqua_cycle

- Response goal: `service_more_details`
- Language: `hinglish`
- Service: `Aqua Cycle`
- Review status: **REVISED**
- Brief summary: `{"approved_facts": ["a pedal-powered H2O Play Park activity on the water"], "next_action": "answer_service", "next_question": "Duration check karein?"}`

> Aqua Cycle ki ek khaas baat: a pedal-powered H2O Play Park activity on the water. Duration check karein?

## holdout · h2o-turn-kayaking

- Response goal: `factual_answer`
- Language: `en`
- Service: `Kayak`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> The individual Kayak turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

## holdout · h2o-turn-zorbing_ball

- Response goal: `factual_answer`
- Language: `en`
- Service: `Zorbing Ball`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> The individual Zorbing Ball turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

## holdout · h2o-turn-kids_paddle_boat

- Response goal: `factual_answer`
- Language: `en`
- Service: `Kids Paddle Boat`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"]}`

> The individual Kids Paddle Boat turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

## holdout · unknown-1

- Response goal: `factual_answer`
- Language: `hinglish`
- Service: `Floating Gazebo`
- Review status: **PASS**
- Brief summary: `{"approved_facts": ["Requested detail unavailable; do not invent"], "next_action": "none"}`

> Floating Gazebo ke liye yeh detail abhi confirmed nahi hai. Entartica team verify kar sakti hai.

## holdout · activity-1

- Response goal: `activity_discovery`
- Language: `hinglish`
- Service: `—`
- Review status: **PASS**
- Brief summary: `{"approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Aap thrill ya relaxation prefer karenge?"}`

> Adventure ke liye Jet Ski aur Speed Boat, aur relaxed pace ke liye Kayak ya Aqua Cycle explore kar sakte hain. Aap thrill ya relaxation prefer karenge?
