"""Common control/result envelopes; business payloads keep their own schemas."""

import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from backend.agent.policy import ExecutionError


class ToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: ExecutionError | None = None
    pause: dict[str, Any] | None = None

    @classmethod
    def from_handler(cls, value):
        if not isinstance(value, dict):
            return cls(success=False, error=ExecutionError(code="invalid_tool_result", message="工具未返回约定的结构化结果。"))
        data = {key: item for key, item in value.items() if key not in {"_execution", "error", "pause"}}
        json.dumps(data, allow_nan=False)
        failure = value.get("error")
        return cls(data=data, success=not bool(failure), error=ExecutionError(code="operation_rejected", message=str(failure)) if failure else None, pause=value.get("pause"))

    def legacy(self):
        return {**self.data, **({"error": self.error.message} if self.error else {}), **({"pause": self.pause} if self.pause else {})}


class CapabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    capability: str
    status: str
    outcome: Literal["answered", "answered_with_errors", "verified", "partially_verified", "unverified", "incomplete", "failed", "cancelled"]
    verified_steps: int = 0
    reasoned_steps: int = 0
    limitations: list[str] = Field(default_factory=list)
