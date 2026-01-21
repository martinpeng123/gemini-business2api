# Claude API 完整接口文档

本项目现已支持 **Claude 的两种 API 接口**，与 Gemini CLI 并存提供服务。

## 📋 概述

### 支持的 Claude 接口

#### 1️⃣ Claude Messages API（原生格式）✨ 推荐
- 端点：`POST /v1/messages`
- 完全兼容 Anthropic Claude API 原生格式
- 无需修改现有 Claude SDK 客户端代码
- 支持流式和非流式响应
- 支持多模态（文本 + 图片）

#### 2️⃣ Claude Code CLI（命令行工具）
- 端点：`/v1/claude-code/*`
- 基于 Claude Code CLI 工具
- OpenAI 兼容格式
- 会话管理功能

---

## 🌟 Claude Messages API（推荐）

### 快速开始

无需安装额外工具，直接配置 API Key 即可使用。

**配置环境变量**：
```bash
# .env 文件
CLAUDE_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
```

**启动服务**：
```bash
python main.py
```

### API 端点

#### POST /v1/messages

完全兼容 Anthropic Claude Messages API 的原生格式。

**请求示例（非流式）**：
```json
POST /v1/messages
x-api-key: your-api-key

{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "messages": [
    {"role": "user", "content": "Hello, Claude!"}
  ],
  "stream": false
}
```

**响应示例**：
```json
{
  "id": "msg_01XYZ...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Hello! How can I help you today?"
    }
  ],
  "model": "claude-3-5-sonnet-20241022",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 15
  }
}
```

**流式请求示例**：
```json
POST /v1/messages
x-api-key: your-api-key

{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "messages": [
    {"role": "user", "content": "写一个 Python 快速排序"}
  ],
  "stream": true
}
```

**流式响应（Server-Sent Events）**：
```
event: message_start
data: {"type":"message_start","message":{"id":"msg_01XYZ...","type":"message","role":"assistant","content":[],"model":"claude-3-5-sonnet-20241022","stop_reason":null,"usage":{"input_tokens":10,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"这是"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"一个"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":150}}

event: message_stop
data: {"type":"message_stop"}
```

### 支持的参数

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `model` | string | ✅ | 模型名称（如 `claude-3-5-sonnet-20241022`） |
| `messages` | array | ✅ | 消息列表 |
| `max_tokens` | integer | ✅ | 最大生成 token 数（Claude 必需参数） |
| `stream` | boolean | ❌ | 是否流式响应（默认 false） |
| `system` | string | ❌ | 系统提示词 |
| `temperature` | float | ❌ | 温度参数（0.0-1.0） |
| `top_p` | float | ❌ | Top-p 采样 |
| `stop_sequences` | array | ❌ | 停止序列 |

### 多模态支持（文本 + 图片）

**请求示例**：
```json
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "这张图片里有什么？"
        },
        {
          "type": "image",
          "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "iVBORw0KGgoAAAANS..."
          }
        }
      ]
    }
  ]
}
```

### 认证方式

支持两种认证方式：

1. **x-api-key Header**（Claude 标准）：
   ```bash
   curl -X POST http://localhost:7860/v1/messages \
     -H "x-api-key: your-api-key" \
     -H "Content-Type: application/json" \
     -d '...'
   ```

2. **Authorization Header**（通用）：
   ```bash
   curl -X POST http://localhost:7860/v1/messages \
     -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '...'
   ```

### 使用示例

#### Python (Anthropic SDK)

无需修改现有代码，只需更改 base_url：

```python
from anthropic import Anthropic

client = Anthropic(
    api_key="your-api-key",
    base_url="http://localhost:7860"  # 指向本地服务
)

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Hello, Claude!"}
    ]
)

print(message.content[0].text)
```

#### Python (httpx)

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:7860/v1/messages",
        headers={"x-api-key": "your-api-key"},
        json={
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": "Hello!"}
            ]
        }
    )
    print(response.json())
```

#### JavaScript (fetch)

```javascript
const response = await fetch('http://localhost:7860/v1/messages', {
  method: 'POST',
  headers: {
    'x-api-key': 'your-api-key',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    model: 'claude-3-5-sonnet-20241022',
    max_tokens: 1024,
    messages: [
      { role: 'user', content: 'Hello, Claude!' }
    ]
  })
});

const result = await response.json();
console.log(result.content[0].text);
```

#### cURL

```bash
curl -X POST http://localhost:7860/v1/messages \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello, Claude!"}
    ]
  }'
```

### 错误响应格式

```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "Invalid API key"
  }
}
```

---

## 🛠️ Claude Code CLI

详细文档请参考 [CLAUDE_CODE_API.md](./CLAUDE_CODE_API.md)

### 快速说明

- 端点：`/v1/claude-code/*`
- 需要安装 Claude Code CLI 工具
- OpenAI 兼容格式
- 支持命令执行、会话管理

---

## 🔄 API 对比

| 特性 | Claude Messages API | Claude Code CLI |
|------|-------------------|----------------|
| 端点 | `/v1/messages` | `/v1/claude-code/*` |
| 格式 | Claude 原生格式 | OpenAI 兼容格式 |
| 工具依赖 | ❌ 无需额外工具 | ✅ 需要 Claude CLI |
| SDK 兼容 | ✅ 完全兼容 Anthropic SDK | ⚠️ 需适配 |
| 流式响应 | ✅ Claude SSE 格式 | ✅ OpenAI SSE 格式 |
| 多模态 | ✅ 支持 | ✅ 支持 |
| 会话管理 | ❌ 无状态 | ✅ 有会话功能 |
| 推荐场景 | 标准 API 调用 | CLI 工具集成 |

---

## 📚 支持的模型

所有 Claude 3 系列模型：

- `claude-3-5-sonnet-20241022` ⭐ 推荐
- `claude-3-5-haiku-20241022`
- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`

---

## 🐛 故障排查

### 1. 404 Not Found

**问题**：请求 `/v1/messages` 返回 404

**解决**：
- 确认服务已启动
- 检查日志中是否有 "Claude API 原生路由已注册: /v1/messages"
- 确认请求路径正确（不是 `/v1/claude-code/chat`）

### 2. 401 Authentication Error

**问题**：认证失败

**解决**：
- 检查 `.env` 中的 `CLAUDE_API_KEY` 配置
- 确认请求头中携带了正确的 API Key
- 使用 `x-api-key` 或 `Authorization: Bearer xxx`

### 3. 422 Validation Error

**问题**：请求验证失败

**解决**：
- Claude API 要求 `max_tokens` 参数必须提供
- 检查 `messages` 格式是否正确
- 确认 `role` 只能是 `user` 或 `assistant`

---

## 🔐 安全性

1. **API Key 保护**：所有接口都需要有效的 API Key 认证
2. **请求验证**：使用 Pydantic 严格验证请求格式
3. **错误处理**：统一的错误响应格式
4. **格式转换**：安全的格式转换，防止注入攻击

---

## 📖 更多资源

- [Anthropic Claude API 官方文档](https://docs.anthropic.com/claude/reference/messages_post)
- [Claude Code CLI GitHub](https://github.com/anthropics/claude-code)
- [OpenAI API 兼容性说明](https://platform.openai.com/docs/api-reference)

---

**维护**: 此模块与 Gemini API 模块保持相同的架构和代码风格
**版本**: 1.0.0
**最后更新**: 2025-01-20
