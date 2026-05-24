import tempfile
import unittest
from pathlib import Path

from hub.fake_node import FakeNode
from hub.protocol import make_message


NODE = {"node_id": "CAN_01", "surface_type": "metal_can"}
SAFETY = {
    "node_defaults": {
        "max_solenoid_pulse_duration_ms": 100,
        "minimum_solenoid_cooldown_ms": 1500,
        "rolling_duty_cycle_window_seconds": 60,
        "max_rolling_on_time_ms_per_window": 1000,
        "max_heat": 1.0,
        "tap_heat_per_ms": 0.002,
        "heat_recovery_per_second": 0.0,
        "vibration_max_duration_ms": 2000,
        "vibration_heat_per_ms": 0.0002,
    }
}


class SafetyTests(unittest.TestCase):
    def test_refuses_overlong_tap(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = FakeNode(NODE, SAFETY, Path(tmp))
            response = node.handle(make_message("TAP", "CAN_01", {"duration_ms": 9999}))
            self.assertEqual(response["message_type"], "SAFETY_REFUSAL")
            self.assertEqual(response["payload"]["reason"], "max_pulse_duration_exceeded")

    def test_refuses_tap_during_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = FakeNode(NODE, SAFETY, Path(tmp))
            first = node.handle(make_message("TAP", "CAN_01", {"duration_ms": 50}))
            second = node.handle(make_message("TAP", "CAN_01", {"duration_ms": 50}))
            self.assertEqual(first["message_type"], "ACK")
            self.assertEqual(second["message_type"], "SAFETY_REFUSAL")
            self.assertEqual(second["payload"]["reason"], "cooldown_active")


if __name__ == "__main__":
    unittest.main()
