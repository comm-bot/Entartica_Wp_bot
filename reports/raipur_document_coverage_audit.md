# Raipur approved-document coverage audit

## Executive summary

Five approved Raipur DOCX documents are present and extractable. The active
knowledge set contains five active documents and 60 active chunks. Two questions
currently meet the unchanged production acceptance rules: the Raipur location
and activities. Most other common questions have a relevant approved source,
but their semantic score is below the configured `0.65` minimum. This is a
correct safety rejection, not a reason to lower thresholds.

The audit also confirmed two retrieval implementation defects:

- Intent routing did not normalize punctuation or several common approved
  phrasings, so questions such as `price?`, `book?`, `timings?`, and `life
  jackets?` were incorrectly routed as unknown.
- FAQ chunk metadata was derived from the injected `General` section heading
  rather than the FAQ question. Consequently, all 31 active FAQ chunks have
  `faq_topic=general`.

Both code paths have been corrected for future ingestion. No corpus record,
embedding, threshold, approved DOCX, WhatsApp, or Exotel configuration was
changed. A controlled FAQ re-ingestion must be separately approved before the
corrected FAQ-topic metadata can appear in Supabase.

## Current document inventory

| Source file | Category | Extracted sections | Audit finding |
| --- | --- | --- | --- |
| `raipur_location_information.docx` | `location_information` | Official Location Details; Location Overview; Confirmed Experience Categories; Customer Information Controls | Clear location and qualified operating-hours guidance. Live open status is intentionally not supplied. |
| `raipur_services.docx` | `services` | Staycation and Daycation; Water Ride Portfolio; Floating Celebration Services; Celebration Options and Add-Ons | Specific ride/activity lists are present, but family/group suitability is distributed across sections. |
| `raipur_booking_policy.docx` | `booking_policy` | Booking Enquiry Only; Information to Collect; Enquiry and Confirmation Process; Pricing and Quotation; Payment; Availability and Operational Conditions; Changes/Cancellation/Rescheduling | Strong safety boundaries, but key customer questions are paragraph-based rather than FAQ-shaped. |
| `raipur_safety_guidelines.docx` | `safety_guidelines` | General Safety Conditions; Water Ride and Boating Safety; Celebration Safety; Human Handover Required | Strong weather and operating-team boundaries. Specific age/height/weight/medical rules are expressly absent. |
| `raipur_faq.docx` | `faq` | General; Human Handover | Covers many direct questions, including location, activities, booking enquiry, pricing boundary, operating hours, weather, and final safety decision. |

No draft, pending-approval, unapproved, or information-required document was
found. There are no tables that the extractor fails to read, although the
services document includes a compact table-like activity listing whose dense
layout is less retrieval-friendly than question-and-answer wording.

## Active ingestion metadata

| Measure | Result |
| --- | --- |
| Active Raipur documents | 5 |
| Inactive/older Raipur documents | 6 |
| Active chunks | 60 |
| Chunks by source | FAQ 31; Services 11; Booking Policy 8; Location Information 5; Safety Guidelines 5 |
| Chunking versions | `raipur_v2` for four documents; `raipur_faq_v3` for FAQ |
| Active duplicate content hashes | 0 |
| Active source filenames mismatching current documents | 0 |
| FAQ topic metadata | 31 `general`, 0 topic-specific |

The topic coverage result is a confirmed ingestion-metadata defect, not a
document-content defect. Corrected code will use the actual FAQ question for
new metadata; no active data was rebuilt during this audit.

## Coverage matrix and retrieval-gap findings

`Exact` means the approved source directly states the answer. `Implied` means a
related statement exists but must not be expanded into a stronger claim.

