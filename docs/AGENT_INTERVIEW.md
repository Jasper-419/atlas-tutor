# Atlas：Agent 应用与运行时工程讲解

Atlas 是 Next.js/React + FastAPI 的学习应用。产品闭环是“资料取证 → 解释或题卡 → 用户真实作答 → 学习证据 → 有针对性的反馈”。工程重点是让模型调用真实业务工具，并控制权限、确认、副作用和恢复。它适合展示 Agent 应用开发及部分平台工程思考，不声称覆盖所有岗位要求，也不将单个学习应用包装成通用多 Agent 平台。

## 一分钟介绍

“我在 Atlas 中实现了基于模型原生 tool calling 的有界 AgentLoop。模型在课程资料、学习证据和用户问题的上下文中决定下一步，但服务端独立校验工具参数、用户归属和 capability profile。出题与评分进入真实领域服务，掌握度只能由真实答题证据产生；改路径先生成精确版本预览，必须由确认接口接受。运行保存在 session、turn、checkpoint 和顺序事件中，浏览器断连可重放界面事件，worker 中断可从 checkpoint 继续。读取工具有限重试，写入依靠回执和领域幂等处理重复执行；solve能力还能让模型计划、调用受限Python、读取真实输出与检查，再用同一步骤的执行凭据完成计划；推理说明与执行校验分开。trace关联主循环与工具内部模型的时间、状态和用量。我还写了 9 个隔离任务检查，fixture 与真实模型结果分别报告。”

上述是实现设计的概述。宣称某个恢复窗口或模型效果“已验证”前，应出示对应运行报告；轻量 suite 当前没有覆盖杀进程、网络重试和全部并发窗口。

## 代码导览

| 讲解点 | 代码锚点 | 看什么 |
| --- | --- | --- |
| 对话入口、真实作答、人工确认 | [tutor/api.py](../backend/tutor/api.py)：`new_turn`、`answer`、`respond` | 请求幂等、用户范围、精确 action_id、真实用户输入来源 |
| 模型动态控制的循环 | [tutor/runner.py](../backend/tutor/runner.py)：`run`、`run_claim` | model → tool calls → tool results → model；预算、暂停与恢复 |
| 原生协议适配 | [tutor/providers.py](../backend/tutor/providers.py)：`wire_request`、`model_round` | OpenAI Chat/Responses 与 Anthropic wire 转换；不从普通文字解析可执行指令 |
| 工具与能力边界 | [agent/registry.py](../backend/agent/registry.py)：`ToolDefinition`、`ToolRegistry`；[tutor/tools.py](../backend/tutor/tools.py)：`schemas`、`execute` | Pydantic 参数、profile schema、执行时二次权限检查、模式限制及独立 handler |
| 运行策略与回执 | [agent/policy.py](../backend/agent/policy.py)、[agent/execution.py](../backend/agent/execution.py) | rounds/tool calls/重试/超时上限；同 call ID 的参数摘要与成功回执 |
| 对外 Agent 能力与观测 | [agent/service.py](../backend/agent/service.py)、[agent/inspection.py](../backend/agent/inspection.py) | 统一运行详情；Agent 与 workflow 结果按 kind 区分 |
| durable state 与事件 | [tutor/store.py](../backend/tutor/store.py)：`admit`、`claim`、`checkpoint`、`emit`；[models/tutor.py](../backend/models/tutor.py) | turn 状态、租约、worker token、单调 seq；checkpoint 不作为公开 API 返回 |
| 提交前所有权检查 | [tutor/mutations.py](../backend/tutor/mutations.py)：`mutation_scope`、`check_owner` | before_commit fencing，旧 worker 或取消后的执行不能提交新业务写入 |
| 真实学习证据 | [learning.py](../backend/learning.py)：`generate_practice`、`submit_answer` | 模型不能直接设置掌握度；Attempt 与 LearningEvidence 由服务计算 |
| 人类批准的具体对象 | [tutor/paths.py](../backend/tutor/paths.py)：`propose`、`apply`、`digest` | 展示精确变更，核对 base_version 与快照摘要，过期预览拒绝 |
| 上下文和长期记忆 | [tutor/context.py](../backend/tutor/context.py)：`build_context`、`related_memories`、`budget_messages` | 当前课程、检索、最近作答、偏好、历史摘要；保持工具调用与回执配对 |
| 固定业务 workflow | [workflows.py](../backend/workflows.py)：`execute_graph`、`research_step`、`plan_step`、`persist_step` | LangGraph 固定依赖路径及 checkpoint，和 Tutor AgentLoop 分工 |
| 可验证解题 | [solver.py](../backend/solver.py)、[sandbox.py](../backend/sandbox.py)、[sandbox_worker.py](../backend/sandbox_worker.py) | 有限AST解释器、真实stdout/checks、计划/步骤/版本绑定、reasoned与verified |
| 能力与结果协议 | [agent/capabilities.py](../backend/agent/capabilities.py)、[agent/contracts.py](../backend/agent/contracts.py) | 能力指令、结束核对、公共CapabilityResult、工具控制封装 |
| 练习重点与依据核验 | [practice_contracts.py](../backend/practice_contracts.py) | 范围/答案/真实引文、一次修正、私有题目合同、修题后回执失效 |
| 嵌套模型观测 | [agent/telemetry.py](../backend/agent/telemetry.py) | ContextVar父子关联、请求前占位、取消后未知用量、避免耗时重复累加 |
| 可复现任务检查 | [agent/evaluation.py](../backend/agent/evaluation.py)：`run_worker`、`FixtureProvider`；[案例](../evaluations/agent_tasks.json) | 外部模型可替换，真实 API/DB 不替换；逐项判定、保留失败 |

