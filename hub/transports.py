from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import enabled_nodes, resolve_project_path
from .fake_node import FakeNode


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
        self.configs = configs
        self.serial_config = configs["room"]["transport"]["serial"]

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("serial transport is a phase-1 placeholder")


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
