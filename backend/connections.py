"""User-scoped model connections. Credentials are encrypted and never serialized."""

import os
import tempfile
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from sqlalchemy.orm import Session
from backend.config import get_settings
from backend.database import get_db, SessionLocal
from backend.models import LLMConnection, LLMCredential, LLMSelection
from backend.security import current_user
from backend.model_providers import (
    ModelConfig,
    ModelError,
    check_status,
    request_completion,
)

Protocol = Literal["openai-completions", "openai-responses", "anthropic-messages"]


class ConnectionProbe(BaseModel):
    connection_id: str | None = Field(default=None, min_length=1, max_length=40)
    base_url: str = Field(min_length=1, max_length=2000)
    protocol: Protocol = "openai-completions"
    api_key: SecretStr = Field(default=SecretStr(""), max_length=4096)
    model: str = Field(default="", max_length=200)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请输入不含凭据、查询参数或片段的 HTTP(S) API 地址")
        try:
            parsed.port
        except ValueError:
            raise ValueError("API 地址的端口无效") from None
        if any(ord(char) < 33 for char in value):
            raise ValueError("API 地址不能包含空白或控制字符")
        if value.endswith(("/chat/completions", "/responses", "/messages")):
            raise ValueError(
                "请填写 API 基础地址，去掉 /chat/completions、/responses 或 /messages"
            )
        return value

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        secret = value.get_secret_value().strip()
        if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in secret):
            raise ValueError("API Key 不能包含空白或非 ASCII 字符")
        return SecretStr(secret)

    @field_validator("model")
    @classmethod
    def clean_model(cls, value):
        return value.strip()


class ConnectionInput(ConnectionProbe):
    name: str = Field(min_length=1, max_length=100)
    models: list[str] = Field(min_length=1, max_length=200)
    clear_api_key: bool = False

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请填写连接名称")
        return value

    @field_validator("models")
    @classmethod
    def valid_models(cls, value):
        models = list(dict.fromkeys(model.strip() for model in value if model.strip()))
        if not models or any(len(model) > 200 for model in models):
            raise ValueError("请填写至少一个有效模型 ID（每个不超过 200 字符）")
        return models

    @model_validator(mode="after")
    def selected_model(self):
        if self.model not in self.models:
            raise ValueError("默认模型必须在模型列表中")
        if self.clear_api_key and self.api_key.get_secret_value():
            raise ValueError("清除密钥时不能同时填写新密钥")
        return self


class SelectionInput(BaseModel):
    connection_id: str | None = Field(default=None, min_length=1, max_length=40)


