from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .protocol import make_message


class FakeNode:
    def __init__(
        self,
        node_config: dict[str, Any],
        safety_config: dict[str, Any],
        state_dir: Path,
    ):
        self.node_config = node_config
        self.node_id = node_config["node_id"]
        self.safety = safety_config.get("node_defaults", {})
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / f"{self.node_id}.json"
        self.state = self._load_state()
        self._recover_heat()

    def _default_state(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "online": True,
            "heat": 0.0,
            "fatigue": 0.0,
            "last_tap_time": None,
            "last_update": time.time(),
            "current_mode": "social",
            "fake_tof_distance_mm": 900,
            "fake_piezo_ring": 0.0,
            "rolling_on_events": [],
            "actuator_availability": {
                "solenoid_tapper": "available",
                "vibration_motor": "available",
            },
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = self._default_state()
        merged = self._default_state()
        merged.update(state)
        return merged

    def _save_state(self) -> None:
        self.state["last_update"] = time.time()
        self.state_path.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")

    def _recover_heat(self) -> None:
        now = time.time()
        elapsed = max(0.0, now - float(self.state.get("last_update") or now))
        recovery = float(self.safety.get("heat_recovery_per_second", 0.02)) * elapsed
        self.state["heat"] = max(0.0, float(self.state.get("heat", 0.0)) - recovery)
        self.state["fatigue"] = self.state["heat"]
        self._prune_rolling(now)

    def _prune_rolling(self, now: float) -> None:
        window = float(self.safety.get("rolling_duty_cycle_window_seconds", 60))
        self.state["rolling_on_events"] = [
            event for event in self.state.get("rolling_on_events", [])
            if now - float(event.get("time", 0)) <= window
        ]

    def _state_payload(self) -> dict[str, Any]:
        return {
            "online": bool(self.state.get("online", True)),
            "heat": round(float(self.state.get("heat", 0.0)), 4),
            "fatigue": round(float(self.state.get("fatigue", 0.0)), 4),
            "mode": self.state.get("current_mode", "social"),
            "last_seen": time.time(),
            "sensors": {
                "tof_distance_mm": self.state.get("fake_tof_distance_mm"),
                "piezo_ring": self.state.get("fake_piezo_ring"),
            },
            "actuator_availability": self.state.get("actuator_availability", {}),
        }

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        self._recover_heat()
        command = message["message_type"]
        correlation_id = message["correlation_id"]
        payload = message.get("payload", {})

        if command == "PING":
            response = make_message("PONG", self.node_id, {"status": "online"}, correlation_id)
        elif command == "REQUEST_STATE":
            response = make_message("STATE", self.node_id, self._state_payload(), correlation_id)
        elif command == "QUIET":
            self.state["current_mode"] = "quiet"
            response = make_message("ACK", self.node_id, {"mode": "quiet"}, correlation_id)
        elif command == "SET_MODE":
            self.state["current_mode"] = str(payload.get("mode", "social"))
            response = make_message("ACK", self.node_id, {"mode": self.state["current_mode"]}, correlation_id)
        elif command == "RESET_FATIGUE":
            self.state["heat"] = 0.0
            self.state["fatigue"] = 0.0
            self.state["rolling_on_events"] = []
            self.state["last_tap_time"] = None
            response = make_message("ACK", self.node_id, {"heat": 0.0, "fatigue": 0.0}, correlation_id)
        elif command == "TAP":
            response = self._handle_tap(payload, correlation_id)
        elif command == "VIBRATE":
            response = self._handle_vibrate(payload, correlation_id)
        else:
            response = make_message("ERROR", self.node_id, {"reason": f"unsupported_command:{command}"}, correlation_id)

        self._save_state()
        return response

    def _refusal(self, reason: str, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        return make_message(
            "SAFETY_REFUSAL",
            self.node_id,
            {"reason": reason, "requested": payload, "state": self._state_payload()},
            correlation_id,
            {"allowed": False, "status": "refused", "reason": reason},
        )

    def _handle_tap(self, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        duration = int(payload.get("duration_ms", 0))
        now = time.time()
        if self.state.get("current_mode") == "quiet":
            return self._refusal("node_quiet_mode", payload, correlation_id)

        max_duration = int(self.safety.get("max_solenoid_pulse_duration_ms", 100))
        if duration <= 0:
            return self._refusal("invalid_duration", payload, correlation_id)
        if duration > max_duration:
            return self._refusal("max_pulse_duration_exceeded", payload, correlation_id)

        last_tap = self.state.get("last_tap_time")
        cooldown_ms = int(self.safety.get("minimum_solenoid_cooldown_ms", 1500))
        if last_tap is not None and (now - float(last_tap)) * 1000 < cooldown_ms:
            return self._refusal("cooldown_active", payload, correlation_id)

        self._prune_rolling(now)
        rolling_total = sum(int(event.get("duration_ms", 0)) for event in self.state["rolling_on_events"])
        rolling_max = int(self.safety.get("max_rolling_on_time_ms_per_window", 1000))
        if rolling_total + duration > rolling_max:
            return self._refusal("rolling_duty_cycle_exceeded", payload, correlation_id)

        heat_add = duration * float(self.safety.get("tap_heat_per_ms", 0.002))
        max_heat = float(self.safety.get("max_heat", 1.0))
        if float(self.state.get("heat", 0.0)) + heat_add > max_heat:
            return self._refusal("fatigue_heat_limit", payload, correlation_id)

        self.state["last_tap_time"] = now
        self.state["rolling_on_events"].append({"time": now, "duration_ms": duration})
        self.state["heat"] = float(self.state.get("heat", 0.0)) + heat_add
        self.state["fatigue"] = self.state["heat"]
        self.state["fake_piezo_ring"] = min(1.0, duration / max_duration)
        return make_message(
            "ACK",
            self.node_id,
            {"gesture": "tap", "duration_ms": duration, "heat": self.state["heat"]},
            correlation_id,
            {"allowed": True, "status": "allowed"},
        )

    def _handle_vibrate(self, payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
        duration = int(payload.get("duration_ms", 0))
        if self.state.get("current_mode") == "quiet":
            return self._refusal("node_quiet_mode", payload, correlation_id)
        max_duration = int(self.safety.get("vibration_max_duration_ms", 2000))
        if duration <= 0:
            return self._refusal("invalid_duration", payload, correlation_id)
        if duration > max_duration:
            return self._refusal("vibration_duration_exceeded", payload, correlation_id)
        heat_add = duration * float(self.safety.get("vibration_heat_per_ms", 0.0002))
        max_heat = float(self.safety.get("max_heat", 1.0))
        if float(self.state.get("heat", 0.0)) + heat_add > max_heat:
            return self._refusal("fatigue_heat_limit", payload, correlation_id)
        self.state["heat"] = float(self.state.get("heat", 0.0)) + heat_add
        self.state["fatigue"] = self.state["heat"]
        return make_message(
            "ACK",
            self.node_id,
            {"gesture": "vibrate", "duration_ms": duration, "heat": self.state["heat"]},
            correlation_id,
            {"allowed": True, "status": "allowed"},
        )
