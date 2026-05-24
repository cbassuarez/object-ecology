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

The fake transport runs on the Python standard library alone. The serial
transport (a real Pico over USB CDC) needs `pyserial`, and the firmware
upload flow uses `mpremote`. Both are pinned in `requirements.txt`:

```bash
cd /opt/object-ecology
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

You can skip the install entirely while you're only exercising the fake
transport — `import serial` is lazy and only happens when
`room.transport.mode = "serial"`.

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

The main loop currently polls node health and logs it:

```bash
python3 -m hub.main --once
python3 -m hub.main
```

It works against either transport — fake or serial — depending on
`room.transport.mode`.

## Talking To A Real Pico (phase 1)

Phase-1 firmware is in `firmware/pico_node/`. It mirrors the fake node's
safety model and blinks the onboard LED on accepted commands, but drives
no other GPIO yet — see `firmware/pico_node/README.md` for the full scope.

One-time wiring:

1. Flash MicroPython onto the Pico W (see firmware README).
2. Upload the firmware:

   ```bash
   mpremote connect /dev/ttyACM0 cp firmware/pico_node/main.py :main.py
   mpremote connect /dev/ttyACM0 reset
   ```

3. Point the node at the serial transport. In `config/room.yaml`:

   ```json
   "transport": {
     "mode": "serial",
     "serial": {
       "device": "/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_<serial>-if00",
       "baud": 115200,
       "timeout": 1.0
     }
   }
   ```

   And in `config/nodes.yaml`, flip the matching node:
   `"transport_channel": "serial"`. The by-id path is preferred over
   `/dev/ttyACM0` because it survives replug and other ACM devices.

4. Run the usual CLI:

   ```bash
   tools/ping-node CAN_01      # Pico LED flashes, host gets PONG
   tools/tap-node CAN_01 --duration-ms 50
   tools/tap-node CAN_01 --duration-ms 50    # cooldown_active
   tools/tap-node CAN_01 --duration-ms 9999  # max_pulse_duration_exceeded
   ```

If the Pico is unplugged or unresponsive, the host receives a synthetic
`ERROR` with `reason` `serial_timeout` or `serial_io_failure` and the
room-brain loop keeps going.

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

Phase 1 (done — USB-CDC):

- USB-CDC serial transport (`SerialTransport` in `hub/transports.py`)
- Pico W MicroPython firmware that parses the protocol and refuses unsafe
  commands locally (`firmware/pico_node/main.py`)
- real RS485 serial transport for multi-node bus topology — deferred

Phase 2 (in progress — first real actuator):

- GPIO output from Pico to MOSFET-switched solenoid and vibration motor
- hardware-`Timer`-enforced absolute pulse cutoff so the gate goes LOW even
  if Python execution hangs mid-pulse
- wiring spec at `firmware/pico_node/WIRING.md` (Heschen HS-0530B 24 V
  solenoid + small ERM, separate 24 V rail, common ground, flyback diodes,
  1.5 A inline fuse, 10 kΩ gate pulldowns)
- `SOLENOID_ENABLED` / `VIBRATION_ENABLED` constants default to False —
  fresh upload behaves identically to phase 1 (LED only). Flip the flag and
  re-upload only after the WIRING.md pre-power checklist passes.

Phase 3:

- ToF sensor integration
- piezo/contact sensing

Phase 4:

- room audio/prosody analysis

Phase 5:

- multi-object ecological behavior engine

Do not proceed into real hardware without explicit confirmation.
