from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

COMMAND_TYPES = {
    "PING",
    "REQUEST_STATE",
    "TAP",
    "VIBRATE",
    "QUIET",
    "SET_MODE",
    "RESET_FATIGUE",
}

RESPONSE_TYPES = {
    "PONG",
    "STATE",
    "ACK",
    "ERROR",
    "SAFETY_REFUSAL",
}

MESSAGE_TYPES = COMMAND_TYPES | RESPONSE_TYPES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def make_message(
    message_type: str,
    node_id: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    safety_status: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unknown message_type: {message_type}")
    return {
        "timestamp": timestamp or utc_now(),
        "message_type": message_type,
        "node_id": node_id,
        "correlation_id": correlation_id or new_correlation_id(),
        "payload": payload or {},
        "safety_status": safety_status or {},
    }


def serialize_message(message: dict[str, Any]) -> str:
    return json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n"


def deserialize_message(line: str) -> dict[str, Any]:
    message = json.loads(line)
    message_type = message.get("message_type")
    if message_type not in MESSAGE_TYPES:
        raise ValueError(f"unknown message_type: {message_type}")
    for key in ("timestamp", "node_id", "correlation_id", "payload"):
        if key not in message:
            raise ValueError(f"message missing required key: {key}")
    return message
