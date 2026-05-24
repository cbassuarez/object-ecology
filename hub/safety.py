from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SafetyDecision:
    allowed: bool
    status: str
    reason: str | None = None
    payload: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {"allowed": self.allowed, "status": self.status}
        if self.reason:
            data["reason"] = self.reason
        if self.payload is not None:
            data["payload"] = self.payload
        return data


class CentralSafety:
    def __init__(
        self,
        room_config: dict[str, Any],
        safety_config: dict[str, Any],
        state_path: Path,
    ):
        self.room_config = room_config
        self.config = safety_config.get("central", {})
        self.node_defaults = safety_config.get("node_defaults", {})
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"tap_events": []}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"tap_events": []}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _prune(self, now: float) -> None:
        window = 60.0
        self.state["tap_events"] = [
            event for event in self.state.get("tap_events", [])
            if now - float(event.get("time", 0)) <= window
        ]

    def check_command(self, node_id: str, command: str, payload: dict[str, Any]) -> SafetyDecision:
        now = time.time()
        self._prune(now)

        if self.room_config.get("emergency_quiet"):
            return SafetyDecision(False, "refused", "central_emergency_quiet", payload)

        if command != "TAP":
            return SafetyDecision(True, "allowed", payload=payload)

        total_events = self.state.get("tap_events", [])
        node_events = [event for event in total_events if event.get("node_id") == node_id]
        if len(total_events) >= int(self.config.get("max_total_taps_per_minute", 20)):
            return SafetyDecision(False, "refused", "central_total_tap_rate_limit", payload)
        if len(node_events) >= int(self.config.get("max_taps_per_node_per_minute", 6)):
            return SafetyDecision(False, "refused", "central_node_tap_rate_limit", payload)

        duration = int(payload.get("duration_ms", 0))
        max_duration = int(self.node_defaults.get("max_solenoid_pulse_duration_ms", 100))
        if duration > max_duration and self.config.get("clamp_unsafe_durations", False):
            clamped = dict(payload)
            clamped["duration_ms"] = max_duration
            return SafetyDecision(True, "clamped", "central_duration_clamp", clamped)

        return SafetyDecision(True, "allowed", payload=payload)

    def record_response(self, node_id: str, command: str, response_type: str, payload: dict[str, Any]) -> None:
        if command == "TAP" and response_type == "ACK":
            self.state.setdefault("tap_events", []).append(
                {"time": time.time(), "node_id": node_id, "duration_ms": payload.get("duration_ms")}
            )
            self._prune(time.time())
            self._save_state()