## 五分钟演示

演示目标是让人看到一次工具结果与一次真正的状态边界，不靠讲复杂术语。前置条件是使用当前版本的桌面 Atlas，已连接模型，已有课程与资料。浏览器 UI 和 fixture 报告分别标注，避免把录制或模拟输出说成 live。

| 时间 | 操作 | 展示证据 |
| --- | --- | --- |
| 0:00–0:40 | 选择解题，求1到100整数和并要求程序核对 | 计划→真实stdout5050→checks→绑定凭据完成；说明检查边界 |
| 0:40–1:30 | 请求 2 道新题；先看题卡再真实提交 A | 未答题没有标准答案；assessment、Attempt/Evidence 来自服务器 |
| 1:30–2:20 | 切到规划，请求首节点 17 分钟并增加迁移练习 | 展示变更预览；未确认路径不变；点击拒绝后路径仍不变 |
| 2:20–3:20 | 展示隔离运行 `--cases qa_write_denied,tool_failure_recovery` 的报告 | 明说 provider 是 fixture：服务器拒绝写入，错误状态查询后正确读取，失败 span 仍保留 |
| 3:20–4:15 | 打开一个 turn 的运行详情/JSON 报告 | policy、model/tool spans、Token 与耗时；明确不展示私有思维内容 |
| 4:15–5:00 | 打开 evaluation 与 runner/store 的关键函数 | 解释 checkpoint 与 UI event replay 的区别；讲一个尚未验证的崩溃窗口及改进方式 |

可先生成离线报告，现场无需等待：

```bash
.venv-atlas/bin/python scripts/evaluate_agent.py --output data/agent-evals/demo
.venv-atlas/bin/python scripts/evaluate_agent.py --mode live --cases document_qa --output data/agent-evals/live-demo
```

第二条确实请求模型，会产生实际用量。若模型服务不可用，展示失败报告和诚实边界即可，不切换到 fixture 后继续称为 live。不要现场通过停生产进程制造恢复；进程恢复演示需专门的临时数据库与独立进程。

## 十个追问及回答

