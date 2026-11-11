# Atlas 核心学习与 Agent

第二轮已补教学阶段/反馈/误解复习、题目修复重算、版本化原文与学习笔记；使用与运行状态见 [核心对齐记录](DEEPTUTOR_CORE_ALIGNMENT.md)。Agent工具策略、观测与面试演示见 [Agent讲解](AGENT_INTERVIEW.md)。

## 使用

运行 `python3 scripts/dev.py`，打开 `http://127.0.0.1:3000`。首页和 `/chat` 是学习对话，`/dashboard` 保留原工作台。现有课程、图谱、练习、复习、洞察和设置继续使用同一份数据。

- 可以直接输入学习目标，让 Atlas 创建课程并启动规划；也可选择已有课程/知识节点继续学习。
- 点击附件上传 PDF、TXT、Markdown 或 DOCX。尚未选课时自动创建资料课程；导入完成后点击“基于资料规划学习路径”，确认目标并发送。原始附件保存在受控本地数据目录，导入以持久任务执行。
- 选择学习、规划路径、复习或解题。解题无需先选课程，显示计划与实际计算校验；Tutor仍可查询进度与错题、检索资料、准备讲解、动态出题、评估真实答案并安排复习。
- 题卡提交后显示评分与补教。评分尚未完成时临时禁用；失败/取消且没有真实答题记录时可以重新提交。已评分的题目不会重复贡献独立掌握证据。
- Atlas 需要关键背景时会暂停提问，在输入框回答即可继续。已有路径的重大变更展示精确预览，明确接受后才应用；拒绝保留原路径，过期预览要求重新生成。
- 刷新或暂时离开不会取消后台对话。处理过程和题卡从服务器事件恢复；“停止”取消后续工作，已在停止前提交的真实评分继续保留。

## 实现边界

`backend/tutor/runner.py:run` 是实际Agent Loop：模型返回原生工具调用→服务端执行工具→结构化结果作为tool消息加入上下文→再次请求模型，直到结束、等待用户或触及预算。`backend/tutor/` 包含API、上下文、模型协议、精确路径预览、持久事件和worker；`backend/agent/` 承载工具契约、策略、回执执行器、准入与运行观测。模型选择沿用用户AI连接，支持OpenAI Chat Completions、OpenAI Responses和Anthropic Messages原生工具调用；模型本身也需支持工具调用。

默认最多6次带工具的模型请求，另有无工具收尾，12个逻辑工具调用，480秒活跃执行上限。模型瞬时异常仅在未输出文本时最多重试1次；读取工具瞬时异常最多重试1次；进程恢复另外消耗冻结的max_tool_recoveries（默认1），总attempts也持久限额。写工具不做异常盲重试；成功/失败回执可复用，非重放安全写入的未知结果先暂停核对，用户续答不能将它标为成功。暂停等待不计作持续运行，以上不构成金额硬配额。

33项工具分为独立handler并使用Pydantic参数契约。tutor/qa/research/planner/solve五种Capability声明指令、权限与结束核对，兼容旧profile；qa只读业务数据和必要会话控制。solve默认14次工具决策模型请求、20个逻辑工具调用，以容纳最多6步骤及收尾；服务端环境配置可降低或调整预算。schema筛选之外，执行器、dispatcher、领域服务分别检查策略、模式与用户归属。

`backend/solver.py` 管理本轮计划/执行凭据，`sandbox.py`在清空环境变量的独立子进程调用有限AST解释器。支持直接安全builtins、赋值、if/for/while与基本容器；禁止import、属性、函数定义、lambda、推导式、文件和网络。源码、AST、值大小、整数、循环步数、输出、CPU和墙钟均受限；macOS内存由值限制和RSS检查补充，不能声称完整OS沙箱或任意Python支持。Python步骤必须引用同一计划/步骤的最新通过凭据，推理步骤只记reasoned；完成前不能绕过solve_finish，提交别的题卡也不能跳过未完成解题。

聊天“运行详情”可看model/tool/context span、父子关系、主循环与内部模型用量；complete在请求前写开始占位，取消/超时缺失用量保持未知。汇总Token不与重叠Trace再相加，工具耗时包含子模型故不重复累加。导出仅白名单字段，不含模型messages、完整checkpoint或隐藏答案。

