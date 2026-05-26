"""Config validation entrypoint for public and private broker YAML files."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, ValidationError
import yaml

from mcp_broker.config import BrokerConfig


@dataclass(frozen=True)
class ConfigValidationResult:
    config_path: Path
    schema_path: Path
    ok: bool


class ConfigValidationError(ValueError):
    """Raised when config validation fails."""


def validate_config_file(config_path: Path, schema_path: Path) -> ConfigValidationResult:
    schema = _load_json_mapping(schema_path)
    raw_config = _load_yaml_mapping(config_path)
    _validate_json_schema(raw_config, schema)
    try:
        BrokerConfig.from_file(config_path)
    except ValueError as exc:
        raise ConfigValidationError(f"loader validation failed: {exc}") from exc
    return ConfigValidationResult(config_path=config_path, schema_path=schema_path, ok=True)


def _load_json_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ConfigValidationError(f"schema file must contain valid JSON: {path}: {exc.msg}") from exc
    if not isinstance(loaded, dict):
        raise ConfigValidationError(f"schema file must contain a JSON object: {path}")
    return loaded


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"config file must contain valid YAML: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigValidationError(f"config file must contain a YAML mapping: {path}")
    return loaded


def _validate_json_schema(raw_config: dict[str, Any], schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw_config), key=_error_sort_key)
    if errors:
        joined = "; ".join(_format_schema_error(error) for error in errors)
        raise ConfigValidationError(f"schema validation failed: {joined}")


def _error_sort_key(error: ValidationError) -> tuple[list[str], str]:
    return ([str(part) for part in error.absolute_path], error.message)


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = validate_config_file(args.config, args.schema)
    except ConfigValidationError as exc:
        sys.stdout.write(f"{exc}\n")
        return 1
    sys.stdout.write(f"config validated: {result.config_path} against {result.schema_path}\n")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an mcp-broker YAML config")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
