# Entartica AI Knowledge Base — Coimbatore V1

> Scope: Coimbatore only. This is the initial knowledge layer for the Entartica AI Sales & Customer Experience Agent.
>
> Priority: Coimbatore master location, currently available activities, and Pontoon Boat Celebration.
>
> Source hierarchy:
> 1. Entartica-provided business information
> 2. Entartica official website
> 3. External location research only where explicitly marked
>
> Important: Dynamic commercial facts such as current price, availability, booking status and payment status must come from live business systems/tools, not static FAQ retrieval.

---

# Pontoon Celebration — ACTIVE APPROVED CURRENT CUSTOMER-FACING STANDARD PACKAGE

This section is authoritative for the current Coimbatore WhatsApp Standard Package flow. If older package, recommendation, or pricing sections conflict with this section, this section takes precedence. The older Couple Romance and Family & Friends package definitions are retained only as superseded business history and are not active choices in the current WhatsApp Standard Package flow.

# ACTIVE STANDARD PONTOON PACKAGE — CUSTOMER PRESENTATION

package_id: coimbatore_pontoon_standard
status: ACTIVE
customer_facing: true
presentation_mode: exact
location: coimbatore
product: pontoon_celebration

> IMPORTANT:
> When the customer explicitly asks for the Standard Pontoon Package,
> send the customer-facing presentation below.
> Do not summarize, rewrite, shorten, or replace this presentation with
> another package.
> Dynamic placeholders must be replaced only when the customer value is known.

## CUSTOMER_PACKAGE_MESSAGE

Pontoon Boat Celebration Package ✨

📅 Event Date: {{event_date}}
👥 Guests: {{guest_count}}

🎉 Inclusions:
• Red Carpet Welcome
• 02 Cold Pyro Entry
• Cake
• Music Setup
• Decoration
• Cake cutting in the middle of the serene lake
• 30 Minutes Premium Boat Ride

💰 Special Offer

~₹{{regular_price}}/-~
₹{{offer_price}}/- (15% OFF) including GST

⏰ Rates are valid for today.

✅ Full refund if cancelled before 24 hours of the event date.

## PACKAGE PRESENTATION RULE

When this package is requested:

1. Send the configured Pontoon image.
2. Send CUSTOMER_PACKAGE_MESSAGE.
3. Attach the configured action buttons.
4. Replace {{event_date}} with the customer's known event date.
5. Replace {{guest_count}} with the customer's known guest count.
6. If either value is unknown, omit that line instead of inventing a value.
7. Do not use another Pontoon package for this request.


# ACTIVE COUPLE ROMANCE PONTOON PACKAGE — CUSTOMER PRESENTATION

package_id: coimbatore_pontoon_couple_romance
status: ACTIVE
customer_facing: true
presentation_mode: exact
location: coimbatore
product: pontoon_celebration

> IMPORTANT:
> When the customer explicitly asks for the Couple Romance Package,
> romantic/couple package, or ₹3,999 package, send the customer-facing
> presentation below.
>
> Do not summarize, rewrite, shorten, or replace this presentation with
> another package.
>
> Dynamic placeholders should be replaced only when the customer value is known.

## CUSTOMER_PACKAGE_MESSAGE

Pontoon Couple Romance Celebration ❤️✨

📅 Event Date: {{event_date}}
👥 Guests: 2

🎉 Inclusions:
• Red Carpet Entry
• Basic Boat Decoration
• 250 g Cake — Any Available Flavour
• Music
• 02 Cold Pyros
• 20 Minutes Private Pontoon Boat Ride

💰 Package Price: ~₹3,999/-~
😍 Offer Price: ₹3,400/- (15% off) including GST

🍽️ Food is not included in the package.

## BEST SUITED FOR

• Couples
• Anniversaries
• Romantic Dates
• Birthday Celebrations for Two
• Private Couple Celebrations
• Proposal / Romantic Occasions

## PACKAGE RULES

- This package is for 2 guests only.
- Ride duration is 20 minutes.
- Cake size is 250 g.
- Cake flavour is any available flavour.
- Basic boat decoration is included.
- Music is included.
- Red carpet entry is included.
- 02 cold pyros are included.
- Food is not included.
- Actual requested time must be checked against live availability.
- Do not claim a slot is available without backend verification.

## PACKAGE PRESENTATION RULE

When this package is explicitly requested:

1. Send the configured Couple Romance Pontoon image if a dedicated approved image is configured.
2. Send CUSTOMER_PACKAGE_MESSAGE exactly.
3. Include APPROVED ADD-ONS.
4. Attach the configured package action buttons.
5. Replace {{event_date}} with the customer's known event date.
6. Guests should display as 2.
7. If event date is unknown, omit the Event Date line instead of inventing a date.
8. Do not replace this package with the ₹5,999 Standard Package.
9. Follow-up FAQ questions should use normal LLM + RAG answering instead of resending the full package.

## Standard Package Identity

- Package ID: coimbatore_pontoon_standard
- Package Name: Pontoon Boat Celebration Package
- Status: ACTIVE, APPROVED, CURRENT, CUSTOMER-FACING

## Standard Package Inclusions

- Red Carpet Welcome
- 02 Cold Pyro Entry
- Cake — any available flavour
- Music Setup
- Decoration
- Cake cutting in the middle of the serene lake
- 30 Minutes Premium Boat Ride

## Standard Package Commercial Terms

- Original Package Price: ₹5,999
- Offer Price: ₹5,100 (15% off), including GST
- Offer Note: Rates are valid for today.
- Refund Rule: Full refund if cancelled before 24 hours of the event date.

Availability and final booking confirmation must still be verified by the team.

## Approved Standard Package Add-ons

The following existing approved Pontoon service add-ons apply to the active Standard Package, subject to operational availability:

- Pyro Gun — ₹750 / gun
- Customized Cake — from ₹1,000, depending on cake
- Singer — ₹8,000
- Neon Hanging — ₹1,000
- Fire Works — ₹3,000 / 25 shots
- Photoshoot — ₹10,000 for 1 Reel + 25 Photos
- Drone Photoshoot — +₹5,000 with photoshoot
- Fruit Champagne — ₹800
- Theme Concept — human quotation

## Standard Package Authority Rule

For explicit requests such as “package”, “standard package”, “send package”, “package details”, “₹5,999 package”, “pontoon package”, or a resend request, always use `coimbatore_pontoon_standard`. Do not recommend or present the superseded Couple Romance or Family & Friends packages for those requests.

