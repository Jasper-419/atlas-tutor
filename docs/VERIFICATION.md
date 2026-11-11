# Atlas 验证记录

日期：2026-11-10。环境：macOS、Node.js 22.23.2、Python 3.12.8，SQLite 本地模式。

## 已执行

- Next.js 16.4.6 生产构建、TypeScript 检查通过。
- npm 依赖审计：0 个已知漏洞（修复了初始安装的 source-map-js 间接依赖）。
- 后端 Python 编译与两份核心冒烟通过；SQLite 空库迁移、回滚、升级及 ORM metadata 差异检查通过。
- PostgreSQL/pgvector 类型、带课程/用户过滤的原生向量排序及离线迁移 SQL 编译通过。
- 真实公开 Python 文档读取成功；防 SSRF 拒绝私有、回环、链路本地和不允许的协议/端口。
- 首次使用旧 OpenAI 配置时返回 HTTP 429，失败处理已验证；更换 DeepSeek 密钥后，以下真实 AI 成功流程已全部通过。
- Chrome 浏览器：通过真实表单注册；进入工作台；加入人工课程；显示知识图谱；进入讲义；提交练习；反馈在进度刷新后仍可见；新增学习记忆；分析页显示实际作答；复习、任务、设置、课程页面可访问；导出成功。
- 手机宽度 390 px：无横向溢出，导航可以打开关闭。

## 最终复验

- 独立审查发现的 4 项 Important 均已修复：任务取消不能覆盖成功状态；未答练习不能跳过掌握门槛；PostgreSQL 首次练习生成锁定实际节点；讲义引用在刷新后恢复。
- 同步修复薄弱记忆的聚合判定、答题反馈的跨页面恢复、PostgreSQL 向量值导出和配置空值回退。
- 修复后的两份后端检查、TypeScript 与 Next.js 生产构建均再次通过；Compose 配置解析和 Git whitespace 检查通过。
- 新版前端实际通过 17 项 Chrome UI 检查，浏览器异常为 0；目标输入框能够将目标带入课程创建表单。
- `python3 scripts/dev.py --setup-only` 成功；一键启动后网页、同源 API 代理、登录态接口状态符合预期。

## 视觉验收

按用户追加的 OpenAI、DeepSeek、Claude 参考方向，将登录页改为单列居中，将工作台改为中性色侧栏、目标输入框与内容优先的布局。保留 Atlas 自有符号和青绿色知识状态。

已查看桌面和 390 px 手机截图：无横向溢出；课程、图谱和学习工作区可操作。设计检查无 FAIL；侧栏分组标题和知识节点序号为功能信息，焦点描边为键盘输入反馈。居中登录页保留留白，辅助说明采用较小字号。

## DeepSeek 真实 AI 验收

用户更新 `.env` 后，已验证密钥（模型列表 HTTP 200），将过期默认模型名更新为当前可用的 `deepseek-flash`，并重启服务加载配置。常规生成关闭 DeepSeek 思考模式，保留 OpenAI 兼容路径。

- 真实生成 4 个知识节点、3 条先修边，并通过 DAG 校验与持久化。
- 真实生成 1,726 字符讲义，包含 6 个检索引用，重新读取后引用仍存在。
- 经 Next.js 同源代理完成 SSE，收到 45 个增量事件；回答和对话保存成功。
- 真实生成 3 道结构化练习，含选择题和开放题，提交前不返回标准答案。
- 开放题真实 Rubric 评分与掌握度更新成功；未完成的题目不会被当作已掌握。
- 真实抓取 Python 官方资料并使用模型综合研究笔记，新增 2 条资料记录。
- 真实重规划成功，保留路径历史，版本从 1 更新为 2。
- 本次完整验收耗时约 40 秒，实际记录 7 次模型调用、19,125 个输入 Token、4,474 个输出 Token；该单次结果不是性能基准。
- 验收使用临时账号，结束后已删除临时账号、课程和资料；没有修改用户密钥或其他学习数据。
- 额外发现并修复：Tutor 对“换个例子讲解这一节”等隐式追问，会带当前节点标题与学习目标一起检索，保证相关资料可进入回答上下文。定向检查验证失败后已修复。
- 修复后又执行一次真实 DeepSeek 追问：收到 30 个 SSE 增量事件、1 条有效资料引用；引用随对话保存，临时账号已清理。

## 验证边界

