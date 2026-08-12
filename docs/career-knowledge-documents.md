# 技术资料证据库

## 目标

让用户在“职业事实库”的每条项目事实下上传对应的 Markdown 技术文档，并将资料保存到当前用户的数据域中。资料可以在前端直接修改、归档；未归档资料会作为面试出题和 `InterviewEvaluator` 的核验上下文，而不是直接当作候选人的回答或系统指令。

## 数据链路

1. 前端 `CareerStudio` 在每条 `project` 类型事实下通过 `multipart/form-data` 上传 `.md` 文件。
2. `career` API 校验 `fact_id` 属于当前用户，并限制单文件最大 10MB、正文最多保存 100000 字符。
3. Markdown 按 UTF-8 解码并保留原始正文，后端将事实 ID、文件名、正文、解析元数据、来源哈希和用户 ID 写入 `career_knowledge_documents` 表。
4. 前端按事实展示关联文档，编辑操作通过 `PUT /api/v1/career/documents/{id}` 更新数据库正文；更新后重新计算正文哈希。
5. 进入面试时，后端只读取当前用户的未归档资料，根据当前问题做关键词相关性排序，并限制最多 24000 字符后注入出题和评估上下文。
6. `InterviewEvaluator` 要求输出 `knowledge_evidence`，`EvaluationAgent` 再检查证据是否能在上传资料上下文中找到，不能核验的内容会进入 `evidence_warnings`。

## API

| 接口 | 作用 |
| --- | --- |
| `GET /api/v1/career/documents` | 查询当前用户未归档资料 |
| `POST /api/v1/career/documents/upload` | 绑定事实 ID，上传并解析 Markdown |
| `PUT /api/v1/career/documents/{id}` | 修改标题、类型、正文或归档状态 |
| `DELETE /api/v1/career/documents/{id}` | 归档资料，不再进入评估上下文 |

## 安全与边界

- 所有查询和更新都带 `user_id` 条件，避免跨用户读取或修改资料。
- 上传资料被明确标记为“证据”，不会被当作 Prompt 指令执行。
- 评估结果只能引用回答、简历或上传资料中可核验的片段；无法核验时标记证据不足。
- 当前版本把正文保存到数据库，适合原型和中小规模资料；生产环境可进一步把原文件放对象存储、正文分块写入向量库，并保留数据库元数据和版本记录。