---

## 1. Coimbatore Master Location

### Official Location

**Entartica SeaWorld — Periyakulam Lake Boat House, Ukkadam, Coimbatore, Tamil Nadu 641001, India**

Official website location information identifies the site as Periyakulam Lake Boat House, Ukkadam, Coimbatore. The official Coimbatore page also lists the location and general park information. 

### Google Maps

**Google Maps search link:**  
https://www.google.com/maps/search/?api=1&query=Entartica+Sea+World+Periyakulam+Lake+Boat+House+Ukkadam+Coimbatore+Tamil+Nadu+641001

> AI rule: Use the Google Maps link for navigation/location requests. Do not invent latitude/longitude unless an authoritative source is provided.

### Contact

- Website: https://www.entartica.com/
- Official enquiry email shown on the website: sales@entartica.com
- Website-listed helpline: +91 7948502810

### Website-Stated Timings

The dedicated Periyakulam Lake Coimbatore page states:

**All Days — 10:00 AM to 8:30 PM**

Another Coimbatore page currently displays 10:00 AM–8:00 PM. This is a website inconsistency and must be validated with operations before becoming a hard AI answer.

**AI rule:** Do not confidently quote operating hours until the current official operational timing is confirmed.

---

## 2. Nearby Famous Locations

The Entartica Coimbatore page itself lists these nearby places:

| Place | Approx. distance stated by Entartica |
|---|---:|
| VOC Park and Zoo | 3 km |
| Gass Forest Museum | 4 km |
| Gedee Car Museum | 5 km |
| Perur Pateeswarar Temple | 6 km |
| Dhyanalinga Yogic Temple | 20 km |

The website also states that Coimbatore International Airport is approximately 12 km away and Coimbatore Junction approximately 2 km away.

### Additional nearby / notable Coimbatore places for future FAQ enrichment

These can be added as **external location knowledge**, but should not be presented as official Entartica-provided distances until verified:

- Ukkadam
- Valankulam Lake
- Coimbatore Junction
- Brookefields Mall
- Marudamalai Temple
- Isha Yoga Center / Adiyogi
- Eachanari Vinayagar Temple
- Perur Pateeswarar Temple
- Gedee Car Museum
- VOC Park and Zoo
- Gass Forest Museum

**AI rule:** If a customer asks “What can we visit near Entartica?”, provide a short list and clearly avoid claiming exact travel time/distance unless verified through a current maps/location source.

---

# 3. Coimbatore Activity Universe

## Current Confirmed Activity Set

Based on the latest business information supplied for this project, the currently available Coimbatore activities are:

1. Aqua Roller
2. Aqua Cycle
3. Inflatable Sofa Ride
4. Kayak
5. Zorbing Ball
6. Bumper Boat
7. Kids Pedal Boat
8. Inflatable Cycle
9. Other water activities

### H2O Play Park

The official Entartica H2O Play Park page specifically describes:

- Aqua Roller
- Zorbing Ball
- Kids Pedal Boat
- Kayak
- Aqua Cycle
- Inflatable Cycle

The official page describes the activities as follows:

### Aqua Roller
A water-based activity involving a large aqua roller where guests can walk/roll on water.

### Zorbing Ball
A water activity where guests experience rolling around on the water inside a zorbing ball.

### Kids Pedal Boat
A child-focused pedal boat experience.

### Kayak
A kayaking activity combining water exploration, recreation and physical activity.

### Aqua Cycle
A cycling-on-water activity.

### Inflatable Cycle
A water activity using an inflatable cycle designed for light-hearted recreation and balance.

### Inflatable Sofa Ride
A water ride designed for speed, waves and group fun.

### Bumper Boat
A family/kids-oriented bumper-boat experience.

### Important Activity Rule

Do not automatically include activities appearing elsewhere on the Entartica website—such as Jet Ski, Speed Boat, Flyboard, Banana Boat, Shark Boat, etc.—in the **current Coimbatore activity catalogue** unless Entartica confirms that they are currently available at the Coimbatore site.

The website contains broader/global activity listings, while this project has now established the current Coimbatore activity list above.

---

# 4. Activity FAQ Framework

For every activity, the AI should eventually know:

- What is it?
- Who can participate?
- Age restriction
- Height/weight restriction, if applicable
- Duration
- Capacity
- Safety equipment
- Whether advance booking is required
- Whether walk-ins are allowed
- Current price
- Availability
- Weather dependency
- Any medical/safety restrictions
- Whether it is included in a package
- Whether it is an add-on

### Critical rule

Static activity descriptions can come from the Knowledge Base.

Current price and availability must come from live systems.

---

# 5. Celebration Ecosystem — Coimbatore

## Current Confirmed Priority

### 1. Pontoon Boat Celebration

For this project, **Pontoon Boat Celebration is the primary celebration product.**

Other celebration products visible on the Entartica website are not being treated as active Coimbatore AI products at this stage unless separately confirmed.

The broader Coimbatore celebration page currently displays several water-based celebration concepts, but the project scope has explicitly prioritized Pontoon Boat Celebration.

---

# 6. Pontoon Boat Celebration — Website Knowledge

The dedicated Entartica Coimbatore Pontoon Celebration page positions the experience around:

- Sunset views
- Private celebrations
- Luxury on water
- Birthdays
- Anniversaries
- Romantic dinners
- Date nights
- Mini celebrations
- Family experiences

### Website-stated celebration inclusions/features

- Red carpet entry
- 2 pyros on entrance
- Cake celebration
- 30-minute ride
- Balloon decoration
- Music celebration

### Music

The website states that guests can use the onboard music system and play their own music through Bluetooth.

### Food

The dedicated Coimbatore Pontoon Celebration FAQ states that food is not included in the package, while food can be arranged at an additional cost.

> This must be reconciled against the final package definitions supplied by Entartica.

### Decoration

Balloon decoration is stated on the website. Customization can be discussed for special requirements.

### Possible customization/add-ons mentioned by the website

- Private dining setup
- Candles
- Boat-side photography
- Personalized decoration

These should be treated as **possible add-ons/customization references**, not confirmed prices or guaranteed package inclusions.

---

# 7. Pontoon Celebration — Current FAQ Knowledge

## FAQ: What is Pontoon Celebration?

Pontoon Celebration is a private celebration experience on the water at Entartica SeaWorld Coimbatore, designed for occasions such as birthdays, anniversaries, romantic dates and family celebrations.

