-- Ástríðr persistence tables
-- Used by: astridr/engine/persistence.py, astridr/memory/vector_store.py

-- ── Extensions ──────────────────────────────────────────────────────
create extension if not exists vector with schema extensions;

-- ── Audit Logs ──────────────────────────────────────────────────────
create table if not exists public.audit_logs (
    id          bigint generated always as identity primary key,
    timestamp   timestamptz not null default now(),
    profile_id  text not null default 'unknown',
    channel_id  text,
    direction   text,          -- 'inbound' | 'outbound'
    event       jsonb,
    prev_hash   text,
    hash        text
);

create index idx_audit_logs_profile_ts
    on public.audit_logs (profile_id, timestamp desc);

-- ── Budget Tracking ─────────────────────────────────────────────────
create table if not exists public.budget_tracking (
    id          bigint generated always as identity primary key,
    profile_id  text not null,
    spend_date  date not null default current_date,
    spent_usd   numeric(12,6) not null default 0,
    constraint  uq_budget_profile_date unique (profile_id, spend_date)
);

create index idx_budget_date
    on public.budget_tracking (spend_date);

-- ── Session History ─────────────────────────────────────────────────
create table if not exists public.session_history (
    session_id  text primary key,
    profile_id  text not null,
    channel_id  text,
    messages    jsonb not null default '[]'::jsonb,
    turn_count  integer not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index idx_session_profile
    on public.session_history (profile_id);

-- ── Jobs ────────────────────────────────────────────────────────────
create table if not exists public.jobs (
    id            text primary key,
    name          text not null,
    task          text not null,
    trigger       text not null default 'manual',
    status        text not null default 'pending',
    profile_id    text,
    created_at    timestamptz default now(),
    started_at    timestamptz,
    completed_at  timestamptz,
    result        jsonb,
    error         text
);

create index idx_jobs_status
    on public.jobs (status);

-- ── Agent Handoffs ──────────────────────────────────────────────────
create table if not exists public.agent_handoffs (
    id              bigint generated always as identity primary key,
    from_agent_id   text not null,
    to_agent_id     text not null,
    task            text,
    context         jsonb,
    status          text not null default 'pending',
    created_at      timestamptz not null default now()
);

-- ── Agent File Locks ────────────────────────────────────────────────
create table if not exists public.agent_file_locks (
    path        text primary key,
    agent_id    text not null,
    acquired_at timestamptz not null default now()
);

-- ── Semantic Memories (pgvector) ────────────────────────────────────
create table if not exists public.semantic_memories (
    id          bigint generated always as identity primary key,
    entry_id    text not null unique,
    content     text not null,
    embedding   vector(384),   -- all-MiniLM-L6-v2 outputs 384 dims
    metadata    jsonb not null default '{}'::jsonb,
    agent_id    text not null default '',
    created_at  timestamptz not null default now()
);

create index idx_semantic_agent
    on public.semantic_memories (agent_id);

-- HNSW index for fast ANN search
create index idx_semantic_embedding
    on public.semantic_memories
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- ── RPC: match_memories ─────────────────────────────────────────────
-- Called by vector_store.py for semantic search
create or replace function public.match_memories(
    query_embedding vector(384),
    match_count     int default 10,
    filter_agent_id text default null
)
returns table (
    entry_id   text,
    content    text,
    metadata   jsonb,
    similarity float
)
language plpgsql
as $$
begin
    return query
    select
        sm.entry_id,
        sm.content,
        sm.metadata,
        1 - (sm.embedding <=> query_embedding) as similarity
    from public.semantic_memories sm
    where (filter_agent_id is null or sm.agent_id = filter_agent_id)
    order by sm.embedding <=> query_embedding
    limit match_count;
end;
$$;

-- ── RLS ─────────────────────────────────────────────────────────────
-- Enable RLS on all tables (service-role key bypasses)
alter table public.audit_logs enable row level security;
alter table public.budget_tracking enable row level security;
alter table public.session_history enable row level security;
alter table public.jobs enable row level security;
alter table public.agent_handoffs enable row level security;
alter table public.agent_file_locks enable row level security;
alter table public.semantic_memories enable row level security;

-- Service-role policy: full access for the framework
create policy "service_role_all" on public.audit_logs for all using (true) with check (true);
create policy "service_role_all" on public.budget_tracking for all using (true) with check (true);
create policy "service_role_all" on public.session_history for all using (true) with check (true);
create policy "service_role_all" on public.jobs for all using (true) with check (true);
create policy "service_role_all" on public.agent_handoffs for all using (true) with check (true);
create policy "service_role_all" on public.agent_file_locks for all using (true) with check (true);
create policy "service_role_all" on public.semantic_memories for all using (true) with check (true);
