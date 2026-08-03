-- Location-scoped, idempotent knowledge chunks for approved RAG ingestion.
-- The vector dimension is deliberately unconstrained here; the ingestion tool
-- verifies the configured dimension against the embedding API response.

create extension if not exists vector;

create table public.knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  knowledge_document_id uuid not null references public.knowledge_documents(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null check (char_length(trim(content)) > 0),
  content_hash text not null check (content_hash ~ '^[a-f0-9]{64}$'),
  embedding vector not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (knowledge_document_id, chunk_index),
  unique (knowledge_document_id, content_hash)
);

create index knowledge_chunks_document_idx
  on public.knowledge_chunks (knowledge_document_id, chunk_index);

create index knowledge_documents_location_code_idx
  on public.knowledge_documents ((metadata->>'location_code'))
  where is_active;

alter table public.knowledge_chunks enable row level security;
