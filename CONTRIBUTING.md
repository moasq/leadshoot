# Contributing to LeadShoot

Thank you for helping make local-business research more useful and more
honest. Contributions are welcome across the CLI, API, MCP server, data
providers, qualification model, documentation, and test coverage.

## Start with the right issue

- Use **Qualification feedback** when the mode, priority, evidence, unknowns,
  or next action felt wrong for a real niche.
- Use **Bug report** for reproducible failures.
- Use **Feature request** for a new capability or provider.

Before sharing output, remove personal data, private pipeline notes, review
text, and reviewer identities. Public business facts and aggregate review
signals are sufficient.

## Development setup

LeadShoot requires Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
```

Tests must run without network access.

## Repository rules

- `.agents/` is the single source of truth for agent-facing instructions,
  rules, skills, and specialist agents.
- Do not hand-edit generated copies in `AGENTS.md`, `.claude/skills/`,
  `.claude/agents/`, or `skills/leadshoot/`.
- After editing `.agents/`, run:

  ```bash
  python scripts/sync_agents.py
  ```

- Preserve the split between sourced business facts and user-owned workflow
  state such as stages and notes.
- Never turn missing data into a verified gap.
- Keep CLI, MCP, and REST behavior in parity when adding public operations.
- Store aggregate review signals only; do not collect review text, reviewer
  identities, or personal contact data.

The complete project conventions are in [AGENTS.md](AGENTS.md) and the
binding rules under [`.agents/rules/`](.agents/rules/).

## Pull requests

Keep each pull request focused. Include:

- the problem and intended behavior;
- the user or developer impact;
- tests added or changed;
- the commands used to validate the change.

Run before submitting:

```bash
.venv/bin/python -m pytest tests/ -q
```

If agent-facing material changed, also run:

```bash
python scripts/sync_agents.py
git diff --exit-code
```

The second command confirms generated files are synchronized.