## FAQ: How long is the Pontoon Celebration?

The dedicated Coimbatore celebration page states a **30-minute boat ride**.

## FAQ: How many people can join?

The dedicated Coimbatore Pontoon Celebration page currently states **up to 6 guests**.

> Important: another older/general Pontoon page on the Entartica website states a larger boat capacity. This must not be used to override the package-specific limit.

## FAQ: Is decoration included?

The website states balloon decoration is included for the celebration experience.

## FAQ: Can decoration be customized?

The website indicates customization can be discussed for special requirements.

## FAQ: Is cake included?

The dedicated celebration page lists cake celebration as part of the experience.

## FAQ: Is food included?

The dedicated Coimbatore celebration FAQ currently states food is **not included**, but food can be arranged at an additional cost.

## FAQ: Can we play our own music?

Yes. The website states that guests can use the onboard music system and connect/play their own music through Bluetooth.

## FAQ: Can we arrange a private dinner?

The website mentions private dining as an optional/customizable possibility.

## FAQ: What occasions is Pontoon Celebration suitable for?

Current website positioning includes:

- Birthday
- Anniversary
- Romantic dinner
- Date night
- Family celebration
- Mini celebration

## FAQ: Can we book the Pontoon for a special occasion?

Yes. The website presents Pontoon Celebration as a bookable private celebration experience.

---

# 8. Pontoon Celebration — Sales Intent Model

When the customer mentions:

| Customer statement | AI intent |
|---|---|
| Birthday celebration | Birthday |
| Anniversary | Anniversary |
| Proposal | Romantic / Proposal |
| Date night | Romantic |
| Family celebration | Family |
| Private party | Private Celebration |
| Need decoration | Decoration |
| Need cake | Cake |
| Need food | Food Add-on |
| Need photographer | Photography Add-on |
| Need music | Music |
| How many people? | Capacity |
| How much? | Pricing |
| Which date? | Date |
| Can I book? | Booking |

---

# 9. Pontoon Celebration — Sales Qualification

The AI should qualify in this order:

```text
Celebration enquiry
       ↓
Occasion
       ↓
Guest count
       ↓
Preferred date
       ↓
Preferred time
       ↓
Package
       ↓
Inclusions
       ↓
Add-ons
       ↓
Availability
       ↓
Price
       ↓
Booking
       ↓
Payment
       ↓
Confirmation
```

The AI should avoid asking every question at once.

Ask only what is needed for the next decision.

Example:

> “Absolutely! 😊 What are you celebrating?”

Then:

> “Nice! How many guests will be joining?”

Then:

> “Which date are you planning for?”

---

# 10. Pontoon Package Data — Pending Business Input

Two Pontoon Celebration packages are expected to be provided by Entartica.

## Package 1

**Status: Awaiting business information**

Required fields:

- Package name
- Price
- Number of guests
- Ride duration
- Cake
- Decoration
- Pyro
- Music
- Food
- Beverages
- Photography
- Other inclusions
- Add-ons
- Extra guest price
- Available days
- Available time slots
- Booking rules
- Cancellation rules
- Payment rules

## Package 2

**Status: Awaiting business information**

Required fields:

- Package name
- Price
- Number of guests
- Ride duration
- Cake
- Decoration
- Pyro
- Music
- Food
- Beverages
- Photography
- Other inclusions
- Add-ons
- Extra guest price
- Available days
- Available time slots
- Booking rules
- Cancellation rules
- Payment rules

### Critical AI rule

Until these two packages are provided and approved:

**Do not quote package prices or invent package inclusions.**

---

# 11. Known Website Conflicts — Validation Queue

These items are deliberately kept outside the authoritative AI answer layer until Entartica confirms them.

### A. Operating hours

One official Coimbatore page states:

**10 AM–8:30 PM all days**

Another Coimbatore page currently displays:

**10 AM–8 PM**

**Action:** Operations confirmation required.

### B. Pontoon capacity

Dedicated celebration page:

**Up to 6 guests**

Older/general Pontoon page:

**Up to 10 people**

**Action:** Confirm whether 6 is the celebration package limit and 12 is the physical boat capacity.

### C. Food

Dedicated celebration page:

**Food not included; can be arranged at additional cost**

Other Pontoon content references food/drinks as available.

**Action:** Package-specific rule required.

### D. Pontoon pricing

Older/general Pontoon page references a starting price of ₹5,999.

**Action:** Do not use this as current package pricing. Await the two current package definitions.

---

# 12. AI Knowledge Rules for Coimbatore

### Rule 1 — Location

If the customer asks where Entartica Coimbatore is:

Use:

**Periyakulam Lake Boat House, Ukkadam, Coimbatore, Tamil Nadu 641001**

Offer the Google Maps location.

### Rule 2 — Activities

Only present the currently confirmed Coimbatore activity list.

### Rule 3 — Global Website Content

Do not assume that a product appearing elsewhere on entartica.com is currently available at Coimbatore.

### Rule 4 — Prices

Never infer or invent current prices.

Use live pricing/package configuration.

### Rule 5 — Availability

Never answer availability from static knowledge.

Use the availability system.

### Rule 6 — Pontoon Packages

Use the package master once Package 1 and Package 2 are approved.

### Rule 7 — Conflicting Information

If two official sources conflict, do not choose arbitrarily.

Use the approved master data.

### Rule 8 — Human Handoff

Escalate complex customization, unusual group requests, exceptions, refunds and unresolved commercial questions.

---

# 13. Knowledge Base Source Register

| Source | Use |
|---|---|
| Entartica Coimbatore / Periyakulam Lake page | Primary location source |
| Entartica H2O Play Park page | Activity descriptions |
| Entartica Coimbatore celebration page | Celebration ecosystem |
| Entartica Pontoon Celebration page | Pontoon celebration FAQs/features |
| Entartica business-provided package data | **Authoritative package source once supplied** |
| Live pricing system | Authoritative current price |
| Booking system | Authoritative availability/booking |
| Payment system | Authoritative payment status |

---

# 14. Current Status

### 🟢 Confirmed / usable

- Coimbatore location
- Periyakulam Lake Boat House
- Ukkadam
- Coimbatore
- Google Maps navigation link
- Current Coimbatore activity list supplied by Entartica
- H2O Play Park activities
- Pontoon Celebration as priority celebration product
- 30-minute Pontoon ride
- Red carpet
- 2 entrance pyros
- Cake celebration
- Balloon decoration
- Music
- Bluetooth
- Celebration use cases
- Website-listed nearby attractions

