# hdAgent

一个基于 FastAPI + LangGraph 的 Makerfabs 硬件 AI 助手项目，用于围绕指定开发板进行问答、型号识别和代码生成。当前项目内置了一个简单前端页面，后端通过流式接口返回模型输出，适合做板卡技术支持、示例代码生成和产品知识问答。

## 功能特性

- 基于 `FastAPI` 提供 Web 服务与流式聊天接口
- 基于 `LangGraph` 处理意图识别与对话路由
- 支持多模型提供方切换：
  - `DeepSeek`
  - `OpenAI`
  - `Claude`
  - `Qwen`
- 支持根据用户输入识别产品型号
- 支持按产品型号注入设备知识与提示词
- 内置简单前端页面，可直接在浏览器中进行交互

## 当前支持的产品

- `MaTouch_ESP32S3`
- `ESP32-S3-WROOM-1`

对应知识文件位于：

- `backend/product_knowledge/matouch_esp32s3.md`
- `backend/product_knowledge/esp32_s3_wroom_1.md`

## 项目结构

```text
hdAgent/
├── backend/
│   ├── fastapi_app.py         # FastAPI 应用入口
│   ├── langgraph_agent.py     # LangGraph 路由逻辑
│   ├── llm_providers.py       # 多模型提供方封装
│   ├── product_knowledge.py   # 产品列表、别名、知识文件读取
│   ├── schemas.py             # Pydantic 数据模型
│   └── product_knowledge/     # 产品知识库
├── frontend/
│   └── index.html             # 前端页面
├── requirements.txt
├── .env.sample
└── README.md
```

## 运行环境

- Python 3.10 及以上
- 建议使用虚拟环境

## 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 环境变量配置

先复制示例配置：

```bash
cp .env.sample .env
```

然后至少配置一个模型提供方的 API Key。

### DeepSeek

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### OpenAI

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```

### Claude

```env
ANTHROPIC_API_KEY=your_anthropic_api_key_here
CLAUDE_MODEL=claude-3-5-sonnet-latest
```

### Qwen

```env
QWEN_API_KEY=your_qwen_api_key_here
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

## 启动项目

在项目根目录执行：

```bash
uvicorn backend.fastapi_app:app --reload
```

启动后访问：

- 首页: `http://127.0.0.1:8000/`
- 健康检查: `http://127.0.0.1:8000/health`
- 产品型号列表: `http://127.0.0.1:8000/product-model-list`

## 接口说明

### `POST /chat/stream`

流式返回聊天结果，返回类型为 `text/event-stream`。

请求示例：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "帮我写一个 MaTouch_ESP32S3 的触摸屏示例"
    }
  ],
  "current_product_model": "MaTouch_ESP32S3",
  "provider": "deepseek",
  "model": "deepseek-chat"
}
```

主要事件类型：

- `product_model`: 当前识别出的产品型号
- `token`: 模型流式输出片段
- `error`: 服务器错误信息
- `end`: 输出结束

### `GET /product-model-list`

返回当前支持的产品型号列表。

### `GET /health`

用于健康检查，返回：

```json
{
  "ok": true
}
```

## 对话处理流程

项目大致流程如下：

1. 前端发送用户消息到 `/chat/stream`
2. LangGraph 先执行意图识别
3. 如果识别到用户在设置产品型号，则记录当前型号并直接回复
4. 如果尚未选择产品型号，则先追问用户当前产品
5. 如果已确定产品型号，则拼接系统提示词和产品知识
6. 调用对应 LLM 提供方进行流式输出

## 开发说明

- 产品型号与别名定义在 `backend/product_knowledge.py`
- 新增板卡时，建议同步补充：
  - `PRODUCTS` 中的型号、别名、提示语
  - `backend/product_knowledge/` 下的知识文件
- 模型请求封装位于 `backend/llm_providers.py`
- 当前前端为单文件 HTML，适合快速原型验证

## 已知情况

- `backend/main.py` 中存在一份较老的重复/实验性代码，目前实际推荐入口是 `backend.fastapi_app:app`
- 前端直接由 FastAPI 挂载并提供静态访问
- 运行前请确保至少配置了一个可用模型的 API Key，否则接口无法正常生成内容

## License

如果你准备开源这个项目，建议在仓库中补充明确的许可证文件，例如 `MIT`。
