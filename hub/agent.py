from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from .scheduler import RoomBrain


@dataclass
class SocialAgent:
    """Phase-0 of the behavior layer: a slow, mood-driven autonomous loop for
    a single node. Polls STATE, walks a mood parameter, decides whether to
    TAP. Firmware enforces actual safety; this layer just decides whether to
    speak. Real evolutionary dynamics need multiple competing agents and
    arrive later — this is the social baseline.
    """

    brain: RoomBrain
    node_id: str
    tick_seconds: float = 10.0
    tick_jitter: float = 0.5            # ± fraction of tick_seconds
    mood: float = 0.5                   # 0=withdrawn, 1=restless
    mood_drift_sigma: float = 0.04      # per-tick gaussian random walk
    mood_floor: float = 0.05
    mood_ceiling: float = 0.95
    base_tap_probability: float = 0.10
    mood_tap_scale: float = 0.30
    duration_min_ms: int = 25
    duration_max_ms: int = 80
    heat_abstain_threshold: float = 0.5

    def _decide_tap(self) -> int | None:
        self.mood = max(
            self.mood_floor,
            min(self.mood_ceiling, self.mood + random.gauss(0, self.mood_drift_sigma)),
        )
        tap_p = self.base_tap_probability + self.mood_tap_scale * self.mood
        if random.random() > tap_p:
            return None
        return random.randint(self.duration_min_ms, self.duration_max_ms)

    def tick(self) -> dict[str, Any]:
        state_resp = self.brain.send_command(self.node_id, "REQUEST_STATE")
        state = state_resp.get("payload", {}) or {}
        heat = float(state.get("heat", 0.0) or 0.0)
        node_mode = state.get("mode", "social")

        record: dict[str, Any] = {
            "ts": time.strftime("%H:%M:%S"),
            "node": self.node_id,
            "mood": round(self.mood, 3),
            "heat": round(heat, 3),
            "node_mode": node_mode,
        }

        if node_mode == "quiet":
            record["decision"] = "abstain:node_quiet"
            return record
        if heat > self.heat_abstain_threshold:
            record["decision"] = f"abstain:heat>{self.heat_abstain_threshold}"
            return record

        duration = self._decide_tap()
        if duration is None:
            record["decision"] = "abstain:mood"
            return record

        tap_resp = self.brain.send_command(self.node_id, "TAP", {"duration_ms": duration})
        msg_type = tap_resp.get("message_type", "?")
        if msg_type == "ACK":
            record["decision"] = f"tap:{duration}ms"
        elif msg_type == "SAFETY_REFUSAL":
            reason = (tap_resp.get("payload", {}) or {}).get("reason", "?")
            record["decision"] = f"node_refused:{reason}"
        else:
            record["decision"] = f"unexpected:{msg_type}"
        return record

    def run(self, max_ticks: int | None = None) -> None:
        try:
            tick_num = 0
            while True:
                record = self.tick()
                line = "  ".join(f"{k}={v}" for k, v in record.items())
                print(line, flush=True)
                tick_num += 1
                if max_ticks is not None and tick_num >= max_ticks:
                    return
                jitter = 1.0 + random.uniform(-self.tick_jitter, self.tick_jitter)
                time.sleep(self.tick_seconds * jitter)
        except KeyboardInterrupt:
            print("\nstopping; sending QUIET as safety", flush=True)
            try:
                self.brain.send_command(self.node_id, "QUIET")
            except Exception:
                pass