### 🟡 Needs validation

- Exact operating hours
- Pontoon physical capacity vs package capacity
- Food rules
- Customization availability
- Website-listed Pontoon price

### 🔴 Awaiting business input

- Pontoon Package 1
- Pontoon Package 2
- Package pricing
- Exact package inclusions
- Package-specific rules
- Add-on pricing
- Booking/payment rules
- Cancellation/refund rules

---

# 15. Next Knowledge Build

Once the two Pontoon packages are supplied, this file should be expanded into:

```text
COIMBATORE_KNOWLEDGE_BASE.md
│
├── Location
├── Directions
├── Nearby Places
├── Activities
├── H2O Play Park
├── Pontoon Celebration
│   ├── Package 1
│   ├── Package 2
│   ├── Add-ons
│   ├── Pricing Rules
│   └── Booking Rules
├── FAQ Master
├── Sales FAQ
├── Objection Handling
├── Lead Qualification
├── Next Best Actions
├── Guardrails
└── Validation Queue
```

This is the structure intended to feed the future **RAG/Knowledge layer + AI Sales Agent**, rather than being just a customer-facing FAQ document.


# 10. SUPERSEDED BUSINESS HISTORY — Former Pontoon Package Master

## Package 1 — Pontoon Couple Romance Celebration

**Recommended customer-facing name:** Pontoon Couple Romance Celebration

Other options:
- Pontoon Couple Celebration
- Pontoon Romantic Escape
- Pontoon Couple Sunset Celebration

### Commercial Details

| Field | Approved Detail |
|---|---|
| Price | ₹3,999 |
| Guests | 2 only |
| Ride | 20 minutes |
| Timing | Any time between 6:00 AM and 9:00 PM |
| Food | Not included |
| Cake | 250 g, any available flavour |
| Decoration | Basic boat decoration |
| Music | Yes |
| Entry | Red carpet |
| Pyro | 2 cold pyros |

### Included

- Red carpet entry
- Basic boat decoration
- 250 g cake, any available flavour
- Music
- 2 cold pyros
- 20-minute Pontoon ride
- Private experience for 2 guests

### Add-ons

| Add-on | Price |
|---|---:|
| Theme Concept | Connect agent based on theme |
| Pyro Gun | ₹750 / gun |
| Customized Cake | From ₹1,000, depending on cake |
| Singer | ₹8,000 |
| Neon Hanging | ₹1,000 |
| Fire Works — 25 shots | ₹3,000 |
| Photoshoot — 1 Reel + 25 Pics | ₹10,000 |
| Drone Photoshoot | +₹5,000 with photoshoot |
| Fruit Champagne | ₹800 |

### Best suited for

- Couples
- Anniversaries
- Romantic dates
- Birthday celebrations for two
- Private couple celebrations
- Proposal/romantic occasions, subject to operational suitability

---

## Package 2 — Pontoon Family & Friends Celebration

**Recommended customer-facing name:** Pontoon Family & Friends Celebration

Other options:
- Pontoon Group Celebration
- Pontoon Celebration for Family & Friends
- Pontoon Grand Celebration

### Commercial Details

| Field | Approved Detail |
|---|---|
| Up to 6 guests | ₹6,000 |
| Up to 9 guests | ₹7,500 |
| Up to 10 guests | ₹9,000 |
| Ride | 30 minutes |
| Timing | Any time between 6:00 AM and 9:00 PM |
| Food | Not included |
| Cake | 500 g, any available flavour |
| Cake experience | Cake cutting in the middle of the lake |
| Decoration | Boat decoration |
| Music | Yes |
| Entry | Red carpet |
| Pyro | Pyro entry |

### Included

- Red carpet entry
- Boat decoration
- 500 g cake, any available flavour
- Cake cutting in the middle of the lake
- Music
- Pyro entry
- 30-minute Pontoon ride
- Group celebration according to selected guest tier

### Guest Pricing

| Guests | Price |
|---:|---:|
| 1–6 | ₹6,000 |
| 7–9 | ₹7,500 |
| 10 | ₹9,000 |

### Add-ons

| Add-on | Price |
|---|---:|
| Theme Concept | Connect agent based on theme |
| Pyro Gun | ₹750 / gun |
| Customized Cake | From ₹1,000, depending on cake |
| Singer | ₹8,000 |
| Neon Hanging | ₹1,000 |
| Fire Works — 25 shots | ₹3,000 |
| Photoshoot — 1 Reel + 25 Pics | ₹10,000 |
| Drone Photoshoot | +₹5,000 with photoshoot |
| Fruit Champagne | ₹800 |

### Best suited for

- Families
- Friends
- Birthdays
- Anniversaries
- Family occasions
- Friend-group celebrations
- Small group celebrations
- Groups up to 10 guests

---

# 11. Pontoon Package Comparison

| Feature | Couple Romance Celebration | Family & Friends Celebration |
|---|---:|---:|
| Guests | 2 only | Up to 10 |
| Price | ₹3,999 | ₹6,000 / ₹7,500 / ₹9,000 |
| Ride | 20 min | 30 min |
| Red carpet | Yes | Yes |
| Cake | 250 g | 500 g |
| Cake flavour | Any available flavour | Any available flavour |
| Cake moment | Celebration | Cutting in middle of lake |
| Decoration | Basic boat decoration | Boat decoration |
| Music | Yes | Yes |
| Pyro | 2 cold pyros | Pyro entry |
| Food | Not included | Not included |
| Timing | 6 AM–9 PM | 6 AM–9 PM |

All listed add-ons are available to either package subject to operational availability:

- Theme concept — connect agent
- Pyro Gun — ₹750 / gun
- Customized Cake — from ₹1,000
- Singer — ₹8,000
- Neon Hanging — ₹1,000
- Fire Works — ₹3,000 / 25 shots
- Photoshoot — ₹10,000 for 1 Reel + 25 Pics
- Drone Photoshoot — +₹5,000 with photoshoot
- Fruit Champagne — ₹800

---

# 12. Pontoon Package Recommendation Logic

```text
Customer wants Pontoon Celebration
          ↓
How many guests?
          │
     ┌────┴─────────────┐
     ▼                  ▼
   2 guests          3+ guests
     │                  │
     ▼                  ▼
Couple Romance     Family & Friends
     │                  │
     │             ┌────┼───────────┐
     │             ▼    ▼           ▼
     │            1–6  7–9        10
     │             │    │           │
     │             ▼    ▼           ▼
     │           ₹6K  ₹7.5K        ₹9K
     │
     ▼
₹3,999
```

