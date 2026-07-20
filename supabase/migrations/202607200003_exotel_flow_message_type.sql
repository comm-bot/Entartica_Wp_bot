-- Permit normalized inbound WhatsApp Flow response messages.

alter table public.messages
  drop constraint messages_message_type_check;

alter table public.messages
  add constraint messages_message_type_check
  check (message_type in ('text', 'flow', 'image', 'document', 'audio', 'video', 'other'));
