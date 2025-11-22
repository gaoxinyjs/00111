from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from ..core.logger import get_logger


@dataclass
class StateStore:
    """
    Minimal persistence layer to keep strategy runtime state (active positions,
    last signals, etc.) across restarts. Uses a JSON file under data/.
    """

    path: Path
    default_state: Dict[str, Any] = field(default_factory=lambda: {"active_position": None, "last_signals": {}})

    def __post_init__(self) -> None:
        self._logger = get_logger("strategy.state_store")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return dict(self.default_state)
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            merged = dict(self.default_state)
            merged.update(data or {})
            return merged
        except Exception as exc:
            self._logger.warning("Failed to load strategy state (%s), using defaults", exc)
            return dict(self.default_state)

    def save(self, state: Dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fp:
                json.dump(state, fp, ensure_ascii=False, indent=2)
            tmp_path.replace(self.path)
        except Exception as exc:
            self._logger.error("Failed to persist strategy state: %s", exc)