### AI Rules

- Exactly 2 guests + couple/private celebration → recommend Couple Romance Celebration first.
- 3–6 guests → Family & Friends at ₹6,000.
- 7–9 guests → Family & Friends at ₹7,500.
- 10 guests → Family & Friends at ₹9,000.
- More than 10 guests → escalate to sales team.
- Do not invent discounts.
- Do not quote availability without checking the live system.

---

# 13. Pontoon FAQ — Package Specific

### What is Pontoon Celebration?

A private celebration experience on the water at Entartica SeaWorld Coimbatore, designed for occasions such as birthdays, anniversaries, romantic dates and family/friends celebrations.

### How much is the couple package?

**₹3,999 for 2 guests.**

### How much is the family/friends package?

- **₹6,000 for up to 6 guests**
- **₹7,500 for up to 9 guests**
- **₹9,000 for 10 guests**

### How long is the couple ride?

**20 minutes.**

### How long is the family/friends ride?

**30 minutes.**

### What time can we book?

Any time between **6:00 AM and 9:00 PM**, subject to availability.

### Is cake included?

Yes.

- Couple package: **250 g**
- Family & Friends package: **500 g**

Both are any available flavour.

### Where is the cake cut?

For the Family & Friends package, cake cutting is specified as taking place **in the middle of the lake**.

### Is food included?

No. Food is not included in either package.

### Can we play music?

Yes. Music is included.

### Is decoration included?

Yes.

- Couple package: Basic boat decoration
- Family & Friends package: Boat decoration

### Can we choose a theme?

Theme concepts can be discussed with the Entartica team. Connect the customer to the appropriate agent for theme requirements.

### Are pyros included?

Couple package: **2 cold pyros**.

Family & Friends package: **Pyro entry**.

### Can I add a Pyro Gun?

Yes. **₹750 per gun.**

### Can I add fireworks?

Yes. **₹3,000 for 25 shots**, subject to operational approval and applicable safety requirements.

### Can I add a singer?

Yes. **₹8,000**, subject to availability.

### Can I add Neon Hanging?

Yes. **₹1,000**, subject to availability.

### Can I get a customized cake?

Yes. Customized cake starts from **₹1,000**, depending on the cake.

### Is a photoshoot available?

Yes. **₹10,000 for 1 Reel + 25 photos.**

### Is drone photography available?

Yes, as an additional **₹5,000 with the photoshoot**, subject to operational availability and permissions.

### Is Fruit Champagne available?

Yes. **₹800.**

---

# 14. Pontoon Sales Qualification

The AI should qualify progressively:

```text
Celebration enquiry
       ↓
Occasion
       ↓
Guest count
       ↓
Preferred date
       ↓
Preferred time
       ↓
Recommend package
       ↓
Offer relevant add-ons
       ↓
Check availability
       ↓
Booking
       ↓
Payment
       ↓
Confirmation
```

Example:

> “Absolutely! 😊 What are you celebrating?”

Then:

> “Nice! How many guests will be joining?”

Then:

> “Which date are you planning for?”

Do not ask every question at once unless the customer provides the information voluntarily.

---

# 15. Pontoon Next-Best-Action Rules

| Situation | Next Best Action |
|---|---|
| Asks what Pontoon is | Explain experience |
| Says birthday | Ask guest count + date |
| Says anniversary for 2 | Recommend Couple package |
| Says 2 people | Recommend Couple package |
| Says 5 people | Recommend Family & Friends up to 6 |
| Says 8 people | Recommend Family & Friends up to 9 |
| Says 10 people | Recommend Family & Friends up to 10 |
| Says 13+ people | Human sales handoff |
| Asks price | Give applicable package price |
| Wants special theme | Connect to agent |
| Wants singer | Offer ₹8,000 add-on |
| Wants fireworks | Offer ₹3,000 / 25 shots |
| Wants photoshoot | Offer ₹10,000 package |
| Wants drone | Explain +₹5,000 with photoshoot |
| Wants customized cake | Explain from ₹1,000 |
| Wants booking | Collect details + check availability |
| Selects date/time | Check live availability |
| Ready to pay | Generate payment link |
| Payment succeeds | Confirm only from verified payment event |

---

# 16. Pontoon Business Rules Still Pending

The following have not yet been supplied and must remain unassumed:

- Booking process
- Live availability system/API
- Exact slot duration/buffer
- Cancellation policy
- Rescheduling policy
- Refund policy
- Extra guest rules
- Whether the Couple package is strictly limited to 2 guests
- Food availability/add-on pricing
- Theme catalogue
- Add-on availability by time slot
- Fireworks/pyro operational restrictions
- Singer availability
- Drone photography restrictions
- Payment methods
- Advance payment requirement
- Booking confirmation process

---

# 17. Authority Rule

For Pontoon package information, the current business information supplied directly by Entartica in this project is authoritative over older/general website content.

Priority:

1. Current Entartica-provided package data
2. Approved Entartica operational data
3. Current Entartica website
4. Older/general website content

This resolves the previously identified website conflicts around Pontoon capacity, food and pricing.

---

# 18. Current Knowledge Status

### Approved

- Coimbatore location
- Current Coimbatore activity list
- Pontoon Celebration as the active celebration priority
- Couple Romance Celebration — ₹3,999 / 2 guests
- Family & Friends Celebration — ₹6,000 / 1–6, ₹7,500 / 7–9, ₹9,000 / 10
- Package inclusions
- Ride durations
- 6 AM–9 PM timing window
- Add-on prices
- Package recommendation logic
- Package-specific FAQ structure
- Pontoon sales qualification

### Pending validation

- Booking availability
- Cancellation/refund
- Food arrangements
- Theme catalogue
- Operational restrictions
- Payment workflow
- Exact slot availability

### Must come from live systems

- Current availability
- Booking status
- Payment status
- Date-specific inventory
- Date-specific dynamic offers

# 19. Coimbatore Pontoon — Operational Rules V2

This section incorporates business information supplied directly by the Entartica team. It takes precedence over older/general website content where there is a conflict.

## Booking Journey

Current intended booking flow:

