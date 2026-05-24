# Pico Node Placeholder

This directory is reserved for the future Raspberry Pi Pico / Pico W firmware.

Phase 0 does not connect to hardware and does not fire actuators. The firmware
work begins after the host harness can already:

- load config
- address a fake node
- send protocol messages
- log ACK and SAFETY_REFUSAL responses
- model heat, fatigue, cooldown, and refusal

The first firmware target should implement the protocol in `PROTOCOL.md` over
UART/RS485, then add local safety limits before any solenoid output is enabled.
