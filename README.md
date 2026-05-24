# object-ecology

`object-ecology` is the phase-0 control harness for a future networked
cybernetic actuator installation. The eventual work is a small ecology of
ordinary object-bodies with internal actuators and sensors. They are not
chatbots, pets, or responsive gadgets. The engineering model is:

```text
central room brain proposes behavior
local node verifies safety
object may refuse
refusal is logged
refusal becomes part of the artwork
```

This phase builds the boring spine only: config loading, protocol messages, a
fake node, safety budgets, append-only JSONL logs, CLI tools, and a systemd
template. It does not connect to real actuators.

## What This Phase Implements

- JSON-shaped YAML config files in `config/`
- one configured fake object node: `CAN_01`
- line-delimited JSON message protocol
- fake node simulator with persisted heat/fatigue/cooldown state
- central safety checks
- local fake-node safety refusals
- append-only `logs/events.jsonl` and `logs/health.jsonl`
- CLI tools in `tools/`
- a systemd service template in `systemd/object-ecology.service`
- unit tests for protocol, fake node behavior, and safety refusal

## What This Phase Does Not Implement

- final artwork behavior
- audio ML, speech recognition, prosody analysis, or semantic classification
- real RS485 hardware communication
- Pico firmware
- solenoid firing
- web dashboards
- databases
- Docker, Kubernetes, MQTT, OSC, Home Assistant, Ableton, or similar systems

## Install On `room-brain`

Copy this directory to the server, then on `room-brain`:

```bash
sudo mkdir -p /opt/object-ecology
sudo chown -R "$USER:$USER" /opt/object-ecology
rsync -a /path/to/object-ecology-phase0/ /opt/object-ecology/
cd /opt/object-ecology
chmod +x tools/*
```

This phase uses only the Python standard library. A virtual environment is
optional:

```bash
cd /opt/object-ecology
python3 -m venv .venv
. .venv/bin/activate
```

The config files are `.yaml`, but they are intentionally written as
JSON-shaped YAML so they can be parsed without PyYAML on a fresh server.

## CLI Tools

From `/opt/object-ecology`:

```bash
tools/scan
tools/ping-node CAN_01
tools/tap-node CAN_01 --duration-ms 50
tools/tap-node CAN_01 --duration-ms 50
tools/tap-node CAN_01 --duration-ms 9999
tools/vibrate-node CAN_01 --duration-ms 500
tools/quiet-node CAN_01
tools/monitor --iterations 3
tools/simulate-node
```

Expected behavior:

- `ping-node` prints a `PONG`.
- the first safe `tap-node` prints an `ACK` if the node is not hot, quiet, or
  cooling down.
- repeated taps too quickly print `SAFETY_REFUSAL` with `cooldown_active`.
- an overlong tap prints `SAFETY_REFUSAL` with
  `max_pulse_duration_exceeded`.

If you intentionally need a clean fake-node state during testing:

```bash
rm -f logs/fake_nodes/CAN_01.json logs/central_safety.json
```

## Logs

Command attempts are appended to:

```text
logs/events.jsonl
```

Health/state records are appended to:

```text
logs/health.jsonl
```

Each command event includes:

- timestamp
- node id
- command
- requested payload
- central safety decision
- node response type
- node response payload
- response safety status
- transport mode
- correlation id

Refusals are not errors to hide. They are first-class events.

## Protocol

Messages are line-delimited JSON so they can later be sent over serial/RS485.

Commands:

- `PING`
- `REQUEST_STATE`
- `TAP`
- `VIBRATE`
- `QUIET`
- `SET_MODE`
- `RESET_FATIGUE`

Responses:

- `PONG`
- `STATE`
- `ACK`
- `ERROR`
- `SAFETY_REFUSAL`

Every message includes:

- `timestamp`
- `message_type`
- `node_id`
- `correlation_id`
- `payload`
- `safety_status`

## Safety And Refusal

Central safety currently checks:

- emergency quiet
- total tap rate per minute
- tap rate per node per minute
- optional duration clamping

Fake-node local safety checks:

- hard max solenoid pulse duration
- minimum cooldown between taps
- rolling duty-cycle window
- heat/fatigue budget
- quiet mode

The fake node persists state between CLI invocations. This is intentional: a
node that tapped one second ago should still know it is cooling down when the
next command arrives.

## Running Tests

```bash
cd /opt/object-ecology
python3 -m unittest discover -s tests
```

## Room-Brain Loop

The main loop currently polls fake node health and logs it:

```bash
python3 -m hub.main --once
python3 -m hub.main
```

## Systemd Template

The service file is a template only. Do not enable it until manual tests pass.

Install later with:

```bash
sudo cp systemd/object-ecology.service /etc/systemd/system/object-ecology.service
sudo systemctl daemon-reload
sudo systemctl enable object-ecology.service
sudo systemctl start object-ecology.service
```

Check status:

```bash
systemctl status object-ecology.service
journalctl -u object-ecology.service -f
```

## Later Phases

Phase 1:

- real RS485 serial transport
- Pico heartbeat
- Pico command parser

Phase 2:

- one actuator command to a real solenoid through Pico/MOSFET
- local firmware safety limits

Phase 3:

- ToF sensor integration
- piezo/contact sensing

Phase 4:

- room audio/prosody analysis

Phase 5:

- multi-object ecological behavior engine

Do not proceed into real hardware without explicit confirmation.
