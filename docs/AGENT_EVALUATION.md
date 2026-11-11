# Atlas Agent 轻量任务评估

这套评估服务于 Atlas 的 Agent 应用与运行时工程演示。它检查“实际发生了什么”，不把助手说“完成了”当成功。案例定义在 [agent_tasks.json](../evaluations/agent_tasks.json)，执行入口是 [evaluate_agent.py](../scripts/evaluate_agent.py)，实现是 [evaluation.py](../backend/agent/evaluation.py)。当前共 9 项，不建设另一套测试平台。

## 两种证据必须分开

| 模式 | 使用的模型 | 真实执行部分 | 可以说明什么 |
| --- | --- | --- | --- |
| `fixture`，默认 | 明确编写的外部模型响应夹具 | FastAPI、认证、AgentLoop、工具权限、资料检索、SQLite、题卡、评分、学习证据、确认接口、trace API | 给定原生 tool call 时，应用的协议、权限和状态契约是否成立 |
| `live`，显式选择 | 当前环境或项目 `.env` 中的模型配置，不替换 provider | 同上，包括真实外部生成与工具选择 | 此模型和当前 harness 在这一次任务上的实际表现 |

`fixture` 是**模型边界 fixture**，不是模拟应用状态：不会替换工具、领域服务、数据库或返回 `fakeState`。夹具预先决定调用哪个工具，因此 9/9 只能称为契约检查通过，不能称为模型成功率。`qa` 等 capability profile 也是真实服务器权限；fixture 会故意越过 schema 发出写工具调用，验证 dispatch 的拒绝行为。不要把“profile fixture 通过”写成模型表现。

`live` 默认仅运行资料问答、动态题卡、真实作答幂等、人工确认 4 项。每项一次 trial，不计算稳定模型排名、置信区间或 `pass@k`。工具选择、生成质量、用量、延迟和失败均按实际结果保存；不为了通过把模型结果改成固定正确答案。

## 运行

在项目根目录执行，使用现有依赖，无需启动网络服务：

```bash
.venv-atlas/bin/python scripts/evaluate_agent.py
.venv-atlas/bin/python scripts/evaluate_agent.py --cases qa_write_denied,tool_failure_recovery
.venv-atlas/bin/python scripts/evaluate_agent.py --mode live
.venv-atlas/bin/python scripts/evaluate_agent.py --mode live --cases document_qa --output data/agent-evals/live-qa.json
```

`--cases` 接受空格或逗号分隔的案例 ID；只改变选择范围，不改变判定标准。`--timeout 180` 是每个轮次的等待上限，超时会请求取消。真实作答案例包含出题和作答续轮，因此可能调用模型多次。退出码：0 表示所选检查均通过，1 表示任务检查失败，2 表示启动/基础设施失败；失败不应删除。

`live` 只从环境和 `.env` 读取 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`DEEPSEEK_API_KEY`、`LLM_MODEL`，配置优先级沿用 Atlas。项目只设置 `DEEPSEEK_API_KEY` 时使用现有 DeepSeek 默认配置。若模型连接只保存在正式业务数据库中，评估器不会打开正式库取出密钥，应在上述环境变量中配置专用评估连接。模型 ID 会进入报告，密钥、cookie、连接 URL 和 checkpoint 私有 messages 不会导出。

## 隔离与报告

父进程仅加载标准库和案例 JSON；`live` 为读取模型配置额外使用 `python-dotenv`。每次评估启动全新子进程，先覆盖 `ATLAS_DATA_DIR`、`DATABASE_URL` 和 checkpoint 路径为临时目录，再导入任何后端模块。worker 校验临时根与数据库 URL，不满足即退出。关闭通用后台 workflow worker、embedding 和联网搜索；Tutor worker 正常运行。课程通过注册/模板报名 API 创建，评估资料通过真实 source API 切块入库。退出后删除临时库，不修改现有业务库，也不重启用户服务。

默认保存 `data/agent-evals/<时间>/report.json` 与 `report.md`；`.gitignore` 已忽略整个 `data/`。`--output` 可以是目录或 `.json`/`.md` 路径，两种格式都会写出。可提交经过检查的报告副本作为证据，但不要把包含真实学习数据或密钥的文件纳入版本管理。

报告逐任务保留：

- 判定项与布尔结果、异常和实际状态、最终输出片段。
- 公开的工具回执、题卡及数据库行数变化；不会导出标准答案。
- 通过真实运行详情 API 读取的策略和模型/工具 span、运行状态。
- 每轮模型/工具调用、重试、Token 和端到端耗时；另列领域内部模型的 Trace 总量。

