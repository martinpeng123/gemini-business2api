"""
Gemini API 原生格式路由模块

提供与 Google Gemini API 兼容的原生格式接口：
- POST /v1beta/models/{model}:generateContent - 非流式
- POST /v1beta/models/{model}:streamGenerateContent - 流式
"""

import json
import logging
import time
import uuid
from typing import Optional, List, Dict, Any, AsyncGenerator

from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from core.auth import verify_api_key
from core.config import config

logger = logging.getLogger("gemini")

router = APIRouter(tags=["Gemini API"])


# ========== Gemini API 请求模型 ==========

class GeminiPart(BaseModel):
    """Gemini API Part"""
    text: Optional[str] = None
    inline_data: Optional[Dict[str, Any]] = None


class GeminiContent(BaseModel):
    """Gemini API Content"""
    parts: List[GeminiPart]
    role: str = "user"


class GenerationConfig(BaseModel):
    """生成配置"""
    temperature: Optional[float] = None
    maxOutputTokens: Optional[int] = None
    topP: Optional[float] = None
    topK: Optional[int] = None


class GeminiRequest(BaseModel):
    """Gemini API 请求"""
    contents: List[GeminiContent]
    generationConfig: Optional[GenerationConfig] = None
    safetySettings: Optional[List[Dict[str, Any]]] = None
    tools: Optional[List[Dict[str, Any]]] = None


# ========== Gemini API 响应模型 ==========

class GeminiCandidate(BaseModel):
    """候选响应"""
    content: GeminiContent
    finishReason: str = "STOP"
    index: int = 0
    safetyRatings: Optional[List[Dict[str, Any]]] = None


class GeminiResponse(BaseModel):
    """Gemini API 响应"""
    candidates: List[GeminiCandidate]
    usageMetadata: Optional[Dict[str, Any]] = None


# ========== 工具函数 ==========

def gemini_to_openai_messages(contents: List[GeminiContent]) -> List[Dict[str, Any]]:
    """将 Gemini 格式的 contents 转换为 OpenAI 格式的 messages"""
    messages = []

    for content in contents:
        role = content.role

        # Gemini 的 role 映射: user -> user, model -> assistant
        if role == "model":
            role = "assistant"

        parts = content.parts
        if not parts:
            continue

        # 检查是否有图片（多模态）
        has_image = any(p.inline_data is not None for p in parts)

        if has_image:
            # 多模态内容
            content_list = []
            for part in parts:
                if part.text:
                    content_list.append({"type": "text", "text": part.text})
                elif part.inline_data:
                    data = part.inline_data
                    mime_type = data.get("mimeType", "image/jpeg")
                    b64_data = data.get("data", "")
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}
                    })
            messages.append({"role": role, "content": content_list})
        else:
            # 纯文本内容
            text = " ".join(p.text for p in parts if p.text)
            if text:
                messages.append({"role": role, "content": text})

    return messages


def openai_to_gemini_response(openai_response: Dict[str, Any], model: str) -> Dict[str, Any]:
    """将 OpenAI 格式的响应转换为 Gemini 格式"""
    content = openai_response.get("choices", [{}])[0].get("message", {})
    text_content = content.get("content", "")

    return {
        "candidates": [{
            "content": {
                "parts": [{"text": text_content}],
                "role": "model"
            },
            "finishReason": "STOP",
            "index": 0
        }],
        "usageMetadata": {
            "promptTokenCount": openai_response.get("usage", {}).get("prompt_tokens", 0),
            "candidatesTokenCount": openai_response.get("usage", {}).get("completion_tokens", 0),
            "totalTokenCount": openai_response.get("usage", {}).get("total_tokens", 0)
        }
    }


def create_sse_chunk(data: Dict[str, Any]) -> str:
    """创建 SSE 格式的响应块"""
    return f"data: {json.dumps(data)}\n\n"


# ========== 路由端点 ==========

