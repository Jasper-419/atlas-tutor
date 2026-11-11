# Atlas 与 DeepTutor：第二轮核心对照

2026-11-10，核对 DeepTutor 官方 main 与 Atlas 实际代码。保留 Atlas、Next.js/React + FastAPI、现有数据与简洁桌面；本轮按真实学习链路补齐，不搬入整套平台。

2026-11-11检索/记忆增量：已加入有限改写/重排、原查询降级与按需原文版本回读；长期记忆增加真实用户来源、修订/遗忘/失效、个人/课程召回和引用式画像，现为33项工具。保留旧数据与桌面设置弹窗，0008仅新增附表。详见 [检索与长期记忆](RETRIEVAL_MEMORY.md)；下面的29工具/0007为前一轮历史。

2026-11-11增量：当前已增加独立练习范围/题目核验、受限Python解题闭环、5种Capability/公共结果协议与完整内部模型开始/结束span。29项工具、9项隔离任务评估，原3000/8000已备份升级到0007并重启。实现和真实验收见[Agent讲解](AGENT_INTERVIEW.md)、[验证记录](VERIFICATION.md)。这里的对齐仍是选择性核心能力演进，不代表DeepTutor全平台功能一致。

## 本轮补齐

| 原有差距 | 当前实现 |
| --- | --- |
| 教学下一步主要依赖提示词 | 节点持久阶段、待答题卡、真实 next_action、先修约束、暂缓与跨会话续学；解释和自评不直接增加掌握度 |
| 学生说“没懂”之后缺少可追踪的讲法调整 | 引用真实用户原文的 helped/not_helped 反馈，关联当前节点；下一轮使用相关反馈调整讲法 |
| 复习只到节点，具体误解无法单独验证 | 误解级复习项与 PracticeTarget；新的独立开放迁移题通过且语义核验成立才标记解决，复答原题和无关高分不算 |
| 错题或错误答案键无法撤销影响 | 持久修复预览；作废/更正明确确认；开放题在预览时重判，确认只应用已展示结果；同步成绩、独立证据、误解、复习、掌握度和统计，保留原始答卷及审计 |
| 引用无法打开原文，更新后证据可能过期 | 资料版本与不可变文本快照、PDF页/章节定位、受权原文/附件下载；历史引用指向当时版本 |
| 上传同名/新版资料只能叠加，缓存讲义不失效 | 带 expected_version 的文本更新和文件替换，候选索引完成后原子提交；相关讲义标记过期，失败保留原内容；重新导入旧内容不会覆盖新版附件 |
| 研究与回答难以作为独立产物使用 | 完整研究报告可打开/导出；服务器从完成回答保存笔记，支持课程/个人范围、版本编辑和Markdown导出，保留来源与页码 |
| 路径预览没有直接装入学习诊断 | 输入具体误解、学习证据、复习、资料、每日时间与期限；预览快照包含资料版本和课程约束 |

关键模块：`backend/teaching.py`、`learning.py`、`assessment_repair.py`、`notes.py`、`library.py`、`core_api.py`、`models/{teaching,notebook,library}.py`。增量迁移为 `20261110_0006`。界面复用引用弹窗、笔记抽屉和聊天确认卡，没有新增复杂导航。

## 验证证据

- 全新SQLite升级到0006通过；真实主库迁移前创建备份。
- 资料/笔记/教学/修复集成使用真实FastAPI、SQLite与worker，仅题目审查模型为明确fixture。覆盖历史版本、权限、索引失败原子性、旧文件重导入、版本冲突、精确修复确认和统计重算。
- 定向服务smoke覆盖反馈/暂缓、迁移题语义证明、修复后新核验保留或重新打开误解、调用者rollback、幂等及私有答案保护。
- 真实DeepSeek：故意错误的验收题先判0分；提出修复预览，确认前分数不变，确认后变100分、掌握度55；真实反馈记录、Agent保存笔记及导出通过。临时账号清理。
- 桌面1440×900：19项真实操作与9项明确fixture评分展示通过，7张截图人工检查；旧评分被最新成绩/答案覆盖，作废题锁定，刷新一致。没有手机端工作。
- Next.js生产构建/TypeScript、后端compile与关键smoke通过；检查范围不包含性能、检索准确率或教学效果基准。

## 运行状态

2026-11-11更新：原3000/8000已加载可验证Agent增量，仍用原data/atlas.db。新增0007仅为PracticeBatch私有核验JSON字段；原32张Atlas表的原列/行内容摘要与备份一致。备份位于data/backups/before-verified-agent-20261111-000405/；下文是更早阶段的运行历史。

2026-11-10 20:54更新：已按用户要求重启原3000/8000并加载当前版本，继续使用原 `data/atlas.db`；32张Atlas表内容与重启前一致，已备份。当前状态与验证见 [验证记录](VERIFICATION.md#2026-11-10-2054--原数据服务已重启)。下文保留第二轮交付时的历史状态。

主数据已保留并升级，备份在 `data/backups/before-core-alignment-2-20261110.db`。现有3000/8000进程的停止操作被执行工具中止，未返回原因，因此没有声称它已加载本轮后端。

本轮桌面验收使用 `http://127.0.0.1:3002` 和独立的 `data/core2-verification/`；该库只用于验收，不替代原学习数据。正常使用原数据时，在项目根目录运行：

```bash
python3 scripts/dev.py --restart
```

该新增参数只识别当前项目目录和Atlas命令对应的端口进程，先正常退出再启动；遇到其他程序占用端口会拒绝停止。执行工具未代替用户运行这个停止动作。原启动终端的Ctrl+C后再次运行普通启动命令也可。

## 仍保留的差距

Atlas目前仍以文本教材为主。已提供有限Python AST解释器的真实执行校验；任意代码的容器/OS隔离、多模态原图证据、GraphRAG等多引擎知识库、块级笔记协作/完整插件生态、外部Agent/MCP委派及分层长期记忆仍保留差距。对应服务或模型未在本机配置的，不计作实机能力。

官方参考：[教学反馈](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/teaching.py)、[教学证据](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/lesson_evidence.py)、[题目来源与契约](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/semantic_assessment.py)、[掌握与导航](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/policy.py)、[题目修复](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/learning/service.py)、[笔记工作流](https://github.com/HKUDS/DeepTutor/blob/main/deeptutor/api/routers/co_writer.py)。
