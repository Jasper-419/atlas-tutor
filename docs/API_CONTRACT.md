# Atlas 前后端接口约定

所有业务路由以 `/api` 开头。JSON 使用 snake_case，ID 除用户为整数外均为字符串。前端通过 Next.js 同源代理访问 FastAPI。认证使用 HttpOnly Cookie `atlas_session`，响应不得含凭据。

## 数据对象

`User`: `{id:number,email,full_name,is_admin,preferences?:object}`。

`Node`: `{id,course_id,title,summary,objective,content:string|null,estimated_minutes:number,difficulty:string,position:number,status:'locked'|'available'|'learning'|'mastered',mastery:number}`，mastery 范围 0–100。

Node 另返回 `lesson_citations:Citation[]`，用于刷新和跨会话恢复讲义来源。

`Course`: `{id,title,goal,background,minutes_per_day:number,deadline:string|null,status:'planning'|'active'|'failed'|'completed',created_at,updated_at,progress:number,total_nodes:number,mastered_nodes:number,next_node_id:string|null,task_id:string|null,plan_version:number}`。

`CourseDetail`: Course + `{nodes:Node[],edges:{source,target}[],sources:Source[],plan_versions:{version:number,reason,created_at}[]}`。

`Source`: `{id,course_id,title,url:string|null,kind,chunk_count:number,created_at}`。

`Citation`: `{id,source_id,title,url:string|null,excerpt,chunk_index:number}`。

`Message`: `{id,role:'user'|'assistant',content,citations:Citation[],created_at}`。

`Exercise`: `{id,node_id,type:'choice'|'open',prompt,options:string[],rubric:string}`；未提交前不得返回标准答案。

`Attempt`: `{id,exercise_id,node_id,answer,score:number,feedback,correct_answer:string,mastery:number,passed:boolean,next_node_id:string|null,created_at}`。

`Review`: `{id,node_id,course_id,node_title,course_title,due_at,interval_days:number,mastery:number}`。

`Memory`: `{id,course_id:string|null,category,content,created_at,updated_at}`。

`Task`: `{id,course_id:string|null,kind:'plan'|'research'|'replan',status:'queued'|'running'|'succeeded'|'failed'|'cancelled',progress:number,message,error:string|null,result:object|null,created_at,updated_at,traces:Trace[]}`。

`Trace`: `{id,step,status,detail,duration_ms:number|null,prompt_tokens:number,completion_tokens:number,model:string|null,created_at}`。

## 认证与用户

- `POST /auth/register` `{email,password,full_name}` → User，并设置 Cookie。
- `POST /auth/login` `{email,password}` → User，并设置 Cookie。
- `POST /auth/logout` → `{ok:true}`。
- `GET /me` → User；`PATCH /me` `{full_name?,preferences?}` → User。
- `GET /me/export` → 包含该用户全部学习数据的 JSON 下载。
- `DELETE /me` `{password}` → `{ok:true}`，删除账户和私人资料。

## 工作台与课程

- `GET /dashboard` → `{courses:Course[],stats:{courses,total_nodes,mastered_nodes,due_reviews,learning_minutes},activity:{id,title,detail,created_at}[],reviews:Review[],daily_activity:{date,attempts:number}[]}`。
- `GET /courses` → Course[]。
- `POST /courses` `{goal,background,minutes_per_day,deadline?,level?}` → Course，创建持久化规划任务，前端轮询 course/task。
- `GET /courses/{id}` → CourseDetail；`DELETE /courses/{id}` → `{ok:true}`。
- `PATCH /nodes/{id}` `{title?,summary?,objective?,estimated_minutes?}` → Node。
- `PUT /courses/{id}/graph` `{edges:{source,target}[]}` → CourseDetail，校验归属、先修引用与无环，保存路径版本。
- `POST /courses/{id}/replan` 已禁止无预览的直接覆盖，返回409；请通过 Tutor 的 `propose_path_change` 与确认接口调整既有路径。
- `POST /courses/{id}/research` `{query}` → Task。
- `GET /templates` → `{id,title,description,level,minutes,topics:string[]}[]`；`POST /templates/{id}/enroll` → CourseDetail。此为明确标注的人工编写入门课程，不能伪称 AI 生成。

## 教学与练习

