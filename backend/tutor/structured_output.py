"""Contracts for turns that explicitly request a JSON object."""

import json
import re


JSON_REQUEST = re.compile(
    r"(?:^|[\n。！？.!?；;])\s*(?:请\s*)?(?:"
    r"(?:只|仅)?(?:输出|返回)\s*(?:一个\s*)?JSON(?![a-z0-9_]|\s*(?:数组|列表))(?:\s*对象)?"
    r"|(?:用|以)\s*JSON\s*(?:格式)?\s*(?:作答|回答|输出)"
    r"|(?:please\s+)?(?:output|return|respond\s+with)\s+(?:only\s+)?(?:a\s+)?JSON\b(?!\s+(?:array|list)\b)(?:\s+object)?"
    r")", re.IGNORECASE,
)
JSON_FENCE = re.compile(r"\A\s*```(?:json)?\s*([\s\S]*?)\s*```\s*\Z", re.IGNORECASE)


def requested_object(text):
    """Return None for prose, or the requested object's example when supplied."""
    match = JSON_REQUEST.search(text)
    if not match:
        return None
    following = text[match.end():].lstrip(" \t\r\n:：")
    if following.startswith("["):
        return None
    if following.startswith("{"):
        try:
            example, _ = json.JSONDecoder().raw_decode(following)
            return example
        except ValueError:
            pass
    return {}


def json_instruction(example):
    instruction = "最终回答只能是一个有效 JSON 对象。不要添加 Markdown 围栏、前言或解释。"
    if example:
        instruction += "保留下列示例的字段名和字段类型，按问题填写实际值：" + json.dumps(
            example, ensure_ascii=False,
        )
    return instruction


def quote_field(example):
    fields = [
        key for key, value in (example or {}).items()
        if isinstance(value, str)
        and value.strip().casefold() in {"原文", "逐字原文", "verbatim quote", "exact quote"}
    ]
    return fields[0] if len(fields) == 1 else None


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON object fields")
    return result


def normalized_object(answer, example):
    if not isinstance(answer, str):
        return None
    fenced = JSON_FENCE.fullmatch(answer)
    try:
        obj = json.loads(fenced[1] if fenced else answer, object_pairs_hook=_unique_fields)
        if not isinstance(obj, dict):
            return None
        if example and (
            obj.keys() != example.keys()
            or any(type(obj[key]) is not type(value) and not (
                type(obj[key]) in (int, float) and type(value) in (int, float)
            ) for key, value in example.items())
        ):
            return None
        return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except ValueError:
        return None
