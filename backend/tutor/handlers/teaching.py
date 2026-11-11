"""Learning state, practice, assessment and human-confirmed repair proposals."""

import re

from fastapi import HTTPException

from backend import learning
from backend.models.domain import Exercise, Node, Review
from backend.tutor.handlers.base import owned


async def get_learning_state(inv):
    inv.course()
    return learning.get_learning_state(inv.db, inv.user_id, inv.course_id, inv.selected_node_id)


async def get_recent_attempts(inv):
    inv.course()
    return {
        "attempts": learning.get_recent_attempts(inv.db, inv.user_id, inv.course_id, inv.selected_node_id)
    }


async def get_teaching_state(inv):
    from backend.teaching import get_teaching_state as read_state

    inv.course()
    return read_state(inv.db, inv.user_id, inv.course_id, inv.selected_node_id)


async def resume_practice(inv):
    state = await get_teaching_state(inv)
    exercises = state.get("pending_exercises", [])
    if not exercises:
        return {"message": "当前知识点没有待作答题卡。", "next_action": state["next_action"]}
    inv.session.node_id = state["node_id"]
    inv.db.commit()
    await inv.context.emit("question", {"node_id": state["node_id"], "exercises": exercises})
    result = {"kind": "practice", "node_id": state["node_id"], "exercises": exercises, "resumed": True}
    validation = learning.practice_validation(inv.db, inv.user_id, state["node_id"], exercises)
    if validation:
        result["validation"] = validation
    return result


async def record_teaching_feedback(inv):
    from backend.teaching import record_feedback

    node = inv.node()
    if inv.args["content"] not in inv.user_message():
        return {"error": "反馈必须逐字来自当前用户原文，不能从模型回答或资料中推断。"}
    return record_feedback(
        inv.db, inv.user_id, node.id, inv.args["content"], inv.args["effect"], inv.args["strategy"], inv.key
    )


async def defer_learning(inv):
    from backend.teaching import defer_node

    node = inv.node()
    return defer_node(inv.db, inv.user_id, node.id, inv.args["reason"], inv.args["days"])


async def generate_practice(inv):
    node = inv.node()
    exercises = await learning.generate_practice(
        inv.db, inv.user_id, node.id, inv.args["focus"], inv.args["difficulty"], inv.args["count"], inv.key
    )
    result = {"kind": "practice", "node_id": node.id, "exercises": exercises}
    validation = learning.practice_validation(inv.db, inv.user_id, node.id, exercises)
    if validation:
        result["validation"] = validation
    await inv.context.emit("question", {"exercises": exercises, "node_id": node.id})
    return result


async def submit_answer(inv):
    inv.course()
    exercise = owned(inv.db, Exercise, inv.args["exercise_id"], inv.user_id)
    node = owned(inv.db, Node, exercise.node_id, inv.user_id)
    if node.course_id != inv.course_id:
        raise HTTPException(404, "题目不属于当前课程。")
    answer, actual = inv.args["answer"].strip(), inv.user_message()
    if answer.casefold() not in actual.casefold() or (
        len(answer) == 1
        and answer.isascii()
        and not re.search(r"(?<![a-zA-Z])" + re.escape(answer) + r"(?![a-zA-Z])", actual, re.IGNORECASE)
    ):
        return {"error": "答案必须逐字来自当前用户消息。请让用户使用题卡提交，不能替用户作答。"}
    result = await learning.submit_answer(inv.db, inv.user_id, exercise.id, inv.args["answer"], inv.key)
    await inv.context.emit("assessment", result)
    return {"kind": "assessment", **result}


async def propose_question_repair(inv):
    from backend.assessment_repair import propose_repair

    inv.course()
    exercise = owned(inv.db, Exercise, inv.args["exercise_id"], inv.user_id)
    node = owned(inv.db, Node, exercise.node_id, inv.user_id)
    if node.course_id != inv.course_id:
        raise HTTPException(404, "题目不属于当前课程。")
    pending = await propose_repair(inv.db, inv.user_id, exercise.id, inv.args["reason"], inv.key)
    pending["call_id"] = inv.call_id
    inv.db.commit()
    return {"pause": pending}


async def review_queue(inv):
    return {"reviews": learning.list_due_reviews(inv.db, inv.user_id, inv.course_id)}


async def rate_review(inv):
    review = owned(inv.db, Review, inv.args["review_id"], inv.user_id)
    node = owned(inv.db, Node, review.node_id, inv.user_id)
    if inv.course_id and node.course_id != inv.course_id:
        raise HTTPException(404, "复习记录不属于当前课程。")
    return learning.rate_review(inv.db, inv.user_id, review.id, inv.args["rating"])
