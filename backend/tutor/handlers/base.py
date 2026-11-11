"""Shared ownership and invocation context for tool business handlers."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from backend.models.domain import Course, Node
from backend.models.tutor import TutorEvent, TutorSession, TutorTurn

MISSING_COURSE = "尚未选择课程，请先list_courses/select_context，或为新目标create_learning_path。"


def owned(db, model, identifier, user_id):
    item = db.query(model).filter_by(id=identifier, user_id=user_id).first()
    if not item:
        raise HTTPException(404, "资源不存在。")
    return item


class MissingCourse(Exception):
    """Preserve the legacy tool result for a missing conversation course."""


class MissingNode(Exception):
    """Preserve the legacy tool result when a course has no usable node."""


@dataclass
class ToolInvocation:
    context: Any
    db: Any
    turn: TutorTurn
    session: TutorSession
    args: dict
    key: str
    call_id: str
    user_id: str

    @property
    def course_id(self):
        return self.session.course_id

    @property
    def selected_node_id(self):
        return self.args.get("node_id") or self.session.node_id

    def course(self):
        if not self.course_id:
            raise MissingCourse()
        return owned(self.db, Course, self.course_id, self.user_id)

    def node(self):
        self.course()
        node_id = self.selected_node_id
        if not node_id:
            node = (
                self.db.query(Node)
                .filter_by(user_id=self.user_id, course_id=self.course_id, retired=False)
                .filter(Node.status.in_(["available", "learning"]))
                .order_by(Node.position)
                .first()
            )
            if node:
                node_id = node.id
                self.session.node_id = node.id
                self.db.commit()
        if not node_id:
            raise MissingNode()
        node = owned(self.db, Node, node_id, self.user_id)
        if node.course_id != self.course_id or node.retired:
            raise HTTPException(404, "节点不属于当前课程。")
        return node

    def user_message(self):
        response = (
            self.db.query(TutorEvent)
            .filter_by(turn_id=self.turn.id, type="user_response")
            .order_by(TutorEvent.seq.desc())
            .first()
        )
        return response.payload["content"] if response else self.turn.input
