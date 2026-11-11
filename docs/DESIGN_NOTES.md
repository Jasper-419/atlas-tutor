# Atlas 界面方向

当前交付目标为桌面浏览器。用户已明确后续不考虑手机端，因此设计、实现和验收均以桌面端为准。

用户指定参考 OpenAI、DeepSeek、Claude。采用共同的交互思路：清晰的侧栏、克制的色彩、直接可输入的主任务、易读的内容、居中简洁的身份表单。Atlas 保留自己的名字、路径形标志和知识状态颜色，不使用其他产品的标志。

- 登录：让用户创建账号或继续学习；单列，邮箱与密码真实提交，不添加未实现的第三方登录。
- 工作台：回答“今天从哪里继续”；目标输入框可带入新课程，课程和复习使用真实数据。
- 课程：回答“为什么先学这些”；先修依赖、掌握状态和版本可查看、编辑。
- 学习：回答“这一节哪里还没理解”；正文、练习与 Tutor 形成工作区。
- 辅助页面：记忆可修正，任务可追踪，统计来自实际事件；空状态明确。

初始设计技能抽签为 Editorial greeting（seed 1938389447）。用户追加参考方向后，主体改为中性 AI 工作台；Instrument Sans 为正文，Instrument Serif 仅用于底部短句。静态检查的侧栏分组标题和知识节点序号有实际导航/数据用途；输入框焦点的轻描边用于可访问性。