- `GET /nodes/{id}` → Node。
- `POST /nodes/{id}/lesson` → `{content,citations:Citation[]}`。
- `GET /nodes/{id}/messages` → Message[]。
- `POST /nodes/{id}/messages` `{content,request_id}` → SSE：`event: token` `data: {content}`；`event: done` `data: {message:Message}`；`event: error` `data: {detail}`。可选 meta 事件含 citations。
- `GET /nodes/{id}/exercises` → Exercise[]；`POST /nodes/{id}/exercises` → Exercise[]，真实生成并持久化。
- `POST /exercises/{id}/attempts` `{answer,request_id}` → Attempt，幂等；保存评分、更新掌握度/复习/记忆。
- `GET /attempts?course_id=...&incorrect=true` → `(Attempt & {prompt,node_title,course_title})[]`。
- `GET /review/due` → Review[]；`POST /review/{id}/complete` `{rating:number}` → Review，rating 1–5。

## 资料、记忆、分析和任务

- `POST /courses/{id}/sources` multipart `file` → Source，支持 PDF/TXT/MD/DOCX。
- `POST /courses/{id}/sources/text` `{title,content,url?}` → Source。
- `DELETE /sources/{id}` → `{ok:true}`。
- `GET /courses/{id}/search?q=...` → Citation[]。
- `GET /me/memories?course_id=&include_history=false` → Memory[]（默认排除 forgotten/superseded）；`POST /me/memories` `{content,category,course_id?,facet?}` → Memory；`PATCH /me/memories/{id}` `{content,expected_revision?}` → Memory，冲突409；`DELETE /me/memories/{id}` → `{ok:true}`（永久删除及清理派生画像文本）。
- `GET /me/memories/{id}` → `{memory,evidence,history}`，证据为来源类型/标签/逐字片段/受权链接，不公开内部 hash/隐藏答案。
- `POST /me/memories/{id}/forget` `{expected_revision?}` → Memory，停用并保留修订；不再召回。
- `GET /me/memory/recall?q=&course_id=&limit=8` → `{memories,profile}`；未选课程仅个人范围，选课程包含个人及该课程。
- `GET /me/memory/profile?course_id=` → `{id?,course_id,status,groups,method?,created_at?,updated_at?}`；只有ready含可用claims，每条绑定memory_id/revision/quote。
- `POST /me/memory/consolidate` `{course_id?,request_id}` → 同上画像。显式模型请求，键为同用户幂等回执；pending/failed/stale不发布事实，相同键不重跑。
- Memory新增revision/status/origin/facet/evidence_count/source_status，原字段保留。0008仅新增附表，未修改历史Memory行；无来源旧记录可通过原文PATCH确认成manual。
- `GET /analytics` → `{stats:{courses,total_nodes,mastered_nodes,due_reviews,learning_minutes,attempts,average_score},daily_activity:{date,attempts,average_score}[],mastery:{node_id,title,course_title,mastery}[],usage:{calls,prompt_tokens,completion_tokens,average_duration_ms},weak_nodes:{node_id,title,course_title,mastery}[]}`。
- `GET /tasks` → Task[]；`GET /tasks/{id}` → Task；`POST /tasks/{id}/cancel` → Task；`POST /tasks/{id}/retry` → Task。
- `GET /system/status` → `{model_configured:boolean,model:string,embedding_configured:boolean,search_configured:boolean,database:string,worker:string,version:string}`，无任何秘密。

错误使用适当 HTTP 状态和 `{detail:string}`；无权限资源返回 404。所有时间返回 ISO 8601 UTC。

## 共享 Tutor 与持久对话

主入口使用以下协议；节点 `messages` 接口保留旧兼容用途。

- `GET /tutor/sessions?course_id=&node_id=` → 会话列表；`POST /tutor/sessions` `{course_id?,node_id?,title?,mode?:'outline'|'study'|'review'}` → 会话。
- `GET /tutor/sessions/{id}` → 会话及 `turns`，每轮含 `input/output` 字符串、状态、公共 `pending_action`、`last_seq` 和持久结构化 `events`。不返回内部 checkpoint 或模型凭据。
- `POST /tutor/sessions/{id}/turns` `{content,request_id,capability?:'tutor'|'qa'|'research'|'planner'|'solve',profile?:同名兼容字段}` → 受理轮次，默认tutor。两字段同时传须一致；能力/profile/策略冻结到checkpoint，同request_id不能换能力；客户端不能自定预算。
- `POST /tutor/sessions/{id}/answers` `{exercise_id,answer,request_id}` → 评分与后续补教轮次；真实评分完成前不应将题卡视为已评分。
- `GET /tutor/turns/{id}` → 最新轮次；`GET /tutor/turns/{id}/events?after_seq=0` → 持久 SSE，`id:seq / event:type / data:{seq,type,payload}`。
- 事件包含 `status/content/content_reset/tool_start/tool_result/citations/question/assessment/confirmation/input_required/user_response/done/error`。`content_reset{text}` 替换中断的未完成模型轮次输出，`user_response` 含恢复位置 `output_offset`。
- `POST /tutor/turns/{id}/respond` `{content?}` 续答；`{approved:boolean,action_id}` 接受或拒绝当前精确路径预览。过期预览409，不在确认时重新调用模型生成另一份路径。
- `POST /tutor/turns/{id}/cancel` → 最新轮次。轮次状态为 queued/running/waiting_input/waiting_confirmation/completed/failed/cancelled。
- `POST /courses/{id}/imports` multipart file → 持久 `ingest` Task；`POST /tutor/imports` 同样返回Task，并在未选课时创建 `draft` 资料课程。

