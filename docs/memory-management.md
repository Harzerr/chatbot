# 对话记忆管理设计

## 1. 为什么不再使用固定截断

原实现直接取最近几条消息，优点是简单，但会丢失较早的关键事实，例如用户之前说明的技术选型、约束条件和已经讨论过的结论。这里的改进不是无限扩大上下文，而是把“历史保存”和“本轮送入模型的上下文”分开：历史完整保存，模型上下文按相关性和预算选择。

## 2. 业界常见设计

成熟的 Agent 通常采用分层记忆：

1. **线程级短期记忆**：保存当前会话状态、消息和流程节点，用于恢复同一会话。
2. **长期记忆**：按用户或租户命名空间保存跨会话事实、偏好和稳定信息。
3. **语义检索**：根据当前问题召回历史中相关的完整轮次，而不是只按时间截取。
4. **上下文预算**：使用 token 或近似 token 预算控制输入大小，优先保留高价值内容。
5. **摘要与异步写入**：长会话可以在后台生成滚动摘要，记忆写入不阻塞主请求。

这与 LangGraph 将 thread-scoped short-term memory、cross-thread long-term store 和上下文管理分开的设计一致：

- [LangGraph：管理对话历史](https://langchain-ai.github.io/langgraph/how-tos/memory/manage-conversation-history/)
- [LangGraph：Memory 概念](https://langchain-ai.github.io/langgraphjs/how-tos/manage-conversation-history/)
- [LangGraph：Persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)

## 3. 当前项目的落地方案

```text
用户问题
  ├─ Mem0 search：召回跨会话长期记忆
  ├─ Qdrant chat scroll：读取当前会话的完整历史
  ├─ Qdrant semantic search：在当前 chat_id 内召回相关旧轮次
  └─ Context Selector：去重、预算控制、按时间排序
       └─ LangGraph / InterviewSkill / 普通聊天
```

### 3.1 存储层

- Qdrant 继续保存当前会话的完整问答轮次，不删除旧消息。
- 语义检索同时绑定 `tenant_id`、`user_id`、`chat_id`，避免跨租户、跨用户和跨会话召回。
- Mem0 继续保存适合跨会话复用的长期记忆，失败时只降级长期记忆，不阻断当前问答。
- 当前请求结束后，Mem0 和 Qdrant 写入仍在后台执行，避免把记忆持久化耗时放到主响应路径。

### 3.2 滚动摘要层

新增 `app/services/conversation_summary.py` 和 `app/services/conversation_summary_jobs.py`：

- 当会话达到 `8` 个轮次时，通过现有 RQ Worker 异步生成第一版摘要；之后每新增 `4` 个轮次再更新一次。
- 摘要按 `tenant_id:user_id:chat_id` 写入 Redis，包含版本号、覆盖到的时间点、覆盖轮次数、模型和更新时间。
- 生成摘要时只处理“尚未被摘要覆盖的历史轮次”，并保留最近 `4` 个轮次作为原始上下文。
- 摘要 Prompt 要求只记录用户明确确认的事实，处理冲突时标记“待确认”，并把对话内容当作数据而不是指令。
- 使用 Redis 分布式锁避免同一会话的多个摘要任务并发覆盖。
- 主请求只从 Redis 读取已生成摘要；摘要生成失败时自动退回原有语义检索链路，不影响问答。

`app/agent/chat_agent.py` 将摘要、最近轮次和最多 `2` 条语义相关原始证据组合给模型：摘要负责覆盖旧事实，原始证据负责核验细节，最近轮次负责保持对话连续性。

### 3.3 上下文选择层

`app/services/conversation_context.py` 负责上下文选择：

1. 先召回与当前问题最相关的历史轮次。
2. 再保留最近若干完整轮次，保证对话连续性。
3. 使用文档 ID 去重，避免同一轮同时来自 scroll 和 semantic search 时重复注入。
4. 只加入完整的 User/Assistant 轮次，不在句子中间截断。
5. 按时间重新排序后送给模型，避免语义召回改变对话顺序。
6. 超过上下文预算时丢弃低优先级的完整轮次，而不是破坏单条消息。

当前默认配置：

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `INTERVIEW_HISTORY_RECENT_TURNS` | `4` | 始终优先保留的最新轮次 |
| `INTERVIEW_HISTORY_RELEVANT_TURNS` | `6` | 当前问题最多召回的相关旧轮次 |
| `INTERVIEW_HISTORY_CONTEXT_MAX_CHARS` | `12000` | 上下文近似预算，防止输入无限增长 |
| `INTERVIEW_HISTORY_SEARCH_TIMEOUT` | `5s` | 语义历史检索超时后回退到近期轮次 |

这里的字符数是低成本的近似保护，不是模型 tokenizer 的精确 token 数。后续可以按实际模型接入 tokenizer，将预算切换为 token 预算。

## 4. 解决了什么问题

| 问题 | 原实现 | 当前实现 |
|---|---|---|
| 旧事实丢失 | 固定取最近消息 | 当前问题语义召回旧轮次 |
| 轮次被截断 | 字符串切片可能截断语义 | 只选择完整问答轮次 |
| 历史重复 | 不同来源可能重复注入 | 通过文档 ID 去重 |
| 长会话膨胀 | 历史越长上下文越大 | 相关性 + 最近性 + 预算控制 |
| 检索不稳定 | 检索失败影响主流程 | 5 秒超时后回退到近期轮次 |
| 数据安全 | 可能扩大召回范围 | Qdrant 查询强制租户、用户、会话过滤 |
| 长会话 Token 成本 | 历史上下文随轮次增长 | 摘要覆盖旧轮次，仅保留近期轮次和少量证据 |
| 摘要任务阻塞主请求 | 需要在接口内调用 LLM | RQ Worker 后台生成，接口只读 Redis |

## 5. 验证方式

运行纯函数回归测试：

```bash
./.venv/bin/python -m unittest tests.test_conversation_context tests.test_conversation_summary tests.test_ai_regression -v
./.venv/bin/python -m tests.benchmark_memory_context --turns 8 20 40 80
```

重点验证：

- 旧的高相关轮次可以被召回；
- 最近轮次仍然保留；
- 同一轮不会重复；
- 预算不足时按完整轮次淘汰，不会把文本切成半句；
- 选择上下文不会修改或删除 Qdrant 中的持久化历史。

### 5.1 本次离线基准结果

基准脚本使用相同的完整问答轮次，比较固定窗口、语义检索上下文和“滚动摘要 + 最近轮次 + 证据”的上下文。Token 使用 `字符数 / 4` 作为近似值，不能替代真实模型 tokenizer，但可以稳定比较方案变化。

| 会话轮次 | 固定窗口旧事实 | 语义上下文 Token | 摘要上下文 Token | 摘要 Token 减少 |
|---:|---|---:|---:|---:|
| 8 | 未召回 | 204 | 178 | 12.75% |
| 20 | 未召回 | 259 | 180 | 30.50% |
| 40 | 未召回 | 259 | 180 | 30.50% |
| 80 | 未召回 | 259 | 180 | 30.50% |

这组结果验证了两个设计目标：固定取最近消息会丢失早期事实；滚动摘要可以在保留早期事实的同时，把模型输入控制在稳定范围。真实生产效果还需要记录 `prompt_tokens`、首字延迟、完整响应延迟、摘要命中率和回答正确率，不能只用离线字符数推断接口性能。

### 5.2 RQ 真实链路冒烟

在服务器上使用不存在的会话执行了一次真实摘要任务，避免触发外部模型调用：

- Worker 已加载 `conversation_summary` 队列；
- 任务成功被 Worker 消费，结果为 `{"status": "skipped", "reason": "below_trigger", "turns": 0}`；
- 这验证了 Redis 入队、RQ Worker 路由、Qdrant 只读查询和低于阈值时的安全退出；
- 服务器的本地 Qdrant 请求需要配置 `NO_PROXY=127.0.0.1,localhost`，否则会被 SOCKS 代理拦截；外部模型请求仍按服务器原代理配置执行。

要验证完整摘要生成，需要在同一个 `chat_id` 产生至少 8 个问答轮次，等待 Worker 日志出现 `Conversation summary updated`，再对比请求指标中的 `prompt_tokens` 和响应延迟。

## 6. 下一阶段

下一阶段可以增加摘要质量评测集：预置“旧事实查询、冲突事实查询、跨轮次关联查询和不可回答查询”，分别检查摘要召回、时间新鲜度、冲突处理和幻觉率。摘要与原始消息同时保留，仍可回源到证据；摘要失败时继续回退到原始轮次。
