"""Server-owned run budgets and typed execution failures."""

import os
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.model_providers import ModelError

Profile = Literal["tutor", "qa", "research", "planner", "solve"]


class RuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile: Profile = "tutor"
    max_rounds: int = Field(default=6, ge=1, le=16)
    max_tool_calls: int = Field(default=12, ge=1, le=64)
    max_model_retries: int = Field(default=1, ge=0, le=2)
    max_read_retries: int = Field(default=1, ge=0, le=2)
    max_tool_recoveries: int = Field(default=1, ge=0, le=2)
    timeout_seconds: int = Field(default=480, ge=10, le=1800)

    @classmethod
    def defaults(cls, profile="tutor"):
        base = {"max_rounds": 14, "max_tool_calls": 20} if profile == "solve" else {}
        overrides = {key: os.environ["ATLAS_AGENT_" + key.upper()] for key in cls.model_fields if key != "profile" and "ATLAS_AGENT_" + key.upper() in os.environ}
        try:
            return cls(profile=profile, **{**base, **overrides})
        except ValidationError:
            raise ModelError("Agent 运行策略配置无效，请检查 ATLAS_AGENT_* 服务端参数。") from None


class ExecutionError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class TransientModelError(ModelError):
    """Transport/provider rejection before output; a bounded retry is safe."""

    def __init__(self, message, code="provider_unavailable"):
        super().__init__(message)
        self.code = code
        self.retryable = True


def policy_from_checkpoint(checkpoint):
    saved = (checkpoint or {}).get("agent", {}).get("policy")
    if saved:
        try:
            return RuntimePolicy.model_validate(saved)
        except ValidationError:
            raise ModelError("保存的 Agent 策略无效，无法继续该轮次。") from None
    return RuntimePolicy.defaults((checkpoint or {}).get("agent", {}).get("profile", "tutor"))
