# Atlas FinanceBench 评测

使用 [Patronus AI 的 FinanceBench 公开版](https://github.com/patronus-ai/financebench/tree/cc39aeb4afdf33909ee1412188bf89035950c2eb)全部 **150 道原始题、84 份原始 PDF**，固定上游提交 `cc39aeb4afdf33909ee1412188bf89035950c2eb`。同目录的 `financebench.json` 记录原件哈希、题目 ID、上传文件哈希和原始页码区间。

## 原始资料如何导入

保留可直接导入的原件。公开 PDF 如果带加密标记且可用空密码打开，则生成未加密副本。文件超过 Atlas 的 250 页、400,000 提取字符或 12 MiB 限制时，按连续原始页号分卷，保留可复制的 PDF 书签。所有分卷上传到同一个课程。转换程序逐页核对复制前后的提取文本，并验证分卷范围完整覆盖原始页序。规则只用 PDF 的内容和大小。

84 份 PDF 共 12,013 页，对应 149 个上传文件。39 份 PDF 用空密码打开后生成副本，53 份 PDF 分成多个上传文件，两者有重叠。正式评测覆盖全部 150 道题。分卷处理由评测脚本完成，Atlas 接收符合现有上传限制的文件。

## 指标与运行条件

每题另建一个真实 `qa` Agent 会话，逐字发送官方 `question` 字段。该题对应的完整原始文档已通过 Atlas 上传和导入任务进入课程。标准答案和证据标签只用于评分。三组共用模型、工具和上下文规则，仅切换课程的检索引擎。评测关闭网页搜索。

本地千问运行使用 Qwen3-4B-Instruct 生成回答和执行 PageIndex 选页，使用 Qwen3-Embedding-0.6B 为资料片段和问题生成向量。导入后等待 Atlas 完成向量索引。模型 ID 和 Ollama 模型摘要写入报告。默认的云端评测命令读取本地模型配置，向量索引关闭。每个模型组合使用独立的输出目录。

- **证据页命中率 @5**。首次检索返回的至多五条引用中，至少一条指向正确文档的原始版本且页码范围覆盖任一标准证据页。全部证据页命中率使用相同候选，要求覆盖所有标准页。
- **首条引用命中率**。检查 Agent 最终回答出现的第一个 Atlas 格式 `[n]`，通过保存的编号解析来源、版本和页码。工具补查得到的引用也可以参与。缺少编号、引用无法解析、回答未完成或页码不匹配，均计为未命中。
- FinanceBench 页号从 0 开始。评分使用从 1 开始的原始 PDF 物理页号。分卷引用用「分卷原始起始页 + 卷内页号 − 1」还原，评分保留卷内和原始页码供核查。

每题每组运行一次，失败保留在分母里。结果衡量给定完整来源文档时的证据定位和引用，范围包含多页的引用按覆盖计分。财务答案的内容准确率需要另行评分。实时模型重跑可能产生不同回答。

模型服务返回 HTTP 402 或进程中断时，使用相同模型、样本和输出目录加 `--resume` 续跑。程序保留已结束的试验，将中断记录保存到 `interruptions.jsonl`。三组各有 150 条有效记录后才能核验正式结果。

## 复现

在仓库根目录使用 Python 3.12，按 `requirements.lock.txt` 安装依赖。脚本从固定上游版本下载资料，并在各自隔离的临时 SQLite 和文件目录中运行。安装 Ollama 后，用一个终端启动本地服务。

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=16384 \
  OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=2 ollama serve
```

在另一个终端下载模型并运行。

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull qwen3-embedding:0.6b
mkdir -p data/ollama
printf 'FROM qwen3-embedding:0.6b\nPARAMETER num_ctx 2048\n' > data/ollama/Embedding.Modelfile
ollama create atlas-qwen3-embedding:0.6b -f data/ollama/Embedding.Modelfile

# 下载公开数据，处理 84 份 PDF，并核对清单
python scripts/evaluate_financebench.py --prepare --manifest data/financebench/rebuilt.json
cmp evaluations/retrieval/financebench.json data/financebench/rebuilt.json

# 运行全部 150 道原始题，每题对照三组
PYTHONHASHSEED=0 python scripts/evaluate_financebench.py \
  --local-ollama --workers 2 --jobs 1 --output data/financebench/reproduction

# 用原始题目、页码映射和逐题记录重算分数，无需模型
python scripts/evaluate_financebench.py --verify-run data/financebench/reproduction
```

运行输出包含 `run.json`、`summary.json`、`page-indexes.json` 和 `cases.jsonl`。逐题记录提供候选页范围、正文首条引用、路由、工具和最终答案。数据许可见 [FinanceBench 数据卡](https://huggingface.co/datasets/PatronusAI/financebench)。
