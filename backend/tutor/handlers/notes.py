"""User memory and notebook writes using the existing domain contracts."""

import re
from fastapi import HTTPException


def explicit_forget_request(text):
    # Conservative command gate, not a general natural-language intent model.
    # Unclear requests must go through ask_user instead of changing memory.
    if re.search(r"(?:不要|别|不必|无需|不想|不能|不可|不准|不要再)\s*(?:忘[记掉]|删除|移除)|\b(?:do\s+not|don't|never)\s+(?:forget|delete|remove)\b", text, re.I):
        return False
    commands = re.split(r"[。！？!?;；\n]", text)
    for sentence in commands:
        if re.search(r"^\s*(?:请|帮我|请帮我|麻烦|麻烦你|现在|我想|我要|我希望你|你可以|可以|把|将|再|然后|并|，|,|\s)*(?:忘[记掉]|别再记|不要记|删除|移除).{0,80}(?:记忆|偏好|记录|memory|memory_id)", sentence, re.I):
            return True
        if re.search(r"^\s*(?:please\s+)?(?:forget|remove|delete)\b.{0,80}\b(?:memory|preference|record|memory_id)\b", sentence, re.I):
            return True
    return False


async def remember_memory(inv):
    from backend.memory.service import remember_from_turn
    memory = remember_from_turn(inv.db, inv.user_id, inv.turn.id, **inv.args, request_key=inv.key)
    inv.db.commit()
    await inv.context.emit("memory_saved", {"memory_count": 1, "memory_id": memory["id"], "revision": memory["revision"]})
    return {"saved": True, "content": memory["content"], "memory": memory}


async def recall_memory(inv):
    from backend.memory.service import recall, inspect_memory
    result = recall(inv.db, inv.user_id, inv.args["query"], course_id=inv.course_id, limit=inv.args["limit"])
    result["memories"] = [{**memory, "evidence": inspect_memory(inv.db, inv.user_id, memory["id"])["evidence"][:2]} for memory in result["memories"]]
    await inv.context.emit("memory_recalled", {"memory_count": len(result["memories"]), "profile_status": result["profile"]["status"]})
    return {"kind": "memory", **result}


async def consolidate_memory(inv):
    from backend.memory.service import consolidate
    course_id = inv.course_id if inv.args["scope"] == "selected" else None
    result = await consolidate(inv.db, inv.user_id, course_id=course_id, request_key=inv.key)
    await inv.context.emit("memory_profile", {"profile_status": result["status"]})
    return {"kind": "memory_profile", "profile": result, "message": "学习画像已整理并保留来源。" if result["status"] == "ready" else "画像尚未就绪，请以当前状态为准。"}


async def forget_memory(inv):
    from backend.memory.service import forget_memory as forget
    if not explicit_forget_request(inv.user_message()):
        raise HTTPException(403, "需要用户明确要求忘记某条记忆或偏好；意图不清时请先用ask_user确认。")
    result = forget(inv.db, inv.user_id, **inv.args)
    inv.db.commit()
    await inv.context.emit("memory_forgotten", {"memory_count": 1, "memory_id": result["id"]})
    return {"kind": "memory", "forgotten": True, "memory": result}


async def save_note(inv):
    from backend.notes import create_note

    result = create_note(
        inv.db, inv.user_id, inv.args["title"], inv.args["content"], inv.course_id, inv.args["source_ids"], inv.key
    )
    inv.db.commit()
    await inv.context.emit("note_saved", result)
    return {"kind": "note", "note": result}
