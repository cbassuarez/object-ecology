from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .protocol import utc_now


class JsonlLogger:
    def __init__(self, events_path: Path, health_path: Path):
        self.events_path = events_path
        self.health_path = health_path
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.health_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self.health_path.touch(exist_ok=True)

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        record.setdefault("timestamp", utc_now())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def event(self, record: dict[str, Any]) -> None:
        self._append(self.events_path, record)

    def health(self, record: dict[str, Any]) -> None:
        self._append(self.health_path, record)
