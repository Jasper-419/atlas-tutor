"""Task-local correlation for nested model calls, with safe public metadata."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import uuid4


@dataclass(frozen=True)
class TraceScope:
    turn_id: str
    token: str
    user_id: int
    parent_id: str | None = None


_scope = ContextVar("atlas_agent_trace_scope", default=None)


@contextmanager
def trace_scope(turn_id, token, user_id):
    marker = _scope.set(TraceScope(turn_id, token, user_id))
    try:
        yield
    finally:
        _scope.reset(marker)


@contextmanager
def child_span(identifier):
    current = _scope.get()
    if current is None:
        yield
        return
    marker = _scope.set(replace(current, parent_id=identifier))
    try:
        yield
    finally:
        _scope.reset(marker)


def start_operation(user_id, step, model):
    current = _scope.get()
    if current is None or current.user_id != user_id or step == "tutor_agent_round":
        return None
    from backend.models.domain import now
    from backend.tutor import store
    identifier = "operation:" + str(uuid4())
    # Persist before the provider await, so cancellation still leaves an honest
    # unknown-usage span. A lost lease here stops work before issuing a request.
    store.emit(current.turn_id, "model_operation_start", {"span_id": identifier,
        "parent_id": current.parent_id, "name": step, "model": model,
        "started_at": now()}, current.token)
    return identifier


def record_operation(user_id, step, status, model, duration_ms, prompt_tokens, completion_tokens, operation_id=None):
    current = _scope.get()
    if current is None or current.user_id != user_id or step == "tutor_agent_round":
        return
    from backend.models.domain import now
    from backend.tutor import store
    # Never publish exception bodies, prompts, private answers or configuration.
    payload = {"span_id": operation_id or "operation:" + str(uuid4()), "parent_id": current.parent_id,
               "name": step, "model": model, "status": status, "duration_ms": duration_ms,
               "ended_at": now(), "usage_known": status == "succeeded" and bool(prompt_tokens or completion_tokens),
               "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}
    try:
        store.emit(current.turn_id, "model_operation", payload, current.token)
    except store.LostLease:
        # An observation cannot revive cancelled work or an old worker's lease.
        pass
