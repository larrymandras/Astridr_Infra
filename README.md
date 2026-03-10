# Astridr Infrastructure

Infrastructure configurations extracted from the [Astridr](https://github.com/larrymandras/astridr) monorepo. This repository contains Docker, config, scripts, and Supabase database definitions for the Astridr AI agent framework.

## Repository Structure

```
docker/
  Dockerfile              # Python 3.13-slim image, non-root user, health check
  docker-compose.yml      # Full stack: Supabase (DB, Auth, REST, Realtime, Storage, Studio, Kong, Meta), Ollama, Astridr agent

config/
  mcp-servers.yaml        # MCP server connections (filesystem, fetch, Notion, Brave, Tavily, Perplexity, ElevenLabs, Figma)
  profiles.yaml           # Multi-profile routing (personal, business, consulting) + runtime agent profiles
  agent-types.yaml        # 10-agent Valkyrjur warband: commander + 9 specialists with autonomy rules, memory layout, daily rhythms
  security-rules.yaml     # 14-layer security pipeline (PII filter, injection defense, secret scanning, RLS, audit log, HITL gates)
  health-checks.yaml      # Health check intervals and retry config
  llm-failover.yaml       # LLM provider failover chain: OpenRouter -> Ollama -> Anthropic direct

scripts/
  migrate.py              # Migration from Antidote v0.1.0 (Mac) to Astridr (Windows): config conversion, SQLite schema migration, secret extraction
  nssm_setup.py           # NSSM Windows service wrapper: install/start/stop/restart/status/uninstall with log rotation
  supabase-sync.ps1       # Nightly Supabase local-to-cloud migration sync via Windows Task Scheduler

supabase/
  config.toml             # Supabase CLI local dev configuration
  migrations/
    20260305164538_create_persistence_tables.sql   # Core tables: audit_logs, budget_tracking, session_history, jobs, agent_handoffs, agent_file_locks, semantic_memories (pgvector)
    20260305233433_create_episodic_memories.sql     # Episodic memory with 90-day TTL
    20260305235000_create_shared_knowledge.sql      # Cross-agent knowledge store with pgvector semantic search
```

## Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Node.js (for MCP servers via npx)
- NVIDIA GPU drivers (for Ollama GPU acceleration, optional)
- NSSM (for Windows service installation, optional)

### Quick Start (Docker)

```bash
# Clone and navigate
git clone https://github.com/larrymandras/Astridr_Infra.git
cd Astridr_Infra/docker

# Copy and configure environment
cp .env.example .env  # Create your .env with required variables

# Start the full stack
docker compose up -d
```

### Windows Service (NSSM)

```bash
python scripts/nssm_setup.py install
python scripts/nssm_setup.py start
```

### Supabase Migrations

Migrations run automatically when starting the Supabase stack. To push to a linked cloud project:

```powershell
# One-time push
npx supabase db push --linked

# Or schedule nightly via the sync script
powershell scripts/supabase-sync.ps1
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM access |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token for channel integration |
| `SUPABASE_DB_PASSWORD` | No | Postgres password (default: `astridr-local-dev`) |
| `JWT_SECRET` | No | JWT signing secret (default: local dev token) |
| `SUPABASE_ANON_KEY` | No | Supabase anonymous key (default: local dev key) |
| `SUPABASE_SERVICE_ROLE_KEY` | No | Supabase service role key (default: local dev key) |
| `SUPABASE_ACCESS_TOKEN` | No | For cloud sync script |
| `ANTHROPIC_API_KEY` | No | Direct Anthropic API (failover provider) |
| `NOTION_API_KEY` | No | Notion MCP server |
| `BRAVE_API_KEY` | No | Brave Search MCP server |
| `TAVILY_API_KEY` | No | Tavily MCP server |
| `PERPLEXITY_API_KEY` | No | Perplexity MCP server |
| `ELEVENLABS_API_KEY` | No | ElevenLabs TTS MCP server |
| `FIGMA_PERSONAL_ACCESS_TOKEN` | No | Figma MCP server |
| `REALTIME_SECRET_KEY_BASE` | No | Supabase Realtime secret |

## Exposed Ports

| Port | Service |
|------|---------|
| 8080 | Astridr Agent API |
| 8099 | Astridr Health Check |
| 54321 | Supabase API (Kong) |
| 54322 | PostgreSQL |
| 54323 | Supabase Studio |
| 11434 | Ollama API |
