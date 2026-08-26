"""Small deterministic validator for the contract suite's JSON Schema subset.

Production services must use a complete draft 2020-12 implementation. This
test helper deliberately supports only the keywords used by this repository so
the trust-boundary checks run offline with the Python standard library.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


class ContractValidationError(AssertionError):
    pass


class ContractValidator:
    def __init__(self, schema_path: Path):
        self.schema_path = schema_path.resolve()
        self._documents: dict[Path, Any] = {}

    def validate(self, instance: Any) -> None:
        schema = self._load(self.schema_path)
        self._validate(instance, schema, self.schema_path, "$")

    def resolve_ref(self, ref: str, base_path: Path) -> tuple[Any, Path]:
        document_ref, separator, fragment = ref.partition("#")
        target_path = (base_path.parent / document_ref).resolve() if document_ref else base_path
        document = self._load(target_path)
        target = document
        if separator and fragment:
            if not fragment.startswith("/"):
                raise ContractValidationError(f"Unsupported JSON pointer in {ref}")
            for raw_part in fragment[1:].split("/"):
                part = unquote(raw_part).replace("~1", "/").replace("~0", "~")
                try:
                    target = target[int(part)] if isinstance(target, list) else target[part]
                except (KeyError, IndexError, ValueError, TypeError) as error:
                    raise ContractValidationError(f"Unresolvable reference {ref}") from error
        return target, target_path

    def _load(self, path: Path) -> Any:
        if path not in self._documents:
            try:
                self._documents[path] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ContractValidationError(f"Cannot load schema {path}: {error}") from error
        return self._documents[path]

    def _validate(self, value: Any, schema: Any, base_path: Path, location: str) -> None:
        if schema is True:
            return
        if schema is False:
            self._fail(location, "value is forbidden")
        if not isinstance(schema, dict):
            self._fail(location, "schema must be an object or boolean")

        if "$ref" in schema:
            target, target_path = self.resolve_ref(schema["$ref"], base_path)
            self._validate(value, target, target_path, location)

        if "not" in schema:
            try:
                self._validate(value, schema["not"], base_path, location)
            except ContractValidationError:
                pass
            else:
                self._fail(location, "value matches a forbidden schema")

        if "allOf" in schema:
            for child in schema["allOf"]:
                self._validate(value, child, base_path, location)

        if "oneOf" in schema:
            matches = 0
            for child in schema["oneOf"]:
                try:
                    self._validate(value, child, base_path, location)
                except ContractValidationError:
                    continue
                matches += 1
            if matches != 1:
                self._fail(location, f"expected exactly one matching schema, found {matches}")

        expected_type = schema.get("type")
        if expected_type is not None and not self._is_type(value, expected_type):
            self._fail(location, f"expected {expected_type}, got {type(value).__name__}")

        if "const" in schema and value != schema["const"]:
            self._fail(location, f"expected constant {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            self._fail(location, f"value {value!r} is outside the enum")

        if isinstance(value, dict):
            required = schema.get("required", [])
            missing = [name for name in required if name not in value]
            if missing:
                self._fail(location, f"missing required properties: {missing}")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                extra = sorted(set(value) - set(properties))
                if extra:
                    self._fail(location, f"additional properties are forbidden: {extra}")
            for name, child in properties.items():
                if name in value:
                    self._validate(value[name], child, base_path, f"{location}.{name}")

        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                self._fail(location, "array has too few items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                self._fail(location, "array has too many items")
            if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
                self._fail(location, "array items are not unique")
            item_schema = schema.get("items")
            if isinstance(item_schema, (dict, bool)):
                for index, item in enumerate(value):
                    self._validate(item, item_schema, base_path, f"{location}[{index}]")
            if "contains" in schema:
                matches = 0
                for item in value:
                    try:
                        self._validate(item, schema["contains"], base_path, location)
                    except ContractValidationError:
                        continue
                    matches += 1
                if matches < schema.get("minContains", 1):
                    self._fail(location, "array does not contain enough matching items")
                if "maxContains" in schema and matches > schema["maxContains"]:
                    self._fail(location, "array contains too many matching items")

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                self._fail(location, "string is too short")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                self._fail(location, "string is too long")
            if "pattern" in schema and re.search(schema["pattern"], value) is None:
                self._fail(location, f"string does not match {schema['pattern']}")
            if schema.get("format") == "date-time":
                try:
                    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as error:
                    self._fail(location, f"invalid date-time: {error}")
            if schema.get("format") == "uri" and not urlparse(value).scheme:
                self._fail(location, "URI must include a scheme")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                self._fail(location, "number is below minimum")
            if "maximum" in schema and value > schema["maximum"]:
                self._fail(location, "number is above maximum")

    @staticmethod
    def _is_type(value: Any, expected: str | list[str]) -> bool:
        if isinstance(expected, list):
            return any(ContractValidator._is_type(value, candidate) for candidate in expected)
        checks = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        return expected in checks and checks[expected](value)

    @staticmethod
    def _fail(location: str, message: str) -> None:
        raise ContractValidationError(f"{location}: {message}")
