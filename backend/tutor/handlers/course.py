"""Course selection, planning tasks and exact path-change proposals."""

from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from backend import learning
from backend.models.domain import Course, Node, Task
from backend.serializers import course_json, task_json
from backend.tutor import paths
from backend.tutor.handlers.base import owned


async def list_courses(inv):
    return {
        "courses": [
            course_json(inv.db, course)
            for course in inv.db.query(Course)
            .filter_by(user_id=inv.user_id)
            .order_by(Course.updated_at.desc())
            .limit(30)
        ]
    }


async def select_context(inv):
    course = owned(inv.db, Course, inv.args["course_id"], inv.user_id)
    node = owned(inv.db, Node, inv.args["node_id"], inv.user_id) if inv.args["node_id"] else None
    if node and (node.course_id != course.id or node.retired):
        raise HTTPException(404, "节点不属于当前课程。")
    inv.session.course_id, inv.session.node_id = course.id, node.id if node else None
    inv.db.commit()
    return {
        "course_id": course.id,
        "node_id": inv.session.node_id,
        "state": learning.get_learning_state(inv.db, inv.user_id, course.id, inv.session.node_id),
    }


async def create_learning_path(inv):
    course = inv.db.query(Course).filter_by(id=inv.key, user_id=inv.user_id).first()
    if not course:
        course = Course(
            id=inv.key,
            user_id=inv.user_id,
            title=inv.args["goal"][:100],
            goal=inv.args["goal"],
            background=inv.args["background"],
            minutes_per_day=inv.args["minutes_per_day"],
            level=inv.args["level"],
            deadline=inv.args["deadline"],
        )
        inv.db.add(course)
        inv.db.flush()
    task_id = str(uuid5(NAMESPACE_URL, inv.key + ":plan"))
    task = inv.db.query(Task).filter_by(id=task_id, user_id=inv.user_id).first()
    if not task:
        task = Task(id=task_id, user_id=inv.user_id, course_id=course.id, kind="plan", payload={})
        inv.db.add(task)
        course.task_id = task_id
    inv.session.course_id, inv.session.node_id, inv.session.mode = course.id, None, "outline"
    inv.db.commit()
    from backend.workflows import dispatch

    dispatch(task.id)
    return {"kind": "task", "task": task_json(inv.db, task), "course_id": course.id}


async def get_task_status(inv):
    return {
        "kind": "task",
        "task": task_json(inv.db, owned(inv.db, Task, inv.args["task_id"], inv.user_id)),
    }


async def plan_course(inv):
    course = inv.course()
    replay = inv.db.query(Task).filter_by(id=inv.key, user_id=inv.user_id).first()
    if replay:
        return {"kind": "task", "task": task_json(inv.db, replay), "course_id": course.id}
    if inv.db.query(Node.id).filter_by(user_id=inv.user_id, course_id=course.id, retired=False).first():
        return {"error": "课程已有路径，请使用propose_path_change生成待确认预览。"}
    active = (
        inv.db.query(Task)
        .filter_by(user_id=inv.user_id, course_id=course.id)
        .filter(Task.status.in_(["queued", "running"]))
        .first()
    )
    if active:
        return {
            "kind": "task",
            "task": task_json(inv.db, active),
            "message": "请等待资料导入或规划任务完成后继续。",
        }
    if inv.args["goal"]:
        course.goal = inv.args["goal"]
    for field in ("minutes_per_day", "level", "deadline"):
        if inv.args.get(field) is not None:
            setattr(course, field, inv.args[field])
    task = inv.db.query(Task).filter_by(id=inv.key, user_id=inv.user_id).first()
    if not task:
        task = Task(id=inv.key, user_id=inv.user_id, course_id=course.id, kind="plan", payload={})
        inv.db.add(task)
        course.status, course.task_id = "planning", inv.key
    inv.db.commit()
    from backend.workflows import dispatch

    dispatch(task.id)
    return {"kind": "task", "task": task_json(inv.db, task), "course_id": course.id}


async def propose_path_change(inv):
    inv.course()
    pending = await paths.propose(inv.db, inv.user_id, inv.course_id, inv.args["reason"], inv.key)
    pending["call_id"] = inv.call_id
    if not pending["changes"]:
        return {"unchanged": True, "message": "生成结果与当前路径一致，无需修改。"}
    return {"pause": pending}
