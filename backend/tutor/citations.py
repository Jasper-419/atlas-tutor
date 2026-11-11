"""Normalize explicit citation labels against the current turn's references."""

import re


CITATION_GUIDANCE = (
    "资料问答的最终回答先给结论，并紧跟直接支持它的引用。"
    "使用 sources 或工具结果中 citation 字段的数字，格式为 [数字]，例如 [3]。"
    "核对摘录是否支持该句，优先引用直接证据，不要默认选第一条或罗列候选。"
    "不要用文件名、页码、链接或 Citation 字样代替编号。证据不足时说明缺失。"
    " In the final answer, place the supporting [number] immediately after the first source-backed claim."
)

_LABEL = re.compile(
    r"^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}(?P=fence)[`~]*[ \t]*$|\Z)"
    r"|(?<!`)(?P<code>`+)[^\n]*?(?P=code)(?!`)"
    r"|\$\$.*?\$\$|\$[^$\n]*\$"
    r"|(?<![\\!])\[(?:citation[ \t]+|引用[ \t]*)(?P<number>[1-9][0-9]*)\](?![\[(:])",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def normalize_citation_labels(text, citations):
    numbers = {str(item["citation"]) for item in citations if type(item.get("citation")) is int}
    if not numbers:
        return text

    def replace(match):
        number = match["number"]
        return f"[{number}]" if number in numbers else match[0]

    return _LABEL.sub(replace, text)
