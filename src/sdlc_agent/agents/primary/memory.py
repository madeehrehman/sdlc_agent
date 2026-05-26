"""Living memory for the Primary agent.

Persisted as a JSON file at project_memory_path. Read at session start,
updated after every closed ticket. Injected into sub-agent assignments.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_EMPTY: dict = {
    "architecture_decisions": [],
    "coding_standards": {},
    "lessons_learned": [],
    "component_map": {},
    "open_risks": [],
}


class ProjectMemory:
    """Read/write the Primary agent's living memory document."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> dict:
        """Return current memory dict. Returns empty structure if file missing."""
        if not self.path.exists():
            return dict(_EMPTY)
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return dict(_EMPTY)

    def write(self, data: dict) -> None:
        """Overwrite memory with provided dict."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update(self, updates: dict[str, Any]) -> dict:
        """Merge updates into existing memory. Lists are appended, dicts are merged."""
        current = self.read()
        for key, value in updates.items():
            if key in current and isinstance(current[key], list) and isinstance(value, list):
                current[key] = current[key] + value
            elif key in current and isinstance(current[key], dict) and isinstance(value, dict):
                current[key] = {**current[key], **value}
            else:
                current[key] = value
        self.write(current)
        return current

    def as_context_string(self) -> str:
        """Render memory as a human-readable string for LLM injection."""
        data = self.read()
        lines = ["# Project Memory\n"]
        for key, value in data.items():
            lines.append(f"## {key.replace('_', ' ').title()}")
            if isinstance(value, list):
                lines.extend(f"- {item}" for item in value) if value else lines.append("- (none)")
            elif isinstance(value, dict):
                lines.extend(f"- {k}: {v}" for k, v in value.items()) if value else lines.append("- (none)")
            else:
                lines.append(str(value))
            lines.append("")
        return "\n".join(lines)
