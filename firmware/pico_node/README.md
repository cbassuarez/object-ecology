# Pico Node Firmware

MicroPython firmware for the Raspberry Pi Pico W. Speaks the line-delimited
JSON protocol described in `PROTOCOL.md` over USB CDC and mirrors the same
local safety model as the host-side fake node.

## Scope (phase 2)

- Implements every command the fake node implements: `PING`, `REQUEST_STATE`,
  `QUIET`, `SET_MODE`, `RESET_FATIGUE`, `TAP`, `VIBRATE`.
- Refuses overlong pulses, cooldown violations, rolling-duty exceedance,
  heat-ceiling violations, and any actuator command while in `quiet` mode.
- Blinks the onboard LED on accepted `PING`/`TAP`/`VIBRATE` so the physical
  reach of a command is always visible, even when no actuator is wired.
- Drives MOSFET-switched solenoid (GP15) and vibration motor (GP14) when the
  per-actuator enable flags are True. See `WIRING.md` for the circuit.
- Hardware safety cutoff: every actuator pulse is guarded by a one-shot
  `machine.Timer` ISR that forces the pin LOW after the absolute pulse cap,
  even if Python execution hangs mid-pulse.
- `QUIET` is a kill switch: immediately drops both actuator pins LOW and
  refuses subsequent `TAP`/`VIBRATE` with `node_quiet_mode`.

### Default = safe

`SOLENOID_ENABLED` and `VIBRATION_ENABLED` at the top of `main.py` default
to `False`. A fresh upload behaves identically to phase 1 (LED only). The
host sees `actuator_availability` reported as `"symbolic_only"` per actuator
and the ACK payload includes `"actuator_mode": "symbolic_only"`.

To go physical for the first time, follow `WIRING.md`'s Pre-power
checklist, then flip the relevant flag and re-upload. The state payload
will then report `"wired"` for that actuator.

`firmware_phase: 2` appears in `PONG` and `STATE` so the host can tell at a
glance which firmware is on the Pico.

## One-time setup (already done for the current Pico W)

1. Hold `BOOTSEL` while plugging the Pico into USB. It enumerates as a
   mass-storage device labeled `RPI-RP2`.
2. Copy the official MicroPython UF2 for Pico W (`RPI_PICO_W-*.uf2` from
   <https://micropython.org/download/RPI_PICO_W/>) onto the volume. The Pico
   auto-reboots into MicroPython.
3. Confirm it shows up as `/dev/ttyACM0` and the stable by-id symlink at
   `/dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_*-if00`.

## Uploading `main.py`

Install `mpremote` (one-time, in the host's venv or system-wide):

```bash
pip install mpremote
```

From the project root:

```bash
mpremote connect /dev/ttyACM0 cp firmware/pico_node/main.py :main.py
mpremote connect /dev/ttyACM0 reset
```

After reset the Pico runs `main.py` automatically on every boot. The onboard
LED blinks once briefly (~150 ms) to mark a successful boot, then the firmware
waits on stdin.

## Sanity check from the REPL

```bash
mpremote connect /dev/ttyACM0
```

`Ctrl-C` in the REPL interrupts `main.py`. From there you can inspect state
or re-import. Soft reset (`Ctrl-D`) restarts `main.py`.

In normal operation you don't poke the firmware directly — the host harness
opens the serial port and exchanges line-delimited JSON via the
`SerialTransport` in `hub/transports.py`.
