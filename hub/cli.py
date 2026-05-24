from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import enabled_nodes, load_configs
from .scheduler import RoomBrain
from .transports import list_serial_ports


def _root_from_tool() -> Path:
    return Path(__file__).resolve().parents[1]


def _print_response(response: dict) -> None:
    print(json.dumps(response, indent=2, sort_keys=True))


def main(tool_name: str | None = None) -> int:
    tool = tool_name or Path(sys.argv[0]).name
    parser = argparse.ArgumentParser(prog=tool)
    parser.add_argument("--root", default=str(_root_from_tool()), help="Project root")

    if tool in {"ping-node", "quiet-node"}:
        parser.add_argument("node_id")
    elif tool == "tap-node":
        parser.add_argument("node_id")
        parser.add_argument("--duration-ms", type=int, required=True)
    elif tool == "vibrate-node":
        parser.add_argument("node_id")
        parser.add_argument("--duration-ms", type=int, required=True)
    elif tool == "monitor":
        parser.add_argument("--iterations", type=int, default=5)
        parser.add_argument("--interval", type=float, default=1.0)
    elif tool in {"scan", "simulate-node"}:
        pass
    else:
        parser.error(f"unsupported tool name: {tool}")

    args = parser.parse_args()

    if tool == "scan":
        configs = load_configs(args.root)
        print(f"room_id: {configs['room'].get('room_id')}")
        print(f"transport_mode: {configs['room']['transport'].get('mode')}")
        print("nodes:")
        for node in enabled_nodes(configs["nodes"]):
            print(f"  - {node['node_id']} ({node.get('surface_type')}, channel={node.get('transport_channel')})")
        ports = list_serial_ports()
        print("serial_ports:")
        if ports:
            for port in ports:
                print(f"  - {port}")
        else:
            print("  - none found or pyserial not installed")
        return 0

    brain = RoomBrain(args.root)

    if tool == "ping-node":
        _print_response(brain.send_command(args.node_id, "PING"))
    elif tool == "quiet-node":
        _print_response(brain.send_command(args.node_id, "QUIET"))
    elif tool == "tap-node":
        _print_response(brain.send_command(args.node_id, "TAP", {"duration_ms": args.duration_ms}))
    elif tool == "vibrate-node":
        _print_response(brain.send_command(args.node_id, "VIBRATE", {"duration_ms": args.duration_ms}))
    elif tool == "monitor":
        for _ in range(args.iterations):
            for response in brain.poll_health():
                _print_response(response)
            time.sleep(args.interval)
    elif tool == "simulate-node":
        print("fake-node demo: ping, state, tap, immediate repeated tap")
        _print_response(brain.send_command("CAN_01", "PING"))
        _print_response(brain.send_command("CAN_01", "REQUEST_STATE"))
        _print_response(brain.send_command("CAN_01", "TAP", {"duration_ms": 50}))
        _print_response(brain.send_command("CAN_01", "TAP", {"duration_ms": 50}))
    return 0
