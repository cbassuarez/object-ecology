from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Optional

from .presence import PresenceDetector
from .scheduler import RoomBrain


@dataclass
class EcologicalAgent:
    """Single-object behavior loop driven by an audio presence detector.

    State machine, after the risk-disturbance / security-dilemma model:

        social   — long stretches; occasional mood-drifted taps
        vigilant — listening; rare tiny taps
        alarm    — one sharp tap on a sudden onset
        conceal  — full silence after sustained presence
        recover  — silence while heat decays back toward zero

    The host agent owns the vigilance threshold; the firmware enforces the
    actual safety budget (heat, cooldown, rolling duty). When the firmware
    refuses, the agent logs the refusal and moves on — refusal is data, not
    failure.

    Habituation: the vigilance threshold drifts. Long stretches of presence
    without sharp onsets relax it (less reactive); sharp onsets snap it
    down (more reactive). It decays back toward baseline during quiet.
    """

    brain: RoomBrain
    node_id: str
    presence: PresenceDetector

    tick_seconds: float = 2.0
    tick_jitter: float = 0.3

    # state machine
    state: str = "social"
    state_entered_at: float = field(default_factory=time.monotonic)
    above_threshold_since: Optional[float] = None

    # Ambient-relative thresholding. The "vigilance threshold" is
    #     effective_threshold_db = ambient_floor_db + delta_db
    # where ambient_floor_db is the rolling 20th-percentile of recent
    # smoothed dBFS readings (the room's actual quiet baseline, regardless
    # of mic gain), and delta_db is how much *above* that floor counts as
    # presence. delta_db habituates over time.
    db_history_size: int = 300              # ~10 min at 2 s ticks
    warmup_ticks: int = 20                  # don't react to presence until baseline settles

    delta_db_baseline: float = 10.0
    delta_db: float = 10.0
    delta_db_floor: float = 3.0
    delta_db_ceiling: float = 25.0
    delta_relax_per_tick: float = 0.2       # rises toward ceiling when calm-but-present
    delta_snap_on_onset: float = 3.0        # drops on sharp onset (more reactive)
    delta_decay_to_baseline: float = 0.15   # drifts back to baseline during quiet

    db_history: Deque[float] = field(default_factory=deque)
    tick_count: int = 0

    # social-mode parameters
    social_base_tap_p: float = 0.10
    social_mood: float = 0.5
    social_mood_drift_sigma: float = 0.015     # random walk size per tick
    social_mood_quiet_drift: float = 0.006     # directional drift toward chatty per quiet tick
    social_mood_floor: float = 0.05
    social_mood_ceiling: float = 0.95
    social_mood_onset_target: float = 0.4      # mood snaps toward this on onset
    social_mood_onset_pull: float = 0.3        # how strongly onset pulls mood
    social_mood_presence_decay: float = 0.02   # per-tick mood drop while presence sustained
    social_mood_scale: float = 0.30
    social_duration_min_ms: int = 25
    social_duration_max_ms: int = 80
    social_max_heat: float = 0.5

    # vigilant-mode parameters
    vigilant_tap_p: float = 0.03
    vigilant_duration_min_ms: int = 15
    vigilant_duration_max_ms: int = 25
    vigilant_max_heat: float = 0.3

    # alarm gesture
    alarm_duration_ms: int = 70

    # Circadian rhythm. A smooth sinusoidal multiplier on social/vigilant
    # tap probability, peaking at peak_hour and troughing 12 h opposite.
    # Alarm taps are not scaled — a sleeping animal still wakes to threat.
    circadian_peak_hour: float = 14.0
    circadian_min_multiplier: float = 0.7
    circadian_max_multiplier: float = 2.5

    # Chatter (burst of short pulses) parameters. When the agent decides
    # to "speak" in social state, it picks between a single tap and a
    # chatter burst — probability scales with mood (excited → more chatter).
    chatter_base_p: float = 0.25                # baseline chatter share at mood=0
    chatter_mood_scale: float = 0.30            # added share at full mood
    chatter_count_min: int = 3
    chatter_count_max: int = 6
    chatter_pulse_ms_min: int = 8
    chatter_pulse_ms_max: int = 16
    chatter_gap_ms_min: int = 50
    chatter_gap_ms_max: int = 90

    # Self-noise blanking: how long after firing our own actuator we ignore
    # incoming audio (so the click doesn't trip the onset detector and feed
    # back into alarm). Long enough to cover the pulse + a comfortable margin
    # of room decay.
    self_tap_blank_seconds: float = 1.0

    # state durations / heat targets
    seconds_present_before_conceal: float = 12.0
    seconds_absent_before_recover: float = 8.0
    seconds_in_vigilant_before_relax: float = 5.0
    recover_until_heat: float = 0.1

    # ---- helpers --------------------------------------------------------

    def _transition(self, new_state: str) -> None:
        self.state = new_state
        self.state_entered_at = time.monotonic()

    def _send_tap(self, duration_ms: int) -> tuple[str, dict[str, Any]]:
        # Blank the presence detector before issuing the command so the
        # click of our own solenoid doesn't trip an onset and feed back.
        self.presence.blank_for(self.self_tap_blank_seconds)
        resp = self.brain.send_command(self.node_id, "TAP", {"duration_ms": duration_ms})
        return resp.get("message_type", "?"), resp.get("payload", {}) or {}

    def _send_chatter(self, count: int, pulse_ms: int, gap_ms: int) -> tuple[str, dict[str, Any]]:
        # Total burst duration plus a comfortable margin of room decay.
        total_ms = count * pulse_ms + (count - 1) * gap_ms
        self.presence.blank_for((total_ms + 500) / 1000.0)
        resp = self.brain.send_command(
            self.node_id, "CHATTER",
            {"count": count, "pulse_ms": pulse_ms, "gap_ms": gap_ms},
        )
        return resp.get("message_type", "?"), resp.get("payload", {}) or {}

    def _pick_chatter_pattern(self) -> tuple[int, int, int]:
        count = random.randint(self.chatter_count_min, self.chatter_count_max)
        pulse_ms = random.randint(self.chatter_pulse_ms_min, self.chatter_pulse_ms_max)
        gap_ms = random.randint(self.chatter_gap_ms_min, self.chatter_gap_ms_max)
        return count, pulse_ms, gap_ms

    def _speak_social(self) -> str:
        """Decide single-tap vs chatter and fire it. Returns the action label
        for the trace, including the refusal reason if the node refused."""
        chatter_p = self.chatter_base_p + self.chatter_mood_scale * self.social_mood
        if random.random() < chatter_p:
            count, pulse_ms, gap_ms = self._pick_chatter_pattern()
            msg_type, payload = self._send_chatter(count, pulse_ms, gap_ms)
            tag = f"chatter:{count}x{pulse_ms}ms/{gap_ms}ms"
        else:
            duration = random.randint(self.social_duration_min_ms, self.social_duration_max_ms)
            msg_type, payload = self._send_tap(duration)
            tag = f"social_tap:{duration}ms"
        if msg_type == "SAFETY_REFUSAL":
            reason = payload.get("reason", "?")
            return f"{tag}:refused:{reason}"
        return f"{tag}:{msg_type}"

    def _ambient_floor_db(self) -> float:
        if len(self.db_history) < 10:
            return -60.0
        sorted_h = sorted(self.db_history)
        return sorted_h[len(sorted_h) // 5]  # 20th percentile

    def _circadian_multiplier(self) -> float:
        now = datetime.now()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        phase = 2.0 * math.pi * (hour - self.circadian_peak_hour) / 24.0
        norm = (1.0 + math.cos(phase)) / 2.0  # 1 at peak, 0 at trough
        return self.circadian_min_multiplier + (
            self.circadian_max_multiplier - self.circadian_min_multiplier
        ) * norm

    def _update_mood(self, snap, is_present: bool) -> None:
        """Mood drifts toward chatty (ceiling) in quiet, gets chastened by
        onsets, and decays under sustained presence. The directional bias is
        what makes the object 'wake up' the longer it's left alone."""
        if snap.onset:
            target = self.social_mood_onset_target
            self.social_mood += self.social_mood_onset_pull * (target - self.social_mood)
        elif is_present:
            self.social_mood = max(self.social_mood_floor,
                                   self.social_mood - self.social_mood_presence_decay)
        else:
            drift = self.social_mood_quiet_drift + random.gauss(0, self.social_mood_drift_sigma)
            self.social_mood = min(self.social_mood_ceiling,
                                   max(self.social_mood_floor, self.social_mood + drift))

    def _update_delta(self, snap, is_present: bool) -> None:
        # Onset always snaps delta down — closer to floor, more reactive.
        if snap.onset:
            self.delta_db = max(
                self.delta_db_floor,
                self.delta_db - self.delta_snap_on_onset,
            )
            return
        # Sustained presence without onset relaxes (less reactive).
        if is_present:
            self.delta_db = min(
                self.delta_db_ceiling,
                self.delta_db + self.delta_relax_per_tick,
            )
        else:
            # Quiet: drift back toward baseline.
            if self.delta_db < self.delta_db_baseline:
                self.delta_db = min(self.delta_db_baseline,
                                    self.delta_db + self.delta_decay_to_baseline)
            elif self.delta_db > self.delta_db_baseline:
                self.delta_db = max(self.delta_db_baseline,
                                    self.delta_db - self.delta_decay_to_baseline)

    # ---- main loop ------------------------------------------------------

    def tick(self) -> dict[str, Any]:
        snap = self.presence.snapshot()
        state_resp = self.brain.send_command(self.node_id, "REQUEST_STATE")
        state_payload = state_resp.get("payload", {}) or {}
        heat = float(state_payload.get("heat", 0.0) or 0.0)
        node_mode = state_payload.get("mode", "social")
        now = time.monotonic()
        time_in_state = now - self.state_entered_at

        # Update the ambient-floor estimate (rolling 20th-percentile of
        # smoothed dBFS). Don't react to "presence" until enough samples
        # have accumulated for the floor to be meaningful.
        if len(self.db_history) >= self.db_history_size:
            self.db_history.popleft()
        self.db_history.append(snap.smoothed_db)
        self.tick_count += 1
        ambient_floor = self._ambient_floor_db()
        effective_threshold = ambient_floor + self.delta_db

        if self.tick_count < self.warmup_ticks:
            is_present = False
        else:
            is_present = snap.smoothed_db > effective_threshold

        if is_present:
            if self.above_threshold_since is None:
                self.above_threshold_since = now
        else:
            self.above_threshold_since = None
        seconds_present = (now - self.above_threshold_since) if self.above_threshold_since else 0.0

        self._update_delta(snap, is_present)

        # Update mood every tick so the directional bias accumulates regardless
        # of state. Bias: drifts up while quiet, retreats on onset/presence.
        self._update_mood(snap, is_present)

        circ = self._circadian_multiplier()

        record: dict[str, Any] = {
            "ts": time.strftime("%H:%M:%S"),
            "state": self.state,
            "dB": round(snap.smoothed_db, 1),
            "floor": round(ambient_floor, 1),
            "Δ": round(self.delta_db, 1),
            "thr": round(effective_threshold, 1),
            "mood": round(self.social_mood, 2),
            "circ": round(circ, 2),
            "onset": snap.onset,
            "heat": round(heat, 3),
            "t_in_state": round(time_in_state, 1),
        }
        action = "wait"

        # During warmup the ambient-floor estimate is still unreliable.
        # Hold state in social and never fire alarms — but mood-driven taps
        # are fine; they don't depend on presence sensing.
        if self.tick_count < self.warmup_ticks:
            tap_p = (self.social_base_tap_p + self.social_mood_scale * self.social_mood) * circ
            if heat <= self.social_max_heat and random.random() < tap_p:
                record["action"] = "warmup_" + self._speak_social()
            else:
                record["action"] = "warmup"
            return record

        # PRIORITY: a sharp onset interrupts to alarm (unless already silenced).
        if snap.onset and self.state in ("social", "vigilant"):
            self._transition("alarm")
            msg_type, _ = self._send_tap(self.alarm_duration_ms)
            action = f"alarm_tap:{self.alarm_duration_ms}ms:{msg_type}"
            record["action"] = action
            return record

        if self.state == "social":
            if is_present and seconds_present > 1.0:
                self._transition("vigilant")
                action = "→vigilant"
            elif heat > self.social_max_heat:
                action = f"abstain:heat>{self.social_max_heat}"
            else:
                tap_p = (self.social_base_tap_p + self.social_mood_scale * self.social_mood) * circ
                if random.random() < tap_p:
                    action = self._speak_social()
                else:
                    action = "abstain:mood"

        elif self.state == "vigilant":
            if seconds_present > self.seconds_present_before_conceal:
                self._transition("conceal")
                action = "→conceal"
            elif not is_present and time_in_state > self.seconds_in_vigilant_before_relax:
                if heat > 0.3:
                    self._transition("recover")
                    action = "→recover"
                else:
                    self._transition("social")
                    action = "→social"
            elif heat < self.vigilant_max_heat and random.random() < self.vigilant_tap_p * circ:
                duration = random.randint(self.vigilant_duration_min_ms, self.vigilant_duration_max_ms)
                msg_type, _ = self._send_tap(duration)
                action = f"vigilant_tap:{duration}ms:{msg_type}"
            else:
                action = "listening"

        elif self.state == "alarm":
            self._transition("vigilant")
            action = "→vigilant (post-alarm)"

        elif self.state == "conceal":
            if not is_present and time_in_state > self.seconds_absent_before_recover:
                self._transition("recover")
                action = "→recover"
            else:
                action = "silent"

        elif self.state == "recover":
            if heat < self.recover_until_heat:
                self._transition("social")
                action = "→social"
            else:
                action = f"cooling:heat={heat:.2f}"

        if node_mode == "quiet":
            action = f"node_quiet({action})"

        record["action"] = action
        return record

    def run(self, max_ticks: Optional[int] = None) -> None:
        self.presence.start()
        # Brief settle so the smoothed dBFS reflects real ambient before the
        # first decision.
        time.sleep(0.8)
        # Wake the node from any previous quiet and start with a clean heat
        # budget. The firmware's heat model is pure software state; resetting
        # it is fine on host-side startup.
        try:
            self.brain.send_command(self.node_id, "SET_MODE", {"mode": "social"})
            self.brain.send_command(self.node_id, "RESET_FATIGUE")
        except Exception:
            pass
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
        finally:
            self.presence.stop()
