import tempfile
import unittest
from pathlib import Path

from hub.fake_node import FakeNode
from hub.protocol import make_message


class FakeNodeTests(unittest.TestCase):
    def test_ping_state_and_quiet(self):
        node_config = {"node_id": "CAN_01", "surface_type": "metal_can"}
        safety_config = {"node_defaults": {}}
        with tempfile.TemporaryDirectory() as tmp:
            node = FakeNode(node_config, safety_config, Path(tmp))
            pong = node.handle(make_message("PING", "CAN_01"))
            self.assertEqual(pong["message_type"], "PONG")
            quiet = node.handle(make_message("QUIET", "CAN_01"))
            self.assertEqual(quiet["message_type"], "ACK")
            state = node.handle(make_message("REQUEST_STATE", "CAN_01"))
            self.assertEqual(state["message_type"], "STATE")
            self.assertEqual(state["payload"]["mode"], "quiet")


if __name__ == "__main__":
    unittest.main()