fixture 的 `tokens_measured=false`，主循环 Token 显示 `null`；其他计数中的 0 也不代表模型免费或零耗时。live 的 Token 来自服务商返回 usage；若服务商未返回，则不能把 0 当实际消耗。当前运行 span 关联主Loop与内部生成/核验/评分请求；中断请求保留开始span和未知用量。`domain_model_usage` 的Trace与它有重叠，两者不要直接相加。历史轮次可能缺少内部关联。没有价格表就不臆测金额。端到端耗时包含 worker 排队与检查，并非纯模型延迟。

## 9 项案例及 grader 边界

| ID | 真实判定 | 尚不能证明 |
| --- | --- | --- |
| `document_qa` | 检索工具返回自有资料，引用 source/version 可解析，正文包含引用与相关概念，有模型/工具 span | 教学解释的全面正确性与措辞质量；最小字符串检查还需人读 |
| `practice` | 真实出题服务落库，question event 对应数据库题目，公开题卡无答案/解析，出题不写 Attempt 或学习证据 | 大范围题目质量、难度校准或答案正确率 |
| `answer_idempotency` | 通过 answers API 真正提交 A，同 request_id 复用 turn，真实 assessment，Attempt/Evidence 各新增一条，换答案返回 409 | 所有崩溃窗口都 exactly once；本例题目和用户回答都不是模型效果分数 |
| `approval_boundary` | 预览暂停，路径快照不变，错误 action_id 拒绝，用户拒绝后仍不改路径 | 并发修改导致旧预览失效、接受成功分支和进程重启恢复；这些可另由现有 smoke 检查 |
| `cross_user` | 他人会话/轮次/trace 不可读，跨用户建会话与工具切换课程拒绝 | 完整渗透测试或所有接口授权覆盖 |
| `qa_write_denied` | qa 目录无业务写工具，模型边界强发写调用也被服务器拒绝，题目/记忆/作答/证据计数不变 | 模型是否自觉遵守权限；fixture 特意验证服务器不信任模型 |
| `scope_refusal` | 含混重点被澄清或拒绝，不创建题卡或学习证据 | 对所有开放问题都能正确识别范围；fixture只验证拒绝协议 |
| `verified_solve` | 真实子进程求和5050、检查通过、执行凭据完成计划且不写课程成绩 | 任意Python/OS沙箱、全部输入正确性或数学证明 |
| `tool_failure_recovery` | 不存在节点触发真实领域错误，tool_result 回传，下一次正确状态查询成功，失败 span 保留 | 外部 429/超时瞬时重试、kill/crash 后恢复、工具成功但回执未落盘的窗口 |

这组案例不新增 LLM judge；客观状态用代码判定，主观问答和题目质量由人抽看报告。live 中模型直接回答、没有调用任务要求的工具，会如实不通过过程检查；这表示本任务的显式工具使用要求没有满足，不代表所有等价回答都无效。若模型拒绝 qa 写请求而没有发工具调用，dispatcher 越权检查未被实际触发，会保留失败，不将“没尝试”伪装为服务端防护证据。

## 面试中如何陈述结果

先报模式、日期、模型、任务选择和 trial 数，再分别说成功状态、引用、权限、用量、耗时。例如：“这次 fixture 的 9 个案例检查真实 API 与数据库契约，外部模型响应被替换；另一次 DeepSeek live 是 4 个任务各一次，结果见报告。”实际运行前不要填写通过率或成本。一次失败应展示失败工具、参数/权限错误和后续状态，说明是模型选择、harness 还是 grader 限制。

当前可执行产物以生成的报告为准。本文件不预填尚未发生的 live 成绩。

## 设计依据

[Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) 区分 task、trial、grader 与真实环境 outcome。本项目据此同时检查公开执行轨迹和数据库状态，小样本仅用于回归与演示，不推断总体模型能力。