```text
Customer asks
      ↓
AI checks WhatsApp / booking system
      ↓
Slot available
      ↓
Customer details collected
      ↓
Payment link
      ↓
100% payment
      ↓
Booking confirmed
      ↓
Confirmation sent
      ↓
Notify Site Team + Management
```

### Booking Rules

- Current payment model: **100% advance payment**.
- Booking is confirmed after required payment is received and the booking is successfully recorded.
- Booking availability must be checked against backend slot availability.
- Backend should support creation/management of available Pontoon slots.
- Customers can request any time between **6:00 AM and 9:00 PM**, subject to package duration and live availability.
- Couple package duration: **20 minutes**.
- Family & Friends package duration: **30 minutes**.
- Recommended reporting time: **10–15 minutes before booked time**.
- The formal Terms & Conditions currently say guests should arrive at least **15–30 minutes before** the scheduled time. Until this is normalized, the customer-facing operational instruction should be **15 minutes before**, while the formal T&C remains authoritative for the legal wording.

## Availability

The AI must not assume a slot is free.

It should:

1. Identify requested date.
2. Identify requested time.
3. Identify package/duration.
4. Check backend slot availability.
5. Only then proceed toward booking/payment.

Example:

> “I can check that for you. What date and preferred time would you like?”

After availability is confirmed:

> “That slot is available. I can proceed with your booking details.”

## Customer Details

Before generating a payment link, the system should collect the minimum approved booking fields.

Recommended fields:

- Customer name
- WhatsApp/mobile number
- Email, if required
- Event/celebration type
- Number of guests
- Selected package
- Date
- Time
- Selected add-ons
- Special cake/theme requirements
- Any operational notes

The exact mandatory fields should be finalized with the booking implementation.

---

# 20. Cancellation, Rescheduling, Refund & Weather Rules

The current supplied Terms & Conditions state:

### Cancellation

- Confirmed bookings are generally **non-refundable**.
- No refund for late arrival or no-show.
- Bookings are non-transferable without prior management approval.

### Rescheduling

- Rescheduling is subject to availability.
- Price revisions may apply when changing the booking date.
- AI must connect the customer to a human agent for cancellation/rescheduling requests.

### Weather / Operational Conditions

Boat operations depend on:

- Weather
- Water level
- Government permissions
- Operational/safety conditions

Management may delay, postpone or cancel an activity for safety reasons.

Safety decisions taken by the operations team are final.

### AI Rule

The AI may explain the published policy but must **not promise a refund, reschedule approval, date change, weather exception or compensation**.

Those actions require human/management handling.

---

# 21. Guest & Capacity Rules

### Children

- No age restriction has been specified for the Pontoon celebration.
- Children must remain under adult supervision.
- The AI should not invent an age limit.

### Pregnant Guests

- Pregnant guests are **not allowed**.

### Elderly Guests

- Elderly guests may participate if they are physically fit to ride.

### Capacity

- Couple package: **2 guests only**.
- Family & Friends:
  - Up to 6 → ₹6,000
  - Up to 9 → ₹7,500
  - 10 guests → ₹9,000
- Above 12 guests: standard Pontoon package capacity is not available; human sales/management escalation is required.
- Additional guests beyond the confirmed booking should not be accommodated.

---

# 22. Food, Cake & Outside Items

### Food

Food can be arranged based on customer requirement.

The AI should not invent a menu or food price. It should connect to the sales/food team for the current options and quotation.

### Outside Food

Outside food and beverages are **not allowed** unless specifically approved by management.

### Cake

Customers **may bring their own cake**.

The package cake remains part of the applicable package unless the commercial team confirms a different arrangement.

### Decorations

Customers cannot bring their own decorations.

Theme/decorations must be arranged through Entartica.

### Alcohol

Alcohol is **not allowed**.

---

# 23. Photography & Media

### Entartica Photography

The current paid photography offering is:

**1 Reel + 25 Photos — ₹10,000**

### Delivery

Photography deliverables are expected within **2 weeks**.

### Customer's Own Phone

Customers may take normal phone photographs/videos during the experience, and the site team can help where operationally feasible.

### Customer's Own Photographer

This needs explicit operational confirmation before the AI says yes.

**AI default:** connect to human agent for approval.

### Drone Photography

Drone photography is available during the event at the boat/celebration location.

Drone photoshoot add-on:

**₹5,000 extra with the photography package.**

Operational/permission checks should still be handled by the responsible team.

---

# 24. Fireworks, Pyro & Themes

### Fireworks

Current business input states no special restriction.

However, the AI should still avoid making safety/legal guarantees and should follow site/management instructions.

### Pyro

Current business input states no special restriction.

### Theme Concepts

Themes can be arranged based on customer requirements.

Theme pricing is not fixed in the current KB.

**AI rule:** Connect customer to a human agent for customized theme requirements and pricing.

---

# 25. Location & On-Site Customer Journey

### Exact Google Maps Link

https://share.google/AUJRM6sIvbEqeJeH2

### Nearby Landmark

**Periyakulam Lake Park**

### On-site Facilities / Navigation

| Customer asks | Current answer |
|---|---|
| Is parking available? | Yes |
| Is parking capacity enough? | Site team says there is enough parking |
| Is there an entry gate? | Yes |
| Is there a booking counter? | Yes |
| Where do I go for Pontoon boarding? | After the booking counter |
| Where is H2O Play Park? | After the booking counter |
| Are washrooms available? | Yes, inside the park |
| Changing rooms? | No |
| Lockers? | No |
| Food/cafe? | Food/cafe options are nearby |
| First aid? | Yes |
| Waiting area? | Yes |
| Nearby landmark? | Periyakulam Lake Park |

### Customer Arrival Response

Recommended AI answer:

> “You can use the Google Maps location to reach Entartica. Once you arrive, go to the booking counter. The Pontoon boarding point and H2O Play Park are after the booking counter. Please arrive around 15 minutes before your booked time.”

---

# 26. AI Permission Matrix — Confirmed

| Action | AI |
|---|---|
| Answer FAQ | ✅ Automatic |
| Quote package price | ✅ Automatic |
| Recommend package | ✅ Automatic |
| Add ₹750 Pyro Gun | ✅ Automatic, when customer selects it |
| Give discount | ❌ Human Agent |
| Refund | ❌ Human Agent |
| Cancellation | ❌ Human Agent |
| Rescheduling approval | ❌ Human Agent |
| Corporate quote | ❌ Human Agent |
| Custom theme price | ❌ Human Agent |
| Special/custom cake price | ❌ Human Agent |
| Fireworks arrangement | ❌ Human Agent |
| Weather exception | ❌ Human Agent |
| >12 guests | ❌ Human Agent |
| Confirm live availability | ✅ Only through backend availability tool |
| Generate payment link | ✅ Once booking data is complete |
| Confirm payment received | ✅ Only through verified payment status |
| Confirm booking | ✅ Only after verified payment + booking creation |

