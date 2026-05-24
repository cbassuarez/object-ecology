# Object Node Protocol

Messages are line-delimited JSON. Each line is one object.

Required fields:

- `timestamp`
- `message_type`
- `node_id`
- `correlation_id`
- `payload`
- `safety_status`

Initial commands:

- `PING`
- `REQUEST_STATE`
- `TAP`
- `CHATTER`
- `VIBRATE`
- `QUIET`
- `SET_MODE`
- `RESET_FATIGUE`

`CHATTER` payload: `{"count": N, "pulse_ms": P, "gap_ms": G}`. Fires a
burst of `N` short pulses with `G` ms of silence between each. Per-pulse
duration is capped tighter than a single `TAP` (so chatter is mechanically
quieter), and the total burst duration is bounded so the firmware response
arrives within serial timeout. Burst is atomic — the firmware validates
the whole pattern before firing the first pulse.

Initial responses:

- `PONG`
- `STATE`
- `ACK`
- `ERROR`
- `SAFETY_REFUSAL`

Important rule: real node firmware must enforce local safety before acknowledging
actuator commands. The room brain can propose behavior, but the object may
refuse.
