"""Fence service commits against cancellation and worker ownership changes."""

from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.models.tutor import TutorTurn
from backend.tutor.store import LostLease

_owner = ContextVar("atlas_tutor_mutation_owner", default=None)


@contextmanager
def mutation_scope(turn_id, worker_token):
    marker = _owner.set((turn_id, worker_token))
    try:
        yield
    finally:
        _owner.reset(marker)


@event.listens_for(Session, "before_commit")
def check_owner(db):
    identity = _owner.get()
    if identity is None:
        return
    # Scalar projection avoids refreshing away unflushed event/turn changes.
    # The row lock orders cancellation and the business commit on PostgreSQL.
    with db.no_autoflush:
        row = db.execute(
            select(TutorTurn.status, TutorTurn.worker_token)
            .where(TutorTurn.id == identity[0])
            .with_for_update()
        ).first()
    if not row or row.status != "running" or row.worker_token != identity[1]:
        raise LostLease()