| Customer intent | Intended category / expected source | Coverage | Relevant approved section | Current finding and recommendation |
| --- | --- | --- | --- | --- |
| Where is Entartica SeaWorld Raipur? | Location / location information | Exact | Official Location Details; FAQ location question | Accepted live (`0.708`). Keep. |
| How can I reach the Raipur location? | Location / location information | Partial | Official Location Details | Location is named, but no route/travel directions are approved. **B — management clarification required.** |
| What are the operating timings? | Location / location information or FAQ | Exact but qualified | Official Location Details; FAQ operating-hours question | Source says generally 10 AM–10 PM for confirmed floating celebrations and says hours may vary. The wording should be surfaced directly; prior punctuation routing was a defect. |
| Is the location open today? | Location / none | Absent for live status | Customer Information Controls | Do not infer real-time opening. **C — human handover.** |
| What activities are available? | Services / services or FAQ | Exact | Water Ride Portfolio; FAQ experiences question | Accepted live from FAQ (`0.705`). Keep. |
| Which water sports are available? | Services / services | Exact activity list, terminology differs | Water Ride Portfolio | Ride names are approved, but “water sports” was not an intent phrase. Routing corrected; source could add a direct FAQ. |
| Are activities available for children? | Safety / safety guidelines | Partial only | Services list includes kids' activities; Safety human-handover section | Listing a kids' ride is not approval of eligibility. **C — human handover for eligibility.** |
| Are group activities available? | Services/booking / services and booking policy | Partial | Party Boat private-group wording | No general group-package promise. **B — management clarification required.** |
| What activities are suitable for families? | Services / services | Partial | Floating Gazebo family occasion wording | Not a general suitability statement. **B — management clarification required.** |
| How can I make a booking? | Booking / booking policy or FAQ | Exact | Booking Enquiry Only; FAQ booking-enquiry question | Enquiry flow is approved, but confirmation remains team-controlled. Add direct FAQ wording. |
| Is submitting an enquiry a confirmed booking? | Booking / booking policy or FAQ | Exact | Enquiry and Confirmation Process | Source expressly says confirmation requires authorized-team confirmation and required advance payment. Rejected live at `0.520`, correctly below threshold. |
| How is booking confirmation provided? | Booking / booking policy | Exact | Enquiry and Confirmation Process | Authorized team provides it after required conditions. Rejected live at `0.520`; direct FAQ wording would improve retrieval. |
| Can I book for a group? | Booking / booking policy | Partial | Party Boat private group; customized-event controls | No general group-booking rule. **B — management clarification required.** |
| Can I book for a corporate event? | Booking / none | Absent | None | **C — human handover.** |
| What details are required for a booking enquiry? | Booking / booking policy | Exact | Information to Collect | Approved list exists. Add an FAQ-shaped list. |
| What is the price? | Pricing / booking policy or FAQ | Exact boundary only | Pricing and Quotation; FAQ price question | No price may be given; authorized team provides quotation. **C — human handover for a price.** |
| How can I get a quotation? | Pricing / booking policy | Exact | Pricing and Quotation; Enquiry and Confirmation Process | Team provides applicable quotation after enquiry review. Routing punctuation defect corrected; live score `0.446` remains below threshold. |
| Is pricing fixed? | Pricing / booking policy | Exact boundary | Pricing and Quotation | Rates are offer-based and reconfirmed at booking. Do not add values. |
| Are group packages available? | Pricing / none | Absent/partial | Party Boat separate quotation | No generic group-package statement. **B — management clarification required.** |
| Can the chatbot confirm a final price? | Pricing / FAQ or booking policy | Exact | Pricing and Quotation; FAQ price question | No. Rejected at `0.615`, correctly below `0.65`. |
| What safety rules apply? | Safety / safety guidelines | Exact | General Safety Conditions; Water Ride and Boating Safety | Approved operating-team and equipment guidance exists. Rejected at `0.438`; direct FAQ wording recommended. |
| Are life jackets provided? | Safety / none | Absent | Water Ride and Boating Safety | Source requires use of safety equipment but does not say life jackets are provided. **APPROVAL REQUIRED – SOURCE INFORMATION MISSING.** |
| What should guests do during bad weather? | Safety / safety guidelines | Exact boundary | General Safety Conditions | Operations depend on suitable conditions; activity may be delayed, changed, or stopped. Rejected at `0.300`, correctly below threshold. |
| Are children allowed? | Safety / none | Absent | Human Handover Required | Specific eligibility is not defined. **C — human handover.** |
| Are there age, health, or weight restrictions? | Safety / none | Explicitly unavailable | Human Handover Required | Source says it does not define these restrictions. **C — human handover.** |
| Who decides whether an activity can operate safely? | Safety / safety guidelines or FAQ | Exact | General Safety Conditions; FAQ final-safety question | Operating/authorized team makes the on-site safety decision. |
| Cancellation, refund, availability, payment, final confirmation | Booking / booking policy | Exact handover boundary | Payment; Availability; Changes/Cancellation/Rescheduling | Team-only decisions; never automate. |
| Weather-related closures | Safety / safety guidelines | Exact qualified boundary | General Safety Conditions | Do not promise a closure or reopening; conditions and safety clearance govern operations. |
| Human support | FAQ / FAQ human handover | Exact | Human Handover | Correctly hand over prices, availability, booking confirmation, payment, cancellation/refund/rescheduling, medical/eligibility, customized/large groups, and uncovered information. |

