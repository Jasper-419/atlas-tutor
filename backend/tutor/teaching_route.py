"""Recognize teaching questions that can be answered from the dialogue alone."""

import re


DIRECT_TEACHING_SYSTEM = """你是 Atlas 学习导师。根据对话中给出的题目、代码或作答，准确解释概念、反馈或提供提示。
遵循用户指定的语言、篇幅和格式；没有指定时用中文。需要时用简短的例子说明关键点。
代码使用带语言标识的 Markdown 代码块，公式使用 LaTeX。
用户只要提示时，提供一个能推进思考的线索，保留最终答案和完整解法。反馈应针对给出的作答和具体误解。
关键题干或作答缺失时，提出一个具体的澄清问题。只依据已给出的内容，不声称查过资料、历史记录或执行过操作。"""

_TEACHING_REQUEST = re.compile(
    r"解释|讲解|讲讲|说说|是什么|什么意思|为什么|怎么理解|如何理解|"
    r"区别|有什么不同|哪里错|点评|反馈|给.{0,12}提示|"
    r"\b(?:explain|clarify|why|what|how|hint|feedback|tutor|difference between)\b",
    re.IGNORECASE,
)
_NEEDS_TOOLS = re.compile(
    r"(?:查阅|查找|查询|检索|读取|查看|翻看|回顾|找回|结合|根据|引用|对照|从)"
    r"[^。！？\n]{0,20}(?:课程|讲义|课件|教材|资料|笔记|文档|文件|PDF|附件|上传|原文|来源|作答|答题|错题|学习记录|学习进度|记忆)|"
    r"(?:我的|我上传的|本课程的|这门课的)(?:课程|讲义|课件|教材|资料|笔记|文档|文件|附件|学习记录|学习进度|记忆)|"
    r"(?:我的|我)(?:上次|上一轮|上周|最近|之前|刚才|以前|历史|较早|昨天|前天)"
    r"[^。！？\n]{0,18}(?:作答|答题|回答|答错|练习|错题|笔记|进度)|"
    r"(?:上次|上一轮|昨天|前天|上周)(?:我|的)[^。！？\n]{0,12}(?:怎么答|答了|答错|作答|回答|错题|练习)|"
    r"我(?:的)?第[一二三四五六七八九十\d]+(?:次|道|轮)[^。！？\n]{0,8}(?:作答|答题|回答|练习|答案)|"
    r"(?:给(?:我|我们)?|出|生成|创建|安排)[^。！？\n]{0,10}"
    r"(?:题卡|练习|选择题|判断题|填空题|开放题|编程题|[道套一两几]题|测验)|"
    r"出题|错题|批改|评分|判分|改分|提交答案|记录(?:答案|作答|反馈)|"
    r"学习路径|学习计划|保存|存到|忘记|记住|更新记忆|联网|上网|搜索网页|执行代码|运行(?:这段|这个|一下|以下)?代码|"
    r"\b(?:my|our|uploaded|attached|course)\s+(?:(?:prior|previous|latest|earlier|recent|past|course|uploaded)\s+)?"
    r"(?:course\s+(?:materials?|documents?|notes?)|courses?|materials?|notes?|files?|documents?|"
    r"learning (?:history|progress)|progress|(?:first|second|previous|prior|past|last|earlier|recent)\s+"
    r"(?:answers?|attempts?|submissions?|mistakes?|work))\b|"
    r"\b(?:how|what)\s+did\s+i\s+(?:answer|submit|write|solve)\b[^.!?\n]{0,40}"
    r"\b(?:last time|earlier|yesterday|before|previously)\b|"
    r"\b(?:read|cite|retrieve|check|look\s+up|search|use)\b[^.!?\n]{0,32}"
    r"\b(?:the (?:uploaded|attached|course)\s+(?:file|document|material|notes?)|my\s+(?:history|progress|attempts?))\b|"
    r"\b(?:create|generate|make|give|provide|write|set|assign)\b[^.!?\n]{0,24}"
    r"\b(?:practice\s+(?:questions?|exercises?)|(?:new|another)\s+(?:questions?|exercises?)|"
    r"a\s+(?:quiz|exercise|question)|(?:\d+|one|two|three|a few|some)\s+(?:questions?|exercises?|quizzes))\b|"
    r"\b(?:quiz me|grade my|score my|submit (?:my|the) answer|save (?:a|my|this|the)|remember (?:that|this|my)|"
    r"forget (?:that|this|my)|learning (?:path|plan)|search the web|browse the web|(?:run|execute) (?:the |this |my )?code)\b",
    re.IGNORECASE,
)


def is_direct_teaching(request):
    return bool(_TEACHING_REQUEST.search(request) and not _NEEDS_TOOLS.search(request))