[Anthropic：Building effective agents](https://www.anthropic.com/research/building-effective-agents) 将固定代码路径的 workflow 与模型动态选择工具的 agent 分开。Atlas 分别保留二者，评估也不把固定 fixture 的流程当成模型自主规划成绩。

[LangGraph：Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) 说明重试会重新执行节点，外部副作用需应用保证幂等；[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 说明 checkpoint 与长期 store 的职责。Atlas Tutor 有自己的 turn/checkpoint/event 机制，这些文档用于对照设计，不代表 Tutor 由 LangGraph 执行，也不代表采用其文档中所有能力。

## 2026-11-10 的一次本地基线

本轮已产生下列本地报告，均位于 git 忽略目录；重跑会得到新的实际结果，不保证同样通过。fixture 报告：JSON（本地 `data/agent-evals/fixture-final/report.json`）、Markdown（本地 `data/agent-evals/fixture-final/report.md`）。live 报告：JSON（本地 `data/agent-evals/live-initial/report.json`）、Markdown（本地 `data/agent-evals/live-initial/report.md`）。

- fixture：7/7 个任务契约检查通过，外部 provider 为脚本；不计作模型效果。
- live：`deepseek-flash`，4 个任务各一次，自动契约检查 4/4 通过。没有重复试到通过，也没有修改 live 输出。

| live task | 案例耗时 ms | 主循环模型/工具调用 | 主循环 prompt/completion tokens |
| --- | ---: | --- | --- |
| document_qa | 3954 | 2 / 1 | 6396 / 332 |
| practice | 6292 | 2 / 1 | 10957 / 190 |
| answer_idempotency | 8822 | 3 / 1 | 17888 / 508 |
| approval_boundary | 7447 | 3 / 2 | 15542 / 432 |

这些数字只对应报告中的一次试验与上述有限 grader。**人工抽看发现内容限制**：资料问答引用了正确的自有资料，但其额外类比和表格仍需专家评价；动态题卡实际围绕模板节点的 Python 名字/对象，而请求的 focus 是“定义与例子”。本套出题 grader 检查的是题卡服务、保密与状态契约，没有判定 focus 一致性，因此不能将 4/4 表述为“用户语义任务成功率 100%”。后续若要量化主题遵循，应先规定节点目标与用户 focus 冲突时的产品行为，再加入人工标注或校准过的 grader。

live 的隐私证据是公开题卡字段不含标准答案/解析；fixture 另含专用私有答案标记检测。两者都不是对任意自然语言泄漏的完整证明。领域 Trace 总量为 13 条、prompt/completion 54009/2451，含主循环 10 条与工具内部 3 条，不与表中用量相加，也没有按价格计算费用。


## 2026-11-11 · 可验证能力增量

当前fixture为9项，报告verified-agent-fixture-final（本地 `data/agent-evals/verified-agent-fixture-final/report.md`），9/9契约检查通过。新增含混focus与真实执行闭环；原7项仍保留。有效练习案例改为明确的Python赋值/对象引用，旧含混请求另作拒绝案例，不再用无关题冒充完成。fixture仍只替换模型，受限Python子进程真实运行。

三项真实DeepSeek单次任务见practice/scope_refusal（本地 `data/agent-evals/verified-practice-live/report.md`）、verified_solve（本地 `data/agent-evals/verified-solve-live/report.md`）：

| task | 耗时ms | 已记录模型/工具调用 | 输入/输出Token |
| --- | ---: | --- | --- |
| practice | 9298 | 5 / 1 | 16079 / 1411 |
| scope_refusal | 1882 | 1 / 1 | 6515 / 173 |
| verified_solve | 9746 | 5 / 4 | 24690 / 924 |

practice包含范围、生成与独立逐题核验内部调用；scope_refusal真实模型直接ask_user澄清，未生成题卡，不冒充实际触发了后端scope拒绝（后者由fixture与定向域检查覆盖）。solve实际使用for循环累加得到stdout=5050，三项检查通过，随后同计划/步骤凭据完成。报告是各一次trial与有限合同检查，不是统计成功率或完整语义正确性证明。

可复现命令：

```bash
.venv-atlas/bin/python scripts/evaluate_agent.py --mode live --cases practice scope_refusal verified_solve
.venv-atlas/bin/python -m backend.tests.verified_agent_smoke
.venv-atlas/bin/python -m backend.tests.practice_contracts_smoke
.venv-atlas/bin/python -m backend.tests.solver_smoke
```

第一条会调用模型并产生真实用量；其余分别明确使用外部provider fixture或完全无模型调用，均隔离数据。


## 检索与长期记忆专项（2026-11-11）

新增检索排名入口 `scripts/evaluate_retrieval.py`，lexical/fixture/live 均使用实际检索 facade 和隔离语料，报告 Recall、MRR、nDCG，重复证据只计一次。6 个合成小例的 live 报告在 `evaluations/retrieval/live.json`，不能据此推断大库质量或提升幅度。

`backend.tests.memory_agent_integration_smoke` 使用真实 AgentLoop/dispatcher/API/数据库，覆盖来源写入、跨会话召回与 context、提取画像/内部 span、版本化回读/全局引用、遗忘/修改/永久删除和 qa 权限；只替换外部 provider 响应，用量为明确 fixture。另一次真实 deepseek-flash 3 轮链路保存偏好、整理画像、新会话召回、忘记并检查失效通过，报告 `data/memory-evals/live.json`。9 项通用 Agent fixture 回归通过，报告 `data/agent-evals/retrieval-memory-fixture/`。这些任务互补，不应合成一个模型准确率数字。实现及局限见 [RETRIEVAL_MEMORY.md](RETRIEVAL_MEMORY.md)。
