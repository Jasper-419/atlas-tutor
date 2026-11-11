"""Focused API/runtime check using a local model gateway; never calls a paid API."""

import asyncio
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

folder = tempfile.TemporaryDirectory(prefix="atlas-connections-")
os.environ.update(
    ATLAS_DATA_DIR=folder.name,
    DATABASE_URL="sqlite:///" + str(Path(folder.name) / "test.db"),
    WORKER_MODE="disabled",
    OPENAI_API_KEY="",
    DEEPSEEK_API_KEY="",
)

from fastapi.testclient import TestClient
from backend.main import app
from backend.llm import complete, stream_chat

requests = []


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "local-model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append((self.path, dict(self.headers), body))
        if body["model"] == "rejected":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"upstream-private-detail"}')
            return
        protocol = self.path.rsplit("/", 1)[-1]
        usage = {"prompt_tokens": 3, "completion_tokens": 2}
        text = '{"ok": true}'
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = {
                "completions": [
                    {"choices": [{"delta": {"content": "hello"}}]},
                    {"choices": [], "usage": usage},
                ],
                "responses": [
                    {"type": "response.output_text.delta", "delta": "hello"},
                    {
                        "type": "response.completed",
                        "response": {"usage": {"input_tokens": 3, "output_tokens": 2}},
                    },
                ],
                "messages": [
                    {
                        "type": "message_start",
                        "message": {"usage": {"input_tokens": 3}},
                    },
                    {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "hello"},
                    },
                    {"type": "message_delta", "usage": {"output_tokens": 2}},
                    {"type": "message_stop"},
                ],
            }[protocol]
            for event in events:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        result = {
            "completions": {
                "choices": [{"message": {"content": text}}],
                "usage": usage,
            },
            "responses": {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
            "messages": {
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        }[protocol]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


def run():
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{gateway.server_port}/v1"
    try:
        with TestClient(app) as a, TestClient(app) as b:
            for client, name in [(a, "a"), (b, "b")]:
                assert (
                    client.post(
                        "/api/auth/register",
                        json={
                            "email": name + "@example.com",
                            "password": "AtlasSmoke123!",
                            "full_name": name,
                        },
                    ).status_code
                    == 200
                )
            root = "/api/me/llm-connections"
            response = a.get(root)
            assert response.status_code == 200, response.text
            user_id = a.get("/api/me").json()["id"]
            payload = {
                "name": "Local",
                "base_url": base_url,
                "protocol": "openai-completions",
                "models": ["local-model"],
                "model": "local-model",
                "api_key": "test-user-secret",
            }
            response = a.post(root, json=payload)
            assert response.status_code == 200, response.text
            connection = response.json()
            identifier = connection["id"]
            assert "test-user-secret" not in response.text
            assert connection["has_api_key"] is True
            assert a.get(root).json()["active_connection_id"] == identifier
            assert b.get(root).json()["connections"] == []
            assert (
                b.put(root + "/active", json={"connection_id": identifier}).status_code
                == 404
            )
            assert b.put(root + "/" + identifier, json=payload).status_code == 404
            assert b.delete(root + "/" + identifier).status_code == 404
            assert (
                b.post(
                    root + "/test",
                    json={**payload, "api_key": "", "connection_id": identifier},
                ).status_code
                == 404
            )
            # Blank on edit reuses this connection's secret; changing origin must not leak it.
            assert (
                a.put(
                    root + "/" + identifier, json={**payload, "api_key": ""}
                ).status_code
                == 200
            )
            changed = {**payload, "api_key": "", "base_url": base_url + "/elsewhere"}
            assert a.put(root + "/" + identifier, json=changed).status_code == 422
            assert (
                a.post(
                    root + "/test", json={**changed, "connection_id": identifier}
                ).status_code
                == 422
            )
            assert a.post(
                root + "/discover",
                json={**payload, "api_key": "", "connection_id": identifier},
            ).json()["models"] == ["local-model"]
            assert (
                a.post(
                    root + "/test",
                    json={**payload, "api_key": "", "connection_id": identifier},
                ).json()["ok"]
                is True
            )
            for protocol, path in [
                ("openai-completions", "/v1/chat/completions"),
                ("openai-responses", "/v1/responses"),
                ("anthropic-messages", "/v1/messages"),
            ]:
                assert (
                    a.put(
                        root + "/" + identifier, json={**payload, "protocol": protocol}
                    ).status_code
                    == 200
                )
                result = asyncio.run(
                    complete(
                        [{"role": "user", "content": "JSON please"}],
                        user_id,
                        "connection-smoke",
                        json_mode=True,
                    )
                )
                assert result == {"ok": True}

                async def stream():
                    return "".join(
                        [
                            token
                            async for token in stream_chat(
                                [{"role": "user", "content": "Hello"}], user_id
                            )
                        ]
                    )

                assert asyncio.run(stream()) == "hello"
                route, headers, body = requests[-1]
                assert route == path, route
                assert (
                    headers.get("x-api-key")
                    if protocol == "anthropic-messages"
                    else headers.get("Authorization")
                ) == (
                    "test-user-secret"
                    if protocol == "anthropic-messages"
                    else "Bearer test-user-secret"
                )
                assert a.get("/api/system/status").json()["model"] == "local-model"
            failed = a.post(root + "/test", json={**payload, "model": "rejected"})
            assert failed.status_code == 502 and "HTTP 401" in failed.text
            assert "upstream-private-detail" not in failed.text
            assert "test-user-secret" not in failed.text
            # A local service with no credential must never inherit the server's secret.
            from backend.config import get_settings

            get_settings().api_key = "server-key-must-not-reach-custom-endpoint"
            local = b.post(root, json={**payload, "api_key": ""})
            assert local.status_code == 200, local.text
            second_user = b.get("/api/me").json()["id"]
            asyncio.run(
                complete(
                    [{"role": "user", "content": "Hi"}], second_user, "local-no-auth"
                )
            )
            assert "Authorization" not in requests[-1][1]
            assert "x-api-key" not in requests[-1][1]
            exported = a.get("/api/me/export").text
            assert "test-user-secret" not in exported
            assert "encrypted_key" not in exported
            # The raw business database must not contain the API key either.
            from backend.database import engine
            from sqlalchemy import text as sql

            with engine.connect() as db:
                encrypted = db.execute(
                    sql("SELECT encrypted_key FROM atlas_llm_credentials")
                ).scalar()
                assert encrypted and "test-user-secret" not in encrypted
            assert (
                a.put(root + "/active", json={"connection_id": None}).status_code == 200
            )
            assert a.get(root).json()["active_connection_id"] is None
            assert a.delete(root + "/" + identifier).status_code == 200
            assert a.get(root).json()["connections"] == []
            assert (
                a.post(
                    root,
                    json={**payload, "base_url": "https://user:secret@example.com/v1"},
                ).status_code
                == 422
            )
            assert a.post(root, json={**payload, "model": "missing"}).status_code == 422
            assert TestClient(app).get(root).status_code == 401
            assert (
                b.request(
                    "DELETE", "/api/me", json={"password": "AtlasSmoke123!"}
                ).status_code
                == 200
            )
            with engine.connect() as db:
                assert (
                    db.execute(
                        sql("SELECT count(*) FROM atlas_llm_connections")
                    ).scalar()
                    == 0
                )
                assert (
                    db.execute(
                        sql("SELECT count(*) FROM atlas_llm_credentials")
                    ).scalar()
                    == 0
                )
        print(
            "PASS: connections CRUD, user isolation, write-only encrypted credentials, discovery/test, three protocols, streaming, selection and export"
        )
    finally:
        gateway.shutdown()


if __name__ == "__main__":
    run()
