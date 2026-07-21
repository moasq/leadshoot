#!/usr/bin/env python3
"""Generate all derived agent files from the .agents/ single source of truth.

  .agents/agents.md            -> AGENTS.md            (root standard file)
  .agents/skills/<id>/skill.md -> .claude/skills/<id>/SKILL.md
                               -> skills/<id>/SKILL.md (portable copies)
  .agents/agents/<id>/agent.md -> .claude/agents/<id>.md

Idempotent; run after any .agents/ edit. Never edit generated files directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".agents"

STAMP = ("<!-- GENERATED from {src} - edit there and run "
         "`python scripts/sync_agents.py`. -->\n")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_or_empty, body)."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            close = text.find("\n", end + 1)
            return text[: close + 1], text[close + 1:]
    return "", text


def write(dest: Path, content: str, written: list[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_text() != content:
        dest.write_text(content)
        written.append(str(dest.relative_to(ROOT)))


def main() -> int:
    if not SRC.is_dir():
        print(f"missing {SRC}", file=sys.stderr)
        return 1
    written: list[str] = []

    # 1) root AGENTS.md (frontmatter stripped - it's a plain standard file)
    src = SRC / "agents.md"
    _, body = split_frontmatter(src.read_text())
    write(ROOT / "AGENTS.md",
          STAMP.format(src=".agents/agents.md") + body.lstrip("\n"), written)

    # 2) skills -> .claude/skills/ and portable skills/
    for skill_md in sorted(SRC.glob("skills/*/skill.md")):
        skill_id = skill_md.parent.name
        fm, body = split_frontmatter(skill_md.read_text())
        stamped = fm + STAMP.format(
            src=f".agents/skills/{skill_id}/skill.md") + body
        write(ROOT / ".claude" / "skills" / skill_id / "SKILL.md",
              stamped, written)
        write(ROOT / "skills" / skill_id / "SKILL.md", stamped, written)

    # 3) sub-agents -> .claude/agents/
    for agent_md in sorted(SRC.glob("agents/*/agent.md")):
        agent_id = agent_md.parent.name
        fm, body = split_frontmatter(agent_md.read_text())
        stamped = fm + STAMP.format(
            src=f".agents/agents/{agent_id}/agent.md") + body
        write(ROOT / ".claude" / "agents" / f"{agent_id}.md", stamped, written)

    if written:
        print("synced:")
        for path in written:
            print(f"  {path}")
    else:
        print("everything already in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
