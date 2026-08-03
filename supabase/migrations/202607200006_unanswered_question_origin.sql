-- Distinguish explicitly marked development retrieval records from production questions.

alter table public.unanswered_questions
  add column record_origin text not null default 'production'
  check (record_origin in ('production', 'development_retrieval_test'));

create index unanswered_questions_development_origin_idx
  on public.unanswered_questions (record_origin, created_at desc)
  where record_origin = 'development_retrieval_test';
