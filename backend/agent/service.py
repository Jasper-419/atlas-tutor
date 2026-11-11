"""One admission boundary freezes capability permissions and execution policy."""

from fastapi import HTTPException
from backend.agent.policy import RuntimePolicy
from backend.agent.capabilities import resolve_capability
from backend.tutor import store


def admit_turn(db, session, content, request_id, seed=None, profile=None, capability=None):
    from backend.tutor.tools import get_registry
    from backend.models.tutor import TutorTurn
    try:
        selected = resolve_capability(profile, capability)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    profile = selected.profile
    previous = db.query(TutorTurn).filter_by(session_id=session.id, request_id=request_id).first()
    if previous:
        previous_profile = (previous.checkpoint or {}).get("agent", {}).get("profile", "tutor")
        if previous_profile != profile:
            raise HTTPException(409, "request_id 已用于另一种 Agent 能力。")
    policy = RuntimePolicy.defaults(profile)
    registry = get_registry()
    cp = dict(seed or {})
    cp["agent"] = {"version": 2, "capability": selected.name, "profile": profile, "policy": policy.model_dump(), "allowed_tools": sorted(registry.allowed_names(profile))}
    turn = store.admit(db, session, content, request_id, cp)
    # Admission serializes concurrent requests; validate the winning record too.
    if (turn.checkpoint or {}).get("agent", {}).get("profile", "tutor") != profile:
        raise HTTPException(409, "request_id 已用于另一种 Agent 能力。")
    return turn