DeepSeek 真实模型成功链路已验收。使用测试 stub 的检查仅用于恢复和异常语义，两者证据分开记录。当前 RAG 为关键词检索；未配置 embedding 服务，不声称已经验证语义检索。

Docker daemon 未启动，未运行整套容器；PostgreSQL/pgvector 实例、Redis/Celery、Tavily、embedding 服务未实机验收。不声称存在实测成功率、检索 Recall、故障恢复成功率、P95 延迟或教学效果数据。


## 2026-11-10 · DeepTutor 核心对齐

本轮保留Atlas主体和既有数据，完成持久共享Tutor、原生工具、教学证据、动态补题、具体误解记忆、持久导入/研究和聊天主入口。细节见[Tutor说明](TUTOR_CORE.md)。

- 新增0004/0005迁移，真实数据库迁移前通过SQLite backup保存快照。
- Next.js生产构建、TypeScript、后端compile、ruff（新增核心模块）、git diff --check、Compose配置解析通过。
- 原有账户smoke、workflow_smoke、AI连接smoke通过；新增一个Tutor集成smoke，真实API/SQLite/worker运行，仅外部模型使用明确fixture。
- Tutor smoke覆盖跨用户隔离、入队幂等、单活跃轮次、持久SSE游标、提问续答、运行取消、选择/开放题评分与补教、精确路径接受/拒绝/过期、租约恢复幂等及生命周期重启。
- 独立审查的4项Important已修复并定向验证：取消后模型返回不能提交成绩/新题；ask_user续答可作为真实评分输入；失败/取消且无Attempt的题卡恢复重试；已完成checkpoint恢复直接收尾不再调用模型。
- 真实DeepSeek工具验证：get_learning_state + retrieve_materials；generate_practice；真实题卡评分（单份首答掌握度上限55）；ask_user/respond；propose_path_change拒绝后版本不变。临时API验收账号均已清理。
- 真实资料验收：从未选课程状态上传Markdown，持久导入成功；调用plan_course基于上传资料生成6节点路径和3条来源记录；propose_path_change接受前版本1、明确接受后版本2；导出的学习数据包含新会话与轮次。临时账号及原始附件随后清理。
- 真实Chrome桌面验收：已有Python课新会话→查询进度→动态选择/开放题→刻意错答→0分评分与针对性补教；刷新恢复题卡、答案、评分及全文。另验证开放题评分停止后无Attempt则解锁重试，刷新仍可重试，再提交进入pending；停止前已评分的题保持锁定。仅新增独立验收会话与作答，未删除既有学习数据。
- 三种协议的原生tool call请求转换/流响应归一化通过本地wire fixture；实际模型使用DeepSeek，未调用其他供应商付费账号。

本轮验证目标为桌面；未安排手机端工作。Docker实际容器、PostgreSQL实例、Redis/Celery、可选Tavily与embedding仍保留原验证边界。


## 2026-11-10 · 第二轮核心补齐

教学阶段/反馈/暂缓、误解迁移验证、题目争议修复、原文版本与原子更新、笔记保存编辑导出已接通。详见 [核心对照](DEEPTUTOR_CORE_ALIGNMENT.md)。

- 0006 fresh SQLite迁移通过，真实主库升级前保存备份。
- notebook_repair_smoke、教学定向smoke、核心API集成、旧题目/账户/工作流/Tutor关键检查通过；未新增覆盖率或压测平台。
- 三项独立审查修复均有针对证据：旧资料重导入保留当前附件；最新Attempt覆盖历史assessment并标作废；修复预览保存新的target_checks，确认零模型调用。
- 真实DeepSeek纠错：错误答案键使正确作答0分，确认修复前保持0，接受后100/掌握度55；真实记录not_helped与save_note/导出成功。临时账号删除。
- 隔离桌面19项真实交互+9项评分fixture通过，7张1440×900截图已看；临时账号清理，未触碰正式用户学习数据。
- 原3000/8000重启被工具中止（未给原因），正式服务未声称已加载新版；3002/8002使用独立验收库。已准备仅重启当前项目的 --restart 命令，帮助/语法检查通过，停止动作未代用户执行。

## 2026-11-10 · Agent 应用与运行时工程

本轮增加类型化24工具注册与独立handler、四种profile、统一准入/冻结策略、工具回执执行器、模型与工具span、脱敏观测API及桌面弹窗。没有增加数据表或迁移，继续使用0006。

