from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_structured_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"{path} is not JSON-shaped YAML and PyYAML is not installed. "
                "Keep config files in the included JSON-shaped YAML format, "
                "or install PyYAML."
            ) from exc
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a mapping")
        return data


def load_configs(root: str | Path | None = None) -> dict[str, Any]:
    root_path = Path(root) if root else PROJECT_ROOT
    return {
        "root": root_path,
        "room": load_structured_file(root_path / "config" / "room.yaml"),
        "nodes": load_structured_file(root_path / "config" / "nodes.yaml"),
        "safety": load_structured_file(root_path / "config" / "safety.yaml"),
    }


def enabled_nodes(nodes_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in nodes_config.get("nodes", []) if node.get("enabled", True)]


def get_node(nodes_config: dict[str, Any], node_id: str) -> dict[str, Any]:
    for node in enabled_nodes(nodes_config):
        if node.get("node_id") == node_id:
            return node
    raise KeyError(f"node not configured or disabled: {node_id}")


def resolve_project_path(root: Path, maybe_relative: str | Path) -> Path:
    path = Path(maybe_relative)
    return path if path.is_absolute() else root / path
