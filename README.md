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
