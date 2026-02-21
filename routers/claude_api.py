"""
Claude API 原生格式路由模块

提供与 Anthropic Claude API 兼容的原生格式接口：
- POST /v1/messages - Messages API（支持流式和非流式）
"""

import json
import logging
import time
import uuid
from typing import Optional, List, Dict, Any, AsyncGenerator, Union

from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from core.config import config

logger = logging.getLogger("claude")

router = APIRouter(tags=["Claude API"])


# ========== Claude API 请求模型 ==========

class ClaudeContentText(BaseModel):
    """Claude 文本内容块"""
    type: str = "text"
    text: str


class ClaudeContentImage(BaseModel):
    """Claude 图片内容块"""
    type: str = "image"
    source: Dict[str, str]


class ClaudeContent(BaseModel):
    """Claude 内容块（联合类型）"""
    # 使用 Union 无法直接序列化，使用通用字典
    pass


class ClaudeMessage(BaseModel):
    """Claude 消息"""
    role: str
    content: Any  # 可以是字符串或内容块列表


class ClaudeRequest(BaseModel):
    """Claude API 请求"""
    model: str
    messages: List[ClaudeMessage]
    max_tokens: Optional[int] = Field(default=4096, gt=0)  # 设置默认值 4096
    stream: bool = False
    system: Optional[Union[str, List[Dict[str, Any]]]] = None  # 支持字符串或内容块数组
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    tools: Optional[List[Dict[str, Any]]] = None  # 工具定义列表
    tool_choice: Optional[Dict[str, Any]] = None  # 工具选择策略


# ========== Claude API 响应模型 ==========

class ClaudeUsage(BaseModel):
    """Claude 使用量统计"""
    input_tokens: int
    output_tokens: int


class ClaudeResponse(BaseModel):
    """Claude API 响应"""
    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[Dict[str, Any]]
    model: str
    stop_reason: str
    stop_sequence: Optional[str] = None
    usage: ClaudeUsage


class ClaudeError(BaseModel):
    """Claude 错误响应"""
    type: str = "error"
    error: Dict[str, Any]


# ========== 工具函数 ==========

