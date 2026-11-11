"""Normalize the three model wire protocols used by custom API gateways."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit
import httpx


class ModelError(Exception):
    pass


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    protocol: str = "openai-completions"
    configured: bool = True


def request_parts(config, messages, *, json_mode=False, stream=False, max_tokens=6000):
    headers = {"Content-Type": "application/json"}
    messages = [dict(message) for message in messages]
    if json_mode:
        messages.insert(
            0,
            {
                "role": "system",
                "content": "Return only a valid JSON object, without Markdown fences.",
            },
        )
    body = {"model": config.model, "stream": stream}
    if config.protocol == "anthropic-messages":
        path = "/messages"
        headers["anthropic-version"] = "2023-06-01"
        if config.api_key:
            headers["x-api-key"] = config.api_key
        body.update(
            system="\n\n".join(m["content"] for m in messages if m["role"] == "system"),
            messages=[m for m in messages if m["role"] != "system"],
            max_tokens=max_tokens,
        )
    else:
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
        if config.protocol == "openai-responses":
            path = "/responses"
            body.update(input=messages, max_output_tokens=max_tokens, store=False)
            if json_mode:
                body["text"] = {"format": {"type": "json_object"}}
        else:
            path = "/chat/completions"
            body.update(messages=messages, temperature=0.35, max_tokens=max_tokens)
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            if stream:
                body["stream_options"] = {"include_usage": True}
            if urlsplit(config.base_url).hostname == "api.deepseek.com":
                body["thinking"] = {"type": "disabled"}
    return config.base_url.rstrip("/") + path, headers, body


def check_status(response):
    if response.status_code >= 400:
        hint = {
            401: "API Key 无效或已过期。",
            403: "请检查 API Key 的模型访问权限。",
            404: "请检查 API 地址、协议和模型 ID。",
            429: "请求过于频繁或额度不足，请检查服务商配额。",
        }.get(response.status_code, "请检查模型服务状态与配置。")
        raise ModelError(f"模型服务返回 HTTP {response.status_code}；{hint}")


def usage_tokens(usage):
    return {
        "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
        "completion_tokens": usage.get(
            "completion_tokens", usage.get("output_tokens", 0)
        ),
    }


def completion_text(config, data):
    if data.get("error") or data.get("status") in {"failed", "incomplete", "cancelled"}:
        raise ModelError("模型未完成回复，请检查模型配置或重试。")
    if config.protocol == "anthropic-messages":
        content = "".join(
            item.get("text", "")
            for item in data["content"]
            if item.get("type") == "text"
        )
    elif config.protocol == "openai-responses":
        content = "".join(
            part.get("text", "")
            for item in data["output"]
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    else:
        content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ModelError("模型未返回有效文本。")
    return content, usage_tokens(data.get("usage") or {})


async def request_completion(
    config, messages, *, json_mode=False, max_tokens=6000, timeout=100
):
    url, headers, body = request_parts(
        config, messages, json_mode=json_mode, max_tokens=max_tokens
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15)
        ) as client:
            response = await client.post(url, headers=headers, json=body)
        check_status(response)
        return completion_text(config, response.json())
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ):
        raise ModelError(
            "模型服务连接失败或响应无效；请检查网络、API 地址、协议和模型。"
        ) from None


def stream_event(config, data):
    kind = data.get("type", "")
    if data.get("error") or kind in {"error", "response.failed", "response.incomplete"}:
        raise ModelError("模型流返回错误，请检查配置或重试。")
    usage = data.get("usage") or {}
    token = ""
    done = False
    if config.protocol == "anthropic-messages":
        if kind == "message_start":
            usage = data.get("message", {}).get("usage") or {}
        if (
            kind == "content_block_delta"
            and data.get("delta", {}).get("type") == "text_delta"
        ):
            token = data["delta"].get("text", "")
        done = kind == "message_stop"
    elif config.protocol == "openai-responses":
        if kind == "response.output_text.delta":
            token = data.get("delta", "")
        if kind == "response.completed":
            usage = data.get("response", {}).get("usage") or {}
            done = True
    else:
        choices = data.get("choices") or []
        if choices:
            token = choices[0].get("delta", {}).get("content") or ""
            done = choices[0].get("finish_reason") is not None
    return token, usage, done
