# 简历解析链路

## 目标

将简历上传、文本解析、OCR 回退和职业事实提取拆成可追踪的阶段，避免长时间同步请求和失败原因丢失。

## 当前数据流

```text
上传文件
  → ResumeSource 保存原文件元数据
  → ResumeParseJob 创建解析任务
  → Redis + RQ Worker 执行 PDF/图片解析
  → 保存解析器、页数、质量分和警告
  → 更新用户简历文本
  → 职业事实库单独执行结构化提取
```

## 解析策略

1. PDF 优先使用 `pdftotext -layout`。
2. 页面文本结构使用 `pypdf` 恢复。
3. 文本不足时使用 `pdftoppm` 将页面渲染为图片，再调用视觉模型 OCR。
4. 图片简历直接调用视觉模型，统一返回页级解析结果。
5. OCR 默认最多处理 8 页，避免超长文件造成模型成本和延迟失控。

## 任务状态

```text
queued
  → processing
  → completed
```

异常状态为 `failed`，接口会保存错误原因，支持通过以下接口重试：

```text
GET  /api/v1/users/me/resume/jobs/{job_id}
POST /api/v1/users/me/resume/jobs/{job_id}/retry
```

应用重启时，未完成的任务会被恢复为 `queued` 并重新入队。

## RQ Worker

本项目使用 Redis 保存队列，RQ Worker 独立执行解析任务。启动 Redis 后，可以在项目目录执行：

```bash
source .venv/bin/activate
python -m app.workers.resume_worker
```

生产环境可以安装 `docs/chatbot-resume-worker.service`：

```bash
sudo cp docs/chatbot-resume-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chatbot-resume-worker
sudo systemctl status chatbot-resume-worker
```

开发环境的 `start_venv_tmux.sh` 会额外创建 `resume_worker` 窗口。

## 部署依赖

Ubuntu 服务器需要安装 Poppler：

```bash
sudo apt update
sudo apt install -y poppler-utils
```

其中：

- `pdftotext` 用于文本型 PDF 解析。
- `pdftoppm` 用于扫描 PDF 页面渲染和 OCR 回退。

## 职业事实校验

职业事实提取仍然由 `/api/v1/career/facts/extract` 单独触发。模型返回结果会经过 Pydantic 字段校验，并返回：

- `accepted_count`：通过校验的事实数量。
- `rejected_count`：未通过校验的数量。
- `warnings`：每条失败事实的索引、标题和原因。

只有用户确认后的事实才会进入后续定制简历生成流程。
