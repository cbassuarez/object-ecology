import unittest

from hub.protocol import deserialize_message, make_message, serialize_message


class ProtocolTests(unittest.TestCase):
    def test_round_trip_line_delimited_json(self):
        message = make_message("PING", "CAN_01", {"hello": "body"})
        encoded = serialize_message(message)
        self.assertTrue(encoded.endswith("\n"))
        decoded = deserialize_message(encoded)
        self.assertEqual(decoded["message_type"], "PING")
        self.assertEqual(decoded["node_id"], "CAN_01")
        self.assertEqual(decoded["payload"]["hello"], "body")


if __name__ == "__main__":
    unittest.main()
