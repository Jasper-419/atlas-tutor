"""Material retrieval, generated lessons and persisted evidence research."""

from backend import learning
from backend.models.tutor import TutorTurn


async def retrieve_materials(inv):
    inv.course()
    from backend.retrieval_agent import retrieve, retrieval_event
    history = [{"role": "user", "content": item.input[:1500]} for item in inv.db.query(TutorTurn).filter(
        TutorTurn.user_id == inv.user_id, TutorTurn.session_id == inv.session.id,
        TutorTurn.id != inv.turn.id, TutorTurn.status == "completed",
    ).order_by(TutorTurn.created_at.desc()).limit(4)][::-1]
    result = await retrieve(inv.db, inv.user_id, inv.course_id, inv.args["query"],
        node_id=inv.selected_node_id, history=history, limit=inv.args["limit"],
        mode=inv.args["mode"], source_ids=inv.args["source_ids"])
    citations = result["citations"]
    await inv.context.emit("citations", {"citations": citations})
    meta = result["retrieval"]
    await inv.context.emit("retrieval_result", retrieval_event(meta, citations))
    return {"sources": [{"citation": i, **citation} for i, citation in enumerate(citations, 1)], "retrieval": meta}


async def read_material(inv):
    from backend.retrieval_agent import read_material as read
    inv.course()
    result = read(inv.db, inv.user_id, inv.course_id, **inv.args)
    await inv.context.emit("citations", {"citations": result.get("citations", [])})
    return {"kind": "material", **result}


async def prepare_lesson(inv):
    node = inv.node()
    # Preparing or reopening a lesson updates teaching state/activity in the
    # domain service; it is deliberately registered as a business write.
    result = await learning.prepare_lesson(inv.db, inv.user_id, node.id)
    await inv.context.emit("citations", {"citations": result["citations"]})
    return result


async def research_topic(inv):
    from backend.research import research_topic as research

    inv.course()
    result = await research(inv.user_id, inv.course_id, inv.args["query"], emit=inv.context.emit)
    if result.get("citations"):
        await inv.context.emit("citations", {"citations": result["citations"]})
    return {
        "kind": "research",
        "summary": result["summary"],
        "citations": result.get("citations", []),
        "research_mode": result.get("research_mode"),
        "outline": result.get("outline", []),
    }
