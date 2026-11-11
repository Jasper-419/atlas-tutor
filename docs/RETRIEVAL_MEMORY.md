# Atlas 检索与长期记忆

2026-11-11，保留 Atlas、Next.js/React + FastAPI、原有数据与桌面设置弹窗。本轮针对 Agent 的检索决策、来源核验和长期记忆控制，新增 4 项工具，现有工具总数 33，Capability 仍为 5 种。

参考 DeepTutor v1.7.2 / `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db` 的 [记忆记录/事实/画像](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/memory/store.py)、[偏好更新边界](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/memory/consolidator/modes/update.py)与[排名评估](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/rag/eval/metrics.py)。Atlas 独立实现于现有 SQLAlchemy、领域服务及原生 AgentLoop，没有引入文件型记忆存储、大型 RAG 框架或新必需服务。

## 检索是可检查的执行过程

`backend/retrieval_agent.py` 在兼容原 `search` 的基础上提供 `retrieve`。技术编号与单字符可检索；保留原查询，只在指代含混且存在已授权上下文，或明确 enhanced 模式时，有限扩展、改写并融合候选。最多一次改写和一次重排。清晰 auto 查询不额外调用这两项模型；lexical 不调用模型。

重排必须完整排列实际候选 ID，并逐字引用候选 excerpt；未知/重复/遗漏 ID、虚构片段、模型异常都会降级。原文从数据库读取，模型不能生成来源。已有向量但查询向量不可用时标记 `embedding_unavailable`；维度变化与其他混合检索异常也给出降级状态，原本无向量的词法库不显示错误。

Agent 可先 `retrieve_materials` 找候选，再 `read_material` 按 source_id、version、page 或 chunk_indices 回读不可变快照。禁止路径输入；所有操作强制用户/课程归属，校验快照哈希并限制长度。不同页、不同原文范围不会错误共用引用编号。检索状态事件与额外模型的父子 span 可在原运行详情中检查；脱敏导出仅含白名单计数/状态。

## 索引兼容与恢复

向量索引记录 embedding 协议、端点与模型的签名，以及实际维度。切换到同维度的另一模型时，检索跳过不兼容的向量，仍可用关键词检索原资料。迁移 0009 保留旧向量，缺少身份的旧索引显示待重建。运行详情会显示降级原因。

配置 embedding 后，可从课程资料详情发起重建。后台导入、替换和重建会保存已经校验的向量批次。同一任务在恢复或重试时复用与当前资料片段和模型签名匹配的批次。候选索引全部通过校验后与任务完成状态一并提交。重建只更新向量，原文版本、片段标识和历史引用继续可读。重建期间修改原文或切换已发布索引会阻止旧任务提交。

`.venv-atlas/bin/python -m backend.tests.index_recovery_smoke` 使用隔离 SQLite、真实任务和受控向量响应检查中断、租约接管、重试复用和陈旧任务拒绝。

## 课程知识库检索引擎

每门课程的资料构成一个知识库。新课程和沿用旧默认设置的课程使用自动检索，升级保留明确选过的手动引擎。上传先提交原文和可搜索片段；带原件的文本 PDF 和配置了 Embedding 的资料再补建页级或向量索引。「课程资料 → 高级检索设置」可手动指定引擎。切换和重建保留原始资料、版本、片段与历史引用。

| 引擎 | 检索方式 | 使用条件 |
| --- | --- | --- |
| Atlas | 原有词法检索与可选向量融合 | 作为通用后备和手动选项 |
| LlamaIndex | `BM25Retriever` 与 `SimpleVectorStore` 分别召回，使用 RRF 融合 | 向量需配置 `EMBEDDING_MODEL`、`EMBEDDING_BASE_URL` 和服务所需的密钥；未配置时使用 BM25 |
| PageIndex | PageIndex Flash 在本地提取 PDF 章节树，Atlas 在限定的候选页中选取证据 | 至少一份带文本层且保留原件的 PDF；其他格式由 Atlas 检索 |
| LightRAG | LightRAG SDK 在课程独立工作区提取实体和关系，使用 `mix` 检索图谱与向量证据 | 可用的聊天模型和 Embedding 服务；每库最多 600 个资料片段 |

自动模式按问题路由。常规查询用 LlamaIndex，页码与章节问题优先检索已就绪的 PageIndex，明确涉及多份资料的关系问题优先使用与当前资料清单匹配的 LightRAG。通用检索为空时，LLM 可以从已就绪、符合资料范围的引擎中选择一次补查。模型选择失败后保留已有检索结果。

已有 DeepSeek 聊天配置可用于 PageIndex 候选页判断与 LightRAG 实体关系提取。向量请求使用独立的 Embedding 配置。自动模式会在课程对话中补建缺失的旧资料索引，LlamaIndex 本地索引限 3,000 个片段。自动图谱需要用户明确询问跨资料关系、至少两份资料且总计不超过 40 个片段，每个资料版本与 Embedding 配置组合最多自动构建一次，课程自动构建间隔一小时。图谱构建期间继续通用检索。

自动 PageIndex 逐个资料版本构建，LightRAG 图谱绑定完整资料清单。资料变化时旧图谱停止用于新查询。LightRAG 图谱由 SDK 在 Atlas 本地进程中构建，部署时 API 与 Worker 需共享 `ATLAS_DATA_DIR` 下的 `knowledge/` 目录。

