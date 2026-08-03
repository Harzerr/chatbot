# 简历优化模块

简历优化模块已经并入主项目的求职工作台，前端入口为 `/resume-optimizer`。它复用主项目的认证、SQLite/SQLAlchemy 数据库和 `/api/v1/career` API，不再启动原型目录中的独立 FastAPI 服务，也不直接读写共享 JSON 文件。

## 功能边界

- 原型的 `resume-profiles.json` 可以从 A4 编辑器导入。
- 导入内容会转换为当前登录用户的职业事实和教育档案；事实默认是“待确认”，确认后才能参与 AI 生成。
- 同一用户重复导入时，按“事实类型 + 标题”跳过重复记录，不会重复创建。
- 定制简历生成后，可在 A4 编辑器中编辑摘要、经历、项目、项目顺序和章节显示状态。
- 编辑保存到对应的 `resume_documents` 版本；PDF 导出继续使用后端 XeLaTeX 母版。

## API

- `POST /api/v1/career/profile/import`：导入原型 JSON。
- `PUT /api/v1/career/resumes/{resume_id}`：保存当前用户拥有的简历版本编辑。

所有接口都要求登录，并校验资源所属用户。原型 JSON 中的证件照、校徽和 HTML 只作为导入文件内容，不会直接写入服务端静态目录；生产环境应继续通过头像上传接口管理图片。

## 发布

修改前端或后端后，提交并推送到 `yql_dev`。GitHub Actions 在 runner 上完成前端构建，服务器只接收静态产物。后端发布时应沿用 systemd/Docker 的服务重启流程，不要在 2GB 服务器上运行 `npm run build`。
