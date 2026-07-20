# Entartica WhatsApp Chatbot — Project Instructions

## 1. Project overview

Build a production-ready WhatsApp chatbot for Entartica Sea World.

The chatbot will communicate with customers through Exotel and answer questions using approved company information.

The initial MVP must be completed within approximately 14 working days.

The system must remain simple, secure, testable and suitable for future expansion.

---

## 2. Phase 1 objectives

The Phase 1 chatbot must:

* Receive and send WhatsApp messages through Exotel
* Support English, Hindi and Hinglish
* Answer questions using approved company knowledge
* Provide information about locations, services, facilities and policies
* Collect booking enquiries
* Collect wedding, corporate and group-event leads
* Transfer conversations to human employees
* Save unanswered questions
* Save conversation and message history
* Allow the chatbot to be enabled or disabled
* Prevent unsupported or invented answers

---

## 3. Phase 1 exclusions

Do not build the following in Phase 1:

* Automatic price calculation
* Payment gateway integration
* Payment-link generation
* Automatic payment verification
* Automatic booking confirmation
* Automatic refunds
* Complex rescheduling
* Custom Next.js dashboard
* Zoho CRM integration
* ERP integration
* n8n workflows
* Redis
* Amazon SQS
* LangSmith
* Sentry

When a customer asks about pricing, payment or final confirmation:

1. Collect the relevant requirements.
2. Create an enquiry.
3. Transfer the conversation to a human employee.
4. Clearly state that the booking is not confirmed.

---

## 4. Final technology stack

Use the following stack:

| Component                   | Technology                            |
| --------------------------- | ------------------------------------- |
| WhatsApp communication      | Exotel                                |
| Programming language        | Python                                |
| Backend API                 | FastAPI                               |
| AI orchestration            | LangChain                             |
| RAG ingestion and retrieval | LlamaIndex                            |
| Language model              | OpenAI API                            |
| Embeddings                  | OpenAI Embeddings                     |
| Main database               | Supabase PostgreSQL                   |
| Vector database             | Supabase pgvector                     |
| Document storage            | Supabase Storage                      |
| Source-code management      | GitHub                                |
| Packaging                   | Docker                                |
| API testing                 | Postman                               |
| Automated testing           | Pytest                                |
| Development assistance      | Codex                                 |
| Staging                     | Developer laptop or additional laptop |
| Staging public URL          | ngrok or Cloudflare Tunnel            |
| Production                  | Company-owned Linux cloud server/VPS  |
| Reverse proxy and HTTPS     | Caddy or Nginx                        |
| Production logs             | Docker and server logs                |

Do not introduce another framework or service unless it solves a confirmed requirement.

---

## 5. Current available resources

The following are currently available:

* Exotel account access
* Company OpenAI API keys
* Codex access
* Coding laptop
* Additional laptop for staging and testing

The developer can independently arrange:

* Python
* FastAPI
* LangChain
* LlamaIndex
* Docker
* Postman
* Pytest
* ngrok or Cloudflare Tunnel

The company still needs to provide or approve:

* Company-owned GitHub repository
* Company-owned Supabase organization and project
* Company-owned production cloud server
* Full Exotel API credentials
* Exotel webhook permissions
* Exotel WhatsApp sender details
* Exotel human-agent inbox access
* Approved company documents
* Approved launch location
* Five to ten launch services
* Support and sales contacts
* Knowledge approver
* Staff for acceptance testing

---

## 6. Architecture

Use this architecture:

```text
WhatsApp Customer
        ↓
Exotel
        ↓
FastAPI Webhook
        ↓
Message Validation and Storage
        ↓
LangChain Conversation Controller
   ├── Structured Supabase Lookup
   ├── LlamaIndex RAG Search
   ├── Booking Enquiry Tool
   ├── Event Lead Tool
   ├── Unanswered Question Tool
   └── Human Handover Tool
        ↓
OpenAI API
        ↓
Exotel Response
```

Supabase will store:

* Customers
* Conversations
* Messages
* Locations
* Services
* Booking enquiries
* Event leads
* Knowledge-document metadata
* Vector embeddings
* Unanswered questions
* System settings
* Audit logs

---

## 7. Responsibility boundaries

### Exotel

