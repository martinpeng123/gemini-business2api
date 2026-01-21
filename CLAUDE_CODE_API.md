# Claude Code CLI API 接口文档

本项目现已支持 **Claude Code CLI** 服务接口，与 Gemini CLI 并存提供服务。

## 📋 概述

Claude Code CLI 接口提供了与 Anthropic Claude Code 命令行工具的完整集成，支持：
- ✅ 命令执行
- ✅ 会话管理
- ✅ 流式/非流式对话
- ✅ OpenAI 兼容格式
- ✅ 多模态支持（计划中）

## 🚀 快速开始

### 1. 安装 Claude Code CLI

确保已安装 `claude` 命令行工具：

```bash
# 通过 npm 安装（推荐）
npm install -g @anthropic-ai/claude-code

# 或通过其他包管理器
# 具体安装方法请参考 Claude Code 官方文档
```

### 2. 配置环境变量

在 `.env` 文件中添加以下配置：

```bash
# Claude API Key（必需）
CLAUDE_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx

# 可选配置
CLAUDE_CLI_PATH=claude  # CLI 可执行文件路径
CLAUDE_CLI_MAX_CONCURRENCY=10  # 最大并发数
CLAUDE_CLI_TIMEOUT=300  # 默认超时（秒）
CLAUDE_CLI_SESSION_DIR=data/claude_sessions  # 会话存储目录
CLAUDE_CLI_ALLOWED_COMMANDS=chat,ask,code,explain,fix,test,review  # 允许的命令白名单
```

### 3. 启动服务

```bash
python main.py
```

服务启动后，Claude Code CLI 接口将在 `/v1/claude-code/*` 路径下可用。

## 📡 API 接口

### 基础 URL

```
http://localhost:7860/v1/claude-code
```

### 认证

所有接口需要在 Header 中提供 API Key：

```
Authorization: Bearer your-api-key
```

---

### 1. 健康检查

**端点**: `GET /v1/claude-code/health`

**描述**: 检查 Claude Code CLI 服务状态

**无需认证**

**响应示例**:
```json
{
  "status": "ok",
  "has_api_key": true,
  "cli_path": "claude",
  "max_concurrency": 10
}
```

---

### 2. 执行命令

**端点**: `POST /v1/claude-code/execute`

**描述**: 执行 Claude Code CLI 命令

**请求体**:
```json
{
  "command": "chat",
  "args": ["--help"],
  "timeout": 300,
  "response_format": "openai",  // "openai" 或 "native"
  "working_dir": "/path/to/project"  // 可选
}
```

**响应示例**:
```json
{
  "success": true,
  "output": "...",
  "error": null,
  "exit_code": 0,
  "duration": 1.23
}
```

---

### 3. 对话接口（核心接口）

**端点**: `POST /v1/claude-code/chat`

**描述**: 与 Claude 进行对话（OpenAI 兼容格式）

#### 流式请求示例

```json
{
  "messages": [
    {"role": "user", "content": "Hello, Claude!"}
  ],
  "model": "claude-3.5-sonnet",
  "stream": true,
  "session_id": "optional-session-id",
  "include_tools": false,
  "temperature": 0.7,
  "top_p": 1.0,
  "response_format": "openai",
  "timeout": 300,
  "working_dir": "/path/to/project"
}
```

#### 流式响应（Server-Sent Events）

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"claude-3.5-sonnet","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"claude-3.5-sonnet","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"claude-3.5-sonnet","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

#### 非流式请求示例

```json
{
  "messages": [
    {"role": "user", "content": "What is 2+2?"}
  ],
  "model": "claude-3.5-sonnet",
  "stream": false
}
```

#### 非流式响应

```json
{
  "content": "2 + 2 = 4",
  "role": "assistant",
  "model": "claude-3.5-sonnet",
  "session_id": "abc123",
  "finish_reason": "stop",
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

---

### 4. 会话管理

#### 4.1 列出所有会话

**端点**: `GET /v1/claude-code/sessions`

**响应示例**:
```json
[
  {
    "session_id": "abc123",
    "created_at": "2025-01-20T10:00:00",
    "last_used_at": "2025-01-20T10:30:00",
    "message_count": 5,
    "working_dir": "/path/to/project",
    "model": "claude-3.5-sonnet"
  }
]
```

#### 4.2 创建新会话

**端点**: `POST /v1/claude-code/sessions`

**请求体**:
```json
{
  "working_dir": "/path/to/project",
  "model": "claude-3.5-sonnet"
}
```

**响应**: 返回新创建的 `SessionInfo`

#### 4.3 删除会话

**端点**: `DELETE /v1/claude-code/sessions/{session_id}`

**响应示例**:
```json
{
  "status": "success",
  "message": "会话 abc123 已删除"
}
```

---

## 🔧 支持的模型

- `claude-3.5-sonnet` （默认）
- `claude-3-opus`
- `claude-3-sonnet`
- `claude-3-haiku`
- 其他 Claude Code CLI 支持的模型

## 📝 使用示例

### Python (httpx)

```python
import httpx