@router.post("/v1beta/models/{model_action:path}")
async def gemini_generate(
    model_action: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key")
):
    """
    Gemini API 原生格式统一入口

    支持：
    - POST /v1beta/models/{model}:generateContent - 非流式
    - POST /v1beta/models/{model}:streamGenerateContent - 流式
    """
    from urllib.parse import unquote

    # URL 解码
    decoded = unquote(model_action)

    # 判断请求类型
    is_stream = ":streamGenerateContent" in decoded
    is_generate = ":generateContent" in decoded and not is_stream

    if not (is_stream or is_generate):
        raise HTTPException(status_code=404, detail="Not Found")

    # 提取模型名称
    if is_stream:
        model_name = decoded.split(":streamGenerateContent")[0]
    else:
        model_name = decoded.split(":generateContent")[0]

    # 验证 API Key - 支持多种认证方式
    # 1. x-goog-api-key header (Gemini 标准)
    # 2. Authorization header (OpenAI 兼容)
    # 3. URL 参数 key= (Gemini 备用)
    api_key_from_request = None

    if x_goog_api_key:
        api_key_from_request = x_goog_api_key
    elif authorization:
        # 提取 Bearer token 或直接使用
        if authorization.startswith("Bearer "):
            api_key_from_request = authorization[7:]
        else:
            api_key_from_request = authorization
    else:
        # 尝试从 URL 参数获取
        api_key_from_request = request.query_params.get("key")

    # 如果配置了 API Key，则验证
    if config.basic.api_key:
        if not api_key_from_request:
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": 401, "message": "API key not provided", "status": "UNAUTHENTICATED"}}
            )
        if api_key_from_request != config.basic.api_key:
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": 401, "message": "Invalid API key", "status": "UNAUTHENTICATED"}}
            )

    # 解析请求体
    try:
        body = await request.json()
        gemini_req = GeminiRequest(**body)
    except Exception as e:
        logger.error(f"[GEMINI-API] 请求解析失败: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")

    # 转换为 OpenAI 格式
    messages = gemini_to_openai_messages(gemini_req.contents)

    # 获取生成配置
    gen_config = gemini_req.generationConfig or GenerationConfig()
    temperature = gen_config.temperature or 0.7
    max_tokens = gen_config.maxOutputTokens
    top_p = gen_config.topP

    # 构建 OpenAI 请求
    openai_req = {
        "model": model_name,
        "messages": messages,
        "stream": is_stream,
        "temperature": temperature,
    }
    if max_tokens is not None:
        openai_req["max_tokens"] = max_tokens
    if top_p is not None:
        openai_req["top_p"] = top_p

    # 调用内部 chat 实现
    from main import chat_impl, ChatRequest

    class MockRequest:
        def __init__(self, client_host="127.0.0.1"):
            self.client = type('obj', (object,), {'host': client_host})()
            self.headers = {}
            # 添加 state 对象，模拟 Starlette 的 Request.state
            self.state = type('State', (object,), {
                'first_response_time': None,
                'model': None
            })()

    chat_req = ChatRequest(**openai_req)
    mock_request = MockRequest()

    if is_stream:
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

                            if content:
                                full_text += content

                                # 转换为 Gemini 格式
                                gemini_chunk = {
                                    "candidates": [{
                                        "content": {
                                            "parts": [{"text": content}],
                                            "role": "model"
                                        },
                                        "finishReason": None,
                                        "index": 0
                                    }]
                                }
                                yield create_sse_chunk(gemini_chunk)

                        except (json.JSONDecodeError, KeyError, IndexError) as e:
                            logger.warning(f"[GEMINI-API] 流解析失败: {e}")
                            continue

                # 发送最终响应
                final_chunk = {
                    "candidates": [{
                        "content": {
                            "parts": [{"text": full_text}],
                            "role": "model"
                        },
                        "finishReason": "STOP",
                        "index": 0
                    }],
                    "usageMetadata": {
                        "promptTokenCount": 0,
                        "candidatesTokenCount": 0,
                        "totalTokenCount": 0
                    }
                }
                yield create_sse_chunk(final_chunk)

            except HTTPException as e:
                error_chunk = {
                    "error": {
                        "code": e.status_code,
                        "message": e.detail
                    }
                }
                yield create_sse_chunk(error_chunk)
            except Exception as e:
                logger.error(f"[GEMINI-API] 流生成失败: {e}")
                error_chunk = {
                    "error": {
                        "code": 500,
                        "message": str(e)
                    }
                }
                yield create_sse_chunk(error_chunk)

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream"
        )
    else:
        # 非流式响应
        try:
            response = await chat_impl(chat_req, mock_request, authorization)
        except HTTPException as e:
            raise e
        except Exception as e:
            logger.error(f"[GEMINI-API] 生成失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))

        # 转换为 Gemini 格式
        gemini_response = openai_to_gemini_response(response, model_name)

        return JSONResponse(content=gemini_response)