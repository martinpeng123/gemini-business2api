"""
Claude Code CLI 输出解析与格式转换

处理 claude-code 输出，转换为 OpenAI 兼容格式
"""

import json
import uuid
import time
from typing import Optional, Any

from .models import ChatChunk, ToolCall


def parse_claude_native_output(output: str) -> dict:
    """
    解析 claude-code 原生 JSON 输出

    Args:
        output: claude-code 原始输出

    Returns:
        dict: 解析后的数据

    Raises:
        json.JSONDecodeError: JSON 解析失败
    """
    # 尝试解析 JSON
    try:
        parsed = json.loads(output)
        return parsed
    except json.JSONDecodeError:
        # 如果不是 JSON，返回原始文本
        return {"raw_output": output}


def convert_to_openai_response(
    claude_output: dict,
    model: str,
    request_id: Optional[str] = None
) -> dict:
    """
    将 claude-code 输出转换为 OpenAI 兼容的非流式响应格式

    Args:
        claude_output: claude-code 解析后的输出
        model: 模型名称
        request_id: 请求 ID

    Returns:
        dict: OpenAI 兼容的响应格式

    Example:
        >>> convert_to_openai_response({"content": "Hello"}, "claude-3.5-sonnet")
        {
            "id": "chatcmpl-xxx",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "claude-3.5-sonnet",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    """
    request_id = request_id or f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    # 提取内容
    content = ""
    if isinstance(claude_output, dict):
        content = claude_output.get("content") or claude_output.get("text") or claude_output.get("response", "")
    elif isinstance(claude_output, str):
        content = claude_output

    # 提取 finish_reason
    finish_reason = "stop"
    if isinstance(claude_output, dict):
        finish_reason = claude_output.get("finish_reason", "stop")

    # 提取 usage
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(claude_output, dict) and "usage" in claude_output:
        usage_data = claude_output["usage"]
        usage["prompt_tokens"] = usage_data.get("input_tokens", usage_data.get("prompt_tokens", 0))
        usage["completion_tokens"] = usage_data.get("output_tokens", usage_data.get("completion_tokens", 0))
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

    # 提取 tool_calls
    tool_calls = None
    if isinstance(claude_output, dict) and "tool_calls" in claude_output:
        tool_calls = claude_output["tool_calls"]

    response = {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }

    if tool_calls:
        response["choices"][0]["message"]["tool_calls"] = tool_calls

    return response


def create_openai_stream_chunk(
    request_id: str,
    model: str,
    delta: dict,
    finish_reason: Optional[str] = None,
    index: int = 0
) -> str:
    """
    创建 OpenAI 兼容的流式 chunk

    Args:
        request_id: 请求 ID
        model: 模型名称
        delta: 增量内容，如 {"content": "hello"} 或 {"role": "assistant"}
        finish_reason: 结束原因
        index: 选择索引

    Returns:
        str: SSE 格式的数据块 "data: {...}\n\n"

    Example:
        >>> create_openai_stream_chunk("chatcmpl-xxx", "claude-3.5-sonnet", {"content": "hello"})
        'data: {"id": "chatcmpl-xxx", "object": "chat.completion.chunk", "created": 1234567890, "model": "claude-3.5-sonnet", "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": null}]}\n\n'
    """
    created = int(time.time())

    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": index,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }

    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def parse_stream_line(
    line: str,
    response_format: str,
    request_id: str,
    model: str
) -> str:
    """
    解析 claude-code 流式输出的单行

    根据 response_format 转换为对应格式

    Args:
        line: claude-code 输出的一行
        response_format: 响应格式（openai 或 native）
        request_id: 请求 ID
        model: 模型名称

    Returns:
        str: 格式化后的输出

    Example:
        >>> parse_stream_line("Hello world", "openai", "chatcmpl-xxx", "claude-3.5-sonnet")
        'data: {"id": "chatcmpl-xxx", ...}\n\n'
    """
    if not line or line.strip() == "":
        return ""

    if response_format == "native":
        # 原生格式直接返回
        return f"{line}\n"

    # OpenAI 格式
    return create_openai_stream_chunk(
        request_id=request_id,
        model=model,
        delta={"content": line}
    )


def create_stream_end_chunk(request_id: str, model: str) -> str:
    """
    创建流式结束 chunk

    Args:
        request_id: 请求 ID
        model: 模型名称

    Returns:
        str: SSE 格式的结束数据块
    """
    created = int(time.time())

    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }

    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def parse_tool_calls(claude_output: dict) -> list[ToolCall]:
    """
    解析 claude-code 输出中的工具调用

    Args:
        claude_output: claude-code 解析后的输出

    Returns:
        list[ToolCall]: 工具调用列表
    """
    tool_calls = []

    if isinstance(claude_output, dict):
        raw_calls = claude_output.get("tool_calls") or claude_output.get("tools") or []

        for i, call in enumerate(raw_calls):
            if isinstance(call, dict):
                tool_calls.append(ToolCall(
                    id=call.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    type=call.get("type", "function"),
                    function={
                        "name": call.get("name", call.get("function", {}).get("name", "")),
                        "arguments": call.get("arguments", call.get("function", {}).get("arguments", "{}")),
                    }
                ))

    return tool_calls


def extract_content_from_output(output: Any) -> str:
    """
    从各种格式的输出中提取文本内容

    Args:
        output: 输出数据（可能是 dict, str, list 等）

    Returns:
        str: 提取的文本内容
    """
    if isinstance(output, str):
        return output

    if isinstance(output, dict):
        # 尝试多个可能的键
        for key in ["content", "text", "response", "message", "output"]:
            if key in output and output[key]:
                value = output[key]
                if isinstance(value, str):
                    return value
                elif isinstance(value, list):
                    # 处理文本块列表
                    parts = []
                    for item in value:
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            text = item.get("text") or extract_content_from_output(item)
                            if text:
                                parts.append(text)
                    return "\n".join(parts)
                elif isinstance(value, dict):
                    return extract_content_from_output(value)

        # 尝试 JSON 序列化
        return json.dumps(output, ensure_ascii=False)

    if isinstance(output, list):
        return "\n".join(extract_content_from_output(item) for item in output if item)

    return str(output)


def build_user_prompt(messages: list) -> str:
    """
    从消息列表构建用户提示词

    Args:
        messages: 消息列表

    Returns:
        str: 组合后的提示词
    """
    parts = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            if role == "system":
                parts.append(f"[SYSTEM]: {content}")
            elif role == "user":
                parts.append(f"[USER]: {content}")
            elif role == "assistant":
                parts.append(f"[ASSISTANT]: {content}")
            else:
                parts.append(f"[{role.upper()}]: {content}")
        elif isinstance(content, list):
            # 处理多模态内容
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(f"[{role.upper()}]: {item.get('text', '')}")
                    elif item.get("type") == "image_url":
                        parts.append(f"[{role.upper()}]: [IMAGE]")

    return "\n".join(parts)