学习服务统一处理新题卡与旧练习API。Attempt额外返回 `independent/misconception/criteria_scores`；掌握度依据独立学习证据计算，复答不会重复提升。Task.kind新增ingest；Course.status新增draft。

## Agent 执行观测

- `GET /agent/capabilities` → `{capabilities:[{name,title,description,profile,execution:'agent_loop'}]}`，当前五种内置能力。Turn增加capability与公共result，后者含schema_version/status/outcome/verified_steps/reasoned_steps/limitations。
- `GET /agent/tools?profile=tutor` → `{profile,tools}`，工具包含name/description/group/access/replay_safe/timeout_seconds/modes/parameters；只返回公开契约。
- `GET /agent/runs?limit=50` → 当前用户的Agent轮次与Workflow任务摘要，kind分别为agent/workflow。
- `GET /agent/runs/{kind}/{id}` → `{run,policy,spans,events,usage,limitations}`；span.kind为model/tool/context/workflow。未记录的Token与耗时为null，不补假0。
- `GET /agent/runs/{kind}/{id}/export` → 上述脱敏视图的JSON下载；不返回checkpoint、模型messages、工具原始参数/回执或未答题答案。其他用户资源404。

新增持久事件：model_start/model_end/model_error/context_budget/tool_retry/tool_cached，以及model_operation_start/model_operation。内部模型span用parent_id关联tool；usage含main_model_calls/internal_model_calls，并汇总实际记录的调用Token，不与覆盖范围重叠的Trace再相加。中断无结束事件时公开投影标cancelled/interrupted、用量null。工具耗时不重复叠加子调用。事件不包含模型私有思维内容。

非重放安全写操作中断可暂停execution_review；普通文字通过respond续答只能提供核对线索，回执保持uncertain，不能视作执行成功。可重放工具的恢复也消耗持久化max_tool_recoveries与总attempts预算。

solve工具为solve_plan/solve_status/python_check/solve_finish_step/solve_finish。结果kind=solve、action标阶段，plan含version/goal/request/status/steps/counts；execution含evidence_id/step_id/plan_version/status/stdout/error/checks/duration_ms/limits。Python验证是有限AST解释器的真实执行，范围写入limits；已失败或另一计划/步骤的凭据不能完成当前步骤。CapabilityResult.outcome可为verified/partially_verified/unverified/incomplete等，不能将reasoned步骤当作执行证明。

generate_practice成功结果可含validation聚合摘要（method=model_assisted、status、scope、checked_count、repaired、checks），不返回私有答案、引文、hash。历史tool_result保留“生成时”的核验事实；当前题目或评分metadata改变后不再返回旧的当前passed摘要。


### Agent 检索与记忆工具增量（0008）

`retrieve_materials` 支持 `{query,mode?:auto|lexical|enhanced,limit?:1..10,source_ids?:string[]}`，返回真实sources与retrieval元数据（原查询/有限上下文查询、候选数、改写/重排状态、降级warnings）。`read_material` 支持 `{source_id,version?,chunk_indices?,page?,max_chars?}`，页/片段二选一，只读当前课程内不可变版本，字符上限8000。回执中的citation是本轮全局编号。

`remember_memory` 的content必须来自本轮真实用户原文；category=note/preference/goal，scope=auto/personal/course，facet可用于同类偏好替换。新增recall_memory、consolidate_memory（selected/personal）和forget_memory（memory_id、expected_revision?）。后两项及remember属于write，qa/research/planner/solve仅开放记忆读取。运行详情新事件只导出策略/计数/状态，不输出查询、记忆原文或证据文本。