Agent 继续通过 `retrieve_materials` 选取候选，通过 `read_material` 回读原文。PageIndex 的页码和 LightRAG 的片段引用都会映射回所属课程的 Atlas 快照。Agent 运行详情可看到使用的引擎和回退原因。

## 记忆、画像与上下文各有职责

| 层次 | 持久内容 | 约束 |
| --- | --- | --- |
| 原始来源 | 真实 turn 输入、用户续答或 Attempt 答卷 | 助手输出、资料和生成题干不能作为用户陈述 |
| 记忆事实 | 原 Memory + metadata/revision/evidence | Agent 保存须逐字匹配当前用户原文；手动修改明确标来源；带修订冲突检查 |
| 学习画像 | MemoryProfile 的引用摘录 | 只能引用当前事实 ID/revision/quote，不推断新事实；异步返回后重新核对完整事实指纹 |
| 本轮 context | 有界、相关且当前有效的事实/画像 | 按需组装，不是另一个持久记忆；旧画像不注入 |
| 运行 checkpoint | 工具调用、回执、控制阶段 | 用于恢复执行，不替代用户事实来源 |

偏好默认个人范围，其余自动使用所选课程；用户可明确指定范围。跨会话召回只包含个人及当前选中课程，有依据的学习偏好可优先返回。相同 facet 的新偏好替换旧偏好。来源变化、评分修复、手动纠正、遗忘或删除后，旧事实/画像停止使用；替换后不会把更早的偏好复活。

`consolidate_memory` 或设置中的整理动作显式触发画像生成。它先提交 pending 回执释放数据库锁，模型返回后重锁并重检，只有 ready 可提供 claims。模型不可用可提供明确标记的安全摘录降级；格式或引用不合法不发布画像。相同 request_id 复用原状态；失败或中断后使用新键重试。Agent 写入沿用取消/租约提交围栏。

“忘记”停用事实并保留可审查修订；“彻底删除”清除事实、附表与引用它的画像派生文本。遗忘工具要求明确的当前命令，否定删除和无关术语不授权；保守规则不能理解所有语义，含混请求应由 Agent 追问。既有聊天、原始答卷和其他独立记录仍按各自数据管理入口管理。

0008 仅增加 4 张附表，不重写原 Memory 行。历史无来源记忆继续显示，但标为未确认，不自动作为已核实事实注入。用户可在设置点击确认原文，再进入召回。设置内提供来源链接、修订历史、409 草稿保留、纠正/忘记/删除和折叠画像，不增加主导航。

## 跨记录增量整理

从「设置 → 学习记忆 → 整理学习记录」按需处理聊天、笔记和已评分练习。可选择全部记录或单个课程，入库仍保留原有个人或课程范围。聊天和笔记由模型挑选可逐字核对的摘录，练习使用真实答卷与保存的评分。旧答卷可以直接核对题目版本和评分。

每批只读取尚未整理的记录版本或长记录的下一段。保存前重新核对来源，来源、记忆和游标在同一事务提交。归一后相同的摘录在同范围内合并出处，保留修订历史。笔记更新或练习作废会使对应依据失效，仍有独立有效依据的记忆可继续召回。更正、忘记或删除会留下内容摘要用于阻止自动重新加入，原聊天、笔记和答卷继续由各自入口管理。

「核查来源」直接检查当前记录，不调用模型。新增摘录进入现有 Agent 召回；学习画像继续从明确保存或确认的记忆整理。运行 `.venv-atlas/bin/python -m backend.tests.record_memory_smoke` 可验证增量、合并、来源竞争和忘记后的行为。

## 有限验证与实际边界

- `backend.tests.retrieval_smoke`：用户/课程/来源范围、技术编号、降级与非法重排、真实历史版本/页码、重复证据不抬分。
- `backend.tests.memory_provenance_smoke`：真实用户原文、修改/忘记/失效、冲突/幂等、异步快照/取消、旧数据升级保留。
- `backend.tests.memory_agent_integration_smoke`：实际 worker、工具、API、context、权限与来源闭环；仅外部模型响应为 fixture，不是模型能力分数。
- `scripts/evaluate_retrieval.py --mode lexical|fixture|live --k 3`：6 个隔离合成样例，实际 facade 的 Recall/MRR/nDCG；live 本次 6/6 未降级，MRR@3、nDCG@3、Recall@3 为 1.0。小语料不能证明真实大库准确率提升或教学质量。报告在 `evaluations/retrieval/`。
- 真实 `deepseek-flash`：保存实际用户偏好→摘录画像→新会话 recall→forget→不再召回且画像 stale，3 个真实 Agent 轮次通过；报告 `data/memory-evals/live.json`。
- 现有 Tutor 生命周期、修题/笔记 smoke 与 9 项隔离 Agent 任务契约通过；Next.js 生产构建和 TypeScript 通过。

尚未接入 Microsoft GraphRAG、独立向量记忆服务、全量对话自动提取、分布式 exactly-once 或通用外部 Agent 委派。当前是有来源、可撤回和可解释的应用内 Agent 能力。更大真实语料、多 trial 和人工评审应由实际失败驱动。
