# Atlas 后端实现与验证

**最新补充（2026-11-10）**：用户更新为可用 DeepSeek 密钥后，真实课程规划、RAG 讲义、流式 Tutor、结构化练习、开放题评分、研究与重规划均已成功验收。旧 OpenAI 额度限制仅为下文历史记录，已不代表当前状态；最新证据见 `docs/VERIFICATION.md`。DeepSeek 默认模型现为 `deepseek-flash`。

2026-11-10。实现范围：`backend/**`、`requirements.txt`、`alembic.ini`、`migrations/**`。接口严格遵循 `docs/API_CONTRACT.md`，另包含经主代理确认的节点编辑、知识依赖编辑与错题 `course_id` 字段。

## 已实现

- FastAPI `/api`：认证、资料/课程/节点/知识图、教学、Tutor SSE、练习与评分、错题、间隔复习、长期记忆、分析、数据导出/删除、持久化任务与 Trace 的全部约定接口。
- opaque 随机会话令牌，数据库仅保存令牌 SHA-256；密码使用带独立随机盐的 scrypt；Cookie HttpOnly + SameSite=Lax，可配置 Secure；注销撤销会话，删除账户验证密码。请求来源校验、上传整体与文件大小限制。所有私人对象均通过服务端用户/课程过滤；无权限返回 404。移除旧的固定默认管理员账号与泄露数据库 URL 的诊断代码。
- SQLAlchemy 业务数据持久化；SQLite 本地使用 WAL；PostgreSQL 使用 psycopg3。Alembic 冻结初始建表迁移及后续 pgvector 迁移；服务启动自动应用版本迁移。新 Atlas 表使用 `atlas_` 前缀，不迁移或删除旧项目的 `users` 数据。
- LangGraph 的公开资料研究 → 规划/综合 → 校验与保存工作流，默认持久化 SQLite checkpoint，可选 `CHECKPOINT_DATABASE_URL` 使用 PostgreSQL checkpointer。规划实际使用基础、目标水平、每天时间、截止期、学习偏好及已有掌握度；课程明确时间优先于个人偏好。DAG 进行节点、先修引用、无环与拓扑校验。手动编辑依赖创建路径版本；重规划保留已掌握节点，旧未掌握节点与答题/对话历史保留并退出当前路径。
- 任务保存在业务数据库，支持进度、失败、取消、重试；90 秒租约，20 秒心跳，每次 claim 有独立 worker token 防止过期 worker 覆盖新 worker。重试拥有独立 run_id。进程重启后，待执行任务继续处理，失去心跳的运行任务在租约到期后从 checkpoint 恢复。默认内嵌单 worker；可选 Celery + Redis，并通过 Celery beat 从数据库恢复遗留/过期任务。
- 真实 OpenAI 兼容接口，默认 `gpt-4o-mini`，支持 OpenAI base URL 和 DeepSeek；尊重本机 HTTP(S) 代理。模型调用记录模型名、服务实际返回的 token 用量和耗时。调用失败明确失败，不返回模板化 AI 成功结果。教学和 Tutor 会读取个人 explanation_style 等偏好、课程目标和长期记忆。
- PDF/TXT/MD/DOCX 真实解析，重叠分块、关键词排序、可配置 embedding、倒数排名融合、资料引用。SQLite 向量使用 JSON + Python cosine；PostgreSQL 同一列通过 SQLAlchemy `with_variant(Vector(), 'postgresql')` 使用**原生无固定维度 pgvector**，原生 `<=>` cosine 距离在数据库内执行，SQL 内先按用户/课程过滤再 top-K。查询发现已有向量维度不一致返回 409，提示恢复模型或重新上传资料。没有配置 embedding 时使用真实关键词检索。
- 配置 Tavily key 后调用真实搜索；没有 Tavily 时明确标记“公开文档 URL 抓取，未启用全网搜索”，读取用户提供、官方种子或模型建议的 URL。DNS 校验拒绝全部私有/回环/链路本地/保留地址，连接固定到已校验公有 IP；重定向逐次重校验。代理模式 CONNECT 也固定公有 IP，使用原域名 SNI 与 TLS 证书验证，不关闭证书校验。
- 选择题确定性评分；开放题使用真实模型 + rubric 并校验结果。标准答案仅在提交后返回，练习列表和学习数据导出也不泄露未提交答案。答题 request_id 幂等；每道题最近一次成绩只计一次，聚合到节点掌握度，80 分为掌握门槛并决定后继解锁；错题写入薄弱记忆，复习使用有界 SM-2 风格间隔规则。
- 三套明确标注的 Atlas 人工编写入门课：Python、LangGraph、RAG，各含真实教程正文与客观练习，可不调用模型体验注册 → 课程 → 学习 → 练习 → 掌握度/解锁 → 错题与复习闭环。

