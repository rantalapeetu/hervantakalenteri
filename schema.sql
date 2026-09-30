-- Tapahtumataulu Supabaseen (Postgres). Aja SQL Editorissa kerran.

create table if not exists events (
  id                  uuid primary key default gen_random_uuid(),
  source              text not null,          -- esim. 'trey', 'sahkokilta', 'manual'
  external_id         text not null,          -- lähteen oma tunniste (ICS:n UID tai URL)
  title               text not null,
  starts_at           timestamptz not null,
  ends_at             timestamptz,
  location            text,
  organizer           text,
  category            text,                   -- 'bileet' | 'urheilu' | 'ura' | 'opinnot' | ...
  description         text,
  url                 text,
  registration_opens  timestamptz,
  registration_closes timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  -- sama tapahtuma ei tallennu kahdesti, vaan päivittyy uudelleenhaussa
  unique (source, external_id)
);

create index if not exists events_starts_at_idx on events (starts_at);
create index if not exists events_reg_closes_idx on events (registration_closes)
  where registration_closes is not null;

-- Pidä updated_at ajan tasalla
create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists events_set_updated_at on events;
create trigger events_set_updated_at before update on events
  for each row execute function set_updated_at();

-- Rivitason suojaus: kaikki saavat lukea, vain palvelin (service role) kirjoittaa
alter table events enable row level security;

drop policy if exists "events are public" on events;
create policy "events are public" on events for select using (true);