- 最终 `compileall`、`git diff --check`、既有 `backend.tests.tutor_smoke` 通过。Tutor smoke仅替换外部模型，真实API/worker/数据库继续覆盖题卡、作答、人工确认、取消提交围栏与恢复。
- 最终隔离任务评估7/7通过，51项代码检查；外部provider为明确fixture，不是模型效果。最终报告：fixture-delivery（本地 `data/agent-evals/fixture-delivery/report.md`）。
- 真实 `deepseek-flash` 默认4项各一次，自动契约4/4通过；出题focus与节点主题偏离被人工记录，不能称语义任务成功率100%。Token、耗时、内部模型请求的范围和重叠见 [评估说明](AGENT_EVALUATION.md) 与 live报告（本地 `data/agent-evals/live-initial/report.md`）。
- 另做两组必要定向检查，未新增冗余测试框架：内存执行器检查只读瞬时重试、写入不盲重试、成功/失败回执复用、同ID异参拒绝、qa写拒绝、不确定写续答保持uncertain、持久化恢复上限与工具预算；真实隔离ASGI检查模型瞬时重试、输出文本后不重试、耗尽停止、拒绝客户端提额、脱敏导出与未知用量保持null。两组隔离检查均通过。
- 独立代码审查发现的两项P2已修复并复核：execution_review普通续答不再把原操作标成功；恢复不会重新获得无限工具尝试额度。
- 最终Next.js生产构建、TypeScript与设计lint通过；1440×900桌面18项交互、3张截图检查通过。模型/工具span、缺失用量、策略、schema、脱敏下载、Esc与关闭后停止请求均有证据。

新版独立预览保留在 `http://127.0.0.1:3010` / API8010，数据目录 `data/agent-preview/`。旧3000/8000进程未操作，不代表已加载本轮后端。日常数据仍在原目录；正常激活原数据版本的命令继续为 `python3 scripts/dev.py --restart`。验证不包含生产负载、任意外部副作用的exactly-once、全面攻击测试或教学效果；沿用此前Docker/PostgreSQL/Redis/Celery/embedding验证边界。

## 2026-11-10 20:54 · 原数据服务已重启

用户明确要求后，已执行 `python3 scripts/dev.py --restart`，原3000/8000服务已加载当前代码。启动前以SQLite backup保存业务库和checkpoint，完整性检查通过；备份目录为 `data/backups/before-restart-20261110-205411/`。启动后原 `data/atlas.db` 的32张Atlas表记录数与内容摘要均与备份前一致，schema仍为0006。

网页3000返回200，8000健康检查通过；OpenAPI包含新Agent观测路由与NewTurn.profile，通过3000同源代理访问受保护接口正确返回401。此条更新取代上文“原3000/8000尚未加载新版”的历史运行状态。

## 2026-11-11 · 可验证 Agent 能力

已完成练习范围/独立题目核验/一次修正、私有合同与版本绑定、有限Python执行解题、5种Capability/公共结果协议、主循环与内部模型父子观测。保留现有Atlas与桌面界面。

- 真实隔离API/worker/Python集成 `verified_agent_smoke` 通过：提前文字完成被撤回，失败执行不能完成步骤，修正后凭据完成，qa拒绝执行、幂等、/answers不能跳过未完成solve、嵌套用量汇总与根span耗时、取消请求开始占位/未知Token、脱敏导出。
- `practice_contracts_smoke` 通过：含混/跨域零写，重点检索，严格hash/逐题/真实引文，一次修正，取消/来源变化拒绝，真实修题后旧回执失效、历史无指纹保守投影；必要notebook_repair_smoke和原Tutor回归通过。
- `solver_smoke` 通过：实际子进程/有限AST、危险语法拒绝、循环/值/输出限制、CPU/墙钟、取消kill/reap、证据跨步骤/版本拒绝、无理由重规划拒绝。macOS限制与语义子集写入工具limits，不声称任意Python或OS沙箱。
- 默认fixture任务评估9/9通过，真实API/数据库/执行器，仅外部模型明确fixture；报告（本地 `data/agent-evals/verified-agent-fixture-final/report.md`）。
- 真实DeepSeek明确focus练习、含混focus澄清、受限Python求和三项各一次，通过有限合同检查；真实调用/Token与边界见[评估说明](AGENT_EVALUATION.md)。求和案例实际for循环/print得到5050后3项检查通过，同计划步骤凭据完成。没有把模型辅助核验或单次结果称总体质量成功率。
- 独立审查3项P2均修复复核：当前题目回执绑定私有合同、/answers生命周期门槛、内部请求在await前持久开始span。历史核验标为“生成时”，不认证修订后的当前题。
- 最终Next.js生产构建/TypeScript、Python编译与git whitespace检查通过。原3000桌面1440×900的22项交互检查通过，4张截图已看；真实请求的stdout为空，UI显示“无输出”，5050来自实际checks的值，未冒称stdout。临时账号/数据删除且隔离浏览器关闭。之后移除紧凑计划重复summary并要求模型避免内部ID与重复计划，生产构建再次通过；未重复消耗模型。

