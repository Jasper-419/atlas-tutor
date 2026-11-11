"""Conversation control, including the durable human-answer pause payload."""


async def set_mode(inv):
    inv.session.mode = inv.args["mode"]
    inv.db.commit()
    await inv.context.emit("mode", {"mode": inv.session.mode})
    return {"mode": inv.session.mode}


async def ask_user(inv):
    return {
        "pause": {
            "action_id": inv.key,
            "kind": "ask_user",
            "title": "需要你的回答",
            "question": inv.args["question"],
            "call_id": inv.call_id,
        }
    }