参考入口：[ChatGPT](https://chatgpt.com/)、[DeepSeek](https://chat.deepseek.com/)、[Claude](https://claude.ai/)。

## 界面精简

根据用户截图，移除应用侧栏顶部品牌、个人空间身份块、侧栏装饰文案、工作台中英文结束语及全局页脚。侧栏从“新建课程”直接进入导航，账户和退出功能保留在底部；内容区保持清晰的学习目标输入和真实学习数据。

采用 [Anthropic 官方 frontend-design](https://skills.sh/anthropics/skills/frontend-design) 的内容优先与克制规范。可复用安装命令：`npx skills add https://github.com/anthropics/skills --skill frontend-design`。

账户入口参考用户提供的 OpenAI 菜单截图：侧栏底部只显示头像、用户名和展开按钮；个人资料、学习偏好、学习记忆、设置与隐私、退出登录集中在向上展开的菜单里。个人设置相关入口直接打开当前页面上的设置弹窗，不改变地址和原页面状态。弹窗分为个人资料、学习偏好、学习记忆、AI 连接、数据与隐私，桌面端左侧分类，手机端顶部横向分类。资料与偏好保留真实保存，记忆可在弹窗内增删改，支持导出和密码确认删除账号。支持键盘导航、Esc、点击背景或关闭按钮收起；关闭后恢复焦点和页面滚动。旧设置地址兼容为弹窗。

左侧导航顶端起排，主区以目标输入为焦点，不增加装饰区。收紧顶底间距，移除不再使用的样式，保留键盘焦点、移动端导航及表单交互。当前颜色与控件规范见下面的 DeepSeek Harness 参考。

本次通过生产构建和 TypeScript 检查，以及 12 项桌面/手机浏览器检查；包括删除区域确实不在 DOM、导航完整、账户操作、目标快捷键、手机菜单与学习工作区。课程创建页的三步序号表达实际流程；输入焦点与弹层的阴影用于交互状态。

## DeepSeek Harness 源码参考

已核对 DeepSeek 官网链接并阅读官方仓库 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 的实际前端源码。参考文件：

- [主题与色彩](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-theme/src/styles/design-platform.css)、[字体与圆角](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-theme/src/styles/base.css)：白色内容区、冷灰侧栏、分层的中性文字和轻分隔线、系统字体及统一圆角尺度。
- [按钮](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-primitives/src/Button.module.css)：36px 常规控件、12px 圆角、深色主按钮、低对比的悬停与选中状态。
- [弹窗](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-primitives/src/Modal.module.css)、[应用布局](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/src/client/AppFrame.module.css)、[侧栏](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-sidebar/src/client/SidebarRoot.module.css)：明确的内容层级、克制的弹层遮罩和有标签的紧凑导航。

Atlas 将这些规则应用于工作台、课程与学习区、登录表单、账户菜单和设置弹窗。使用内容白 `#ffffff`、侧栏 `#f9fafb`、正文 `#0f1115`、辅助文字 `#61666b`、8% 黑色分隔线；绿色 `#1b6e66` 表示学习掌握和确认状态。正文使用系统字体，Atlas 字标保留 Instrument Sans。按钮 12px、图标控件 8px、面板 16px、弹窗 28px；过渡使用 200ms 的统一曲线。色彩和尺寸集中到 CSS 变量，避免重复主题覆盖。实现继续使用现有 Next.js/React 组件及 FastAPI 接口。

## 课程与学习的桌面布局

继续阅读官方 [ConversationRoot](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-conversation/src/client/skeleton/ConversationRoot.module.css) 和 [SidebarRight](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-sidebar-right/src/client/shell/SidebarRight.module.css)：固定应用框架承载紧凑工具栏，正文和辅助区各自管理滚动；收起辅助区时保留内容组件。

课程详情将标题、主要操作、状态和进度集中到紧凑顶部，路径列表占主要区域，学习目标、投入时间与版本放入右侧信息栏。版本历史默认收起；图谱与资料使用同样的留白和分隔线。课程列表同步简化表面与标题文案。

学习区采用占满窗口的分栏工作区：学习路径、讲义/练习和 AI 导师。顶部可分别收起路径或导师；较窄的桌面窗口优先保留讲义和导师，打开路径时会为正文让出空间。正文和导师独立滚动，提问框固定在导师区底部，收起再展开保留提问草稿。阅读正文最大 760px，重复的讲义首标题只在与知识点标题完全一致时隐藏，不修改存储内容。桌面布局集中在 `frontend/app/learning-desktop.css`。

已通过生产构建和 27 项桌面交互检查，覆盖 1024、1440、1920 宽度及较矮桌面窗口，检查课程视图切换、编辑入口、独立滚动、侧栏切换、草稿保留、练习和设置弹窗。验收使用临时账号与人工编写的入门课，结束后已清理账号及数据。

## 练习复习与学习洞察

继续参考官方 [SegmentedTabs](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-primitives/src/SegmentedTabs.module.css)、[DisclosureRow](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-primitives/src/DisclosureRow.module.css) 和 [DetailDocument](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-primitives/src/DetailDocument.module.css)，采用紧凑分类、分隔线列表和可展开的次要信息。

复习页使用固定顶部与筛选工具栏，待复习项按行展示知识点、掌握度和实际操作。课程与关键词筛选同时作用于到期复习、错题及其数量；无匹配记录时提供清除筛选。错题默认收起作答和反馈，复习评分继续通过真实接口更新安排。

洞察页以四项指标概览和学习节奏为主，知识掌握使用可点击的列表，右侧集中展示待巩固知识与 AI 使用。用量明细默认折叠，无作答的平均分、无调用的平均耗时显示缺失标记。图表随实际容器宽度绘制，文字保持固定字号。知识点跳转补充了经过用户隔离的课程 ID 和节点状态；锁定节点进入课程路径，其余节点进入学习页。页面组件与桌面样式分别集中在 `frontend/components/progress.tsx` 和 `frontend/app/progress-desktop.css`。

生产构建及 32 项桌面检查已通过，覆盖空状态、课程和关键词筛选、错题反馈、复习评分保存、洞察数据一致性、知识点跳转、设置弹窗，以及 1024、1440、1920 宽度。临时账号使用人工编写课程的客观选择题产生真实记录，验收未调用模型，结束后已清理账号及数据。预览：[练习与复习](screenshots/review.jpg)、[学习洞察](screenshots/analytics.jpg)。

## 用户自定义模型 API

继续阅读 Harness 官方 [模型配置指南](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)、[CustomProviderCard](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-models/src/client/CustomProviderCard.tsx)、[ApiKeyInput](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-models/src/client/ApiKeyInput.tsx) 和 [operations](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-settings-models/src/client/operations.ts)。借鉴连接元数据与凭据分离、密钥只写、草稿密钥显隐、模型发现与手工填写并存、下次请求立即使用新配置等做法；保留 Atlas 的 Next.js/React 与 FastAPI 实现，不引入 Harness 插件运行时。

“设置 → AI 连接”继续使用当前页面弹窗，主面板先呈现当前使用的连接，再展示我的连接和添加入口。表单提供 DeepSeek、OpenAI、Anthropic 与自定义 API，支持 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 三种协议。连接名称、基础地址、协议、密钥、模型列表和默认模型可编辑；获取列表后勾选模型，也可直接填写 ID。测试仅发送一条简短模型请求；保存与测试相互独立。资料检索与联网研究放入折叠区，明确由服务端配置。

连接按用户存储，独立选择默认连接；首次添加自动使用，保留显式切回服务端默认的入口。课程规划、讲义、练习评估、研究综合和流式导师均通过用户配置解析，失败不会静默切换其他连接。模型调用保留真实用量与失败记录。凭据通过 Fernet 加密后写入独立表，读取只返回是否已保存，不进入学习数据导出。编辑留空保留原密钥，改变地址或协议必须重新输入或明确清除；匿名本地连接不会继承服务端密钥。

通过生产构建、TypeScript 检查、后端定向和原有冒烟检查；桌面验收覆盖 1024、1440、1920 宽度，以及添加、发现、测试、编辑、切换、删除、草稿密钥显隐与设置关闭后的原页面草稿保留。三种协议的请求、JSON 输出与流式响应使用本地模拟 API 验证，桌面验收还通过真实 Tutor SSE 路由验证用户所选连接；未调用付费服务。临时验收账号和学习数据均已清理。