## 配置与启动

```sh
.venv-atlas/bin/python -m backend.bootstrap
.venv-atlas/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

默认 `DATABASE_URL=sqlite:///.../data/atlas.db`、`WORKER_MODE=embedded`、`ATLAS_CHECKPOINT_PATH=.../data/checkpoints.db`。容器使用 `backend/Dockerfile`；PostgreSQL 部署需要已安装 vector extension 的镜像，例如 `pgvector/pgvector:pg16`，数据库角色需可执行首次 `CREATE EXTENSION`。

模型配置：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`（兼容 `LLM_MODEL`），或 `DEEPSEEK_API_KEY`。Embedding 独立使用 `EMBEDDING_MODEL`、`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`；key/base URL 默认沿用聊天服务，但不假定聊天模型支持 embedding。其他配置：`TAVILY_API_KEY`、`COOKIE_SECURE`、`CORS_ORIGINS`、`MAX_UPLOAD_MB`、`REDIS_URL`、`CHECKPOINT_DATABASE_URL`。

独立 Celery：API 设置 `WORKER_MODE=celery`，并启动：

```sh
.venv-atlas/bin/celery -A backend.worker.celery_app worker --beat --loglevel=info
```

## 实际验证证据

- Python 3.12：`python -m compileall -q backend migrations` 通过。
- `python -m backend.tests.smoke` 通过：Cookie 会话、两用户课程/节点/资料/记忆/任务隔离、人工课程与真实客观题评分、答案保密、答题幂等、资料分块/关键词引用、导出、DAG 循环/外部节点拒绝与版本、任务取消重试、密码删除账户。
- `python -m backend.tests.workflow_smoke` 通过：**明确使用仅测试的模型 stub**，验证真实 LangGraph checkpoint 在 worker 被取消后可恢复、已完成研究不重复、来源持久化、租约 fencing、DAG、SSE 持久化与重放、取消旧 run fencing；不把该验证算作真实模型生成成功。
- 空 SQLite：Alembic upgrade、metadata drift check、downgrade、re-upgrade 通过。
- PostgreSQL：原生 VECTOR 方言类型、带用户/课程过滤和维度过滤的 SQL `<=>` top-K 编译，以及全部离线迁移 SQL（extension 与 JSON→VECTOR 转换）通过。当前 Docker 未启动，**未执行 PostgreSQL/pgvector 实例运行验收**。
- 防 SSRF：拒绝 127.0.0.1、169.254.169.254、::1、localhost、编码形式回环 IP、file URL、带凭据 URL、非允许端口。经本机代理真实读取 Python 官方教程，提取 17,864 字符；TLS 校验保持启用。
- 真实 OpenAI 请求已到达服务，当前环境现有配置返回 **HTTP 429，`error.code=credit_balance_exhausted`，`error.type=insufficient_quota`**，不是 rate_limit_exceeded。任务正确转为 failed 并记录 Trace，未生成假课程。密钥未修改、未输出。该旧配置的首次验收因此未完成真实模型成功链路；后续用户更换 DeepSeek 密钥后，上述成功链路已全部验收，详见最新验证记录。

## 明确限制

- 原生 pgvector 已实现，但当前没有运行中的 PostgreSQL/Docker 完成实例测试；无固定维度向量未创建 HNSW/IVFFlat 索引，首版为数据库原生精确 cosine 排序，适用于目前规模。SQLite 关键词候选和 cosine 在进程内执行。Embedding 服务、Tavily 与 Celery/Redis 的真实部署运行尚未在本机验证。
- 取消会立即改变业务任务状态并阻止后续保存；已经发出的模型/网页 HTTP 调用可能仍结束，不承诺撤销供应商已产生的费用。异常进程退出后最多等待租约约 90 秒再恢复。
- 上传限制默认 12 MB、PDF 250 页、提取文字 400,000 字符；不自带 OCR。只保留解析后的文本块，不保存原始二进制文件。
- 掌握度是透明的练习分数规则；学习分钟由阅读节点预计时间、练习与复习事件估算，不是实际在线计时，也未声称教育效果或测量过的检索准确率。重规划由用户明确触发，避免后台自行产生模型费用。
- 登录节流是单进程的有界内存实现；生产多实例应在入口统一限流。前端 API 同源代理需要正确保留 Cookie 与 Origin，并按实际域名设置 CORS_ORIGINS/COOKIE_SECURE。
