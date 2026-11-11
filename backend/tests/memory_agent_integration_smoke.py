"""Narrow integration: real API/Agent worker, fixture external model boundaries.
Run: .venv-atlas/bin/python -m backend.tests.memory_agent_integration_smoke
No backend configuration/database is imported before isolated_env is installed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    if os.environ.get("ATLAS_MEMORY_INTEGRATION_WORKER") != "1":
        from backend.agent.evaluation import isolated_env
        with tempfile.TemporaryDirectory(prefix="atlas-agent-eval-memory-") as folder:
            env = isolated_env(folder, "fixture")
            env["ATLAS_MEMORY_INTEGRATION_WORKER"] = "1"
            result = subprocess.run([sys.executable, "-m", "backend.tests.memory_agent_integration_smoke"], env=env, text=True, capture_output=True)
            print(result.stdout, end="")
            if result.returncode:
                print(result.stderr, end="", file=sys.stderr)
            raise SystemExit(result.returncode)
    run_worker()


def run_worker():
    root = Path(os.environ["ATLAS_EVAL_ROOT"]).resolve()
    assert root.name.startswith("atlas-agent-eval-memory-") and os.environ["DATABASE_URL"] == "sqlite:///" + str(root / "atlas.db")
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.database import SessionLocal
    from backend.models import Memory, MemoryMetadata, MemoryProfile, MemoryRevision, MemoryWriteReceipt, User

    def ok(response, status=200):
        assert response.status_code == status, (response.status_code, response.text[:800])
        return response.json()

    def tool(identifier, name, args):
        return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}

    class Provider:
        memory_id = None
        source_id = None
        contexts = {}
        internal_calls = 0
        last_citations = []

        async def round(self, config, messages, tools, user_id):
            last_user = max(index for index, message in enumerate(messages) if message["role"] == "user")
            prompt = messages[last_user]["content"]
            results = [json.loads(message["content"]) for message in messages[last_user + 1:] if message["role"] == "tool"]
            if prompt not in self.contexts:
                context_text = messages[0]["content"].split("以下为服务端提供的学习上下文：\n", 1)[1]
                self.contexts[prompt] = json.loads(context_text)
            calls, output = [], "按服务端工具的实际结果完成本轮。"
            if prompt == "请长期记住：我偏好具体例子。" and not results:
                calls = [tool("remember", "remember_memory", {"content": "我偏好具体例子", "category": "preference", "facet": "explanations"})]
            elif prompt == "请召回已保存的例子偏好。" and not results:
                calls = [tool("recall", "recall_memory", {"query": "例子"})]
            elif prompt == "请整理我的学习记忆。" and not results:
                calls = [tool("consolidate", "consolidate_memory", {"scope": "personal"})]
            elif prompt == "请忘记之前保存的例子偏好。" and not results:
                calls = [tool("forget", "forget_memory", {"memory_id": self.memory_id, "expected_revision": 1})]
            elif prompt == "请核对 AtlasCitation.v1 的资料版本。":
                if not results:
                    calls = [tool("retrieve", "retrieve_materials", {"query": "AtlasCitation.v1", "mode": "lexical", "source_ids": [self.source_id]})]
                elif len(results) == 1:
                    ref = results[0]["sources"][0]
                    calls = [tool("read", "read_material", {"source_id": ref["source_id"], "version": ref["source_version"], "chunk_indices": [ref["chunk_index"]]})]
                else:
                    output = "资料版本与回读片段一致。[" + str(results[-1]["citations"][0]["citation"]) + "]"
            elif prompt == "qa权限检查：不得把我的文字保存为长期记忆。" and not results:
                calls = [tool("qa-remember", "remember_memory", {"content": "我的文字", "category": "note"}),
                         tool("qa-organize", "consolidate_memory", {"scope": "personal"}),
                         tool("qa-forget", "forget_memory", {"memory_id": self.memory_id}),
                         tool("qa-recall", "recall_memory", {"query": "例子"}),
                         tool("qa-read", "read_material", {"source_id": self.source_id, "version": 1, "chunk_indices": [0]})]
            elif prompt == "拒绝虚构画像保存" and not results:
                calls = [tool("fabricated", "remember_memory", {"content": "用户精通量子计算", "category": "note"})]
            if calls:
                message = {"role": "assistant", "content": "", "tool_calls": calls}
            else:
                yield {"kind": "text", "text": output}
                message = {"role": "assistant", "content": output}
            yield {"kind": "result", "message": message, "usage": {"prompt_tokens": 80, "completion_tokens": 12}, "usage_known": True}

        async def request_completion(self, config, messages, json_mode=False):
            # Only the genuine external completion boundary is replaced; llm
            # tracing, model selection, profile validation and DB commits run.
            data = json.loads(messages[-1]["content"])
            assert "facts" in data, "Unexpected external model operation in this focused fixture"
            self.internal_calls += 1
            groups = [{"label": "学习偏好", "claims": [{"memory_id": fact["memory_id"], "revision": fact["revision"], "quote": fact["content"][:600]} for fact in data["facts"][:12]]}]
            return json.dumps({"groups": groups}, ensure_ascii=False), {"prompt_tokens": 42, "completion_tokens": 9}

    provider = Provider()
    with patch("backend.tutor.runner.model_round", provider.round), patch("backend.llm.request_completion", provider.request_completion), TestClient(app) as owner:
        foreign = TestClient(app)
        try:
            ok(owner.post("/api/auth/register", json={"email": "owner@memory-integration.test", "password": "AtlasSmoke123!", "full_name": "Owner"}))
            ok(foreign.post("/api/auth/register", json={"email": "other@memory-integration.test", "password": "AtlasSmoke123!", "full_name": "Other"}))
            template = ok(owner.get("/api/templates"))[0]
            course = ok(owner.post(f"/api/templates/{template['id']}/enroll"))
            source_text = "AtlasCitation.v1 preserves immutable raw text and verifies canonical citations. 学习资料必须核对原始版本，真实片段可回读。"
            source = ok(owner.post(f"/api/courses/{course['id']}/sources/text", json={"title": "AtlasCitation.v1", "content": source_text}))
            provider.source_id = source["id"]

            def session(course_id=None):
                return ok(owner.post("/api/tutor/sessions", json={"course_id": course_id} if course_id else {}))

            def run(prompt, selected=None, profile="tutor"):
                selected = selected or session()
                item = ok(owner.post(f"/api/tutor/sessions/{selected['id']}/turns", json={"content": prompt, "request_id": str(time.monotonic_ns()), "profile": profile}))
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    turn = ok(owner.get(f"/api/tutor/turns/{item['id']}"))
                    if turn["status"] in {"completed", "failed", "cancelled", "waiting_input", "waiting_confirmation"}:
                        assert turn["status"] == "completed", (prompt, turn.get("error"), turn["status"])
                        return turn
                    time.sleep(.03)
                raise AssertionError("Actual worker turn timed out: " + prompt)

            def results(turn):
                return [event["payload"] for event in turn["events"] if event["type"] == "tool_result"]

            # Actual source-bound write through Agent registry/worker/handler.
            saved = run("请长期记住：我偏好具体例子。")
            remembered = results(saved)[0]["result"]["memory"]
            provider.memory_id = remembered["id"]
            assert remembered["origin"] == "turn" and remembered["course_id"] is None and remembered["source_status"] == "valid"
            detail = ok(owner.get(f"/api/me/memories/{remembered['id']}"))
            assert detail["evidence"][0]["turn_id"] == saved["id"] and detail["evidence"][0]["quote"] == "我偏好具体例子"
            assert detail["evidence"][0]["url"].startswith("/chat?session=")
            recalled = run("请召回已保存的例子偏好。")
            assert any(item["id"] == remembered["id"] for item in results(recalled)[0]["result"]["memories"])
            assert any(item["id"] == remembered["id"] for item in provider.contexts["请召回已保存的例子偏好。"]["memories"])
            organized = run("请整理我的学习记忆。")
            profile = results(organized)[0]["result"]["profile"]
            assert profile["status"] == "ready" and profile["groups"][0]["claims"][0] == {"memory_id": remembered["id"], "revision": 1, "quote": "我偏好具体例子"}
            assert provider.internal_calls == 1
            trace = ok(owner.get(f"/api/agent/runs/agent/{organized['id']}"))
            assert any(span.get("name") == "memory_consolidation" and span.get("parent_id") == "tool:consolidate" for span in trace["spans"]), trace["spans"]
            assert trace["usage"]["internal_model_calls"] == 1
            rejected = run("拒绝虚构画像保存")
            assert results(rejected)[0]["result"].get("error")
            assert len(ok(owner.get("/api/me/memories"))) == 1
            print("PASS actual Agent: source-bound remember -> new-session recall/context -> extractive consolidation/child span; unsupported write refused")

            # Actual retrieval facade/read handler and canonical global numbers.
            retrieved = run("请核对 AtlasCitation.v1 的资料版本。", session(course["id"]))
            retrieval_result, read_result = [item["result"] for item in results(retrieved)]
            ref, exact = retrieval_result["sources"][0], read_result["citations"][0]
            assert ref["source_id"] == exact["source_id"] == source["id"]
            assert ref["source_version"] == exact["source_version"] == read_result["source"]["version"] == 1
            assert ref["chunk_index"] == exact["chunk_index"] and ref["citation"] == exact["citation"]
            assert read_result["content"] == source_text and exact["excerpt"] == source_text
            all_refs = [ref for event in retrieved["events"] if event["type"] == "citations" for ref in event["payload"]["citations"]]
            assert all(ref["citation"] == exact["citation"] for ref in all_refs if ref["source_id"] == source["id"])
            print("PASS actual Agent retrieval: lexical facade -> read_material immutable version -> canonical citation/event/answer agreement")

            # qa registry hides writes and dispatcher rejects fabricated calls.
            catalog = ok(owner.get("/api/agent/tools", params={"profile": "qa"}))
            names = {item["name"] for item in catalog["tools"]}
            assert {"recall_memory", "read_material", "retrieve_materials"} <= names
            assert not {"remember_memory", "forget_memory", "consolidate_memory"} & names
            with SessionLocal() as db:
                before = (db.query(Memory).count(), db.query(MemoryRevision).count(), db.query(MemoryProfile).count())
            qa = run("qa权限检查：不得把我的文字保存为长期记忆。", session(course["id"]), "qa")
            qa_results = {item["tool"]: item["result"] for item in results(qa)}
            assert all(qa_results[name].get("error") for name in ("remember_memory", "consolidate_memory", "forget_memory"))
            assert qa_results["recall_memory"]["memories"] and qa_results["read_material"]["content"] == source_text
            with SessionLocal() as db:
                assert before == (db.query(Memory).count(), db.query(MemoryRevision).count(), db.query(MemoryProfile).count())
            print("PASS qa actual dispatcher: remember/consolidate/forget denied; recall/read succeed; no memory/profile writes")

            # Original remembered fact is forgotten through the actual tool.
            forgotten = run("请忘记之前保存的例子偏好。")
            assert results(forgotten)[0]["result"]["memory"]["status"] == "forgotten"
            after = run("新轮上下文检查，不沿用已忘记的学习偏好。")
            context = provider.contexts["新轮上下文检查，不沿用已忘记的学习偏好。"]
            assert remembered["id"] not in {item["id"] for item in context["memories"]}
            assert not context["memory_profile"]["groups"] and context["memory_profile"]["status"] == "stale"
            assert not ok(owner.get("/api/me/memory/recall"))["memories"]
            print("PASS actual forget -> fresh-session context excludes fact and stale profile")

            # Public detail/edit/409/forget/export and cross-user API boundaries.
            api_memory = ok(owner.post("/api/me/memories", json={"content": "API_BOUNDARY_INITIAL", "category": "note"}))
            changed = ok(owner.patch(f"/api/me/memories/{api_memory['id']}", json={"content": "API_BOUNDARY_CHANGED", "expected_revision": 1}))
            assert changed["revision"] == 2
            ok(owner.patch(f"/api/me/memories/{api_memory['id']}", json={"content": "STALE_OVERWRITE", "expected_revision": 1}), 409)
            api_detail = ok(owner.get(f"/api/me/memories/{api_memory['id']}"))
            assert len(api_detail["history"]) == 2 and api_detail["memory"]["content"] == "API_BOUNDARY_CHANGED"
            assert ok(owner.post(f"/api/me/memories/{api_memory['id']}/forget", json={"expected_revision": 2}))["status"] == "forgotten"
            foreign_memory = ok(foreign.post("/api/me/memories", json={"content": "FOREIGN_PRIVATE_MARKER"}))
            for path, method, body in [(f"/api/me/memories/{remembered['id']}", "get", None), (f"/api/me/memories/{api_memory['id']}", "patch", {"content": "foreign overwrite"}), (f"/api/me/memories/{api_memory['id']}/forget", "post", {})]:
                response = getattr(foreign, method)(path, **({"json": body} if body is not None else {}))
                ok(response, 404)
            exported = ok(owner.get("/api/me/export"))
            assert all(name in exported for name in ("memory_metadata", "memory_revisions", "memory_profiles", "memory_write_receipts"))
            assert "FOREIGN_PRIVATE_MARKER" not in json.dumps(exported, ensure_ascii=False)
            print("PASS actual APIs: detail/history, PATCH + stale 409, forget, complete new-table export, owner isolation")

            # Permanent deletion must erase derived profile content too while
            # preserving request-key dedupe receipts as nonusable stale rows.
            deleted_content = "DELETED_PROFILE_TEXT_8fa4b7"
            deletion = ok(owner.post("/api/me/memories", json={"content": deleted_content}))
            deletion_profile = ok(owner.post("/api/me/memory/consolidate", json={"request_id": "delete-profile"}))
            assert deleted_content in json.dumps(deletion_profile)
            ok(owner.delete(f"/api/me/memories/{deletion['id']}"))
            export_after = ok(owner.get("/api/me/export"))
            assert deleted_content not in json.dumps(export_after), "hard-delete profile text survives owned export"
            with SessionLocal() as db:
                stored = db.get(MemoryProfile, deletion_profile["id"])
                assert stored.status == "stale" and not stored.facts and not stored.groups
                assert not db.query(MemoryRevision).filter_by(memory_id=deletion["id"]).count()
                assert db.get(MemoryMetadata, deletion["id"]) is None
            calls_before = provider.internal_calls
            replay = ok(owner.post("/api/me/memory/consolidate", json={"request_id": "delete-profile"}))
            assert replay["status"] == "stale" and not replay["groups"] and provider.internal_calls == calls_before
            print("PASS permanent DELETE: persisted/exported profile text scrubbed, metadata/revision cascade, same-key stale replay without model")
        finally:
            foreign.close()
    print("PASS memory/retrieval Agent integration (isolated API/DB/worker; model responses and usage are fixtures, not live quality scores)")


if __name__ == "__main__":
    main()