---

# 27. Lead Scoring V2

Current sales priority:

| Customer signal | Lead score category |
|---|---|
| Just asking / general enquiry | COLD |
| Asked price | WARM |
| Gave date | HOT |
| Gave guest count | HOT |
| Asked availability | HOT |
| Asked payment link | VERY HOT |
| Selected package | VERY HOT |
| Payment pending | VERY HOT |

## Recommended scoring model

For implementation, use a simple additive model:

| Signal | Points |
|---|---:|
| General enquiry | 5 |
| Asked price | +15 |
| Gave date | +20 |
| Gave guest count | +15 |
| Asked availability | +25 |
| Selected package | +30 |
| Asked for payment link | +35 |
| Payment link generated | +40 |
| Payment pending | +45 |
| Payment completed | +50 |

Suggested bands:

- **0–19:** Cold
- **20–39:** Warm
- **40–69:** Hot
- **70+:** Very Hot

The exact scoring thresholds can be tuned after real conversation data is collected.

---

# 28. Lead Nurturing Rules

The AI should nurture based on lead state rather than using one generic follow-up message.

## Cold

Customer is exploring.

Goals:
- Answer question.
- Discover occasion.
- Discover guest count.
- Avoid aggressive selling.

Next action:
- Ask one useful qualification question.

## Warm

Customer has shown commercial interest, such as asking price.

Goals:
- Identify date.
- Identify guest count.
- Recommend appropriate package.

Next action:
- Move toward availability.

## Hot

Customer has supplied date/guest count or asked availability.

Goals:
- Check slot.
- Recommend package.
- Present exact price.
- Move to booking.

Next action:
- Payment link.

## Very Hot

Customer selected package, asked for payment link, or has payment pending.

Goals:
- Remove friction.
- Confirm payment status.
- Complete booking.

Next action:
- Payment/booking confirmation.

### Nurture principle

Do not repeatedly send generic promotional messages.

Each follow-up should respond to the customer's current state.

---

# 29. Booking Follow-Up State Machine

```text
NEW LEAD
   ↓
QUALIFIED
   ↓
PACKAGE RECOMMENDED
   ↓
AVAILABILITY CHECKED
   ↓
PAYMENT LINK SENT
   ↓
PAYMENT PENDING
   ↓
PAYMENT SUCCESS
   ↓
BOOKING CONFIRMED
   ↓
PRE-VISIT REMINDER
   ↓
EVENT COMPLETED
```

Potential recovery states:

```text
PAYMENT PENDING
      ↓
Follow-up
      ↓
Still Pending
      ↓
Human escalation if required

AVAILABILITY UNAVAILABLE
      ↓
Offer alternative time/date
      ↓
Recheck availability
```

---

# 30. Human Handoff Rules — Confirmed

Immediately connect to a human agent when:

- Customer asks for discount.
- Customer requests refund.
- Customer wants cancellation.
- Customer wants rescheduling approval.
- Customer requests corporate pricing.
- Customer requests special/custom theme pricing.
- Customer requests special cake pricing.
- Customer requests fireworks arrangement.
- Customer requests a weather exception.
- Customer has more than 10 guests.
- Customer wants to bring an external photographer and approval is required.
- Customer has an unresolved complaint.
- Customer asks something the AI cannot verify.
- Customer explicitly requests a human.

### Handoff principle

The AI should pass the collected context to the human rather than making the customer repeat everything.

Example handoff payload:

```text
Lead:
Name
Phone

Occasion:
Anniversary

Guests:
2

Date:
24-Aug-2026

Time:
7:00 PM

Package:
Pontoon Couple Romance Celebration

Add-ons:
Photoshoot

Availability:
Available

Payment:
Pending

Customer request:
Wants discount
```

---

# 31. Customer Question Bank — 100 Questions for Sales Team

> Purpose: Sales team should fill/approve the answer, business rule, or escalation route for each question. These are candidate questions generated from the current package, operational rules and known customer needs. They are **not automatically approved customer-facing answers** until the team validates them.

## A. Product & Experience

1. What exactly is Pontoon Celebration?
2. What happens during the Pontoon Celebration?
3. Is the Pontoon private for our group?
4. Which Pontoon package is best for couples?
5. Which Pontoon package is best for families?
6. Which Pontoon package is best for friends?
7. Can we celebrate a birthday on the Pontoon?
8. Can we celebrate an anniversary on the Pontoon?
9. Can we do a proposal on the Pontoon?
10. Can we plan a romantic date on the Pontoon?

## B. Package Selection

11. What is the couple package called?
12. How much is the Couple Romance Celebration?
13. How many guests are allowed in the couple package?
14. How long is the couple ride?
15. What is included in the couple package?
16. What is the Family & Friends package called?
17. How much is the package for 6 people?
18. How much is the package for 9 people?
19. How much is the package for 12 people?
20. How long is the Family & Friends ride?

## C. Guest Count

21. We are 2 people. Which package should we choose?
22. We are 3 people. Which package should we choose?
23. We are 4 people. Which package should we choose?
24. We are 5 people. Which package should we choose?
25. We are 6 people. Which package should we choose?
26. We are 7 people. How much is it?
27. We are 8 people. How much is it?
28. We are 9 people. How much is it?
29. We are 10 people. How much is it?
30. We are 11 people. How much is it?
31. We are 12 people. How much is it?
32. Can we bring 13 people?
33. Can I add one more person after booking?
34. Can I add three more guests?
35. Can children be included in the guest count?

## D. Children, Elderly & Safety

36. Can children come on the Pontoon?
37. Is there any age restriction for children?
38. Can a baby come?
39. Can an elderly person join?
40. Is there any restriction for elderly guests?
41. Can a pregnant woman join?
42. Are life jackets provided?
43. Are life jackets mandatory?
44. What safety rules should we follow?
45. What happens if someone is not fit to ride?

## E. Timing & Availability