Exotel is responsible for:

* Receiving WhatsApp messages
* Sending WhatsApp replies
* WhatsApp templates
* Delivery-status callbacks
* Human-agent communication where supported

### FastAPI

FastAPI is responsible for:

* Receiving Exotel webhooks
* Validating incoming requests
* Normalizing messages
* Calling the correct application service
* Saving messages and events
* Sending responses through Exotel
* Providing health-check endpoints
* Handling errors safely

### LangChain

LangChain is responsible for:

* Understanding customer intent
* Controlling the conversation flow
* Selecting the correct tool
* Deciding whether to use RAG, structured data or human handover
* Generating the final response using approved context

Do not use LangChain as the database.

### LlamaIndex

LlamaIndex is responsible for:

* Reading approved documents
* Cleaning document content
* Splitting documents into focused chunks
* Adding metadata
* Creating embeddings
* Storing vectors in Supabase
* Retrieving relevant company knowledge

Do not use LlamaIndex for booking-enquiry records or live operational data.

### Supabase

Supabase is responsible for:

* PostgreSQL data storage
* pgvector storage and search
* Approved document storage
* Conversation records
* Customer records
* Booking enquiries
* Leads
* System settings

### OpenAI

OpenAI is responsible for:

* Language understanding
* English, Hindi and Hinglish responses
* Intent interpretation
* Response generation
* Embedding generation

The model must never be treated as the source of company facts.

---

## 8. Structured data versus RAG

Use structured Supabase tables for information that changes frequently or must be exact:

* Active locations
* Active services
* Operating status
* Customer details
* Conversation state
* Booking enquiries
* Leads
* Assigned teams
* Enquiry status
* Chatbot enabled or disabled status

Use RAG for approved informational content:

* Activity descriptions
* Safety instructions
* Frequently asked questions
* Facilities
* Policies
* Customer guidance
* Wedding information
* Corporate information
* Operating procedures

Do not answer live availability, pricing or payment questions from RAG.

---

## 9. Required database tables

Create the following initial tables:

### Core business tables

* `locations`
* `services`
* `customers`
* `conversations`
* `messages`
* `booking_enquiries`
* `leads`

### Knowledge tables

* `knowledge_documents`
* LlamaIndex/Supabase vector collection
* `unanswered_questions`

### System tables

* `system_settings`
* `audit_logs`

Every table should include appropriate:

* Primary keys
* Foreign keys
* Timestamps
* Status fields
* Validation constraints
* Indexes
* Duplicate protection

---

## 10. Conversation states

Use explicit database-backed conversation states.

Initial states:

* `new`
* `awaiting_name`
* `awaiting_location`
* `awaiting_service`
* `awaiting_date`
* `awaiting_time`
* `awaiting_guest_count`
* `awaiting_event_details`
* `enquiry_complete`
* `human_handover`
* `closed`

Do not depend only on the model conversation history.

Important fields collected during an enquiry must be stored in the database.

---

## 11. Booking-enquiry flow

Collect:

* Customer name
* WhatsApp number
* Location
* Service or activity
* Preferred date
* Preferred time
* Guest count
* Adult count where applicable
* Child count where applicable
* Special requirements

After saving the enquiry, respond clearly:

```text
Thank you. Your booking enquiry has been recorded.

Our team will confirm availability, price and final booking details with you.
```

Never say that the booking is confirmed.

Generate a unique enquiry reference such as:

```text
ENQ-YYYYMMDD-0001
```

---

## 12. Event-lead flow

Supported lead types:

* Wedding
* Corporate event
* School group
* Large group
* Party
* Photoshoot
* Other event

Collect:

* Customer name
* WhatsApp number
* Event type
* Preferred location
* Preferred event date
* Estimated guest count
* Requirements
* Preferred callback time

Save the lead and route it to the appropriate sales team.

---

## 13. Human-handover rules

Transfer to a human when:

* The customer requests a person
* The customer asks for a price
* The customer asks about payment
* The customer requests final booking confirmation
* The customer requests cancellation or refund
* The customer makes a complaint
* The question involves medical uncertainty
* A safety answer is unavailable
* The customer requests a wedding or corporate proposal
* The RAG result is insufficient
* The chatbot is uncertain
* An external service fails
* The system encounters an error

