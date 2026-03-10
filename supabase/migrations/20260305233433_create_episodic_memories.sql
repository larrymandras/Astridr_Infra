create table if not exists public.episodic_memories (
    id           bigint generated always as identity primary key,
    agent_id     text not null,
    event_type   text not null,
    summary      text not null,
    detail       jsonb not null default '{}'::jsonb,
    occurred_at  timestamptz not null default now(),
    expires_at   timestamptz not null default (now() + interval '90 days')
);

create index if not exists idx_episodic_agent_time
    on public.episodic_memories (agent_id, occurred_at desc);

create index if not exists idx_episodic_expires
    on public.episodic_memories (expires_at);

alter table public.episodic_memories enable row level security;

do $$
begin
    if not exists (
        select 1 from pg_policies where tablename = 'episodic_memories' and policyname = 'service_role_all'
    ) then
        create policy "service_role_all"
            on public.episodic_memories for all using (true) with check (true);
    end if;
end $$;
