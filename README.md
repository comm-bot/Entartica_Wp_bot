# Entartica WhatsApp Chatbot

The Phase 1 backend foundation for the Entartica Sea World WhatsApp chatbot.

## Current milestone

Day 1 foundation: FastAPI application, typed configuration, health check, and automated test setup. Exotel, Supabase, LangChain, and LlamaIndex are intentionally not implemented yet.

## Prerequisites

- Python 3.12

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and adjust non-secret local settings if needed.
4. Start the API:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

5. Open `http://127.0.0.1:8000/health`.

## Test

```powershell
python -m pytest
```

## Configuration

Configuration is read from environment variables through `app/config.py`. Keep real credentials in the untracked `.env` file or your deployment secret manager; never commit them.

## Raipur knowledge ingestion

Customer-facing Raipur Markdown is controlled by `documents/raipur/governance/manifests/raipur_knowledge_manifest.csv`. It covers services, celebrations, general information, FAQs, and policies. Only manifest-ready, active, approved, customer-facing Raipur `.md` files with valid matching front matter are eligible. Governance files and `documents/raipur/reference_archive` are never scanned or embedded.

Review before any database change:

```powershell
python scripts/ingest_raipur_knowledge.py --dry-run
```

After review and explicit approval, ingest with:

```powershell
python scripts/ingest_raipur_knowledge.py
```

The unified ingester stages a replacement, verifies its chunks, then activates it and deactivates only the prior active version of the same source file. It never deletes knowledge rows. `scripts/ingest_raipur_celebrations.py` is deliberately disabled legacy tooling, so it cannot create competing active documents.

The canonical customer-facing Raipur corpus is the active Markdown set under `documents/raipur/active`; all 19 services, including celebration services, live under `active/services`. Legacy DOCX files are retained under `documents/raipur/reference_archive/source_documents`, and governance CSVs are retained under `documents/raipur/governance`; neither is embedded. Generate the local inventory and optional read-only database comparison with:

```powershell
python scripts/audit_raipur_knowledge_inventory.py
python scripts/audit_raipur_knowledge_inventory.py --database
```
