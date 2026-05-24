from __future__ import annotations

from typing import Any

from .config import enabled_nodes, resolve_project_path
from .fake_node import FakeNode
from .protocol import deserialize_message, make_message, serialize_message


class FakeTransport:
    name = "fake"

    def __init__(self, configs: dict[str, Any]):
        root = configs["root"]
        room = configs["room"]
        state_dir = resolve_project_path(root, room["logs"]["fake_state_dir"])
        self.nodes = {
            node["node_id"]: FakeNode(node, configs["safety"], state_dir)
            for node in enabled_nodes(configs["nodes"])
            if node.get("transport_channel", "fake") == "fake"
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        node_id = message["node_id"]
        if node_id not in self.nodes:
            raise KeyError(f"node not available on fake transport: {node_id}")
        return self.nodes[node_id].handle(message)


class SerialTransport:
    name = "serial"

    def __init__(self, configs: dict[str, Any]):
        try:
            import serial as pyserial  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Serial transport requires pyserial. "
                "Install with: pip install -r requirements.txt"
            ) from exc
        self._pyserial = pyserial
        room_serial = configs["room"]["transport"].get("serial") or {}
        self.default_device = room_serial.get("device")
        self.baud = int(room_serial.get("baud", 115200))
        self.timeout = float(room_serial.get("timeout", 1.0))
        self.connections: dict[str, Any] = {}
        for node in enabled_nodes(configs["nodes"]):
            if node.get("transport_channel", "fake") != "serial":
                continue
            device = node.get("serial_device") or self.default_device
            if not device:
                raise ValueError(
                    f"node {node['node_id']} uses transport_channel=serial but no "
                    "device path is configured (set room.transport.serial.device "
                    "or per-node serial_device)"
                )
            self.connections[node["node_id"]] = self._open(device)

    def _open(self, device: str):
        return self._pyserial.Serial(
            device,
            baudrate=self.baud,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        node_id = message["node_id"]
        if node_id not in self.connections:
            raise KeyError(f"node not available on serial transport: {node_id}")
        conn = self.connections[node_id]
        correlation_id = message.get("correlation_id")
        try:
            conn.reset_input_buffer()
        except Exception:
            pass
        line = serialize_message(message).encode("utf-8")
        try:
            conn.write(line)
            conn.flush()
            raw = conn.readline()
        except Exception as exc:
            return make_message(
                "ERROR",
                node_id,
                {"reason": "serial_io_failure", "detail": str(exc)},
                correlation_id=correlation_id,
            )
        if not raw:
            return make_message(
                "ERROR",
                node_id,
                {"reason": "serial_timeout"},
                correlation_id=correlation_id,
            )
        try:
            return deserialize_message(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            return make_message(
                "ERROR",
                node_id,
                {
                    "reason": "serial_response_parse_failure",
                    "detail": str(exc),
                    "raw": raw[:200].decode("utf-8", errors="replace"),
                },
                correlation_id=correlation_id,
            )


def make_transport(configs: dict[str, Any]):
    mode = configs["room"]["transport"].get("mode", "fake")
    if mode == "fake":
        return FakeTransport(configs)
    if mode == "serial":
        return SerialTransport(configs)
    raise ValueError(f"unknown transport mode: {mode}")


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        return []
    return [port.device for port in list_ports.comports()]
