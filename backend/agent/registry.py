"""Typed tool contracts and explicit capability profiles, without execution policy."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel

ToolAccess = Literal["read", "state", "write", "proposal"]
ToolHandler = Callable[[Any], Awaitable[dict]]
TOOL_MODES = ("outline", "study", "review")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[BaseModel]
    modes: tuple[str, ...] = TOOL_MODES
    group: str = "interaction"
    access: ToolAccess = "read"
    replay_safe: bool = False
    timeout_seconds: float = 60
    handler: ToolHandler | None = None

    def __post_init__(self):
        if not self.name or not self.description:
            raise ValueError("Tool name and description are required.")
        if not issubclass(self.arguments, BaseModel):
            raise TypeError("Tool arguments must be a Pydantic model.")
        if not self.modes or set(self.modes) - set(TOOL_MODES):
            raise ValueError("Unknown or empty tool modes.")
        if self.access not in {"read", "state", "write", "proposal"}:
            raise ValueError("Unknown tool access category.")
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be finite and positive.")

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments.model_json_schema(),
            },
        }

    def describe(self):
        """Public developer metadata: never serialize the callable or runtime config."""
        return {
            "name": self.name,
            "description": self.description,
            "group": self.group,
            "access": self.access,
            "replay_safe": self.replay_safe,
            "timeout_seconds": self.timeout_seconds,
            "modes": list(self.modes),
            "parameters": self.arguments.model_json_schema(),
        }


class ToolRegistry:
    def __init__(
        self,
        definitions: Iterable[ToolDefinition],
        profiles: Mapping[str, Iterable[str]],
    ):
        self._tools: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in self._tools:
                raise ValueError(f"Duplicate tool name: {definition.name}")
            if not callable(definition.handler):
                raise ValueError(f"Tool handler is required: {definition.name}")
            self._tools[definition.name] = definition
        self._profiles = {}
        for profile, names in profiles.items():
            if profile not in {"tutor", "qa", "research", "planner", "solve"}:
                raise ValueError(f"Unknown capability profile: {profile}")
            allowed = frozenset(names)
            unknown = allowed - self._tools.keys()
            if unknown:
                raise ValueError(f"Profile {profile} references unknown tools: {sorted(unknown)}")
            self._profiles[profile] = allowed

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def allowed_names(self, profile: str = "tutor") -> frozenset[str]:
        if profile not in self._profiles:
            raise ValueError(f"Unknown capability profile: {profile}")
        return self._profiles[profile]

    def schemas(self, profile: str = "tutor") -> list[dict]:
        # Keep all modes mounted within a profile so set_mode can act in-turn.
        allowed = self.allowed_names(profile)
        return [tool.schema() for name, tool in self._tools.items() if name in allowed]

    def describe(self, profile: str = "tutor") -> list[dict]:
        allowed = self.allowed_names(profile)
        return [tool.describe() for name, tool in self._tools.items() if name in allowed]