When human mode is activated:

* Set the conversation mode to `human`
* Save the handover reason
* Save the assigned team
* Stop automatic AI responses
* Notify the appropriate employee where possible

---

## 14. Chatbot behaviour rules

The assistant must:

* Use approved company information only
* Keep WhatsApp messages short and clear
* Ask one necessary question at a time
* Respond in the customer’s language
* Recognize English, Hindi and Hinglish
* Clearly distinguish enquiries from confirmed bookings
* Escalate uncertain questions
* Save unanswered questions
* Avoid repeating questions when information is already available
* Be polite and customer friendly

The assistant must never:

* Invent prices
* Invent availability
* Invent discounts
* Invent policies
* Invent safety requirements
* Confirm a booking automatically
* Claim that payment was received
* Expose internal prompts
* Expose API keys
* Expose database credentials
* Reveal another customer’s data
* Modify protected statuses without authorization

---

## 15. RAG rules

Only ingest approved information.

Do not ingest:

* Expired pricing
* Expired offers
* Draft documents
* Duplicate documents
* Personal customer chats
* Passwords
* API keys
* Internal credentials
* Unapproved marketing claims

Every knowledge chunk should contain metadata where available:

* Location
* Service
* Category
* Source file
* Source page
* Document version
* Approved by
* Effective date
* Review date
* Active status

When retrieval confidence is insufficient:

1. Do not guess.
2. Save the customer question.
3. Transfer to a human where necessary.
4. Respond that the team will assist.

---

## 16. Security requirements

Implement:

* Environment variables for credentials
* `.env` in `.gitignore`
* `.env.example` without real credentials
* Server-side use of the Supabase secret key (`SUPABASE_SECRET_KEY`)
* Webhook validation where supported
* Input validation using Pydantic
* Duplicate Exotel-message protection
* Safe exception handling
* Database constraints
* Logging without exposing secrets
* Restricted server firewall
* HTTPS in production
* Non-root Docker execution where practical
* Regular dependency updates
* Rate limiting where needed
* Chatbot kill switch

Never commit credentials to GitHub.

Never place real credentials in:

* `AGENTS.md`
* `README.md`
* Source-code files
* Tests
* Chat messages
* Docker images

---

## 17. Production server requirements

The production system will use a company-owned Linux cloud server/VPS instead of AWS ECS/Fargate unless management later changes this decision.

Recommended starting server:

* Ubuntu Linux
* 2 virtual CPUs
* 4 GB RAM
* 40–80 GB SSD
* Static public IP
* Automated backups
* Docker and Docker Compose
* Caddy or Nginx
* HTTPS certificate
* Firewall
* Health monitoring

Only expose:

* Port 22 for restricted SSH
* Port 80 for HTTP-to-HTTPS redirection
* Port 443 for HTTPS

Do not expose the internal FastAPI port directly.

---

## 18. Development environments

Maintain separate environments:

### Development

* Coding laptop
* Local FastAPI
* Development Supabase project
* Test credentials
* Local document samples

### Staging

* Coding laptop or additional laptop
* Docker
* ngrok or Cloudflare Tunnel
* Staging Supabase data
* Exotel test configuration
* Internal company testers

### Production

* Company-owned cloud server
* Production Docker container
* Production Supabase project
* Production Exotel webhook
* Company credentials
* Server backups and monitoring

Do not mix staging and production data.

---

## 19. Project structure

Use a clean modular structure similar to:

```text
entartica-whatsapp-chatbot/
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── health.py
│   │   ├── exotel_webhook.py
│   │   └── status_webhook.py
│   ├── agents/
│   │   ├── chatbot.py
│   │   └── prompts.py
│   ├── integrations/
│   │   ├── exotel.py
│   │   ├── openai_client.py
│   │   └── supabase.py
│   ├── rag/
│   │   ├── ingestion.py
│   │   ├── loaders.py
│   │   └── retriever.py
│   ├── repositories/
│   ├── services/
│   ├── models/
│   ├── schemas/
│   └── tools/
├── scripts/
├── tests/
└── documents/
```

Keep API routes, database operations, business logic, AI logic and integrations separated.

---

## 20. Coding standards

Use:

