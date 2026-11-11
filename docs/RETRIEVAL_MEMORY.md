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

没有实现 GraphRAG、独立向量记忆服务、全量对话自动提取、分布式 exactly-once 或通用外部 Agent 委派。当前是有来源、可撤回和可解释的应用内 Agent 能力，不声称 DeepTutor 全平台等价。更大真实语料、多 trial 和人工评审应由实际失败驱动。