def convert_claude_tools_to_openai(claude_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Claude 工具定义转换为 OpenAI 格式

    Claude: {"name": "x", "description": "y", "input_schema": {...}}
    OpenAI: {"type": "function", "function": {"name": "x", "description": "y", "parameters": {...}}}
    """
    openai_tools = []
    for tool in claude_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {})
            }
        })
    return openai_tools


def convert_claude_tool_choice_to_openai(claude_tool_choice: Dict[str, Any]) -> Union[str, Dict[str, Any]]:
    """
    将 Claude tool_choice 转换为 OpenAI 格式

    Claude: {"type": "auto"} | {"type": "any"} | {"type": "tool", "name": "xxx"}
    OpenAI: "auto" | "required" | {"type": "function", "function": {"name": "xxx"}}
    """
    choice_type = claude_tool_choice.get("type")

    if choice_type == "auto":
        return "auto"
    elif choice_type == "any":
        return "required"
    elif choice_type == "tool":
        return {
            "type": "function",
            "function": {"name": claude_tool_choice.get("name")}
        }
    else:
        return "auto"


def claude_to_openai_messages(claude_req: ClaudeRequest) -> tuple[List[Dict[str, Any]], Optional[str], Optional[List[Dict[str, Any]]], Optional[Union[str, Dict[str, Any]]]]:
    """
    将 Claude 格式的请求转换为 OpenAI 格式

    Returns:
        (messages, system_prompt, tools, tool_choice): OpenAI格式消息列表、系统提示词、工具列表、工具选择策略
    """
    messages = []

    # 处理 system 参数（可能是字符串或内容块数组）
    system_prompt = None
    if claude_req.system:
        if isinstance(claude_req.system, str):
            system_prompt = claude_req.system
        elif isinstance(claude_req.system, list):
            # 提取所有文本块内容
            texts = []
            for block in claude_req.system:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            system_prompt = "\n".join(texts) if texts else None

    # 转换 tools 和 tool_choice
    openai_tools = None
    openai_tool_choice = None
    if claude_req.tools:
        openai_tools = convert_claude_tools_to_openai(claude_req.tools)
        if claude_req.tool_choice:
            openai_tool_choice = convert_claude_tool_choice_to_openai(claude_req.tool_choice)

    for msg in claude_req.messages:
        role = msg.role
        content = msg.content

        # Claude 只支持 user 和 assistant 角色
        if role not in ("user", "assistant"):
            continue

        # 处理 content
        if isinstance(content, str):
            # 纯文本
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            # 内容块列表（多模态/工具调用）
            text_parts = []
            tool_calls = []
            tool_results = []

            for block in content:
                if not isinstance(block, dict):
                    continue

                block_type = block.get("type")

                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append({"type": "text", "text": text})

                elif block_type == "image":
                    source = block.get("source", {})
                    media_type = source.get("media_type", "image/jpeg")
                    data = source.get("data", "")

                    if data:
                        # Claude 的 base64 数据通常不带前缀，需要添加
                        if not data.startswith("data:"):
                            text_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{data}"}
                            })
                        else:
                            text_parts.append({
                                "type": "image_url",
                                "image_url": {"url": data}
                            })

                elif block_type == "tool_use":
                    # Claude tool_use -> OpenAI tool_calls
                    tool_calls.append({
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {}))
                        }
                    })

                elif block_type == "tool_result":
                    # Claude tool_result -> OpenAI tool role message
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id"),
                        "content": block.get("content", "")
                    })

            # 构建消息
            if role == "assistant" and tool_calls:
                # Assistant 消息包含工具调用
                msg_dict = {"role": "assistant"}
                if text_parts:
                    # 如果有文本内容，提取纯文本
                    text_content = " ".join([p.get("text", "") for p in text_parts if p.get("type") == "text"])
                    if text_content:
                        msg_dict["content"] = text_content
                msg_dict["tool_calls"] = tool_calls
                messages.append(msg_dict)

            elif role == "user" and tool_results:
                # User 消息包含工具结果，转换为 tool 角色消息
                messages.extend(tool_results)

            elif text_parts:
                # 普通消息（文本/图片）
                messages.append({"role": role, "content": text_parts})

    return messages, system_prompt, openai_tools, openai_tool_choice


def openai_to_claude_response(
    openai_response: Dict[str, Any],
    model: str,
    message_id: str
) -> Dict[str, Any]:
    """
    将 OpenAI 格式的响应转换为 Claude 格式
    """
    choice = openai_response.get("choices", [{}])[0]
    message = choice.get("message", {})
    text_content = message.get("content", "")
    tool_calls = message.get("tool_calls", [])
    usage = openai_response.get("usage", {})

    # 构建 content 数组
    content_blocks = []

    # 添加文本内容
    if text_content:
        content_blocks.append({"type": "text", "text": text_content})

    # 转换 tool_calls 为 Claude tool_use 格式
    for tool_call in tool_calls:
        if tool_call.get("type") == "function":
            function = tool_call.get("function", {})
            # 解析 arguments JSON 字符串
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            content_blocks.append({
                "type": "tool_use",
                "id": tool_call.get("id"),
                "name": function.get("name"),
                "input": arguments
            })

    # 如果没有任何内容块，添加空文本
    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    # 确定 stop_reason
    finish_reason = choice.get("finish_reason", "stop")
    if finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"

    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0)
        }
    }


def create_claude_sse_chunk(event_type: str, data: Dict[str, Any]) -> str:
    """
    创建 Claude API SSE 格式的响应块

    Claude SSE 格式：
    event: {event_type}
    data: {json_data}
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ========== 路由端点 ==========

@router.post("/v1/messages")
async def claude_messages(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
    authorization: Optional[str] = Header(None)
):
    """
    Claude Messages API 原生格式接口

    支持：
    - POST /v1/messages - 非流式（stream=false）
    - POST /v1/messages - 流式（stream=true）

    认证方式：
    - x-api-key header（Claude 标准）
    - Authorization: Bearer xxx header（通用）
    """
    # 验证 API Key - 支持多种认证方式
    # 1. x-api-key header (Claude 标准)
    # 2. Authorization header (OpenAI 兼容)
    api_key_from_request = None

    if x_api_key:
        api_key_from_request = x_api_key
    elif authorization:
        # 提取 Bearer token 或直接使用
        if authorization.startswith("Bearer "):
            api_key_from_request = authorization[7:]
        else:
            api_key_from_request = authorization

    # 如果配置了 API Key，则验证
    if config.basic.api_key:
        if not api_key_from_request:
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "Missing API key"
                    }
                }
            )
        if api_key_from_request != config.basic.api_key:
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "Invalid API key"
                    }
                }
            )

    # 解析请求体
    try:
        body = await request.json()
        body_size = len(json.dumps(body))
        messages_count = len(body.get('messages', []))
        logger.info(f"[CLAUDE-API] 收到请求: model={body.get('model')}, stream={body.get('stream')}, max_tokens={body.get('max_tokens')}")
        logger.info(f"[CLAUDE-API] Payload 监控: size={body_size} bytes, messages={messages_count}")
        claude_req = ClaudeRequest(**body)
    except Exception as e:
        logger.error(f"[CLAUDE-API] 请求解析失败: {e}")
        logger.error(f"[CLAUDE-API] 请求体: {body if 'body' in locals() else 'N/A'}")
        raise HTTPException(
            status_code=400,
            detail={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": f"Invalid request format: {str(e)}"
                }
            }
        )

    # 转换为 OpenAI 格式
    messages, system_prompt, openai_tools, openai_tool_choice = claude_to_openai_messages(claude_req)

    # 记录工具调用信息
    if openai_tools:
        logger.info(f"[CLAUDE-API] 工具调用: tools={len(openai_tools)}, tool_choice={openai_tool_choice}")

    # Gemini 优化：使用精简的 system prompt 避免 Payload 过大导致 429 限流
    GEMINI_OPTIMIZED_SYSTEM_PROMPT = """You are an AI coding assistant.

Your role is to behave like a concise, reliable CLI-based coding helper,
similar in spirit to "Claude Code", but without assuming any built-in tools.

Core principles:
- Focus on correctness and practical usefulness.
- Prefer clear, minimal explanations over verbosity.
- Do not speculate about unavailable tools, files, or environment state.
- Only rely on information explicitly provided by the user.

When answering:
- If the user asks for code, provide complete, runnable code snippets.
- If the user asks for debugging, reason step-by-step but keep the output concise.
- If information is missing, ask a targeted clarifying question instead of guessing.
- If a request is ambiguous, state the ambiguity briefly and propose safe assumptions.

Formatting rules:
- Use Markdown when appropriate.
- Use fenced code blocks for code.
- Do NOT invent tool calls or system capabilities.
- Do NOT mention system prompts, policies, or internal instructions.

Tone:
- Professional, calm, and precise.
- No emojis, no roleplay, no unnecessary disclaimers."""

    # 根据配置决定是否优化 system prompt
    if system_prompt:
        if config.basic.claude_optimize_system_prompt:
            # Gemini 优化模式：替换为精简版本
            original_size = len(system_prompt.encode('utf-8'))
            optimized_size = len(GEMINI_OPTIMIZED_SYSTEM_PROMPT.encode('utf-8'))
            logger.info(f"[CLAUDE-API] System Prompt 优化: 原始={original_size} bytes -> 优化后={optimized_size} bytes (节省 {original_size - optimized_size} bytes)")
            messages.insert(0, {"role": "system", "content": GEMINI_OPTIMIZED_SYSTEM_PROMPT})
        else:
            # 原始模式：保留完整的 Claude Code system prompt
            logger.info(f"[CLAUDE-API] System Prompt 保持原样: {len(system_prompt.encode('utf-8'))} bytes")
            messages.insert(0, {"role": "system", "content": system_prompt})

    # 构建 OpenAI 请求
    openai_req = {
        "model": claude_req.model,
        "messages": messages,
        "stream": claude_req.stream,
        "max_tokens": claude_req.max_tokens,
    }
    if claude_req.temperature is not None:
        openai_req["temperature"] = claude_req.temperature
    if claude_req.top_p is not None:
        openai_req["top_p"] = claude_req.top_p
    if openai_tools:
        openai_req["tools"] = openai_tools
    if openai_tool_choice:
        openai_req["tool_choice"] = openai_tool_choice

    # 调用内部 chat 实现
    from main import chat_impl, ChatRequest

    class MockRequest:
        def __init__(self, client_host="127.0.0.1"):
            self.client = type('obj', (object,), {'host': client_host})()
            self.headers = {}
            self.state = type('State', (object,), {
                'first_response_time': None,
                'model': None
            })()

    chat_req = ChatRequest(**openai_req)
    mock_request = MockRequest()

    # 生成 Claude 消息 ID
    message_id = f"msg_{uuid.uuid4().hex[:24]}"

    if claude_req.stream:
        # 流式响应
        async def stream_generator() -> AsyncGenerator[str, None]:
            """流式响应生成器"""
            full_text = ""

            try:
                response = await chat_impl(chat_req, mock_request, authorization)

                # 获取流式响应
                async for chunk in response.body_iterator:
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8')

                    if chunk.startswith("data: [DONE]"):
                        break

                    if chunk.startswith("data: "):
                        try:
                            data = json.loads(chunk[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")

                            if content or reasoning:
                                # 转换为 Claude 格式
                                # Claude 使用 content_block_delta 事件
                                text_to_send = content + reasoning
                                if text_to_send:
                                    full_text += text_to_send

                                    claude_chunk = {
                                        "type": "content_block_delta",
                                        "index": 0,
                                        "delta": {
                                            "type": "text_delta",
                                            "text": text_to_send
                                        }
                                    }
                                    yield create_claude_sse_chunk("content_block_delta", claude_chunk)

                        except (json.JSONDecodeError, KeyError, IndexError) as e:
                            logger.warning(f"[CLAUDE-API] 流解析失败: {e}")
                            continue

                # 发送停止事件
                stop_chunk = {
                    "type": "message_stop"
                }
                yield create_claude_sse_chunk("message_stop", stop_chunk)

            except HTTPException as e:
                error_data = {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(e.detail)
                    }
                }
                yield create_claude_sse_chunk("error", error_data)
            except Exception as e:
                logger.error(f"[CLAUDE-API] 流生成失败: {e}")
                error_data = {
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(e)
                    }
                }
                yield create_claude_sse_chunk("error", error_data)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream"
        )
    else:
        # 非流式响应
        try:
            response = await chat_impl(chat_req, mock_request, authorization)
        except HTTPException as e:
            raise HTTPException(
                status_code=e.status_code,
                detail={
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(e.detail)
                    }
                }
            )
        except Exception as e:
            logger.error(f"[CLAUDE-API] 生成失败: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "type": "error",
                    "error": {
                        "type": "api_error",
                        "message": str(e)
                    }
                }
            )

        # 转换为 Claude 格式
        claude_response = openai_to_claude_response(response, claude_req.model, message_id)

        return JSONResponse(content=claude_response)