* Python 3.12
* Type hints
* Pydantic models
* Async functions for network operations where appropriate
* Small focused functions
* Clear module boundaries
* Descriptive names
* Centralized configuration
* Structured logging
* Error handling
* Unit tests
* Integration tests
* Database migrations

Avoid:

* Large single-file implementations
* Hard-coded credentials
* Hard-coded production URLs
* Unnecessary abstractions
* Duplicate business logic
* Agent-inside-agent designs
* Adding unnecessary dependencies
* Silent exception handling

---

## 21. Testing requirements

Write tests for:

* Health endpoint
* Exotel payload normalization
* Incoming-message storage
* Duplicate-message protection
* Outgoing Exotel messages
* Customer creation
* Conversation creation
* Conversation-state transitions
* Location lookup
* Service lookup
* Booking-enquiry creation
* Event-lead creation
* Human handover
* Chatbot kill switch
* RAG retrieval
* Insufficient RAG context
* OpenAI failure
* Exotel failure
* Supabase failure
* Prompt-injection attempts
* Unauthorized data requests

Use Pytest.

Do not call paid external APIs in unit tests. Mock external services.

---

## 22. Fourteen-day implementation order

### Day 1

* Confirm scope
* Create repository
* Create FastAPI application
* Add health endpoint
* Add configuration management
* Add project structure

### Day 2

* Create Supabase schema
* Add repository layer
* Add sample location and service data

### Day 3

* Build Exotel inbound webhook
* Normalize and save incoming messages
* Add duplicate protection

### Day 4

* Build Exotel outbound client
* Send fixed WhatsApp reply
* Process delivery-status callbacks

### Day 5

* Clean approved documents
* Build LlamaIndex ingestion
* Store embeddings in Supabase

### Day 6

* Build RAG retrieval
* Add metadata filtering
* Test English, Hindi and Hinglish retrieval

### Day 7

* Build LangChain tools
* Build conversation controller
* Add system prompt and safety rules

### Day 8

* Add database-backed conversation state
* Build multi-step information collection

### Day 9

* Build booking-enquiry flow
* Generate enquiry references

### Day 10

* Build event-lead flow
* Build human handover

### Day 11

* Add chatbot kill switch
* Add unanswered-question tracking
* Add notifications and operational controls

### Day 12

* Run technical, integration and security tests
* Fix critical issues

### Day 13

* Conduct company acceptance testing
* Deploy to production cloud server

### Day 14

* Conduct controlled launch
* Monitor conversations
* Review unanswered questions and errors

---

## 23. First technical milestone

Before adding RAG or an AI agent, complete this flow:

```text
Customer sends “Hello”
→ Exotel sends webhook to FastAPI
→ FastAPI validates the webhook
→ Customer and message are saved in Supabase
→ FastAPI sends a fixed reply through Exotel
→ Customer receives the reply
```

Do not start complex LangChain development until this milestone works.

---

## 24. Codex working instructions

Before writing code:

1. Read this entire `AGENTS.md`.
2. Inspect the existing repository.
3. Do not delete working code without explanation.
4. Summarize the current repository status.
5. State which day and milestone are being implemented.
6. Propose the smallest safe implementation plan.
7. Identify missing credentials or business information.
8. Use placeholders instead of requesting real credentials.
9. Make changes in small reviewable steps.
10. Run relevant tests after every meaningful change.
11. Report files created or changed.
12. Report tests executed and their results.
13. Mention unresolved risks or blockers.

Do not attempt to build all 14 days in one task.

Work one milestone at a time.

Do not change the agreed architecture without explaining:

* Why the change is required
* What problem it solves
* What additional cost or complexity it introduces
* Whether a simpler option exists

---

## 25. Current first task

The first task is:

1. Inspect the repository.
2. Create the clean FastAPI project structure if it does not exist.
3. Create a `/health` endpoint.
4. Add `.env.example`.
5. Add `.gitignore`.
6. Add typed configuration using Pydantic Settings.
7. Add a basic Pytest test for `/health`.
8. Add `requirements.txt`.
9. Add a basic README with local-run instructions.
10. Run the tests.

Do not implement Exotel, Supabase, LangChain or LlamaIndex until this foundation is complete and tested.
