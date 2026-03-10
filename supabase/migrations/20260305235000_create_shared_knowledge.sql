-- Shared knowledge table for the Urdhr memory bus protocol.
-- Cross-agent knowledge store with optional pgvector embeddings.

create table if not exists public.shared_knowledge (
    id           bigint generated always as identity primary key,
    agent_id     text not null,
    category     text not null default 'fact',
    topic        text,
    content      text not null,
    embedding    vector(384),
    metadata     jsonb not null default '{}'::jsonb,
    published_at timestamptz not null default now(),
    expires_at   timestamptz
);

-- Indexes
create index idx_sk_agent_time on public.shared_knowledge (agent_id, published_at desc);
create index idx_sk_category_time on public.shared_knowledge (category, published_at desc);
create index idx_sk_topic on public.shared_knowledge (topic) where topic is not null;
create index idx_sk_expires on public.shared_knowledge (expires_at) where expires_at is not null;
create index idx_sk_embedding on public.shared_knowledge
    using hnsw (embedding vector_cosine_ops) with (m = 16, ef_construction = 64);

-- Semantic search RPC
create or replace function public.match_shared_knowledge(
    query_embedding vector(384),
    match_count int default 10,
    filter_category text default null,
    filter_agent_id text default null,
    filter_topic text default null
) returns table (
    id bigint,
    agent_id text,
    category text,
    topic text,
    content text,
    metadata jsonb,
    published_at timestamptz,
    similarity float
) language plpgsql as $$
begin
    return query
    select sk.id, sk.agent_id, sk.category, sk.topic, sk.content,
           sk.metadata, sk.published_at,
           1 - (sk.embedding <=> query_embedding) as similarity
    from public.shared_knowledge sk
    where (filter_category is null or sk.category = filter_category)
      and (filter_agent_id is null or sk.agent_id = filter_agent_id)
      and (filter_topic is null or sk.topic = filter_topic)
      and (sk.expires_at is null or sk.expires_at > now())
    order by sk.embedding <=> query_embedding
    limit match_count;
end;
$$;

-- RLS
alter table public.shared_knowledge enable row level security;
create policy "service_role_all" on public.shared_knowledge
    for all using (true) with check (true);
