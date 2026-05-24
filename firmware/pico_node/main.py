# object-ecology — Pico W node firmware (phase 2, GPIO output capable).
#
# Reads line-delimited JSON commands from USB CDC stdin and replies with
# line-delimited JSON on stdout. Mirrors hub/fake_node.py safety semantics
# (pulse cap, cooldown, rolling duty cycle, heat ceiling, quiet mode) AND
# drives the solenoid/vibration MOSFET gates on accepted TAP/VIBRATE when
# the per-actuator enable flags below are True.
#
# DEFAULTS: SOLENOID_ENABLED and VIBRATION_ENABLED are False. A fresh
# upload of this file behaves identically to phase 1 (LED-only) so the
# wiring can be verified with a multimeter before any physical firing.
# Flip the flag(s) to True and re-upload only after the steps in WIRING.md
# have passed.

import json
import sys
import time
from machine import Pin, Timer

NODE_ID = "CAN_01"
FIRMWARE_PHASE = 2

# ----------------------------------------------------------------------------
# Pins. All actuator pins are explicitly initialized OUTPUT LOW before
# anything else, so they cannot float during boot. External 10 kΩ pulldowns
# at the MOSFET gates (see WIRING.md) belt-and-suspenders that.
# ----------------------------------------------------------------------------
LED = Pin("LED", Pin.OUT, value=0)
SOLENOID = Pin(15, Pin.OUT, value=0)
VIBRATION = Pin(14, Pin.OUT, value=0)

# ----------------------------------------------------------------------------
# Per-actuator enable flags. Default False — fresh upload is symbolic only.
# Set to True only after WIRING.md's "Pre-power checklist" has passed for
# the corresponding actuator.
# ----------------------------------------------------------------------------
SOLENOID_ENABLED = True
VIBRATION_ENABLED = False

# Mirror config/safety.yaml node_defaults. Local copy so the node can refuse
# even if the host is misconfigured or the host link is hostile.
SAFETY = {
    "max_solenoid_pulse_duration_ms": 100,
    "minimum_solenoid_cooldown_ms": 1500,
    "rolling_duty_cycle_window_seconds": 60,
    "max_rolling_on_time_ms_per_window": 1000,
    "max_heat": 1.0,
    "tap_heat_per_ms": 0.002,
    "vibration_heat_per_ms": 0.0002,
    "heat_recovery_per_second": 0.02,
    "vibration_max_duration_ms": 2000,
    # CHATTER safety: per-pulse cap is tighter than a single TAP (chatter
    # pulses are quieter), and the inter-pulse gap floor prevents the burst
    # from sounding like a buzz instead of a stutter.
    "chatter_max_pulse_ms": 30,
    "chatter_min_gap_ms": 40,
    "chatter_max_count": 8,
    "chatter_max_total_duration_ms": 800,
}

BLINK_VISIBLE_CAP_MS = 200

state = {
    "mode": "social",
    "heat": 0.0,
    "fatigue": 0.0,
    "last_tap_ticks": None,
    "last_update_ticks": time.ticks_ms(),
    "rolling": [],
}

# ----------------------------------------------------------------------------
# Hardware safety cutoff. The ISR forces _pulse_pin LOW even if Python
# execution hangs while a pulse is in flight. Set _pulse_pin before arming.
# ----------------------------------------------------------------------------
_safety_timer = Timer(-1)  # RP2 port only supports virtual timers (id=-1)
_pulse_pin = None


def _safety_cutoff(_t):
    pin = _pulse_pin
    if pin is not None:
        pin.off()


def fire_pulse(pin, duration_ms, absolute_max_ms):
    """Drive `pin` HIGH for `duration_ms`, with a hardware-enforced LOW after
    `absolute_max_ms + small margin`. Blinks the LED in parallel."""
    global _pulse_pin
    _pulse_pin = pin
    safe_duration = duration_ms
    if safe_duration > absolute_max_ms:
        safe_duration = absolute_max_ms
    cutoff_ms = absolute_max_ms + 20
    _safety_timer.init(period=cutoff_ms, mode=Timer.ONE_SHOT, callback=_safety_cutoff)
    pin.on()
    LED.on()
    try:
        time.sleep_ms(safe_duration)
    finally:
        pin.off()
        LED.off()
        try:
            _safety_timer.deinit()
        except Exception:
            pass
        _pulse_pin = None


def blink_ms(duration_ms):
    LED.on()
    capped = duration_ms if duration_ms < BLINK_VISIBLE_CAP_MS else BLINK_VISIBLE_CAP_MS
    time.sleep_ms(capped)
    LED.off()


def now_iso():
    y, mo, d, h, mi, s, _, _ = time.gmtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}+00:00".format(y, mo, d, h, mi, s)