1. **为什么说是 Agent，而不是聊天包装？**
   Tutor 的模型返回原生工具调用，选择检索、状态读取、题卡、追问或路径提案；工具结果重新进入下一轮模型，下一步不是固定 DAG。路径规划等任务则是代码定义的 LangGraph workflow。两者分别适合动态交互和可预期业务阶段。这个区分参考 [Anthropic 的架构说明](https://www.anthropic.com/research/building-effective-agents)。

2. **为什么不把全部逻辑改成 LangGraph，或拆成多个 Agent？**
   已有 workflow 可以继续承载固定依赖。交互式 Tutor 使用小循环更容易看清 tool_call、恢复点和业务提交边界；目前没有任务证据支持增加协调、上下文复制和额外模型开销。统一工具契约与观测并不要求统一执行框架。

3. **schema 隐藏写工具就安全了吗？**
   不够。schema 是模型接口，服务器仍需校验 profile、当前 mode、Pydantic 参数和 user_id 归属。qa fixture 故意发出不在 schema 的生成题卡/保存记忆请求，只有执行器拒绝且数据库不变，才能证明该边界在这个案例成立。模型输出始终不可信。

4. **人工确认究竟确认了什么？用户说“同意”就行吗？**
   确认的是界面显示的 action_id 与精确路径版本，不是模糊自然语言授权。提案先计算 before/after，确认接口核对 action_id；应用前再次比较版本与快照摘要。用户看到预览后课程若已变化，应拒绝旧预览并重新提案。轻量 eval 检查未确认与拒绝不写；接受和过期冲突需看对应 smoke 或单独演示。

5. **checkpoint 和 event replay 有什么不同？**
   checkpoint 保存程序继续执行所需的 messages、stage、待处理调用、索引与工具回执；event 保存面向用户的时间顺序结果，SSE 以 after_seq 补发。浏览器重连重放事件不等于重新执行工具，事件本身也不够恢复程序。这里是状态快照加事件投影，不是完整 event sourcing。中断模型输出可能需要 content_reset，说明流中已看见的文字与已完成模型轮次不同。

6. **幂等、重试和“恰好一次”是什么关系？**
   重试决定失败后再试多少次；幂等决定相同业务动作重复到达时是否重复生效。读取的瞬时错误可有限重试，写工具不能对任意异常盲重试。call ID 加参数摘要的回执可重用已成功结果，领域稳定键和唯一约束保护回执落盘前的重复窗口。仍不能声称跨外部服务分布式 exactly once，外部副作用必须让提供方支持稳定幂等键或查询对账。[LangGraph 的说明](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) 也区分节点重执行与外部副作用。

7. **有租约为什么还需要 fencing？**
   租约过期只是允许新 worker 接管，旧 worker 的慢请求可能仍返回。业务提交前必须再核对当前 turn 是 running 且 worker_token 匹配。mutation_scope 将执行归属带到 SQLAlchemy before_commit，取消或被接管后提交会被拒绝。它保护本地服务提交；已经发出的不可取消外部副作用仍需提供方幂等。轻量 suite 没有验证全部并发交错。

8. **memory、上下文、checkpoint 是一回事吗？**
   不是。用户偏好/误解等长期记录是可跨轮次检索的业务 memory；本轮 context 是选入模型窗口的课程、资料片段、最近作答和历史摘要；checkpoint 是恢复控制状态。Atlas 以 user/course 范围筛选 memory，再相关排序和截断。未答题的标准答案不进入模型可见的题卡或 context。摘要也可能有模型误差，需要保留原始证据。可对照 [LangGraph 的 checkpoint/store 分工](https://docs.langchain.com/oss/python/langgraph/persistence)。

9. **如何控制死循环、Token、费用和延迟？**
   服务端策略限制模型轮次、工具调用数、重试次数和总超时，工具还各有超时；策略快照冻结到 turn，客户端不能自行提额。context 采用保守字符估算、历史摘要、资料截断与调用/回执配对，超过硬限报错。字符估算不是供应商 tokenizer 的精确成本控制；usage 是事后观测，当前不宣称金额硬配额或总美元预算，也未做大规模压测。

10. **你怎样证明效果，如何解释失败？**
    先区分 fixture 的协议契约与 live 的模型+harness 表现。9 个小任务用真实 API/DB 检查引用、题卡、真实提交、确认和隔离，trace 解释中间失败。live 默认仅 4 项各一次，报告实际工具、状态、用量和耗时。字符串相关性不能证明教学质量，后续应从真实失败收集未见案例、多次 trial 并人工校准。遵循 [Anthropic eval 指南](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) 对 outcome 与 transcript 的区分，不把助手自报成功当成绩。

## 已实现、已验证与后续工作

| 层次 | 当前可以说 | 不应顺口扩展成 |
| --- | --- | --- |
| 实现 | 原生工具 AgentLoop、独立领域工具、profile、durable turn/event、精确人工确认、真实学习证据、回执/预算/span | 通用自治多 Agent 平台、自研基础模型、完整生产可用性承诺 |
| fixture 证据 | 此次报告中列出的具体契约与数据库状态检查 | 模型选对工具的成功率、问答质量、模型平均成本 |
| live 证据 | 报告中所选任务的实际单次结果、实际模型标识与 usage | 未运行模型的成绩、总体排名、稳定成功率或教学成效 |
| 平台能力边界 | 应用内执行策略、授权、租约/提交围栏、观测与隔离任务评估 | 分布式 exactly once、任意第三方副作用自动安全恢复、海量吞吐或 SLA |
| 未来有价值的扩展 | 真实失败语料、多 trial、人工题质评审、专项崩溃窗口验证、按需接外部追踪系统 | 在没有需求或证据时先堆编排框架和 Agent 数量 |

“已实现”不等于本轮轻量 eval 已覆盖全部分支。评估事实以 [评估说明](AGENT_EVALUATION.md) 及具体 JSON/Markdown 报告为准，不能用这份讲解稿替代验证证据。

## 可直接使用的简历措辞

- 基于 Next.js/React 与 FastAPI 构建 Atlas 学习应用，实现模型原生 tool calling 的有界 AgentLoop，接入资料检索、动态题卡与真实作答评分，基于学习证据推进教学。
- 设计类型化工具注册、capability profile 与用户资源隔离；实现路径变更的版本化人工确认，以及 turn/checkpoint/event 持久化、工具回执和运行 span 观测。
- 建设 9 项轻量隔离任务评估，通过真实 API 与数据库检查引用、幂等、确认及权限边界，明确区分脚本 fixture 契约检查与真实模型 trial。

若已有 live 报告，可在第三条补充“使用某模型，对某日期版本完成 N 项各一次实测，记录 Token、延迟和失败分类”，N 与结果必须来自报告。没有用户规模、准确率提升、成本下降或吞吐实测时，不写这些数字；不要将课程学习效果与工程契约通过率混为一谈。


## 当前应能讲清的实现细节

受限执行器实现的是独立进程中的有限Python AST解释器，不将用户源码交给exec/eval，不接收imports/对象属性/函数定义/文件网络。隔离环境不继承API凭据；值、整数、步数、输出、CPU/墙钟受限；macOS不能把RLIMIT_AS当可靠OS内存隔离。检查由Agent提出，真实通过只说明所列检查成立。

练习核验和Agent任务评估职责不同：前者是运行中的模型辅助范围/题目/答案/来源核对；后者用代码检查实际数据库和执行结果。模型辅助核验可能出错，不能因为返回pass就宣称形式证明。实际引文必须存在、输入hash须匹配；修订题目后旧回执只保留生成时历史事实。

当前具备5种内置Capability和33项工具；Capability冻结策略并可阻止未完成solve直接结束，profile仍代表工具权限。已接入来源记录→记忆事实→引用画像的分层记忆，尚未接入完整第三方插件/多入口SDK/外部Agent委派；不要把当前能力选择说成自主多Agent协作。


## 检索与长期记忆：本轮可以展开讲的设计

检索是 Agent 的受控能力：先保留原查询，再按需消解当前用户指代、融合候选、重排；重排只能引用真实候选 ID 和原文片段，失败保留原查询结果。`read_material` 再按用户/课程/不可变版本读页或片段。额外请求受限且进入父子 span；精确原文和页码共同确定引用编号。小语料排名评估与真实模型报告是检查手段，不是普遍准确率提升的证据。

长期记忆分三层：真实用户输入/续答/作答记录是来源，带来源和修订的 Memory 是可召回事实，MemoryProfile 是引用现有事实的摘录画像。它们与窗口 context、运行 checkpoint 职责不同。Agent 不能从助手回答、题目或资料推断用户事实；保存需逐字匹配来源。偏好默认个人范围，课程事实按选中课程隔离；更改、忘记、修题或来源失效会使旧画像停止使用。画像生成后重新核验所有输入指纹，避免异步请求覆盖期间的新修改。

本轮增加 `read_material`、`recall_memory`、`consolidate_memory`、`forget_memory`，连同已有 `remember_memory` 进入同一工具权限、幂等回执和取消提交围栏。记忆整理显式触发；相同请求键复用原回执，失败/中断后换新键才重试。旧无来源数据完整保留但不作为当前已核实事实自动注入，用户可在设置里确认。彻底删除还清除引用它的画像派生文本。自然语言遗忘命令使用保守规则，不清楚时需追问；不宣称规则能理解所有自然语言意图。

可用于简历的新增条目：设计来源可追溯的长期记忆与提取式画像，实施修订冲突、偏好替换、遗忘失效和异步快照重检；实现保留原查询的检索增强、候选原文校验与版本化回读，使用隔离任务和真实模型链路验证。实现、接口和限制见 [RETRIEVAL_MEMORY.md](RETRIEVAL_MEMORY.md)。
