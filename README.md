# hdAgent

`hdAgent` 是一个围绕 Makerfabs 板卡支持场景构建的 Agent 项目。当前已经从最初的单页聊天 Demo，升级为“登录后才能进入聊天”的前后端一体化结构，第一阶段重点完成了：

- Google 登录与邮箱验证码登录
- 用户会话与登录态持久化
- `Makerfabs Agent` Recent 聊天记录
- 用户 Usage / Profile 基础接口
- PostgreSQL + pgvector 的数据库初始化脚本

知识库模块现已接入第一版板型知识库和 RAG 基础能力，优先支持 `txt`、`excel(xlsx)`、网站正文和直接输入文本；GitHub / MCP 仅预留扩展位，暂未启用。

## 当前能力

- 基于 `FastAPI` 提供 Web 服务
- 基于 `LangGraph` 做产品型号识别与聊天意图路由
- 支持多模型提供方：
  - `OpenAI`
  - `DeepSeek`
  - `Claude`
  - `Qwen`
- 支持 Google OAuth 登录
- 支持邮箱 6 位验证码登录
- 支持聊天 Session 持久化与 Recent 列表
- 支持按用户统计最近 7 天 token usage
- 支持板型管理、知识条目录入与软删除
- 支持 `txt` / `xlsx` / 网站正文 / 手工文本入库
- 支持基于 `pgvector` 的板型级知识检索
- 聊天链路已接入板型知识召回

## 当前支持的产品

- `MaTouch_ESP32S3`
- `ESP32-S3-WROOM-1`

对应知识文件：

- `backend/product_knowledge/matouch_esp32s3.md`
- `backend/product_knowledge/esp32_s3_wroom_1.md`

## 项目结构

```text
hdAgent/
├── backend/
│   ├── app/
│   │   ├── api/                  # 业务路由层
│   │   ├── core/                 # 配置、数据库、基础安全工具
│   │   ├── knowledge/            # chunk、embedding、检索等知识库基础模块
│   │   ├── mcp/                  # 预留给 GitHub MCP / 工具调用的扩展模块
│   │   ├── schemas/              # 阶段一的新接口请求/响应模型
│   │   ├── services/             # 认证、聊天、知识库等服务逻辑
│   │   └── main.py               # 当前 FastAPI 主入口
│   ├── sql/
│   │   └── 001_init_postgres.sql # PostgreSQL + pgvector 初始化脚本
│   ├── langgraph_agent.py        # LangGraph 意图路由
│   ├── llm_providers.py          # 多模型调用与 prompt 组装
│   ├── product_knowledge.py      # 产品型号、别名、知识文件读取
│   ├── schemas.py                # 旧聊天链路的 Pydantic 模型
│   ├── fastapi_app.py            # 兼容旧入口，转发到 app.main
│   └── main.py                   # 兼容旧入口，转发到 app.main
├── frontend/
│   ├── index.html                # 前端入口页
│   ├── config.js                 # 前端静态配置
│   ├── app.js                    # 聊天页/登录页逻辑
│   └── styles.css                # 页面样式
├── requirements.txt
├── .env.sample
└── README.md
```

## 运行环境

- Python 3.12+ 推荐
- PostgreSQL 15+ 推荐
- 建议使用虚拟环境

## 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量

先复制模板：

```bash
cp .env.sample .env
```

阶段一至少建议配置：

```env
APP_NAME=Makerfabs Agent
APP_URL=http://127.0.0.1:8000
DATABASE_URL=postgresql://hdagent_app:change_me_now@127.0.0.1:5432/hdagent
SESSION_SECRET=change-me-in-production
```

### Google 登录

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/auth/google/callback
```

### 邮箱验证码登录

开发期本地调试建议：

```env
EMAIL_PROVIDER=console
EMAIL_DEBUG_EXPOSE_CODE=true
```

如果要接真实邮箱 SMTP：

```env
EMAIL_PROVIDER=smtp
EMAIL_FROM=no-reply@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
```

### LLM Provider 示例

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.4

DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_MODEL=claude-3-5-sonnet-latest

QWEN_API_KEY=your_qwen_api_key_here
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

### 知识库 / RAG 配置

```env
KNOWLEDGE_STORAGE_DIR=./data/knowledge
KNOWLEDGE_CHUNK_SIZE=1200
KNOWLEDGE_CHUNK_OVERLAP=180
KNOWLEDGE_TOP_K=5

EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_TIMEOUT_SECONDS=30

MCP_GITHUB_ENABLED=false
```

说明：

- `EMBEDDING_*` 没配置时，知识库仍可入库，但检索会回退到 PostgreSQL 全文检索
- `MCP_GITHUB_ENABLED` 目前只是预留开关，不会真正启用 GitHub MCP

## 数据库初始化

完整 SQL 位于：

- `backend/sql/001_init_postgres.sql`
- `backend/sql/002_knowledge_rag.sql`

执行方式：

```bash
psql -U postgres -f backend/sql/001_init_postgres.sql
psql -U postgres -d hdagent -f backend/sql/002_knowledge_rag.sql
```

该脚本会完成：

- 创建 `hdagent_app` 角色
- 创建 `hdagent` 数据库
- 启用 `vector`、`pgcrypto`、`citext` 扩展
- 创建用户、登录、聊天、usage、知识库预留表

第二个迁移会继续完成：

- 创建 `board_type`、`board_alias`
- 创建 `knowledge_document_v2`、`knowledge_chunk_v2`、`knowledge_job_v2`
- 初始化 `MaTouch_ESP32S3` 和 `ESP32-S3-WROOM-1`
- 初始化板型别名
- 建立 `pgvector` 检索索引和 `tsvector` 全文检索索引

如果你本机还没装 `pgvector`：

- Docker 方式可直接使用 `pgvector/pgvector:pg16`
- Homebrew PostgreSQL 可先安装 `pgvector`，再执行 `CREATE EXTENSION vector;`

## 启动项目

推荐入口：

```bash
.venv/bin/uvicorn backend.app.main:app --reload
```

兼容旧入口也可继续使用：

```bash
.venv/bin/uvicorn backend.fastapi_app:app --reload
```

启动后访问：

- 首页：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/health`
- 启动信息：`http://127.0.0.1:8000/api/bootstrap`
- 当前登录态：`http://127.0.0.1:8000/api/auth/me`
- 产品型号列表：`http://127.0.0.1:8000/product-model-list`

## 阶段一核心接口

### 认证

- `GET /api/auth/config`
- `GET /api/auth/me`
- `GET /api/auth/google/login`
- `GET /api/auth/google/callback`
- `POST /api/auth/email/request-code`
- `POST /api/auth/email/verify-code`
- `POST /api/auth/logout`

### 聊天

- `GET /api/chat/sessions`
- `POST /api/chat/sessions`
- `GET /api/chat/sessions/{session_id}/messages`
- `POST /api/chat/sessions/{session_id}/stream`

SSE 主要事件：

- `product_model`
- `token`
- `error`
- `end`

### 用户

- `GET /api/user/profile`
- `GET /api/user/usage/daily`

### 知识库管理

- `GET /api/admin/boards`
- `GET /api/admin/boards/{board_id}`
- `POST /api/admin/boards`
- `PATCH /api/admin/boards/{board_id}`
- `DELETE /api/admin/boards/{board_id}`
- `GET /api/admin/knowledge/documents`
- `GET /api/admin/knowledge/documents/{document_id}`
- `POST /api/admin/knowledge/documents/text`
- `POST /api/admin/knowledge/documents/website`
- `POST /api/admin/knowledge/documents/file`
- `GET /api/admin/knowledge/documents/{document_id}/download`
- `DELETE /api/admin/knowledge/documents/{document_id}`
- `POST /api/admin/knowledge/retrieve`

## 知识库使用说明

### 1. 安装依赖

新增依赖：

- `openpyxl`
- `python-multipart`

执行：

```bash
pip install -r requirements.txt
```

### 2. 板型管理

板型是知识库的一级归属对象，采用软删除。

创建板型示例：