url = "http://localhost:7860/v1/claude-code/chat"
headers = {
    "Authorization": "Bearer your-api-key",
    "Content-Type": "application/json"
}
data = {
    "messages": [
        {"role": "user", "content": "写一个 Python 快速排序"}
    ],
    "model": "claude-3.5-sonnet",
    "stream": False
}

async with httpx.AsyncClient() as client:
    response = await client.post(url, json=data, headers=headers)
    print(response.json())
```

### JavaScript (fetch)

```javascript
const response = await fetch('http://localhost:7860/v1/claude-code/chat', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer your-api-key',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    messages: [
      { role: 'user', content: 'Explain async/await in JavaScript' }
    ],
    model: 'claude-3.5-sonnet',
    stream: false
  })
});

const result = await response.json();
console.log(result.content);
```

### cURL

```bash
curl -X POST http://localhost:7860/v1/claude-code/chat \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Hello, Claude!"}
    ],
    "model": "claude-3.5-sonnet",
    "stream": false
  }'
```

## 🔐 安全性

1. **API Key 保护**: 所有接口都需要有效的 API Key 认证
2. **命令白名单**: 只允许执行预定义的安全命令
3. **会话隔离**: 每个会话独立存储，互不干扰
4. **超时控制**: 防止长时间运行的命令占用资源
5. **并发限制**: 通过 Semaphore 控制并发执行数量

## 🐛 故障排查

### 1. Claude CLI 未找到

**错误**: `CliNotFoundError: claude-code executable not found`

**解决**:
```bash
# 检查 claude 是否安装
which claude

# 如果未安装，请安装：
npm install -g @anthropic-ai/claude-code

# 或在 .env 中指定完整路径：
CLAUDE_CLI_PATH=/path/to/claude
```

### 2. API Key 无效

**错误**: `403 Forbidden` 或 `API key validation failed`

**解决**:
- 检查 `.env` 中的 `CLAUDE_API_KEY` 是否正确
- 确认 API Key 没有过期
- 确保请求 Header 中携带了正确的 Authorization

### 3. 超时错误

**错误**: `ProcessTimeout: Process timeout after 300 seconds`

**解决**:
```bash
# 在 .env 中增加超时时间
CLAUDE_CLI_TIMEOUT=600  # 增加到 10 分钟

# 或在请求中指定
{
  "timeout": 600
}
```

## 📊 性能建议

1. **使用会话**: 对于连续对话，复用 `session_id` 可以保持上下文
2. **并发控制**: 根据服务器性能调整 `CLAUDE_CLI_MAX_CONCURRENCY`
3. **流式响应**: 对于长文本生成，使用 `stream: true` 获得更好的用户体验
4. **超时设置**: 根据任务复杂度合理设置 `timeout`

## 🔄 与 Gemini CLI 的区别

| 特性 | Claude Code CLI | Gemini CLI |
|------|----------------|------------|
| 端点前缀 | `/v1/claude-code` | `/v1/gemini-cli` |
| 默认模型 | `claude-3.5-sonnet` | `gemini-2.5-flash` |
| API Key 环境变量 | `CLAUDE_API_KEY` | `GEMINI_API_KEY` |
| CLI 路径 | `claude` | `gemini` |
| 会话存储 | `data/claude_sessions` | `data/gemini_sessions` |

## 📚 更多资源

- [Claude API 官方文档](https://docs.anthropic.com/)
- [Claude Code CLI GitHub](https://github.com/anthropics/claude-code)
- [OpenAI API 兼容性说明](https://platform.openai.com/docs/api-reference)

---

## 💡 常见问题

**Q: 可以同时使用 Gemini CLI 和 Claude Code CLI 吗？**
A: 可以！两个服务完全独立，可以同时运行并使用不同的会话。

**Q: 支持工具调用（Function Calling）吗？**
A: 支持！设置 `"include_tools": true` 即可启用 Agent 工具功能。

**Q: 如何迁移现有的 Gemini 会话到 Claude？**
A: 会话不能直接迁移，但可以复制消息历史并在 Claude 中创建新会话。

**Q: 响应格式可以自定义吗？**
A: 支持两种格式：`openai`（OpenAI 兼容）和 `native`（Claude 原生格式）。

---

**维护**: 此模块与 Gemini CLI 模块保持相同的架构和代码风格
**版本**: 1.0.0
**最后更新**: 2025-01-20
