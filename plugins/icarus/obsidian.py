"""Obsidian integration for Icarus fabric entries.

Opt-in via ICARUS_OBSIDIAN=1 environment variable.

- format_entry: appends wikilinks for review_of/revises refs
- ensure_daily_note: links new entries in a daily note
- init_obsidian: one-time vault setup
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LINKS_START = "<!-- ICARUS_OBSIDIAN_LINKS_START -->"
LINKS_END = "<!-- ICARUS_OBSIDIAN_LINKS_END -->"


def _find_entry_file(ref: str, fabric_dir: Path) -> Optional[str]:
    """Resolve agent:id ref to a filename (without .md extension)."""
    if ":" not in ref:
        return None
    agent, entry_id = ref.split(":", 1)
    if not agent or not entry_id:
        return None
    for d in (fabric_dir, fabric_dir / "cold"):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            head = f.read_text("utf-8")[:400]
            m_agent = re.search(r"^agent: (.+)$", head, re.MULTILINE)
            m_id = re.search(r"^id: (.+)$", head, re.MULTILINE)
            if (m_agent and m_id
                    and m_agent.group(1).strip() == agent
                    and m_id.group(1).strip() == entry_id):
                return f.stem  # filename without .md
    return None


def format_entry(filepath: Path, fabric_dir: Path, review_of: str = "", revises: str = ""):
    """Append wikilinks section to a fabric entry for Obsidian navigation."""
    if not review_of and not revises:
        return

    text = filepath.read_text("utf-8")
    links = []

    if review_of:
        target = _find_entry_file(review_of, fabric_dir)
        if target:
            links.append(f"- Reviews: [[{target}]]")
        else:
            links.append(f"- Reviews: {review_of}")

    if revises:
        target = _find_entry_file(revises, fabric_dir)
        if target:
            links.append(f"- Revises: [[{target}]]")
        else:
            links.append(f"- Revises: {revises}")

    if not links:
        return

    generated = (
        f"\n\n{LINKS_START}\n"
        "## Links\n"
        + "\n".join(links)
        + f"\n{LINKS_END}\n"
    )

    existing = re.compile(
        rf"\n*{re.escape(LINKS_START)}.*?{re.escape(LINKS_END)}\n*",
        re.DOTALL,
    )
    text = existing.sub("\n", text).rstrip()
    filepath.write_text(text + generated, "utf-8")


def ensure_daily_note(fabric_dir: Path, entry_filename: str, summary: str):
    """Add a link to the new entry in today's daily note."""
    daily_dir = fabric_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    daily_path = daily_dir / f"{today}.md"

    stem = entry_filename.replace(".md", "")
    link_line = f"- [[{stem}]] {summary}\n"

    if daily_path.exists():
        content = daily_path.read_text("utf-8")
        if f"[[{stem}]]" in content:
            return  # already linked
        daily_path.write_text(content.rstrip() + "\n" + link_line, "utf-8")
    else:
        daily_path.write_text(f"# {today}\n\n{link_line}", "utf-8")


def _vault_dir_for(fabric_dir: Path) -> Path:
    """Resolve the Obsidian vault root for config files."""
    configured = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return fabric_dir


def init_obsidian(fabric_dir: Path) -> dict:
    """One-time Obsidian vault setup for a fabric directory."""
    created = []

    daily_dir = fabric_dir / "daily"
    if not daily_dir.exists():
        daily_dir.mkdir(parents=True, exist_ok=True)
        created.append(str(daily_dir))

    vault_dir = _vault_dir_for(fabric_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    obsidian_dir = vault_dir / ".obsidian"
    if not obsidian_dir.exists():
        obsidian_dir.mkdir(parents=True, exist_ok=True)
        created.append(str(obsidian_dir))

    app_json = obsidian_dir / "app.json"
    if not app_json.exists():
        app_json.write_text(json.dumps({
            "showFrontmatter": True,
            "readableLineLength": True,
        }, indent=2), "utf-8")
        created.append(str(app_json))

    if created:
        logger.info("icarus: obsidian init created %s", created)

    result = {
        "status": "initialized" if created else "already_initialized",
        "fabric_dir": str(fabric_dir),
        "vault_dir": str(vault_dir),
        "created": created,
    }
    try:
        from . import wiki

        result["wiki"] = wiki.init_wiki()
    except Exception as exc:
        logger.debug("icarus: wiki init during obsidian setup failed: %s", exc)

    return result
