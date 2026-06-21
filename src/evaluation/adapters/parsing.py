"""Output parsers shared across adapters.

Extracted from V1's inline ``extract_session_id`` / ``extract_assistant_text``.
"""
from __future__ import annotations

import re
from typing import Optional


_SESSION_ID_RE = re.compile(r"session_id:\s*([A-Za-z0-9_\-]+)")


def extract_session_id(output: str) -> Optional[str]:
    match = _SESSION_ID_RE.search(output or "")
    return match.group(1) if match else None


def extract_assistant_text(stdout: str, stderr: str) -> str:
    """Strip Hermes UI noise (session lines, panels, denied banners) from output."""
    combined = "\n".join(part for part in [stdout or "", stderr or ""] if part)
    lines: list[str] = []
    skipping_panel = False
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped.startswith("session_id:"):
            continue
        if line.startswith("╭─") or line.startswith("╰─"):
            continue
        if "DANGEROUS COMMAND:" in line:
            skipping_panel = True
            continue
        if skipping_panel:
            if "✗ Denied" in line:
                skipping_panel = False
            continue
        lines.append(line)
    return "\n".join(lines).strip()