46. What time does Pontoon Celebration start?
47. Can I book at 6 AM?
48. Can I book at 9 PM?
49. Can I choose any time between 6 AM and 9 PM?
50. How long is the ride?
51. How early should we reach?
52. What happens if we arrive late?
53. Can we extend the ride?
54. Can we change our time on the same day?
55. Is my requested time available?

## F. Booking & Payment

56. How do I book Pontoon Celebration?
57. Can I book directly on WhatsApp?
58. Can you check availability for me?
59. Can I lock my booking by paying an advance?
60. How much advance should I pay?
61. Do I need to pay 100% in advance?
62. When will I receive the payment link?
63. How do I know whether you received my payment?
64. When will my booking be confirmed?
65. Where will I receive my booking confirmation?
66. Can you resend my booking confirmation?
67. Where is my voucher?
68. Can you resend my voucher?
69. How much balance is left?
70. When should I pay the remaining amount?
71. I paid but my booking is not showing. What should I do?

## G. Cancellation & Rescheduling

72. Can I cancel my booking?
73. Can I get a refund if I cancel?
74. Can I change my booking date?
75. Can I change my booking time?
76. Can you confirm my reschedule?
77. Will the price change if I reschedule?
78. What happens if I cannot come?
79. What happens if I am late?
80. What happens if I do not show up?
81. What happens if the weather is bad?
82. What happens if Entartica cancels the ride for safety reasons?

## H. Cake, Food & Decoration

83. What cake flavours are available?
84. Can I get chocolate truffle?
85. Can I get a 1 kg cake?
86. Can I get a customized cake?
87. How much does a customized cake cost?
88. Can I bring my own cake?
89. What should I write on the cake?
90. Can you arrange food?
91. Can I bring my own food?
92. Can I bring my own decorations?
93. Can I choose a decoration theme?
94. Can you arrange a special theme?

## I. Music, Pyro & Entertainment

95. Can we play music?
96. Can we connect our phone to the music system?
97. Can we add a Pyro Gun?
98. Can we add fireworks?
99. Can we arrange a singer?
100. Can we add Neon Hanging?

---

# 32. Additional High-Value Questions for Future Expansion

The sales team should also validate these after the first 100:

- Can I bring my own photographer?
- Can your staff take pictures?
- Is normal phone photography allowed?
- Is photography free?
- What is included in the ₹10,000 photoshoot?
- How many photos do we receive?
- How long does photography delivery take?
- Is drone photography available?
- How much is drone photography?
- Can we get a Reel?
- Can we get more than one Reel?
- Can we request a particular song?
- Can we bring flowers?
- Can we bring gifts?
- Can we bring a proposal ring?
- Can we bring balloons?
- Can we bring a banner?
- Can we have candles?
- Can we have a private dinner?
- Can we arrange a special surprise?
- Can we request a specific cake flavour?
- Can we request a cake design?
- Is food vegetarian/non-vegetarian?
- What food options are available?
- Can you arrange snacks?
- Can you arrange drinks?
- Is fruit champagne alcoholic?
- Can we bring alcohol?
- Can we smoke?
- Can we bring pets?
- Is parking available?
- Is parking free?
- Where is the entrance?
- Where is the booking counter?
- Where is the Pontoon boarding point?
- Where is H2O Play Park?
- Where are the washrooms?
- Are changing rooms available?
- Are lockers available?
- Is there a waiting area?
- Is first aid available?
- What should I do when I reach?
- The contact number is switched off. Please call me.
- Can you call me?
- Can I speak to a human?
- Can I get a discount?
- Do you have any offer?
- Is there a weekday offer?
- Is there a birthday offer?
- Is there an anniversary offer?
- Can you customize the package?
- Can I upgrade my package?
- Can I downgrade my package?
- Can I add more time?
- Can I add another ride?
- Can I book for tomorrow?
- Can I book for today?
- Can I get a same-day booking?
- Can I transfer my booking to someone else?

---

# 33. Sales Team FAQ Collection Template

The 100-question list should become a controlled business questionnaire.

For each question, the sales team should fill:

| Field | Sales Team Input |
|---|---|
| FAQ ID | Pre-filled |
| Question | Pre-filled |
| Approved Answer |  |
| Alternative Answer / Notes |  |
| Can AI Answer? | Yes / No |
| Human Handoff? | Yes / No |
| Price Involved? | Yes / No |
| Requires Live Data? | Yes / No |
| Tool Required |  |
| Applicable Package | Couple / Family & Friends / Both |
| Applicable Guest Count |  |
| Applicable Occasion |  |
| Source/Owner |  |
| Last Verified |  |

This will become the authoritative FAQ approval sheet.

---

# 34. AI Language Policy

The AI should respond in the customer's preferred language:

- English
- Tamil
- Hindi/Hinglish

Language should be detected from the customer's message and conversation history.

The AI should not switch language unnecessarily.

If the customer mixes languages, use natural conversational language matching the customer.

Example:

Customer:
> “Pontoon kitne ka hai?”

AI:
> “Pontoon Couple Romance Celebration ₹3,999 for 2 guests hai. 😊”

Customer:
> “எத்தனை பேர் வரலாம்?”

AI:
> “Couple package 2 guests-க்கு. Family & Friends package 6, 9 அல்லது 12 guests options-ல இருக்கு.”

Final approved Tamil/Hindi copy should be reviewed by the sales team before production.

---

# 35. AI Response & Nurture Principle

The agent should follow:

```text
Answer
  ↓
Understand intent
  ↓
Identify sales stage
  ↓
Ask ONE useful next question
  ↓
Update lead score
  ↓
Take next best action
```

Avoid:

- Long information dumps
- Repeating the entire package every message
- Asking 5–8 questions at once
- Pressuring cold leads
- Inventing availability
- Inventing discounts
- Making refund promises
- Confirming payment without verification

---

# 36. Current Coimbatore KB Readiness

### Business Knowledge
**9/10**

### Pontoon Product Knowledge
**9.5/10**

### Sales Logic
**9/10**

### Operational Knowledge
**8.5/10**

### FAQ Coverage
**8.5/10**, with 100-question sales validation list now prepared

### AI Guardrails
**9.5/10**

### Production RAG Readiness
**8.5/10**

### Overall Current Estimate
**~9/10**, with the remaining gap primarily caused by unvalidated FAQ answers, booking-system implementation, live availability/payment integration, and real customer-conversation data.

The KB should move to **9.5/10 after the sales team fills and approves the 100-question questionnaire and the approved answers are incorporated into the production knowledge structure.