@lru_cache
def credential_cipher():
    settings = get_settings()
    key = os.getenv("ATLAS_CREDENTIALS_KEY", "").strip()
    if not key:
        path = settings.data_dir / ".credentials.key"
        if not path.exists():
            # Atomic publication also works when API and Celery start together.
            with tempfile.NamedTemporaryFile(
                dir=settings.data_dir, delete=False
            ) as temp:
                temporary = temp.name
                os.chmod(temporary, 0o600)
                temp.write(Fernet.generate_key())
                temp.flush()
                os.fsync(temp.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            finally:
                os.unlink(temporary)
        key = path.read_bytes()
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise ModelError(
            "服务端模型密钥加密配置无效，请检查 ATLAS_CREDENTIALS_KEY。"
        ) from None


def decrypt_key(record):
    if not record:
        return ""
    try:
        return credential_cipher().decrypt(record.encrypted_key.encode()).decode()
    except InvalidToken:
        raise ModelError("无法读取已保存的 API Key，请重新填写密钥并保存。") from None


def owned_connection(db, identifier, user_id):
    connection = (
        db.query(LLMConnection).filter_by(id=identifier, user_id=user_id).first()
    )
    if not connection:
        raise HTTPException(404, "连接不存在")
    return connection


def resolve_model_config(user_id):
    with SessionLocal() as db:
        selection = db.get(LLMSelection, user_id)
        if selection and selection.connection_id:
            connection = owned_connection(db, selection.connection_id, user_id)
            return ModelConfig(
                connection.base_url,
                connection.model,
                decrypt_key(db.get(LLMCredential, connection.id)),
                connection.protocol,
            )
    settings = get_settings()
    return ModelConfig(
        settings.base_url,
        settings.model,
        settings.api_key,
        configured=bool(settings.api_key),
    )


def connection_json(connection, has_key):
    return {
        "id": connection.id,
        "name": connection.name,
        "base_url": connection.base_url,
        "protocol": connection.protocol,
        "models": connection.models,
        "model": connection.model,
        "has_api_key": has_key,
        "updated_at": connection.updated_at,
    }


def probe_config(body, db, user_id, *, identifier=None, clear=False):
    identifier = identifier or body.connection_id
    connection = owned_connection(db, identifier, user_id) if identifier else None
    key = body.api_key.get_secret_value()
    stored = db.get(LLMCredential, identifier) if connection else None
    if stored and not key and not clear:
        if body.base_url != connection.base_url or body.protocol != connection.protocol:
            raise HTTPException(
                422,
                "更改 API 地址或协议后，请重新填写 API Key，或选择清除已保存的密钥。",
            )
        key = decrypt_key(stored)
    return ModelConfig(body.base_url, body.model, key, body.protocol)


router = APIRouter(prefix="/api/me/llm-connections", tags=["model-connections"])
DB = Depends(get_db)
AUTH = Depends(current_user)


@router.get("")
def list_connections(user=AUTH, db: Session = DB):
    connections = (
        db.query(LLMConnection)
        .filter_by(user_id=user.id)
        .order_by(LLMConnection.created_at)
        .all()
    )
    keyed = {
        row.connection_id
        for row in db.query(LLMCredential.connection_id)
        .join(LLMConnection)
        .filter(LLMConnection.user_id == user.id)
    }
    selection = db.get(LLMSelection, user.id)
    settings = get_settings()
    return {
        "connections": [connection_json(c, c.id in keyed) for c in connections],
        "active_connection_id": selection.connection_id if selection else None,
        "server_configured": bool(settings.api_key),
        "server_model": settings.model,
    }


@router.put("/active")
def select_connection(body: SelectionInput, user=AUTH, db: Session = DB):
    if body.connection_id:
        owned_connection(db, body.connection_id, user.id)
    selection = db.get(LLMSelection, user.id)
    if not selection:
        selection = LLMSelection(user_id=user.id)
        db.add(selection)
    selection.connection_id = body.connection_id
    db.commit()
    return {"ok": True}


@router.post("/discover")
async def discover_models(body: ConnectionProbe, user=AUTH, db: Session = DB):
    config = probe_config(body, db, user.id)
    headers = {}
    if config.protocol == "anthropic-messages":
        headers["anthropic-version"] = "2023-06-01"
        if config.api_key:
            headers["x-api-key"] = config.api_key
    elif config.api_key:
        headers["Authorization"] = "Bearer " + config.api_key
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(config.base_url + "/models", headers=headers)
        check_status(response)
        data = response.json()
        items = data.get("data", data.get("models", []))
        if isinstance(items, dict):
            items = list(items)
        models = list(
            dict.fromkeys(
                item if isinstance(item, str) else item.get("id", "") for item in items
            )
        )
        models = [
            model
            for model in models
            if isinstance(model, str) and 0 < len(model) <= 200
        ][:200]
        if not models:
            raise ModelError("服务未返回可用模型，请手动填写模型 ID。")
        return {"models": models}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ModelError(
            "无法获取模型列表；该服务可能不支持 /models，请手动填写模型 ID。"
        ) from None


@router.post("/test")
async def test_connection(body: ConnectionProbe, user=AUTH, db: Session = DB):
    if not body.model:
        raise HTTPException(422, "请先填写用于测试的模型 ID")
    config = probe_config(body, db, user.id)
    await request_completion(
        config,
        [{"role": "user", "content": "Reply with OK."}],
        max_tokens=1024,
        timeout=25,
    )
    return {"ok": True, "message": "连接成功，模型已返回回复。"}


def save_connection(body, user, db, identifier=None):
    connection = (
        owned_connection(db, identifier, user.id)
        if identifier
        else LLMConnection(user_id=user.id)
    )
    if body.connection_id and body.connection_id != identifier:
        owned_connection(db, body.connection_id, user.id)
        raise HTTPException(422, "连接 ID 与保存目标不一致")
    probe_config(body, db, user.id, identifier=identifier, clear=body.clear_api_key)
    for field in ("name", "base_url", "protocol", "models", "model"):
        setattr(connection, field, getattr(body, field))
    db.add(connection)
    db.flush()
    credential = db.get(LLMCredential, connection.id)
    key = body.api_key.get_secret_value()
    if body.clear_api_key and credential:
        db.delete(credential)
    elif key:
        if not credential:
            credential = LLMCredential(connection_id=connection.id)
            db.add(credential)
        credential.encrypted_key = credential_cipher().encrypt(key.encode()).decode()
    if identifier is None and not db.get(LLMSelection, user.id):
        db.add(LLMSelection(user_id=user.id, connection_id=connection.id))
    db.commit()
    return connection_json(connection, bool(db.get(LLMCredential, connection.id)))


@router.post("")
def create_connection(body: ConnectionInput, user=AUTH, db: Session = DB):
    return save_connection(body, user, db)


@router.put("/{identifier}")
def update_connection(
    identifier: str, body: ConnectionInput, user=AUTH, db: Session = DB
):
    return save_connection(body, user, db, identifier)


@router.delete("/{identifier}")
def delete_connection(identifier: str, user=AUTH, db: Session = DB):
    db.delete(owned_connection(db, identifier, user.id))
    db.commit()
    return {"ok": True}