练习会先核对明确重点与当前节点范围，含混或跨领域时要求澄清；无论讲义是否过期都按focus检索。生成后独立核对重点、答案与真实资料引文，最多修正一次，失败不落库。`PracticeBatch.validation`保存私有输入/来源/题目合同指纹（0007迁移）；修题后当前摘要失效，历史事件标“生成时”核验。核验属模型辅助检查，不构成形式证明。

`atlas_tutor_sessions` 保存课程/节点/模式和历史摘要；`atlas_tutor_turns` 保存幂等请求、checkpoint、等待状态和执行租约；`atlas_tutor_events` 保存逐轮递增事件。客户端使用 `after_seq` 重连；完整历史题卡/引用从服务端投影恢复。worker 使用数据库认领和90秒租约，不依赖浏览器连接。服务正常退出会释放执行权，进程被强杀后在租约到期时接续。已提交工具通过确定性请求键避免恢复时重复副作用。

教学服务位于 `backend/learning.py`。模型不直接写掌握度；评分维度、首答证据、置信上限、先修解锁和复习间隔由后端规则维护。原有已掌握节点迁移保留基线。复习自评只调整间隔，真实答题才改变掌握证据。Agent 服务提交事务前检查当前 turn/status/worker，取消或过期执行者不能在模型返回后追加学习写入。

`backend/research.py` 按主题组织研究，优先使用已有资料，有限补查并生成带来源笔记。没有可读取证据时明确降级，不把模型建议冒充联网结果。`backend/workflows.py` 保留 LangGraph 规划/研究 checkpoint、取消、fencing，并处理持久导入。上传按内容去重，解析或向量准备失败不替换旧索引。

SQLite 可直接本地运行；PostgreSQL/Celery 等部署选项沿用原项目。Tutor worker在API生命周期运行，多API worker通过数据库租约协调；`WORKER_MODE`控制的是原有规划/研究/导入worker。可选embedding与Tavily需要单独配置；扫描PDF仍需先OCR。DeepTutor完整插件、外部Agent/MCP接入、GraphRAG与任意代码的OS隔离运行环境仍未引入。

## 验证

- `backend.tests.smoke`：已有账户、课程、评分、检索、导出/删除能力。
- `backend.tests.workflow_smoke`：LangGraph checkpoint、取消、任务恢复。
- `backend.tests.tutor_smoke`：真实 API/SQLite/worker/工具/教学状态，仅外部模型使用明确 fixture；覆盖隔离、幂等、事件续接、提问续答、取消写入栅栏、题卡评分、精确路径确认、过期预览和完成 checkpoint 恢复。
- 真实 DeepSeek：原生状态与检索工具、动态题卡、实际评分补教、ask/resume、路径拒绝；桌面真实题卡提交与刷新恢复。资料导入和接受预览的最终记录见 `VERIFICATION.md`。
- 三种模型协议均检查原生 tool call 请求转换与流式响应归一化；DeepSeek 以外的实际供应商连接本轮未调用。

本轮采用独立实现，参考 [DeepTutor 架构](https://github.com/HKUDS/DeepTutor/blob/main/docs-for-dev/ARCHITECTURE.md)、[共享 Agent Loop](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/agents/loop/agent_loop.py)、[工具协议](https://github.com/HKUDS/DeepTutor/blob/main/docs-for-dev/TOOLS_AND_CAPABILITIES.md)、[教学模式](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/capabilities/mastery/mode.py)和[掌握策略](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/mastery.py)。保留 Atlas 的数据模型与界面，按确认范围先完成核心闭环。


本轮检索与长期记忆：`retrieval_agent.py`提供有限改写/重排及失败降级、按需源版本回读；`memory/service.py`提供实际用户来源、修订冲突、个人/课程召回、遗忘/删除和引用画像。旧无来源记忆保留供确认；画像失效重检进入同一Agent工具/取消围栏。设置仍为原弹窗，详细使用和限制见 [RETRIEVAL_MEMORY.md](RETRIEVAL_MEMORY.md)。