def recover_heat():
    now = time.ticks_ms()
    elapsed_s = time.ticks_diff(now, state["last_update_ticks"]) / 1000.0
    if elapsed_s < 0:
        elapsed_s = 0.0
    state["heat"] = max(0.0, state["heat"] - SAFETY["heat_recovery_per_second"] * elapsed_s)
    state["fatigue"] = state["heat"]
    state["last_update_ticks"] = now
    window_ms = SAFETY["rolling_duty_cycle_window_seconds"] * 1000
    state["rolling"] = [
        (t0, dur) for (t0, dur) in state["rolling"]
        if time.ticks_diff(now, t0) <= window_ms
    ]


def actuator_availability():
    return {
        "solenoid_tapper": "wired" if SOLENOID_ENABLED else "symbolic_only",
        "vibration_motor": "wired" if VIBRATION_ENABLED else "symbolic_only",
    }


def state_payload():
    return {
        "online": True,
        "heat": round(state["heat"], 4),
        "fatigue": round(state["fatigue"], 4),
        "mode": state["mode"],
        "sensors": {"tof_distance_mm": None, "piezo_ring": None},
        "actuator_availability": actuator_availability(),
        "firmware_phase": FIRMWARE_PHASE,
    }


def make_response(message_type, correlation_id, payload, safety_status=None):
    return {
        "timestamp": now_iso(),
        "message_type": message_type,
        "node_id": NODE_ID,
        "correlation_id": correlation_id or "",
        "payload": payload or {},
        "safety_status": safety_status or {},
    }


def refusal(correlation_id, reason, requested):
    return make_response(
        "SAFETY_REFUSAL",
        correlation_id,
        {"reason": reason, "requested": requested, "state": state_payload()},
        {"allowed": False, "status": "refused", "reason": reason},
    )


def handle_tap(payload, correlation_id):
    recover_heat()
    if state["mode"] == "quiet":
        return refusal(correlation_id, "node_quiet_mode", payload)
    duration = int(payload.get("duration_ms", 0))
    if duration <= 0:
        return refusal(correlation_id, "invalid_duration", payload)
    if duration > SAFETY["max_solenoid_pulse_duration_ms"]:
        return refusal(correlation_id, "max_pulse_duration_exceeded", payload)
    now = time.ticks_ms()
    if state["last_tap_ticks"] is not None:
        if time.ticks_diff(now, state["last_tap_ticks"]) < SAFETY["minimum_solenoid_cooldown_ms"]:
            return refusal(correlation_id, "cooldown_active", payload)
    rolling_total = sum(d for (_, d) in state["rolling"])
    if rolling_total + duration > SAFETY["max_rolling_on_time_ms_per_window"]:
        return refusal(correlation_id, "rolling_duty_cycle_exceeded", payload)
    heat_add = duration * SAFETY["tap_heat_per_ms"]
    if state["heat"] + heat_add > SAFETY["max_heat"]:
        return refusal(correlation_id, "fatigue_heat_limit", payload)
    state["last_tap_ticks"] = now
    state["rolling"].append((now, duration))
    state["heat"] += heat_add
    state["fatigue"] = state["heat"]
    if SOLENOID_ENABLED:
        fire_pulse(SOLENOID, duration, SAFETY["max_solenoid_pulse_duration_ms"])
        actuator_mode = "wired"
    else:
        blink_ms(duration)
        actuator_mode = "symbolic_only"
    return make_response(
        "ACK", correlation_id,
        {
            "gesture": "tap",
            "duration_ms": duration,
            "heat": state["heat"],
            "actuator_mode": actuator_mode,
        },
        {"allowed": True, "status": "allowed"},
    )


def handle_chatter(payload, correlation_id):
    recover_heat()
    if state["mode"] == "quiet":
        return refusal(correlation_id, "node_quiet_mode", payload)
    count = int(payload.get("count", 4))
    pulse_ms = int(payload.get("pulse_ms", 12))
    gap_ms = int(payload.get("gap_ms", 70))
    if count <= 0 or pulse_ms <= 0:
        return refusal(correlation_id, "invalid_chatter", payload)
    if count > SAFETY["chatter_max_count"]:
        return refusal(correlation_id, "chatter_count_exceeded", payload)
    if pulse_ms > SAFETY["chatter_max_pulse_ms"]:
        return refusal(correlation_id, "chatter_pulse_exceeded", payload)
    if gap_ms < SAFETY["chatter_min_gap_ms"]:
        return refusal(correlation_id, "chatter_gap_too_short", payload)
    total_duration = count * pulse_ms + (count - 1) * gap_ms
    if total_duration > SAFETY["chatter_max_total_duration_ms"]:
        return refusal(correlation_id, "chatter_total_duration_exceeded", payload)
    total_on_time = count * pulse_ms
    rolling_total = sum(d for (_, d) in state["rolling"])
    if rolling_total + total_on_time > SAFETY["max_rolling_on_time_ms_per_window"]:
        return refusal(correlation_id, "rolling_duty_cycle_exceeded", payload)
    heat_add = total_on_time * SAFETY["tap_heat_per_ms"]
    if state["heat"] + heat_add > SAFETY["max_heat"]:
        return refusal(correlation_id, "fatigue_heat_limit", payload)
    # Cooldown check: chatter is itself a single burst, so respect inter-burst
    # cooldown the same way as TAP — don't let two chatters overlap.
    now = time.ticks_ms()
    if state["last_tap_ticks"] is not None:
        if time.ticks_diff(now, state["last_tap_ticks"]) < SAFETY["minimum_solenoid_cooldown_ms"]:
            return refusal(correlation_id, "cooldown_active", payload)
    # Execute the burst. Each pulse uses the per-pulse hardware safety timer
    # when SOLENOID_ENABLED, otherwise LED-only (symbolic) blink.
    for i in range(count):
        if SOLENOID_ENABLED:
            fire_pulse(SOLENOID, pulse_ms, SAFETY["chatter_max_pulse_ms"])
        else:
            blink_ms(pulse_ms)
        if i < count - 1:
            time.sleep_ms(gap_ms)
    end_now = time.ticks_ms()
    state["last_tap_ticks"] = end_now
    state["rolling"].append((end_now, total_on_time))
    state["heat"] += heat_add
    state["fatigue"] = state["heat"]
    return make_response(
        "ACK", correlation_id,
        {
            "gesture": "chatter",
            "count": count,
            "pulse_ms": pulse_ms,
            "gap_ms": gap_ms,
            "total_on_time_ms": total_on_time,
            "heat": state["heat"],
            "actuator_mode": "wired" if SOLENOID_ENABLED else "symbolic_only",
        },
        {"allowed": True, "status": "allowed"},
    )


