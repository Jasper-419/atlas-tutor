"""User-facing memory inspection and explicit consolidation actions."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from backend.database import get_db
from backend.security import current_user

router = APIRouter(prefix="/api", tags=["memory"])
DB, AUTH = Depends(get_db), Depends(current_user)


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)


class ConsolidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: str | None = Field(default=None, max_length=40)
    request_id: str = Field(min_length=1, max_length=120)


@router.get("/me/memories/{memory_id}")
def detail(memory_id: str, user=AUTH, db=DB):
    from backend.memory.service import inspect_memory
    return inspect_memory(db, user.id, memory_id)


@router.post("/me/memories/{memory_id}/forget")
def forget(memory_id: str, body: RevisionBody, user=AUTH, db=DB):
    from backend.memory.service import forget_memory
    result = forget_memory(db, user.id, memory_id, expected_revision=body.expected_revision)
    db.commit()
    return result


@router.get("/me/memory/profile")
def profile(course_id: str | None = None, user=AUTH, db=DB):
    from backend.memory.service import get_profile
    return get_profile(db, user.id, course_id=course_id)


@router.post("/me/memory/consolidate")
async def consolidate(body: ConsolidateBody, user=AUTH, db=DB):
    from backend.memory.service import consolidate as run
    return await run(db, user.id, course_id=body.course_id, request_key=body.request_id)


@router.get("/me/memory/organize")
def organization_status(course_id: str | None = None, user=AUTH, db=DB):
    from backend.memory.organizer import get_run
    return get_run(db, user.id, course_id)


@router.post("/me/memory/organize")
async def organize_records(body: ConsolidateBody, user=AUTH, db=DB):
    from backend.memory.organizer import organize
    return await organize(db, user.id, body.course_id, body.request_id)


@router.get("/me/memory/audit")
def audit_memory(course_id: str | None = None, user=AUTH, db=DB):
    from backend.memory.organizer import audit
    return audit(db, user.id, course_id)


@router.get("/me/memory/recall")
def recall(q: str = Query(default="", max_length=2000), course_id: str | None = None,
           limit: int = Query(default=8, ge=1, le=12), user=AUTH, db=DB):
    from backend.memory.service import recall as read
    return read(db, user.id, q, course_id=course_id, limit=limit)
