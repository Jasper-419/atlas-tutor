"""Explicit response projection keeps passwords, answers and job payloads private."""

from backend.models import Node, Source, PlanVersion, Trace, Course


def fields(item, names):
    return {name: getattr(item, name) for name in names.split()}


def user_json(item):
    return fields(item, "id email full_name is_admin preferences")


def node_json(item):
    return fields(
        item,
        "id course_id title summary objective content lesson_citations lesson_stale lesson_source_versions estimated_minutes difficulty position status mastery",
    )


def source_json(item):
    return fields(item, "id course_id title url kind chunk_count version created_at")


def message_json(item):
    return fields(item, "id role content citations created_at")


def exercise_json(item):
    return fields(item, "id node_id type prompt options rubric revision voided")


def attempt_json(item):
    return fields(
        item,
        "id exercise_id node_id answer score feedback correct_answer mastery passed next_node_id voided created_at",
    )


def memory_json(item):
    return fields(item, "id course_id category content created_at updated_at")


def trace_json(item):
    return fields(
        item,
        "id step status detail duration_ms prompt_tokens completion_tokens model created_at",
    )


def task_json(db, item):
    result = fields(
        item,
        "id course_id kind status progress message error result created_at updated_at",
    )
    result["traces"] = [
        trace_json(t)
        for t in db.query(Trace)
        .filter_by(task_id=item.id, user_id=item.user_id)
        .order_by(Trace.created_at)
    ]
    return result


def course_json(db, item, detail=False):
    nodes = (
        db.query(Node)
        .filter_by(course_id=item.id, user_id=item.user_id, retired=False)
        .order_by(Node.position)
        .all()
    )
    mastered = sum(n.mastery >= 80 for n in nodes)
    result = fields(
        item,
        "id title goal background minutes_per_day deadline status created_at updated_at task_id plan_version",
    )
    result.update(
        progress=round(sum(n.mastery for n in nodes) / len(nodes)) if nodes else 0,
        total_nodes=len(nodes),
        mastered_nodes=mastered,
        next_node_id=next(
            (n.id for n in nodes if n.status in {"learning", "available"}), None
        ),
    )
    if detail:
        result.update(
            nodes=[node_json(n) for n in nodes],
            edges=[
                {"source": p, "target": n.id} for n in nodes for p in n.prerequisites
            ],
            sources=[
                source_json(s)
                for s in db.query(Source)
                .filter_by(course_id=item.id, user_id=item.user_id)
                .order_by(Source.created_at.desc())
            ],
            plan_versions=[
                fields(v, "version reason created_at")
                for v in db.query(PlanVersion)
                .filter_by(course_id=item.id, user_id=item.user_id)
                .order_by(PlanVersion.version.desc())
            ],
        )
    return result


def review_json(db, item):
    node = db.get(Node, item.node_id)
    course = db.get(Course, node.course_id)
    return {
        "id": item.id,
        "node_id": node.id,
        "course_id": course.id,
        "node_title": node.title,
        "course_title": course.title,
        "due_at": item.due_at,
        "interval_days": item.interval_days,
        "mastery": node.mastery,
    }
