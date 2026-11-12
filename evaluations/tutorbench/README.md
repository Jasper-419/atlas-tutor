# Atlas 教学与跨会话评测

## 题集与对照

从 [Scale AI TutorBench](https://huggingface.co/datasets/ScaleAI/TutorBench) 的固定提交 `c70d2311cdca7129cab9376ba22eaa97c3cff3d7` 读取两份 Parquet。该版本含 1,473 行。保留所有 `SUBJECT = Computer Science` 且 `BATCH` 是三个纯文本任务之一的记录，共 84 条，适应性解释 39、反馈 20、提示 25。清单 `cohort.json` 保存原始文件哈希、切片哈希和所有题目 ID。保留原始语言与字段，没有按结果筛题。

两组都使用本地 Ollama 的 `qwen3:4b-instruct-2507-q4_K_M`、相同的 Tutor 核心指令、英文答复和最多 160 词的要求、逐字题干和最后一轮学生消息。解释题也包含数据集给出的初始解释。评分标准只交给评审。每轮生成温度为 0，种子为 42，输出上限 896 tokens。两组按同一随机种子排序，每组连续执行以复用 Ollama 提示词缓存。

- **Single call** 通过和 Atlas 共用的模型适配器调用一次 Qwen，没有工具或应用会话。
- **Atlas Tutor** 每道题用独立账号、新会话走真实 FastAPI、SQLite、Worker 和 Tutor Agent Loop。公开题目没有关联 Atlas 课程或历史记忆。应用保留自己的上下文构建、工具列表和运行策略，因此该对照衡量两种辅导交付方式。它不会单独归因给任一组件。
- 计分使用用户可见的正文。需要澄清时保留可见的追问。失败、取消或没有可见输出的试验留在分母并计零。记录实际模型调用、工具、用量和本机耗时。分组批处理、缓存及本机负载会影响耗时，吞吐与并发另需独立压测。

## 评分

使用独立本地评审 `gemma3:4b-it-q4_K_M` 对每道题的一对回答做逐项判定。评审看见原始对话、两条匿名回答和逐条评分规则。两组各有 42 次出现在 A 位，位置在任务类型内交替。判断格式固定为 0/1 数组。JSON 格式或传输异常最多补试两次，成功结果逐题持久化。

共有 829 条有效规则。按 [TutorBench 论文](https://arxiv.org/html/2510.02663v1#S2.SS3) 的权重设定，关键项为 5，普通项为 1，22 条负向关键项均为禁止性表述，违反才扣 5。4 条上游标记 `deleted` 的规则排除。单题得分为加减后的分数除以正向权重和，截在 0 到 1。按题目等权平均，报告三类分数、配对胜平负、固定种子的配对自助法 95% 区间。区间只反映这组题目在当前运行与评审下的差异。结果是本地评审的对照结果，官方榜单使用不同评审。

对 25 道提示题另发专门的匿名评分请求，显式标明任务类型，判断是否直接给出最终答案或完整解法。泄露率取 `hint-leakage.jsonl`。逐项评分请求中的通用泄露字段不用于汇总。

## 跨会话学习场景

`learning_scenarios.json` 预先写定 Python、LangGraph、RAG 各三个场景，每门课各含旧聊天、笔记、已评分练习。它们是可复现的人工设定，不代表真实学生抽样。记录经真实接口进入 Atlas，归档由实际学习记录整理接口执行。练习场景提交一次真实错题，再提交五次较新的练习，使旧错题越过常规上下文的最近五次尝试窗口。

每个场景用同一账号和课程分别新开两个会话。对照只在该次探测关闭长期记忆召回，课程资料、评分记录、近期尝试和其他工具保持可用。实验组保留正常召回。二者都由相同本地 Qwen 回答。评分检查返回的记录与预设原文一致（忽略空白和句号），下一步选项正确，以及两者同时达标。另通过记忆详情核查来源类型、记录 ID 和来源有效性。错题来自真实评分 API。这里的分数衡量记录使用和复习建议，学生学习增益需要真实学习实验。

## 复跑

在仓库根目录使用 Python 3.12 并安装项目锁定依赖。读取固定 Parquet 需要额外安装 `pyarrow==26.0.1`。下载需要约 1.1 GB。模型生成和评分都在本机运行。

```bash
python -m pip install pyarrow==26.0.1
python scripts/evaluate_tutorbench.py prepare --download

OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 \
  OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_NUM_PARALLEL=4 OLLAMA_MAX_LOADED_MODELS=1 \
  OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve
```

在另一个终端运行：

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull gemma3:4b-it-q4_K_M

PYTHONHASHSEED=0 python scripts/evaluate_tutorbench.py generate --jobs 4
PYTHONHASHSEED=0 python scripts/evaluate_learning_memory.py
PYTHONHASHSEED=0 python scripts/evaluate_tutorbench.py judge --jobs 4
PYTHONHASHSEED=0 python scripts/tutorbench_scoring.py --jobs 4
python scripts/evaluate_tutorbench.py report
```

默认输出目录为 `data/tutorbench/run/`。生成、跨会话和评审可在相同配置与代码下续跑，已落盘的试验不会重复。最终 `report` 核对 168 个响应和 84 份评分一一对应后计算聚合指标。原始响应、逐项判定与记忆来源只保留在本地输出。公开仓库保存评测代码、数据清单和人工设定的跨会话场景。

## 教学路由优化的留出评测

原有 84 道计算机科学题用于诊断。留出集在运行优化版前锁定，来自同一固定上游版本的 5 门其他学科。对每门学科的解释、反馈、提示任务分别按题目 ID 的加盐 SHA-256 排序，取前 2 道，共 30 道。清单 `routing-heldout.json` 保存选择规则、原始文件和题目切片校验和及全部题目 ID。该样本覆盖无 Atlas 课程上下文的纯文本教学。

诊断时按实际工具事件检查开销。84 道旧题中，Atlas 有 50 道没有发起工具调用，两组在这些同题上均发出 50 次模型请求。单次调用组输入 70,285 Token，Atlas 输入 256,285 Token，约为 3.65 倍。这个对照说明开销在首次输入就已出现，完整 Agent 的指令、工具定义和应用上下文各自的贡献需单独分析。

两组均通过真实的 FastAPI 和 Tutor worker 执行，相同本地 Qwen 模型、温度、种子、输出预算和问题顺序，每题使用独立账号及新会话。生成和评分分别保存代码、模型与题集标识。Gemma 使用匿名 A/B 顺序逐项评分，两个版本各占 15 个 A 位。报告保留失败、等待输入、可观测 Token、工具调用和优化版的实际路由。

准备原始 Parquet 后，在本目录运行以下命令。`--atlas-root` 指向对应的干净后端提交。运行时使用各自的临时数据库和同一个本机 Ollama。

```bash
python scripts/evaluate_tutorbench_routing.py prepare
python scripts/evaluate_tutorbench_routing.py generate --arm before --atlas-root /path/to/baseline-checkout
python scripts/evaluate_tutorbench_routing.py generate --arm after --atlas-root /path/to/optimized-checkout
python scripts/evaluate_tutorbench_routing.py judge
python scripts/evaluate_tutorbench_routing.py report
```

逐题生成结果和评分报告保存在 `data/tutorbench/routing-heldout/`。需要读取课程、历史作答或写入题卡的任务由工具任务评测覆盖。

工具任务清单 `routing_tool_tasks.json` 固定六个课程场景，分别验证资料检索与引用、历史作答读取和题卡入库。每版均经真实 Tutor API、工具处理器和临时数据库执行，使用相同本地模型。判断通过需要模型回答和实际业务结果满足对应断言，优化版另外核对走的是完整 Agent Loop。

```bash
python scripts/evaluate_tutor_routing_tools.py --atlas-source /path/to/baseline-checkout --output data/tutorbench/routing-tools/before
python scripts/evaluate_tutor_routing_tools.py --atlas-source /path/to/optimized-checkout --output data/tutorbench/routing-tools/after --require-route
```
