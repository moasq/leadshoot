# Using LeadShoot from any AI agent

LeadShoot is agent-agnostic by design: one engine, one SQLite state file, three
doors. Every agent uses at least one of them - so **every agent works**.

| Door | Who it's for |
|---|---|
| **CLI + `--json`** | *Every* agent that can run a shell command - Grok, Hermes, OpenClaw, custom loops, cron. The universal fallback. |
| **MCP** (stdio or HTTP) | Claude Code, Claude Desktop, Codex CLI, Cursor, Gemini CLI, VS Code Copilot, Antigravity, Windsurf, Cline, Zed… |
| **REST + OpenAPI** | HTTP tool-calling agents, LangChain, custom apps |

**Step 0 for everyone - install the CLI once:**

```bash
pipx install "leadshoot[all]"          # from PyPI when published
# or from a checkout:
git clone https://github.com/moasq/leadshoot && pipx install "./leadshoot[all]"
```

`which leadshoot` gives the absolute path - some clients want it. State lives in
`leadshoot.db` in the working directory; pin it with `--db /absolute/path` or
the `LEADSHOOT_DB` env var so every agent sees the same pipeline.

---

## The universal recipe (works with literally ANY agent)

No MCP? No problem. Every LeadShoot command takes `--json` and returns stable,
parseable output - if your agent can run a shell command, it can drive the
whole engine.

1. **Install** the CLI (Step 0 above).
2. **Teach it**: paste [`skills/leadshoot/SKILL.md`](skills/leadshoot/SKILL.md)
   into the agent's system prompt / skills folder - or just tell it:
   *"Use the `leadshoot` CLI; every command takes `--json`; run
   `leadshoot status` first."*
3. **Let it drive**:

```bash
leadshoot status                        # engine state (always JSON)
leadshoot options                       # valid categories/services/stages/gaps
leadshoot niche "I build websites"      # map the niche deterministically
leadshoot icp new --name x --area "Portland, OR" \
    --categories dentist --service website_design --json
leadshoot find --icp x --limit 25 --json    # also auto-opens the live map
leadshoot leads --gap broken_site --min-score 50 --json
leadshoot mark n4544564889 --stage contacted --note "voicemail" --json
```

`find` opens a live map in the user's browser by itself (its JSON reports the
URL as `live_map`) - pins land as each check commits, so the human watches
while the agent works. On a headless box, pass `--no-open` or set
`LEADSHOOT_NO_OPEN=1`. `leadshoot ui` reopens the map; `leadshoot ui --stop`
ends the background server.

That's the whole contract. Grok, Hermes, OpenClaw, a bash loop - same three
steps:

- **Grok** - give it the SKILL.md as context and shell access; it drives the
  CLI with `--json`.
- **Hermes (Nous)** - same: SKILL.md in the system prompt + a shell tool.
- **OpenClaw** - copy the skill into its skills directory
  (`cp -r skills/leadshoot ~/.openclaw/skills/leadshoot`, or wherever your
  install keeps skills) and make sure `leadshoot` is on PATH.

---

## MCP clients

The server is `leadshoot mcp` (stdio). Tools exposed: `status`, `list_options`,
`save_icp`, `list_icps`, `find_leads`, `list_leads`, `get_lead`,
`update_lead`, `add_review_signal`, `recheck`, `export_leads` - plus baked-in
instructions (cold-start: call `status` first; no ICP → elicit one, then
`save_icp`).

### Claude Code

```bash
claude mcp add leadshoot -- leadshoot mcp --db ~/leads/leadshoot.db
```

Working inside this repo? `.mcp.json` is already here - nothing to do.

### Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.leadshoot]
command = "leadshoot"
args = ["mcp", "--db", "/Users/you/leads/leadshoot.db"]
```

### Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project - already in
this repo):

```json
{
  "mcpServers": {
    "leadshoot": {
      "command": "leadshoot",
      "args": ["mcp", "--db", "/Users/you/leads/leadshoot.db"]
    }
  }
}
```

### Gemini CLI

`~/.gemini/settings.json` - same `mcpServers` JSON block as Cursor. (In this
repo, `GEMINI.md` already points Gemini at the guide.)

### Claude Desktop

`claude_desktop_config.json` - same `mcpServers` JSON block as Cursor.

### VS Code (Copilot agent mode)

`.vscode/mcp.json`:

```json
{ "servers": { "leadshoot": { "type": "stdio", "command": "leadshoot", "args": ["mcp"] } } }
```

### Antigravity / Windsurf / Cline / Zed / anything else MCP

Every MCP client takes the same two facts - command `leadshoot`, args
`["mcp"]` - via its MCP settings UI or JSON. If the client only speaks HTTP:

```bash
leadshoot mcp --transport http --port 8322
# point the client at http://127.0.0.1:8322/mcp
```

---

## Working inside this repo? Zero setup.

The repo carries its own agent instructions - clone it and your agent is
already briefed:

| File | Read by |
|---|---|
| `AGENTS.md` | The open standard - Codex, Copilot, Cursor, Jules, Aider, Zed, Windsurf, Devin, 30+ agents |
| `CLAUDE.md` / `GEMINI.md` | Claude Code / Gemini CLI (pointers to AGENTS.md) |
| `.claude/skills/` + `.claude/agents/` | Claude Code skills & sub-agents (auto-discovered) |
| `.mcp.json` / `.cursor/mcp.json` | Project-scope MCP registration |
| `skills/*/SKILL.md` | Portable skill copies for any skills-compatible tool |

**`.agents/` is the single source of truth** - everything above is generated
from it by `python scripts/sync_agents.py`. Edit there, sync, never hand-edit
generated files.

---

## REST + OpenAPI

```bash
leadshoot serve --port 8321
```

API under `/api/*`, live map UI at `/`, machine-readable schema at
`/openapi.json` - feed that to any OpenAPI-driven tool-calling agent.
(For the map alone you rarely run this by hand - `find` starts a background
copy and opens it; `serve` is for docker, fixed ports, or long-lived
dashboards. `--no-open` skips its own browser launch.)

---

## Multi-agent, one pipeline

All three doors read and write the same `leadshoot.db`. Claude Code can create
the ICP, an OpenClaw cron job can run nightly `find --json`, Grok can qualify
leads by phone research, and you can work the map UI by hand - nothing
conflicts, nobody holds private state. Point every client at the same `--db`
path and it just works.