## Retrieval diagnostic results

The no-write batch used the current production semantic (`0.65`) and lexical
(`0.30`) thresholds. It did not create `unanswered_questions` records.

| Group | Outcome summary |
| --- | --- |
| Services | Activities accepted from FAQ at `0.705`; water-sports (`0.519`) and family (`0.239`) rejected. Water sports is source-supported but needs direct wording; family suitability is partial. |
| Booking | Enquiry/confirmation questions selected the correct booking-policy source and had lexical evidence `0.700`, but semantic score `0.520` rejected them. |
| Pricing | All rejected safely. Quotation selected booking policy at `0.446`; final-price boundary selected FAQ at `0.615`. |
| Safety | Correct safety source selected for rules (`0.438`) and weather (`0.300`), each with lexical evidence `0.700`, but rejected by semantic threshold. |
| Location | Location accepted from location information at `0.708`; timings previously routed unknown because punctuation/phrase handling was incomplete. |
| Unsupported/unrelated | Indore was `unsupported_location`; flights were safely rejected as a handover. |

## Questions already well supported

- Raipur location.
- Confirmed experience categories and listed boat/park activities.
- Booking-enquiry-only boundary.
- No chatbot price, payment, availability, or final-confirmation promise.
- Weather/operating-condition safety boundary.
- Authorized/on-site team safety decisions.
- Cancellation, refund, and rescheduling handover.

## Questions requiring clearer approved source wording

- How to make an enquiry; confirmation is not automatic; how final confirmation is provided.
- How an authorized team provides a quotation, without a price or payment instruction.
- Operating hours are general/qualified rather than live availability.
- General safety rules and bad-weather response.
- “Water sports” wording mapped to the approved water-ride list.

## Questions that must remain human-only

- Whether the location is open today.
- Exact prices, quotations, payment instructions, final availability, and final booking confirmation.
- Life-jacket provision until an approved source explicitly states it.
- Child, age, height, weight, pregnancy, medical, or other eligibility questions.
- General group-package and corporate-event commitments.
- Cancellation, refund, rescheduling, emergency, or on-site safety disputes.

## Approval checklist and exact source files needing a future revision

1. Management approves the proposed FAQ, booking, safety, and pricing wording in the companion reports.
2. Any new statement about life jackets, eligibility, corporate/group packages, travel directions, or live status is supplied by the responsible business owner.
3. Update only the reviewed copies of `raipur_faq.docx`, `raipur_booking_policy.docx`, and `raipur_safety_guidelines.docx`; update `raipur_location_information.docx` or `raipur_services.docx` only if management approves the identified missing facts.
4. Reapprove document versions and confirm effective/review dates.
5. Run a controlled re-ingestion after approval. This is required to apply the corrected FAQ-topic metadata; it was not performed in this audit.
