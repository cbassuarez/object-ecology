# Pico Node Wiring — Phase 2 (one solenoid + one vibration motor)

This is the wiring spec for the first physical-actuator build of `CAN_01`.
It is the contract the firmware in `main.py` is written against — change
either side and the other side has to be updated too.

The artwork's stance is that the local node refuses unsafe behavior. The
wiring must make refusal mechanically possible: gates pulled low on boot,
flyback diodes catching coil collapse, a fuse to cut the rail if a MOSFET
fails short, common ground so refusals propagate cleanly.

## Pin map (Pico W)

| Pico pin | GP# | Direction | Use |
|---|---|---|---|
| 17 | GP13 | reserved | (future: thermistor ADC) |
| 19 | GP14 | OUTPUT | Vibration-motor MOSFET gate |
| 20 | GP15 | OUTPUT | Solenoid MOSFET gate |
| 38 | GND | — | Common ground tie point |
| LED | — | OUTPUT | Onboard visible heartbeat |

Both gate pins boot LOW (the firmware sets `Pin(..., Pin.OUT, value=0)`
before anything else). External pulldowns belt-and-suspenders that.

## Solenoid circuit — Heschen HS-0530B, 24 V, 0.84 A, ED%=5 %

The 24 V supply is **separate** from the Pico's USB power. Pico is powered
from the host USB; the solenoid is powered from a dedicated 24 V brick. The
only shared wire between the two domains is ground.

```
                       24 V +
                         │
                  ┌──────┴──────┐
                  │   solenoid   │      flyback diode
                  │     coil     │◄─── 1N4007 (cathode to 24 V+, anode to drain)
                  └──────┬──────┘
                         │ drain
                       ┌─┴─┐
                       │ M │   logic-level N-channel MOSFET
                       │ O │   (IRLZ44N / IRLB8721 / equiv)
                       │ S │   gate threshold < 2 V
                       └─┬─┘
                         │ source
                         │
                ┌────────┴────────┐
                │   GND  (shared) │
                └─────────────────┘
                         ▲
                         │
                  Pico GND (pin 38)


Pico GP15 ─── 100 Ω ──┬──── MOSFET gate
                      │
                    10 kΩ
                      │
                     GND
```

**Mandatory parts:**

- Flyback diode (1N4007 or 1N5819) across the solenoid coil, cathode to
  24 V+. Without it, the inductive kick when the gate turns off can
  destroy the MOSFET on the very first pulse.
- 10 kΩ gate pulldown gate-to-source. Holds the gate at 0 V while the Pico
  is booting, resetting, or unpowered. Without it the gate floats and the
  solenoid can self-energize briefly at power-on.
- 100 Ω series resistor between Pico GP15 and the MOSFET gate. Limits
  inrush during the gate-charge transition, protects the GPIO pad.
- Inline fuse on the 24 V+ rail, **1.5 A slow-blow**. Heschen draws ~0.84 A
  steady; a stuck-on MOSFET would otherwise burn the coil indefinitely.
- Common ground between the 24 V brick GND, MOSFET source, and Pico GND.

**Do not:**

- Power the solenoid from Pico's `VBUS`, `VSYS`, or `3V3` rails. Pico's
  regulator and the host USB port cannot sustain ~20 W and the Pico will
  reset under load.
- Use a MOSFET that isn't logic-level. IRF520, despite being everywhere
  online, has a gate threshold around 4 V and will not fully turn on from
  the Pico's 3.3 V GPIO — it'll get hot and burn out.
- Skip the flyback diode "for the first test." The first test is exactly
  when you find out you needed it.

## Vibration-motor circuit — small ERM, ~3 V, ~70 mA

Same shape as the solenoid circuit, smaller. The motor is also inductive,
so it still gets a flyback diode — just a smaller one.

- V+ rail: 3.3 V from Pico `3V3 (out)` pin 36 is acceptable (ERM draws
  under the Pico regulator's ~300 mA ceiling). For a larger motor or
  multiple motors, switch to an external 3 V supply.
- N-channel logic-level MOSFET, gate from GP14 via 100 Ω, 10 kΩ pulldown.
- Flyback diode 1N4148 across the motor (cathode to V+, anode to drain).
- No separate fuse — the Pico's 3V3 regulator self-limits.

## Pre-power checklist

Before applying 24 V the very first time:

1. **Multimeter, gate side.** With the Pico powered and firmware uploaded
   *with `SOLENOID_ENABLED=False`*, run `tools/tap-node CAN_01 --duration-ms 50`
   and verify GP15 stays LOW. The onboard LED should still blink.
2. **Flip the constant.** Edit `SOLENOID_ENABLED=True` in `main.py`, re-upload.
3. **Multimeter, gate side again.** Run `tap-node`. GP15 should briefly read
   ~3.3 V for ~50 ms. If you can capture it on a scope, you should see a
   clean square-ish edge.
4. **Continuity check, load side.** With the rail still off: confirm
   solenoid+/–, MOSFET drain/source, fuse, and ground tie are all where the
   diagram says they are. Confirm the flyback diode's cathode bar is toward
   the 24 V+ rail (cathode = the side with the stripe).
5. **First firing, conservative.** Apply 24 V through the fuse. Run a
   single `tap-node CAN_01 --duration-ms 20`. Listen. Watch the fuse and
   the coil temperature with the back of your hand (briefly). Wait at
   least 5 seconds before repeating.
6. **Ramp up.** Move to 30 ms, then 50 ms, then 80 ms over several minutes,
   pausing to feel the coil between tests. Stop and investigate if the
   coil gets hot to the touch — the firmware's heat model should refuse
   well before that, but trust your hand over the model.

## Emergency stop

Three independent kills, in order of speed:

1. `tools/quiet-node CAN_01` — host tells firmware `QUIET`. Firmware drops
   both actuator pins LOW immediately and refuses subsequent TAP/VIBRATE
   with `node_quiet_mode`.
2. Unplug the 24 V brick. Cuts the load rail. Pico keeps running.
3. Unplug the Pico USB. Both gate pulldowns clamp the MOSFET off; nothing
   energized.

## Once it's working

- Bump the per-node `actuators` list in `config/nodes.yaml` only after
  you've verified each one mechanically.
- Mount the solenoid to strike through felt/rubber/wood (per the design
  notebook) before tuning pulse width up — the mechanical interface is the
  instrument.
- Phase 3 adds the thermistor on GP13's ADC so the object can actually
  know its own coil temperature, not just estimate it.
