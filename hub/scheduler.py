from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import enabled_nodes, get_node, load_configs, resolve_project_path
from .logger import JsonlLogger
from .protocol import make_message
from .safety import CentralSafety
from .transports import make_transport


class RoomBrain:
    def __init__(self, root: str | Path | None = None):
        self.configs = load_configs(root)
        self.root: Path = self.configs["root"]
        room = self.configs["room"]
        self.logger = JsonlLogger(
            resolve_project_path(self.root, room["logs"]["events"]),
            resolve_project_path(self.root, room["logs"]["health"]),
        )
        self.safety = CentralSafety(
            room,
            self.configs["safety"],
            resolve_project_path(self.root, room["logs"]["central_safety_state"]),
        )
        self.transport = make_transport(self.configs)

    def send_command(self, node_id: str, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        get_node(self.configs["nodes"], node_id)
        decision = self.safety.check_command(node_id, command, payload)
        command_payload = decision.payload if decision.payload is not None else payload
        message = make_message(
            command,
            node_id,
            command_payload,
            safety_status=decision.as_dict(),
        )

        if not decision.allowed:
            response = make_message(
                "SAFETY_REFUSAL",
                node_id,
                {"reason": decision.reason, "requested": payload},
                message["correlation_id"],
                decision.as_dict(),
            )
        else:
            response = self.transport.send(message)

        self.safety.record_response(node_id, command, response["message_type"], response.get("payload", {}))
        self._log_event(message, response, decision)
        if response["message_type"] == "STATE":
            self._log_health(response)
        return response

    def poll_health(self) -> list[dict[str, Any]]:
        responses = []
        for node in enabled_nodes(self.configs["nodes"]):
            response = self.send_command(node["node_id"], "REQUEST_STATE", {})
            responses.append(response)
        return responses

    def _log_event(self, message: dict[str, Any], response: dict[str, Any], decision) -> None:
        self.logger.event(
            {
                "node_id": message["node_id"],
                "command": message["message_type"],
                "requested_payload": message.get("payload", {}),
                "central_safety": decision.as_dict(),
                "node_response_type": response["message_type"],
                "node_response_payload": response.get("payload", {}),
                "response_safety": response.get("safety_status", {}),
                "transport_mode": self.configs["room"]["transport"].get("mode", "fake"),
                "correlation_id": message["correlation_id"],
            }
        )

    def _log_health(self, response: dict[str, Any]) -> None:
        payload = response.get("payload", {})
        self.logger.health(
            {
                "node_id": response["node_id"],
                "online": payload.get("online"),
                "fatigue": payload.get("fatigue"),
                "heat": payload.get("heat"),
                "mode": payload.get("mode"),
                "last_seen": payload.get("last_seen"),
                "sensor_summary": payload.get("sensors", {}),
                "correlation_id": response["correlation_id"],
            }
        )