def handle_vibrate(payload, correlation_id):
    recover_heat()
    if state["mode"] == "quiet":
        return refusal(correlation_id, "node_quiet_mode", payload)
    duration = int(payload.get("duration_ms", 0))
    if duration <= 0:
        return refusal(correlation_id, "invalid_duration", payload)
    if duration > SAFETY["vibration_max_duration_ms"]:
        return refusal(correlation_id, "vibration_duration_exceeded", payload)
    heat_add = duration * SAFETY["vibration_heat_per_ms"]
    if state["heat"] + heat_add > SAFETY["max_heat"]:
        return refusal(correlation_id, "fatigue_heat_limit", payload)
    state["heat"] += heat_add
    state["fatigue"] = state["heat"]
    if VIBRATION_ENABLED:
        fire_pulse(VIBRATION, duration, SAFETY["vibration_max_duration_ms"])
        actuator_mode = "wired"
    else:
        blink_ms(duration)
        actuator_mode = "symbolic_only"
    return make_response(
        "ACK", correlation_id,
        {
            "gesture": "vibrate",
            "duration_ms": duration,
            "heat": state["heat"],
            "actuator_mode": actuator_mode,
        },
        {"allowed": True, "status": "allowed"},
    )


def handle_quiet(correlation_id):
    state["mode"] = "quiet"
    # Belt-and-suspenders kill: drop both gates LOW even though pulses are
    # synchronous so QUIET only arrives between them.
    SOLENOID.off()
    VIBRATION.off()
    return make_response("ACK", correlation_id, {"mode": "quiet"})


def handle(message):
    command = message.get("message_type")
    correlation_id = message.get("correlation_id", "")
    payload = message.get("payload") or {}
    if command == "PING":
        blink_ms(40)
        return make_response("PONG", correlation_id, {"status": "online", "firmware_phase": FIRMWARE_PHASE})
    if command == "REQUEST_STATE":
        recover_heat()
        return make_response("STATE", correlation_id, state_payload())
    if command == "QUIET":
        return handle_quiet(correlation_id)
    if command == "SET_MODE":
        new_mode = str(payload.get("mode", "social"))
        if new_mode == "quiet":
            return handle_quiet(correlation_id)
        state["mode"] = new_mode
        return make_response("ACK", correlation_id, {"mode": state["mode"]})
    if command == "RESET_FATIGUE":
        state["heat"] = 0.0
        state["fatigue"] = 0.0
        state["rolling"] = []
        state["last_tap_ticks"] = None
        return make_response("ACK", correlation_id, {"heat": 0.0, "fatigue": 0.0})
    if command == "TAP":
        return handle_tap(payload, correlation_id)
    if command == "CHATTER":
        return handle_chatter(payload, correlation_id)
    if command == "VIBRATE":
        return handle_vibrate(payload, correlation_id)
    return make_response("ERROR", correlation_id, {"reason": "unsupported_command:" + str(command)})


def write_line(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")


def main():
    # Boot indicator: two short blinks for phase 2.
    for _ in range(2):
        LED.on()
        time.sleep_ms(80)
        LED.off()
        time.sleep_ms(80)
    while True:
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            try:
                write_line(make_response("ERROR", "", {"reason": "stdin_exception", "detail": str(exc)}))
            except Exception:
                pass
            continue
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle(message)
        except Exception as exc:
            response = make_response("ERROR", "", {"reason": "firmware_exception", "detail": str(exc)})
        try:
            write_line(response)
        except Exception:
            pass


main()
