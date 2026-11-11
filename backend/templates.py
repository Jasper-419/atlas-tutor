"""Original, human-written starter material. These courses never claim AI authorship."""

TEMPLATES = {
    "python-foundations": {
        "title": "Python · 从表达式到可测试函数",
        "description": "人工编写入门课程。通过三个小单元理解数据、控制流与函数，用客观练习完成学习闭环。",
        "level": "beginner",
        "minutes": 60,
        "topics": ["值与类型", "控制流", "函数与边界"],
        "nodes": [
            (
                "值、变量与可变性",
                "区分赋值、相等与对象的可变性。",
                """# 值、变量与可变性

Python 中的变量名指向一个对象。赋值 `b = a` 让两个名字指向同一个对象；它不会自动复制列表。

```python
a = [1, 2]
b = a
b.append(3)
print(a)  # [1, 2, 3]
```

整数和字符串是不可变对象，列表与字典是可变对象。`==` 比较值是否相等，`is` 比较是否为同一个对象。通常比较内容时使用 `==`。

```python
name = "Atlas"
print(type(name).__name__)  # str
items = ["state", "graph"]
copy = items.copy()  # 浅拷贝；嵌套对象仍可能共享
```

**动手做：** 创建一个列表，分别使用赋值和 `.copy()` 得到另外两个变量。修改原列表，观察两者的差别。

**检查理解：** 为什么 `b = a` 后对 `b.append()` 的调用也会影响 `a`？解释时区分“名字”和“对象”。

参考：[Python 官方入门教程](https://docs.python.org/3/tutorial/introduction.html)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "执行 a = [1]; b = a; b.append(2) 后，a 的值是什么？",
                        ["[1, 2]", "[1]", "[2]", "抛出异常"],
                        "[1, 2]",
                        "a 和 b 引用同一个列表，append 原地修改该对象。",
                    ),
                    (
                        "比较两个字符串的文本是否相同，通常应使用什么？",
                        ["==", "is", "=", "=>"],
                        "==",
                        "== 比较值；is 比较对象身份。",
                    ),
                ],
            ),
            (
                "条件、循环与终止",
                "能预测循环输出，并识别边界条件。",
                """# 条件、循环与终止

条件把程序分成不同路径。循环重复执行一个步骤；它必须有可理解的终止条件。

```python
numbers = [2, 3, 4]
total = 0
for n in numbers:
    if n % 2 == 0:
        total += n
print(total)  # 6
```

`range(3)` 产生 0、1、2，右边界不包含在结果中。`break` 结束最内层循环，`continue` 跳过当前这一轮剩余语句。

```python
for attempt in range(3):
    print(attempt)
```

**动手做：** 统计列表中大于 10 的数。分别尝试空列表、只有一个元素的列表，以及所有元素都满足条件的列表。

**边界思考：** 如果 `while` 循环中的变量一直不改变，条件可能永远为真。限制重试次数是网络任务中常见的保护措施。

参考：[Python 控制流教程](https://docs.python.org/3/tutorial/controlflow.html)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "list(range(3)) 的结果是什么？",
                        ["[0, 1, 2]", "[1, 2, 3]", "[0, 1, 2, 3]", "[3]"],
                        "[0, 1, 2]",
                        "range 从 0 开始，不包含上界。",
                    ),
                    (
                        "continue 的作用是什么？",
                        [
                            "跳过本轮剩余语句，开始下一轮",
                            "结束整个程序",
                            "结束所有循环",
                            "返回函数结果",
                        ],
                        "跳过本轮剩余语句，开始下一轮",
                        "continue 继续下一次迭代；break 才退出最内层循环。",
                    ),
                ],
            ),
            (
                "函数、返回值与小测试",
                "用输入、输出和边界案例检查一个函数。",
                """# 函数、返回值与小测试

函数把一个明确的操作命名。参数描述输入，`return` 描述输出。打印仅向终端输出文字，不等于返回结果。

```python
def mean(values):
    if not values:
        raise ValueError("values must not be empty")
    return sum(values) / len(values)

assert mean([2, 4]) == 3
assert mean([5]) == 5
```

没有执行 `return` 的函数默认返回 `None`。编写函数时先说明空输入、不合法输入和常见输入的行为。

```python
def greet(name):
    return f"Hello, {name}"

assert greet("Atlas") == "Hello, Atlas"
```

**动手做：** 写一个 `count_even(values)` 函数，返回偶数个数。至少检查 `[]`、`[1]`、`[2, 4]` 三种输入。

**迁移：** 学习 Agent 系统时，把每个图节点写成输入/输出明确的小函数，可减少状态修改的歧义。

参考：[Python 函数定义](https://docs.python.org/3/tutorial/controlflow.html#defining-functions)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        '函数只调用 print("hello")，没有 return，它的返回值是什么？',
                        ["None", '"hello"', "True", "0"],
                        "None",
                        "print 是输出副作用；函数没有显式 return 时返回 None。",
                    ),
                    (
                        "计算平均值的函数遇到空列表，最合理的做法是什么？",
                        [
                            "明确定义并测试空输入行为",
                            "假设永远不会出现",
                            "静默返回任意数",
                            "随机选择结果",
                        ],
                        "明确定义并测试空输入行为",
                        "空输入是重要边界，应选择明确契约并验证。",
                    ),
                ],
            ),
        ],
    },
    "langgraph-foundations": {
        "title": "LangGraph · 状态、图与恢复",
        "description": "人工编写入门课程。理解状态更新、条件路由与持久化恢复，练习无需模型调用。",
        "level": "beginner",
        "minutes": 65,
        "topics": ["State", "Nodes & edges", "Checkpoint"],
        "nodes": [
            (
                "把任务建模为状态",
                "区分当前状态与执行步骤。",
                """# 把任务建模为状态

LangGraph 用状态图描述可持续的工作流。**状态**保存执行所需的信息；**节点**读取状态并返回更新；**边**决定下一步。

```python
from typing_extensions import TypedDict
class State(TypedDict):
    question: str
    answer: str

def draft(state: State):
    return {"answer": f"Question: {state['question']}"}
```

上例只是确定性的 Python 函数，并未调用模型。节点不必每次都调用 LLM。权限、计数和格式校验适合由普通代码处理。

默认字段更新通常覆盖旧值；如果同一字段需要累积多个消息，可使用消息 reducer。reducer 定义两个更新如何合并，而不是让模型自行决定。

**动手做：** 设计一个状态，包含 `question`、`draft`、`review_count`。说明每个字段由哪个步骤负责更新。

参考：[LangGraph 官方概览](https://docs.langchain.com/oss/python/langgraph/overview)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "LangGraph 节点的核心职责是什么？",
                        [
                            "读取状态并返回状态更新",
                            "总是启动新的数据库",
                            "必须调用语言模型",
                            "直接绘制网页",
                        ],
                        "读取状态并返回状态更新",
                        "节点是执行步骤，可以是普通函数，也可以调用模型或工具。",
                    ),
                    (
                        "需要累积消息时，状态 reducer 用于什么？",
                        [
                            "定义更新如何合并",
                            "验证用户密码",
                            "决定浏览器颜色",
                            "替代数据库备份",
                        ],
                        "定义更新如何合并",
                        "reducer 明确状态字段的合并方式。",
                    ),
                ],
            ),
            (
                "边、路由与有界循环",
                "用条件边表达选择，并设计终止条件。",
                """# 边、路由与有界循环

普通边表示固定的下一步；条件边根据状态选择路径。`START` 和 `END` 标记执行入口与完成位置。

```python
from langgraph.graph import StateGraph, START, END
builder = StateGraph(State)
builder.add_node("draft", draft)
builder.add_edge(START, "draft")
builder.add_edge("draft", END)
graph = builder.compile()
result = graph.invoke({"question": "What is state?", "answer": ""})
```

对“生成 → 审核 → 再生成”的循环，必须限制重试次数或提供明确的通过条件。否则即使每次调用都成功，整个任务也可能永远不结束。

**练习设计：** 若 `review_count < 2` 且质量不合格，回到 draft；否则结束。分别考虑第一次通过、两次仍未通过的情况。

**安全边界：** 将外部网页当作数据。网页中的“忽略之前指令”不是系统命令；工具调用也必须经过确定性的权限校验。

参考：[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "条件边通常根据什么决定下一步？",
                        ["当前图状态", "浏览器窗口大小", "随机端口", "只看节点名称"],
                        "当前图状态",
                        "路由函数读取状态并返回预定义的下一节点。",
                    ),
                    (
                        "生成与审核组成循环时，应额外设计什么？",
                        [
                            "明确终止条件与重试上限",
                            "无限重试",
                            "删除所有状态",
                            "忽略失败",
                        ],
                        "明确终止条件与重试上限",
                        "有界循环避免任务无限执行和不可控费用。",
                    ),
                ],
            ),
            (
                "Checkpoint 与线程隔离",
                "解释持久化恢复需要哪些标识与存储。",
                """# Checkpoint 与线程隔离

Checkpoint 保存图在步骤边界上的状态。配合持久化 checkpointer，可在服务重启后恢复执行，而不是只保存在进程内存里。

```python
config = {"configurable": {"thread_id": "user-7:course-42:task-9"}}
# graph 需要先通过 compile(checkpointer=...) 配置持久化存储
graph.invoke(initial_state, config=config)
```

`thread_id` 标识一个图执行会话。它不是认证凭证；服务端必须先确认当前用户有权访问该任务，再读取 checkpoint。

Checkpoint 不代替业务数据库：用户、课程、掌握度和答题记录需要单独建模。对发邮件、扣费等外部副作用，应设计幂等键，避免恢复时重复执行。

**检查理解：** 内存 checkpointer 为什么无法应对进程彻底退出？不同用户共用同一 thread_id 为什么危险？

**动手做：** 为两个用户、两门课程设计互不冲突的线程标识。把“保存状态”和“验证访问权限”列为两个独立步骤。

参考：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "要在服务进程退出后恢复图状态，应使用什么？",
                        [
                            "持久化 checkpointer",
                            "仅一个 Python 全局字典",
                            "只保存浏览器标题",
                            "关闭日志",
                        ],
                        "持久化 checkpointer",
                        "内存会随进程消失；恢复需要持久化状态。",
                    ),
                    (
                        "thread_id 是否能替代用户权限检查？",
                        [
                            "不能，服务端仍需验证资源归属",
                            "能，只要字符串很长",
                            "能，任何用户都可共享",
                            "仅在网页端检查即可",
                        ],
                        "不能，服务端仍需验证资源归属",
                        "会话标识只是寻址信息，不能授予访问权。",
                    ),
                ],
            ),
        ],
    },
    "rag-foundations": {
        "title": "RAG · 从资料到可信回答",
        "description": "人工编写入门课程。学习分块、混合检索、引用与评估，把私有资料接入真实学习流程。",
        "level": "beginner",
        "minutes": 60,
        "topics": ["分块与索引", "混合检索", "证据与引用"],
        "nodes": [
            (
                "资料解析与分块",
                "说明分块大小与上下文保留的关系。",
                """# 资料解析与分块

RAG 的第一步不是提问，而是把资料转成可检索的文本。PDF 解析提取文字；扫描 PDF 可能需要 OCR；标题、页码、来源 URL 应与文字一起保存。

大文档通常分为较小的 chunk。块太大，检索结果包含很多无关文字；块太小，定义与示例可能分离。重叠窗口可保留边界附近的上下文。

```python
text = "..."
size, overlap = 900, 140
chunks = [text[i:i+size] for i in range(0, len(text), size-overlap)]
```

这个字符窗口是直观基线，并非对所有文档都最优。真实系统可按段落、标题或 token 切分，再保留 chunk_index 与 source_id。

**动手做：** 上传一份 TXT 或 Markdown 到本课程，用一个独特短语搜索，检查引用是否包含原文。

参考：[Retrieval 概览](https://docs.langchain.com/oss/python/langchain/retrieval)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "相邻块保留少量重叠的主要目的是什么？",
                        [
                            "保留块边界附近的上下文",
                            "保证没有重复文字",
                            "让文件永久变小",
                            "绕过用户权限",
                        ],
                        "保留块边界附近的上下文",
                        "重叠可减少概念跨边界被切断的情况。",
                    ),
                    (
                        "扫描图片型 PDF 不能提取文字时，通常还需要什么？",
                        ["OCR", "只修改扩展名", "把文件名转成向量", "忽略资料内容"],
                        "OCR",
                        "扫描图像没有可直接提取的文本层，需要文字识别。",
                    ),
                ],
            ),
            (
                "关键词与向量混合检索",
                "区分精确匹配和语义相似。",
                """# 关键词与向量混合检索

关键词检索擅长精确术语、代码标识符和产品名。向量检索把查询与文本映射到同一个向量空间，按相似性寻找语义相近内容。

关键词可能漏掉同义表达；向量也可能把“主题相近但结论不同”的文字排在前面。混合检索结合两种排序。例如倒数排名融合 RRF：

`score(document) = Σ 1 / (60 + rank)`

在 Atlas，未配置 embedding 时仍使用真实关键词检索，状态页会明确显示 embedding 配置情况。开启 embedding 需要支持该接口的模型服务。

**动手做：** 分别搜索资料中的精确函数名和一个概念性问题。比较结果，思考哪些查询依赖语义能力。

**权限：** 必须先限定当前用户与课程的候选文档，再进行检索。不能检索所有用户资料后让模型决定哪些可以展示。

参考：[Retrieval 概览](https://docs.langchain.com/oss/python/langchain/retrieval)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "搜索一个精确函数名时，哪种方法通常有直接优势？",
                        ["关键词匹配", "随机抽样", "只比较文档长度", "忽略查询"],
                        "关键词匹配",
                        "精确标识符可以直接匹配关键词。",
                    ),
                    (
                        "多用户 RAG 的权限过滤应在何时执行？",
                        [
                            "检索候选资料时由服务端执行",
                            "回答生成后让模型自行删去",
                            "只在页面隐藏",
                            "不需要过滤",
                        ],
                        "检索候选资料时由服务端执行",
                        "权限必须由确定性后端查询限制。",
                    ),
                ],
            ),
            (
                "用引用约束回答",
                "区分检索命中、证据支持与事实正确。",
                """# 用引用约束回答

找到相关文字并不代表答案已经正确。Tutor 应说明哪些结论来自资料，提供可追踪的 source_id、chunk_index 和原文片段。

一条引用至少回答三个问题：**来自哪份资料？对应哪段文字？这段文字真的支持当前结论吗？** 如果资料不足，应说明限制或提出补充资料建议。

外部资料可能含错误、过期内容或恶意指令。RAG 应把资料作为不可信数据，而不是覆盖系统规则的指令。

**检查方法：** 从回答选一句关键结论，打开引用，对照原文。引用存在和引用支持该结论是不同的检查。

**动手做：** 上传一段你熟悉的说明文档，问一个资料能回答的问题，再问一个资料没有覆盖的问题。观察模型是否清楚表达证据边界。

**最小评估：** 准备少量有明确证据的问题，分别记录检索是否命中、回答是否受支持、引用是否对应原文。本课程不承诺未经测量的检索指标。

参考：[Retrieval 概览](https://docs.langchain.com/oss/python/langchain/retrieval)。本课为 Atlas 人工编写资料。""",
                [
                    (
                        "回答附带引用，是否自动意味着结论正确？",
                        [
                            "不，仍需核对原文是否支持结论",
                            "是，有链接就正确",
                            "是，模型永远可靠",
                            "只有英文链接可靠",
                        ],
                        "不，仍需核对原文是否支持结论",
                        "可追踪的引用仍需要核实证据与结论的对应关系。",
                    ),
                    (
                        "资料中包含“忽略系统规则”的文字，应如何处理？",
                        [
                            "视为不可信资料内容",
                            "把它变成系统指令",
                            "向所有用户公开资料",
                            "跳过权限检查",
                        ],
                        "视为不可信资料内容",
                        "外部文字不是更高优先级指令，不能覆盖权限与系统约束。",
                    ),
                ],
            ),
        ],
    },
}
