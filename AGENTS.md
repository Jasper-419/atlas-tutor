# Atlas 项目约定

- 产品统一命名为 Atlas，使用 Next.js/React 前端和 FastAPI 后端。
- 以桌面浏览器为设计、实现和验收目标；后续不为手机端安排适配、样式优化或验证工作。
- 优先快速完成可交付功能，避免冗余测试和额外流程。运行与当前改动直接相关的构建及必要的桌面交互检查即可。
- 界面保持简洁，参考 OpenAI、DeepSeek、Claude，以及 DeepSeek 官方 `deepseek-ai/deepseek-harness` 仓库中的设计实现。已阅读的源码和采用的规范见 `docs/DESIGN_NOTES.md`。
- 个人资料、学习偏好和设置通过当前页面上的弹窗打开，保留原页面状态。
- 每完成一个功能，按上述要求验证后，将该功能的改动单独提交并推送到 `atlas` 远端（`Jasper-419/atlas-tutor`）的 `main` 分支。用户当次指定的提交范围和分支优先。
