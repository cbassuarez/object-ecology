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
- `VIBRATE`
- `QUIET`
- `SET_MODE`
- `RESET_FATIGUE`

Initial responses:

- `PONG`
- `STATE`
- `ACK`
- `ERROR`
- `SAFETY_REFUSAL`

Important rule: real node firmware must enforce local safety before acknowledging
actuator commands. The room brain can propose behavior, but the object may
refuse.
