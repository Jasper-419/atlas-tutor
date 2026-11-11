"""Evidence-controlled teaching navigation shared by every conversation.

Explanation and teaching feedback change navigation, never mastery. A concrete
misconception is resolved only by a new, explicitly targeted open transfer task.
Hooks flush into the caller's transaction; public feedback/defer services commit
through the same mutation fence used by other learning services.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from backend.models.domain import Attempt, Course, Exercise, Memory, Node, now
from backend.models.learning import LearningEvidence
from backend.models.teaching import (
    MisconceptionReview,
    NodeTeachingState,
    PracticeTarget,
    TeachingFeedback,
)
from backend.serializers import exercise_json

PHASES = {"explain", "practice", "remediate", "verify", "mastered", "deferred"}


def _owned(db, model, identifier, user_id):
    item = db.query(model).filter_by(id=identifier, user_id=user_id).first()
    if not item:
        raise HTTPException(404, "资源不存在。")
    return item


def _node(db, user_id, node_id):
    item = _owned(db, Node, node_id, user_id)
    _owned(db, Course, item.course_id, user_id)
    if item.retired:
        raise HTTPException(409, "该学习节点已停用。")
    return item


def _state(db, node):
    state = db.query(NodeTeachingState).filter_by(user_id=node.user_id, node_id=node.id).first()
    if not state:
        state = NodeTeachingState(
            user_id=node.user_id,
            node_id=node.id,
            phase="mastered" if node.mastery >= 80 else "practice" if node.content else "explain",
        )
        db.add(state)
        db.flush()
    return state


def _open_reviews(db, user_id, node_id):
    return db.query(MisconceptionReview).filter_by(
        user_id=user_id, node_id=node_id, status="open"
    ).order_by(MisconceptionReview.due_at, MisconceptionReview.created_at).all()


def _valid_attempts(db, user_id, node_id):
    return db.query(Attempt).join(Exercise, Exercise.id == Attempt.exercise_id).filter(
        Attempt.user_id == user_id, Attempt.node_id == node_id,
        Attempt.voided.is_(False), Exercise.user_id == user_id, Exercise.voided.is_(False),
    )


def _review_json(db, item):
    origin = db.get(Exercise, item.origin_exercise_id)
    return {
        "id": item.id, "node_id": item.node_id,
        "origin_exercise_id": item.origin_exercise_id,
        "origin_attempt_id": item.origin_attempt_id,
        "description": item.description, "status": item.status,
        "due_at": item.due_at, "interval_days": item.interval_days,
        "resolved_attempt_id": item.resolved_attempt_id,
        "resolved_at": item.resolved_at,
        "prompt": origin.prompt if origin else "",
    }


def list_due_misconceptions(db, user_id, course_id=None):
    if course_id:
        _owned(db, Course, course_id, user_id)
    query = db.query(MisconceptionReview).join(Node, Node.id == MisconceptionReview.node_id).filter(
        MisconceptionReview.user_id == user_id, Node.user_id == user_id,
        Node.retired.is_(False), MisconceptionReview.status == "open",
        MisconceptionReview.due_at <= now(),
    )
    if course_id:
        query = query.filter(Node.course_id == course_id)
    return [_review_json(db, item) for item in query.order_by(MisconceptionReview.due_at).limit(100)]


def get_teaching_state(db, user_id, course_id, node_id=None):
    _owned(db, Course, course_id, user_id)
    nodes = db.query(Node).filter_by(
        user_id=user_id, course_id=course_id, retired=False
    ).order_by(Node.position, Node.id).all()
    states = {item.node_id: item for item in db.query(NodeTeachingState).filter(
        NodeTeachingState.user_id == user_id,
        NodeTeachingState.node_id.in_([node.id for node in nodes]),
    )} if nodes else {}
    timestamp = now()

    def deferred(node):
        state = states.get(node.id)
        return bool(state and state.deferred_until and state.deferred_until > timestamp)

    if node_id:
        node = _node(db, user_id, node_id)
        if node.course_id != course_id:
            raise HTTPException(404, "节点不属于当前课程。")
    else:
        due_ids = {item["node_id"] for item in list_due_misconceptions(db, user_id, course_id)}
        eligible = [n for n in nodes if (n.status in {"available", "learning"} or n.id in due_ids)
                    and n.status != "locked" and not deferred(n)]
        node = next((n for n in eligible if n.id in due_ids), None)
        node = node or next((n for n in eligible if n.status == "learning"), None)
        node = node or next(iter(eligible), None) or next((n for n in nodes if deferred(n)), None)
        node = node or next((n for n in nodes if n.mastery >= 80), None) or next(iter(nodes), None)
    if not node:
        return {
            "course_id": course_id, "node_id": None, "phase": "explain", "feedback": [],
            "misconceptions": [], "pending_exercises": [],
            "next_action": {"kind": "plan_course", "label": "规划学习路径", "reason": "当前课程尚未建立知识节点。",
                            "prompt": "请结合课程资料规划学习路径"},
        }
    state = states.get(node.id)
    reviews = db.query(MisconceptionReview).filter_by(user_id=user_id, node_id=node.id).filter(
        MisconceptionReview.status != "voided"
    ).order_by(MisconceptionReview.created_at.desc()).limit(100).all()
    open_reviews = sorted((item for item in reviews if item.status == "open"), key=lambda item: item.due_at)
    feedback = db.query(TeachingFeedback).filter_by(user_id=user_id, node_id=node.id).order_by(
        TeachingFeedback.created_at.desc(), TeachingFeedback.id.desc()
    ).limit(6).all()
    latest_effect = feedback[0].effect if feedback else "unknown"
    submitted = {identifier for identifier, in db.query(Attempt.exercise_id).filter_by(user_id=user_id, node_id=node.id)}
    pending_ids = [identifier for identifier in (state.last_exercise_ids or []) if identifier not in submitted] if state else []
    pending = db.query(Exercise).filter(
        Exercise.user_id == user_id, Exercise.node_id == node.id, Exercise.id.in_(pending_ids),
        Exercise.voided.is_(False),
    ).all() if pending_ids else []
    phase = state.phase if state and state.phase in PHASES else "practice" if node.content else "explain"
    if phase == "deferred" and not deferred(node):
        phase = "remediate" if open_reviews else "practice" if node.content else "explain"
    if deferred(node):
        phase = "deferred"
    elif open_reviews:
        phase = "verify" if phase == "verify" else "remediate"
    elif latest_effect == "not_helped" and phase == "remediate":
        phase = "remediate"
    elif node.mastery >= 80:
        phase = "mastered"
    alternatives = [n for n in nodes if n.id != node.id and n.status in {"available", "learning"} and not deferred(n)]
    action = {"kind": "explain", "label": "继续理解这一点", "reason": "先围绕当前可检验目标准备解释与例子。",
              "node_id": node.id, "prompt": f"请围绕「{node.title}」的目标继续教学，先解释再检验理解"}
    if node.status == "locked":
        prerequisite = next((n for n in nodes if n.id in (node.prerequisites or []) and n.mastery < 80), None)
        phase = "explain"
        action.update(kind="prerequisite", label="先学习前置知识", reason="该节点的前置知识尚未得到充分掌握证据。",
                      node_id=prerequisite.id if prerequisite else node.id,
                      prompt=f"请先带我学习「{prerequisite.title if prerequisite else node.title}」的前置知识")
    elif phase == "deferred":
        alternate = next(iter(alternatives), None)
        action.update(kind="next_node" if alternate else "resume", label="先学习其他可用节点" if alternate else "恢复这一节学习",
                      reason="暂缓只改变教学安排，既不增加掌握度，也不解锁依赖该节点的知识。",
                      node_id=alternate.id if alternate else node.id,
                      prompt=f"请带我学习「{alternate.title}」" if alternate else f"我想恢复「{node.title}」的学习，请继续讲解")
    elif pending and phase in {"practice", "verify"}:
        action.update(kind="answer", label="继续完成待答练习", reason="这批练习已保存；先用真实作答验证理解。",
                      prompt=f"继续「{node.title}」尚未完成的练习，请显示已有题卡，不重复生成")
    elif open_reviews:
        target = open_reviews[0]
        action.update(kind="verify" if phase == "verify" else "remediate",
                      label="验证误解是否已纠正" if phase == "verify" else "纠正这一具体误解", reason=target.description[:500],
                      prompt=f"请用一道新的开放迁移题验证「{node.title}」中的具体误解是否已纠正：{target.description[:900]}" if phase == "verify" else f"请针对「{node.title}」中的具体误解重新讲解，并用一道新的开放迁移题检验：{target.description[:900]}")
    elif latest_effect == "not_helped" and phase == "remediate":
        action.update(kind="explain", label="换一种方式讲解", reason="你反馈上一种讲解没有帮助，先更换例子或解释策略。",
                      prompt=f"刚才对「{node.title}」的讲解没有帮到我，请换一种方式，并先确认我卡在哪一步")
    elif phase == "mastered":
        alternate = next(iter(alternatives), None)
        action.update(kind="next_node" if alternate else "review", label="学习下一个目标" if alternate else "安排巩固复习",
                      reason="当前节点已有真实掌握证据；保留复习安排。",
                      node_id=alternate.id if alternate else node.id,
                      prompt=f"请带我学习下一个目标「{alternate.title}」" if alternate else "请检查已学知识的到期复习并带我巩固")
    elif getattr(node, "lesson_stale", False):
        action.update(kind="refresh_lesson", label="根据新资料重新讲解", reason="课程资料已更新，旧讲义需要重新准备。",
                      prompt=f"请基于更新后的资料重新准备「{node.title}」的讲义")
    elif phase in {"practice", "verify"}:
        action.update(kind="practice", label="用新练习检验理解", reason="讲解或反馈不会增加掌握度；下一步需要真实独立作答。",
                      prompt=f"请给「{node.title}」生成新的练习，检验当前学习目标")
    return {
        "course_id": course_id, "node_id": node.id, "node_title": node.title,
        "objective": node.objective, "phase": phase, "mastery": node.mastery,
        "last_strategy": state.last_strategy if state else "",
        "deferred_until": state.deferred_until if state else None,
        "defer_reason": state.defer_reason if state else "",
        "lesson_stale": bool(getattr(node, "lesson_stale", False)),
        "next_action": action,
        "feedback": [{"id": item.id, "content": item.content, "effect": item.effect,
                      "strategy": item.strategy, "created_at": item.created_at} for item in feedback],
        "misconceptions": [_review_json(db, item) for item in reviews],
        "pending_exercises": [exercise_json(item) for item in sorted(pending, key=lambda item: item.created_at)],
    }


def record_feedback(db, user_id, node_id, content, effect, strategy="", request_id=None):
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 4000:
        raise HTTPException(422, "请提供1至4000字符的真实教学反馈。")
    if effect not in {"helped", "not_helped", "unknown"} or not isinstance(strategy, str) or len(strategy) > 500:
        raise HTTPException(422, "教学反馈类型或策略无效。")
    if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 120):
        raise HTTPException(422, "request_id 长度须为1至120字符。")
    from backend.learning import _write_lock

    node = _write_lock(db, user_id, node_id, unlocked=False)
    key = request_id or str(uuid4())
    previous = db.query(TeachingFeedback).filter_by(user_id=user_id, node_id=node.id, request_key=key).first()
    if previous:
        if (previous.content, previous.effect, previous.strategy) != (content.strip(), effect, strategy.strip()):
            raise HTTPException(409, "request_id 已用于另一份教学反馈。")
        result = get_teaching_state(db, user_id, node.course_id, node.id)
        db.rollback()
        return result
    db.add(TeachingFeedback(user_id=user_id, node_id=node.id, request_key=key,
                            content=content.strip(), effect=effect, strategy=strategy.strip()))
    previous_phase = _state(db, node).phase
    reconcile_assessments(db, user_id, node.id)
    state = _state(db, node)
    if strategy.strip():
        state.last_strategy = strategy.strip()
    if effect == "not_helped":
        state.phase = "remediate"
    elif effect == "helped":
        state.phase = "verify" if _open_reviews(db, user_id, node.id) else "practice"
    else:
        state.phase = previous_phase
    state.updated_at = now()
    db.commit()
    return get_teaching_state(db, user_id, node.course_id, node.id)


def defer_node(db, user_id, node_id, reason="", days=1):
    if not isinstance(reason, str) or len(reason) > 2000 or isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        raise HTTPException(422, "暂缓原因不得超过2000字符，天数须为1至30的整数。")
    from backend.learning import _write_lock

    node = _write_lock(db, user_id, node_id, unlocked=False)
    reconcile_assessments(db, user_id, node.id)
    state = _state(db, node)
    state.phase = "deferred"
    state.deferred_until = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    state.defer_reason, state.updated_at = reason.strip(), now()
    db.commit()
    return get_teaching_state(db, user_id, node.course_id, node.id)


def on_lesson(db, node):
    reconcile_assessments(db, node.user_id, node.id)
    state = _state(db, node)
    state.phase = "remediate" if _open_reviews(db, node.user_id, node.id) else "practice"
    state.deferred_until, state.defer_reason, state.updated_at = None, "", now()
    db.flush()


def practice_target_context(db, user_id, node_id):
    target = next(iter(_open_reviews(db, user_id, node_id)), None)
    if not target:
        return None
    origin = _owned(db, Exercise, target.origin_exercise_id, user_id)
    return {"id": target.id, "description": target.description, "original_question": origin.prompt,
            "requirement": "设计新的开放迁移题，用不同情境和推理要求验证该误解；不可复写原题或直接提示答案。"}


def on_practice(db, node, exercises, target_id=None):
    state = _state(db, node)
    state.last_exercise_ids = [item.id for item in exercises]
    state.deferred_until, state.defer_reason, state.updated_at = None, "", now()
    target = db.query(MisconceptionReview).filter_by(
        id=target_id, user_id=node.user_id, node_id=node.id, status="open"
    ).first() if target_id else None
    for exercise in exercises:
        if target and exercise.type == "open" and exercise.id != target.origin_exercise_id:
            db.add(PracticeTarget(user_id=node.user_id, exercise_id=exercise.id, misconception_id=target.id))
    state.phase = "verify" if target else "practice"
    db.flush()


def _normalize(value):
    return re.sub(r"\W+", "", value.casefold())


def _can_resolve(db, review, attempt, evidence):
    if not attempt or attempt.voided or not attempt.passed or attempt.score < 80 or not evidence or not evidence.independent:
        return False
    exercise = db.get(Exercise, attempt.exercise_id)
    origin = db.get(Exercise, review.origin_exercise_id)
    semantic_confirmation = any(
        check.get("misconception_id") == review.id and check.get("demonstrates_understanding") is True
        for criterion in (evidence.criteria_scores or []) if isinstance(criterion, dict)
        for check in criterion.get("target_checks", []) if isinstance(check, dict)
    )
    return bool(exercise and origin and not exercise.voided and exercise.type == "open"
                and exercise.id != origin.id and exercise.created_at >= review.created_at
                and _normalize(exercise.prompt) != _normalize(origin.prompt)
                and semantic_confirmation
                and db.query(PracticeTarget.id).filter_by(user_id=review.user_id, exercise_id=exercise.id,
                                                         misconception_id=review.id).first())


def _set_memory_status(memory, marker, status, description="", resolved_attempt_id=None):
    memory.category = "misconception" if status == "open" else "resolved_misconception" if status == "resolved" else "invalidated_assessment"
    label = "待纠正的具体误解" if status == "open" else f"已通过新的独立开放迁移题纠正（作答证据 {resolved_attempt_id}）" if status == "resolved" else "源题或评分已更正，旧误解诊断已作废，不再作为薄弱点"
    history = memory.content.split("原始作答记录：\n", 1)[-1] if "原始作答记录：\n" in memory.content else memory.content[len(marker):].lstrip()
    memory.content = f"{marker} [教学诊断：{label}]\n当前诊断：{description}\n原始作答记录：\n{history}"
    memory.updated_at = now()


def _memory_status(db, review, exercise_id=None):
    marker = f"[exercise:{exercise_id or review.origin_exercise_id}]"
    memories = db.query(Memory).filter(Memory.user_id == review.user_id, Memory.course_id == db.get(Node, review.node_id).course_id,
                                      Memory.content.startswith(marker)).all()
    for memory in memories:
        # Keep the original authored/assessment text as history while changing
        # its current diagnostic status, so corrected errors stop misleading RAG.
        _set_memory_status(memory, marker, review.status, review.description, review.resolved_attempt_id)
        from backend.memory.service import sync_assessment_memory
        sync_assessment_memory(db, memory)


def reconcile_assessments(db, user_id, node_id):
    """Rebuild diagnosis validity after a grade/repair, without inventing evidence."""
    node = _owned(db, Node, node_id, user_id)
    _owned(db, Course, node.course_id, user_id)
    state = _state(db, node)
    attempts = _valid_attempts(db, user_id, node.id).order_by(Attempt.created_at, Attempt.id).all()
    valid = {item.id: item for item in attempts}
    first_by_exercise = {}
    for item in db.query(Attempt).filter_by(user_id=user_id, node_id=node.id).order_by(Attempt.created_at, Attempt.id):
        first_by_exercise.setdefault(item.exercise_id, item.id)
    evidence = {item.attempt_id: item for item in db.query(LearningEvidence).filter_by(user_id=user_id, node_id=node.id)}

    def diagnosis(attempt, record):
        if not attempt or attempt.passed:
            return ""
        if record:
            return record.misconception.strip() if record.independent else ""
        # Historical first answers are real work. Materialize their existing
        # feedback, without synthesizing any new LearningEvidence row.
        return attempt.feedback[:3000].strip() if first_by_exercise.get(attempt.exercise_id) == attempt.id else ""

    reviews = db.query(MisconceptionReview).filter_by(user_id=user_id, node_id=node.id).all()
    by_origin = {item.origin_attempt_id: item for item in reviews}
    for review in reviews:
        origin = valid.get(review.origin_attempt_id)
        record = evidence.get(review.origin_attempt_id)
        description = diagnosis(origin, record)
        if not description:
            review.status, review.resolved_attempt_id, review.resolved_at = "voided", None, None
        else:
            review.description = description
            if review.status == "voided":
                review.status, review.due_at = "open", now()
            resolution = valid.get(review.resolved_attempt_id)
            if review.status == "resolved" and not _can_resolve(db, review, resolution, evidence.get(review.resolved_attempt_id)):
                review.status, review.resolved_attempt_id, review.resolved_at = "open", None, None
                review.due_at = now()
        review.updated_at = now()
    # Only independent failed work establishes a new diagnosis. A failed targeted
    # follow-up retains the original review instead of multiplying identical ones.
    for attempt in attempts:
        record = evidence.get(attempt.id)
        description = diagnosis(attempt, record)
        if not description or attempt.id in by_origin:
            continue
        targets = db.query(MisconceptionReview).join(PracticeTarget, PracticeTarget.misconception_id == MisconceptionReview.id).filter(
            PracticeTarget.user_id == user_id, PracticeTarget.exercise_id == attempt.exercise_id,
            MisconceptionReview.user_id == user_id, MisconceptionReview.status == "open",
        ).all()
        if targets:
            for target in targets:
                target.due_at, target.updated_at = now(), now()
            continue
        review = MisconceptionReview(user_id=user_id, node_id=node.id, origin_exercise_id=attempt.exercise_id,
                                     origin_attempt_id=attempt.id, description=description, due_at=now())
        db.add(review)
        db.flush()
        reviews.append(review)
        by_origin[attempt.id] = review
    for review in reviews:
        if review.status != "open":
            continue
        for attempt in attempts:
            if _can_resolve(db, review, attempt, evidence.get(attempt.id)):
                review.status, review.resolved_attempt_id = "resolved", attempt.id
                review.resolved_at = attempt.created_at
                review.interval_days = 7
                review.due_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
                break
    for review in reviews:
        _memory_status(db, review)
    # Repairs can precede the first teaching write after migration. Retire legacy
    # misconception memories even when no MisconceptionReview was ever created.
    represented = {item.origin_exercise_id for item in reviews}
    by_review_id = {item.id: item for item in reviews}
    links = db.query(PracticeTarget).filter(
        PracticeTarget.user_id == user_id, PracticeTarget.misconception_id.in_(by_review_id)
    ).all() if by_review_id else []
    linked = {item.exercise_id: by_review_id[item.misconception_id] for item in links}
    for exercise in db.query(Exercise).filter_by(user_id=user_id, node_id=node.id):
        if exercise.id in represented:
            continue
        if exercise.id in linked:
            _memory_status(db, linked[exercise.id], exercise.id)
            continue
        marker = f"[exercise:{exercise.id}]"
        for memory in db.query(Memory).filter(
            Memory.user_id == user_id, Memory.course_id == node.course_id,
            Memory.category.in_(["misconception", "resolved_misconception", "invalidated_assessment"]),
            Memory.content.startswith(marker),
        ):
            _set_memory_status(memory, marker, "voided")
    if not state.deferred_until or state.deferred_until <= now():
        state.phase = "remediate" if any(r.status == "open" for r in reviews) else "mastered" if node.mastery >= 80 else "practice" if attempts or node.content else "explain"
    state.updated_at = now()
    db.flush()


def on_assessment(db, node):
    reconcile_assessments(db, node.user_id, node.id)