```bash
curl 'http://127.0.0.1:8000/api/admin/boards' \
  -X POST \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  --data-raw '{
    "code": "esp32_s3_custom",
    "name": "ESP32-S3-CUSTOM",
    "description": "Custom S3 board",
    "default_hint": "可以先问我接线和初始化。",
    "aliases": ["custom s3", "esp32 s3 custom"],
    "is_enabled": true
  }'
```

软删除板型示例：

```bash
curl 'http://127.0.0.1:8000/api/admin/boards/3' \
  -X DELETE \
  -b cookies.txt
```

### 3. 录入文本知识

```bash
curl 'http://127.0.0.1:8000/api/admin/knowledge/documents/text' \
  -X POST \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  --data-raw '{
    "board_type_id": 2,
    "title": "ESP32-S3 I2C 默认引脚",
    "text": "ESP32-S3-WROOM-1 默认 SDA 为 GPIO17，SCL 为 GPIO18。"
  }'
```

### 4. 上传 txt / pdf / xlsx / cad 设计文件

```bash
curl 'http://127.0.0.1:8000/api/admin/knowledge/documents/file' \
  -X POST \
  -b cookies.txt \
  -F 'board_type_id=2' \
  -F 'file=@./samples/i2c_guide.txt'
```

### 5. 录入网站正文

当前阶段网站能力是“保存链接 + 手工粘贴正文”，暂不做爬虫抓取。

```bash
curl 'http://127.0.0.1:8000/api/admin/knowledge/documents/website' \
  -X POST \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  --data-raw '{
    "board_type_id": 2,
    "title": "ESP32 官方文档摘录",
    "source_url": "https://docs.espressif.com/",
    "content": "这里填清洗后的正文内容"
  }'
```

### 6. 检索调试

```bash
curl 'http://127.0.0.1:8000/api/admin/knowledge/retrieve' \
  -X POST \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  --data-raw '{
    "board_type_id": 2,
    "query": "ESP32-S3-WROOM-1 的 I2C 默认引脚是什么？",
    "top_k": 5
  }'
```

### 7. 聊天里的 RAG 行为

当前聊天链路的处理顺序：

1. 识别产品型号
2. 根据产品型号映射到 `board_type`
3. 在该板型下检索 `knowledge_chunk_v2`
4. 把命中的知识片段拼进系统提示词
5. 再调用对应 LLM 生成最终回复

如果 embedding 可用：

- 优先走 `pgvector` 相似度检索

如果 embedding 不可用：

- 自动回退到 PostgreSQL 全文检索

## 当前限制

- 文件上传当前支持 `.txt`、`.pdf`、`.xlsx/.xlsm/.xltx/.xltm` 以及常见 CAD 设计文件（如 `.sch/.pro/.brd/.kicad_*`）
- 网站知识当前只支持手工粘贴正文，不会自动抓网页
- 知识入库当前是同步执行，后续可迁移到异步 job worker
- GitHub repo / MCP tools 当前仅预留模块，不会被聊天调用
- 产品静态知识文件 `backend/product_knowledge/*.md` 仍保留作为兼容兜底

## 聊天主流程

1. 用户先完成 Google 登录或邮箱验证码登录
2. 前端获取 `/api/auth/me` 确认当前登录态
3. 进入聊天页后读取 `/api/chat/sessions`
4. 新建聊天时写入 `chat_session`
5. 用户发消息后写入 `chat_message`
6. LangGraph 判断本轮是设置产品、生成代码还是普通聊天
7. 根据当前产品型号拼接系统提示词、静态产品知识和板型知识库检索结果
8. 调用对应 LLM 流式输出
9. 将 assistant 回复与 usage 写回数据库

## 后续计划

- 知识入库异步队列
- 网站正文自动抓取和清洗
- GitHub repo + MCP tools
- RAG 与工具调用联合编排
- 手机验证码登录

## 开发说明

- 现阶段前端仍然是轻量原生 JS + CSS，便于快速迭代
- 现阶段主业务入口是 `backend/app/main.py`
- `backend/fastapi_app.py` 与 `backend/main.py` 仅保留兼容作用
- 新增板卡时，建议同步更新 `backend/product_knowledge.py` 与 `backend/product_knowledge/`

## License

如果准备开源，建议补充明确许可证，例如 `MIT`。
