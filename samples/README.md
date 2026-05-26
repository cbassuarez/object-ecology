# samples/

Runtime data captured from the one-node proof of concept on the
`room-brain` server in May 2026. Preserved here as evidence the system
ran end-to-end on real hardware before that particular workstation was
returned (refurb defect, unrelated to the artwork).

These files are not used by the running code. They are documentation —
the artifact-record of an installation that actually worked.

## Files

- **`events.jsonl`** (612 KB, 1076 records) — every command attempt the
  host central layer logged, with the central safety decision, the
  node's response type, the response payload, the response safety
  status, the transport mode, and a correlation id. Includes both
  `ACK` and `SAFETY_REFUSAL` events; refusals carry the reason
  (`cooldown_active`, `max_pulse_duration_exceeded`,
  `rolling_duty_cycle_exceeded`, `node_quiet_mode`, etc.). The first
  half is fake-transport testing, the later half is real Pico over
  USB-CDC driving a real solenoid.

- **`health.jsonl`** (240 KB, 893 records) — periodic node state
  snapshots from `REQUEST_STATE` polls. Heat, fatigue, mode, sensor
  readings, last-seen timestamp.

- **`seeing-object.log`** (4.5 KB) — agent decision trace from one of
  the later autonomous runs. Each line records `state`, smoothed
  `dB`, rolling ambient `floor`, vigilance `Δ`, computed `thr`,
  current `mood`, circadian multiplier, `onset` flag, firmware `heat`,
  time-in-state, and the action taken (or abstained).

- **`central_safety.json`** — central rate-limiter state at the end of
  the run (recent tap events used for per-minute counting).

- **`fake_nodes/CAN_01.json`** — fake-node persisted state. The system
  ran in serial mode for most of the testing, but earlier fake-mode
  testing left this file.

- **`audio-probes/mtrack-duo-test.wav`** (1.5 MB) — raw stereo capture
  from the M-Audio M-Track Duo, used to verify the audio path before
  building presence detection on top of it. 16-bit stereo at 48 kHz,
  ~16 s. Open in any audio player.
