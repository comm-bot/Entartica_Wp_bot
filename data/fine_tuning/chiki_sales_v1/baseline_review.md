# Current Composer Baseline Review

Subjective scoring status: **HUMAN REVIEW REQUIRED**. No automated judge was used.

Rubric for each reviewer field: 1 = poor, 3 = acceptable, 5 = excellent.

## discovery-0

**Scenario:** celebration_discovery (en)

**Structured brief summary:** `{"service_name": null, "approved_facts": [], "approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

**Current composer output:**

[NO VALID PRODUCTION OUTPUT]

**Gold response:**

That sounds lovely 🎉 For your birthday, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": false, "concise_response": false, "factual_grounding": false, "governance_leakage_free": true, "language_match": false, "next_action_compliance": false, "next_question_compliance": false, "price_hallucination_free": true, "service_name_accuracy": false, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## discovery-6

**Scenario:** celebration_discovery (en)

**Structured brief summary:** `{"service_name": null, "approved_facts": [], "approved_options": ["Floating Gazebo", "Houseboat Celebration", "Jetty Gazebo", "Party Boat Celebration", "Pontoon Celebration"], "next_action": "ask_guest_count", "next_question": "How many guests will be joining?"}`

**Current composer output:**

For your corporate event, you can choose from Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration, or Pontoon Celebration. How many guests will be joining?

**Gold response:**

Let's make it special 🎉 For your corporate event, you can explore Floating Gazebo, Houseboat Celebration, Jetty Gazebo, Party Boat Celebration and Pontoon Celebration. How many guests will be joining?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## date-0

**Scenario:** ask_date (en)

**Structured brief summary:** `{"service_name": null, "approved_facts": ["Guest count: 2", "Occasion: birthday"], "approved_options": [], "next_action": "ask_date", "next_question": "What date are you planning it for?"}`

**Current composer output:**

What date are you planning it for?

**Gold response:**

Perfect — I've noted a birthday for 2 guests. What date are you planning it for?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## date-6

**Scenario:** ask_date (en)

**Structured brief summary:** `{"service_name": null, "approved_facts": ["Guest count: 14", "Occasion: corporate event"], "approved_options": [], "next_action": "ask_date", "next_question": "What date are you planning it for?"}`

**Current composer output:**

What date are you planning it for?

**Gold response:**

Perfect — I've noted a corporate event for 14 guests. What date are you planning it for?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## preference-3

**Scenario:** ask_preference (hinglish)

**Structured brief summary:** `{"service_name": null, "approved_facts": ["5 October 2026", "6 guests"], "approved_options": [], "next_action": "ask_preference", "next_question": "Aap lively, private ya relaxed celebration prefer karenge?"}`

**Current composer output:**

5 October 2026 ko 6 guests ke liye aap lively, private ya relaxed celebration prefer karenge?

**Gold response:**

Great, 5 October 2026 aur 6 guests note ho gaye. Aap lively, private ya relaxed celebration prefer karenge?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## recommend-0

**Scenario:** service_recommendation (en)

**Structured brief summary:** `{"service_name": "Party Boat Celebration", "approved_facts": ["Supports birthday and lively party-style preferences"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

**Current composer output:**

Party Boat Celebration is a great fit for birthdays and lively party-style celebrations 🎉 Would you like to explore its highlights?

**Gold response:**

For the lively party-style experience you want, Party Boat Celebration looks like a strong option ✨ Would you like to explore its highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## recommend-6

**Scenario:** service_recommendation (en)

**Structured brief summary:** `{"service_name": "Floating Gazebo", "approved_facts": ["Supports anniversary and private and intimate preferences"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like to explore its highlights?"}`

**Current composer output:**

Floating Gazebo is a lovely choice for an anniversary celebration with a private and intimate feel. Would you like to explore its highlights?

**Gold response:**

For the private and intimate experience you want, Floating Gazebo looks like a strong option ✨ Would you like to explore its highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-party_boat_celebration-0

**Scenario:** service_overview (en)

**Structured brief summary:** `{"service_name": "Party Boat Celebration", "approved_facts": ["a lively on-water group celebration with music and a social atmosphere"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

**Current composer output:**

Party Boat Celebration is a lively on-water group celebration with music and a social atmosphere—a memorable water experience. 🎉

Would you like its duration or highlights?

**Gold response:**

Party Boat Celebration is a lively on-water group celebration with music and a social atmosphere. It can add a memorable water experience to your visit. Would you like its duration or highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-jetty_gazebo-0

**Scenario:** service_overview (en)

**Structured brief summary:** `{"service_name": "Jetty Gazebo", "approved_facts": ["a comfortable waterside gazebo setting for celebrations"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

**Current composer output:**

Jetty Gazebo offers a comfortable waterside gazebo setting for celebrations—a memorable water experience 🌊

Would you like its duration or highlights?

**Gold response:**

Jetty Gazebo is a comfortable waterside gazebo setting for celebrations. It can add a memorable water experience to your visit. Would you like its duration or highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-speed_boat_ride-0

**Scenario:** service_overview (en)

**Structured brief summary:** `{"service_name": "Speed Boat", "approved_facts": ["a fast-paced boat ride for guests who enjoy excitement on the water"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

**Current composer output:**

Speed Boat is a fast-paced boat ride for guests who enjoy excitement on the water—an exciting and memorable water experience 🌊

Would you like its duration or highlights?

**Gold response:**

Speed Boat is a fast-paced boat ride for guests who enjoy excitement on the water. It can add a memorable water experience to your visit. Would you like its duration or highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-kayaking-0

**Scenario:** service_overview (en)

**Structured brief summary:** `{"service_name": "Kayak", "approved_facts": ["a paddle-based H2O Play Park activity for exploring at your own pace"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

**Current composer output:**

Kayak is a paddle-based H2O Play Park activity for exploring at your own pace. 🌊

Would you like its duration or highlights?

**Gold response:**

Kayak is a paddle-based H2O Play Park activity for exploring at your own pace. It can add a memorable water experience to your visit. Would you like its duration or highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-zorbing_ball-0

**Scenario:** service_overview (en)

**Structured brief summary:** `{"service_name": "Zorbing Ball", "approved_facts": ["a playful H2O activity where balancing, rolling and bouncing are part of the fun"], "approved_options": [], "next_action": "answer_service", "next_question": "Would you like its duration or highlights?"}`

**Current composer output:**

Zorbing Ball is a playful H2O activity where balancing, rolling, and bouncing are part of the fun. 🌊

Would you like its duration or highlights?

**Gold response:**

Zorbing Ball is a playful H2O activity where balancing, rolling and bouncing are part of the fun. It can add a memorable water experience to your visit. Would you like its duration or highlights?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## overview-daycation_package-0

**Scenario:** service_overview (hinglish)

**Structured brief summary:** `{"service_name": "Daycation Package", "approved_facts": ["a day-use experience combining resort comfort with approved water activities"], "approved_options": [], "next_action": "answer_service", "next_question": "Aap duration ya highlights jaana chahenge?"}`

**Current composer output:**

Daycation Package mein aapko resort comfort ke saath approved water activities ka day-use experience milta hai—ek memorable water experience ke liye 🌊

Aap duration ya highlights jaana chahenge?

**Gold response:**

Daycation Package ek engaging water experience hai — a day-use experience combining resort comfort with approved water activities. Visit ko memorable banane ke liye yeh achha option ho sakta hai. Aap duration ya highlights jaana chahenge?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## more-pontoon_celebration

**Scenario:** service_more_details (hinglish)

**Structured brief summary:** `{"service_name": "Pontoon Celebration", "approved_facts": ["a peaceful on-water celebration experience"], "approved_options": [], "next_action": "answer_service", "next_question": "Duration check karein?"}`

**Current composer output:**

Pontoon Celebration ek peaceful on-water celebration experience hai 🌊 Duration check karein?

**Gold response:**

Pontoon Celebration ki ek khaas baat: a peaceful on-water celebration experience. Duration check karein?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## more-aqua_cycle

**Scenario:** service_more_details (hinglish)

**Structured brief summary:** `{"service_name": "Aqua Cycle", "approved_facts": ["a pedal-powered H2O Play Park activity on the water"], "approved_options": [], "next_action": "answer_service", "next_question": "Duration check karein?"}`

**Current composer output:**

Aqua Cycle ek pedal-powered H2O Play Park activity hai jo paani par hoti hai 🚴‍♂️💦 Duration check karein?

**Gold response:**

Aqua Cycle ki ek khaas baat: a pedal-powered H2O Play Park activity on the water. Duration check karein?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## h2o-turn-kayaking

**Scenario:** factual_answer (en)

**Structured brief summary:** `{"service_name": "Kayak", "approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"], "approved_options": [], "next_action": null, "next_question": null}`

**Current composer output:**

Kayak is available for full-day access from 10:00 AM to 6:30 PM. Individual turn duration is separately unavailable.

**Gold response:**

The individual Kayak turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## h2o-turn-zorbing_ball

**Scenario:** factual_answer (en)

**Structured brief summary:** `{"service_name": "Zorbing Ball", "approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"], "approved_options": [], "next_action": null, "next_question": null}`

**Current composer output:**

For Zorbing Ball, the individual turn duration is separately unavailable. Full-day access is from 10:00 AM to 6:30 PM.

**Gold response:**

The individual Zorbing Ball turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## h2o-turn-kids_paddle_boat

**Scenario:** factual_answer (en)

**Structured brief summary:** `{"service_name": "Kids Paddle Boat", "approved_facts": ["Individual turn duration separately unavailable", "Full-day access from 10:00 AM to 6:30 PM"], "approved_options": [], "next_action": null, "next_question": null}`

**Current composer output:**

Kids Paddle Boat is available for full-day access from 10:00 AM to 6:30 PM. Individual turn duration is separately unavailable.

**Gold response:**

The individual Kids Paddle Boat turn duration isn't separately listed. H2O Play Park full-day access runs from 10:00 AM to 6:30 PM.

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## unknown-1

**Scenario:** factual_answer (hinglish)

**Structured brief summary:** `{"service_name": "Floating Gazebo", "approved_facts": ["Requested detail unavailable; do not invent"], "approved_options": [], "next_action": "none", "next_question": null}`

**Current composer output:**

Floating Gazebo ke baare mein requested detail abhi available nahi hai.

**Gold response:**

Floating Gazebo ke liye yeh detail abhi confirmed nahi hai. Entartica team verify kar sakti hai.

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

## activity-1

**Scenario:** activity_discovery (hinglish)

**Structured brief summary:** `{"service_name": null, "approved_facts": [], "approved_options": ["Jet Ski", "Speed Boat", "Kayak", "Aqua Cycle", "Zorbing Ball"], "next_action": "continue_discovery", "next_question": "Aap thrill ya relaxation prefer karenge?"}`

**Current composer output:**

Aap thrill ya relaxation prefer karenge?

**Gold response:**

Adventure ke liye Jet Ski aur Speed Boat, aur relaxed pace ke liye Kayak ya Aqua Cycle explore kar sakte hain. Aap thrill ya relaxation prefer karenge?

**Objective checks:** `{"availability_hallucination_free": true, "booking_confirmation_hallucination_free": true, "composer_validation_passed": true, "concise_response": true, "factual_grounding": true, "governance_leakage_free": true, "language_match": true, "next_action_compliance": true, "next_question_compliance": true, "price_hallucination_free": true, "service_name_accuracy": true, "unsupported_claims_free": true, "unsupported_numeric_facts_free": true, "unsupported_service_names_free": true}`

**Reviewer fields:** Naturalness __/5 · Warmth __/5 · Sales orientation __/5 · Benefit framing __/5 · WhatsApp suitability __/5

**Reviewer notes:** HUMAN REVIEW REQUIRED