激活前通过SQLite backup保存原业务库/checkpoints（完整性通过），目录data/backups/before-verified-agent-20261111-000405/。原库升级0007，原32张Atlas表的原列/行内容摘要保留；3000/8000已重启加载当前代码。UI临时账号清理后再次逐表比对通过。没有修改真实模型密钥、正式用户学习记录或切换到验收库。

本轮边界：主Loop仍使用自身持久状态，固定LangGraph任务保持独立；未声称完整DeepTutor平台、多模态原图、外部MCP/子Agent、分层记忆或任意代码隔离已实现。当前模型辅助练习核验可能出错；程序检查只覆盖列出的输入与断言。Docker/PostgreSQL/Redis/Celery/embedding实机验证边界沿用前文。


## 2026-11-11 · 检索与长期记忆

- 检索 facade：技术编号/单字符、原查询保留、有限上下文改写/融合、候选ID与逐字quote重排校验、失败/向量不可用降级、不可变版本/页/片段回读。
- 记忆：实际用户来源、课程/个人范围、修订/冲突、同facet偏好替换、忘记/删除、失效过滤与提取画像。迁移0008仅新增4张附表，旧无来源数据保留供用户确认。工具33项，Capability仍5种。
- 运行命令：`backend.tests.retrieval_smoke`、`memory_provenance_smoke`、`memory_agent_integration_smoke`、`tutor_smoke`、`notebook_repair_smoke`通过；外部模型fixture与真实数据库/领域/worker明确区分。9项现有Agent fixture通过，报告 `data/agent-evals/retrieval-memory-fixture/`。
- 真实模型：`scripts/evaluate_retrieval.py --mode live --k 3`的6个隔离合成例全部scored、无降级；Recall/MRR/nDCG@3=1.0，仅说明该小语料结果，不能外推通用质量。报告 `evaluations/retrieval/live.json`。
- 真实deepseek-flash三个Agent轮次：remember原文→consolidate引用画像→新会话recall→forget→不再召回且画像stale；9项实际状态检查通过，报告 `data/memory-evals/live.json`。
- 定向独立审查4项问题已修复并复核：跨页/截断引用碰撞、永久删除的画像派生文本残留、缺失查询向量的静默降级、否定删除/无关forgetting误授权。
- Next.js/TypeScript生产构建 `ATLAS_BUILD_DIR=.next/retrieval-memory API_URL=http://127.0.0.1:8000 npm run build`通过；本次自动生成的tsconfig include已清理。后端compile和diff whitespace检查通过。
- 原3000/8000使用 `scripts/dev.py --restart` 安全重启，`/health`=ok、桌面/chat=200，schema=`20261111_0008`。升级前业务/检查点SQLite备份及完整性检查通过，备份 `data/backups/before-retrieval-memory-20261111-003658/`。原32张表180行按原列逐行排序摘要全部一致。

实现及可陈述边界见 [RETRIEVAL_MEMORY.md](RETRIEVAL_MEMORY.md)，本轮未做手机端、负载基准或总体教学/记忆质量评估。

桌面1440×900追加验收：20项操作及控件样式修正后5项复核通过，覆盖默认折叠且零自动整理请求、历史记忆确认、409草稿保留/读取最新版本、来源/修订、跨会话来源链接及草稿隔离、一次真实DeepSeek整理、scope切换、遗忘后画像stale、历史过滤、永久删除及错误来源不回退。仅使用独立浏览器与临时账号；验收账号已清理。原32张表180行摘要再次核对一致，保留证据 `data/memory-evals/original-data-preservation.json`。

最终收尾：样式修正后生产构建再次通过，所有临时浏览器/context关闭、三轮临时账号均清理；原32张表180行最终摘要仍与升级前备份一致。
