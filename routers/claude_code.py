"""
Claude Code CLI 路由模块

提供 claude-code 命令行工具的 API 接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from core.auth import verify_api_key
from core.claude_code import (
    ClaudeCodeManager,
    ExecuteRequest,
    ExecuteResponse,
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    SessionInfo,
    ClaudeCodeError,
    ProcessTimeout,
    CommandNotAllowed,
    SessionNotFound,
    ProcessFailed,
    CliNotFoundError,
)
from core.claude_code.manager import get_claude_code_manager
from core.config import config

logger = logging.getLogger("gemini")

router = APIRouter(prefix="/v1/claude-code", tags=["Claude Code"])


async def verify_claude_code_api_key(authorization: Optional[str] = Header(None)) -> None:
    """验证 Claude Code API Key（使用独立的配置）"""
    claude_api_key = config.basic.api_key
    verify_api_key(claude_api_key, authorization)


@router.post("/execute", response_model=ExecuteResponse)
async def execute_command(
    req: ExecuteRequest,
    authorization: Optional[str] = Header(None),
):
    """
    执行 claude-code 命令

    - command: 命令内容
    - args: 额外参数
    - timeout: 超时时间（秒）
    - response_format: 响应格式（openai 或 native）
    - working_dir: 工作目录
    """
    await verify_claude_code_api_key(authorization)

    manager = await get_claude_code_manager()

    try:
        logger.info(f"[CLAUDE-CODE] 执行命令: {req.command} args={req.args}")
        result = await manager.execute(req)
        logger.info(f"[CLAUDE-CODE] 命令执行完成: success={result.success}")
        return result
    except CommandNotAllowed as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ProcessTimeout as e:
        logger.error(f"[CLAUDE-CODE] 命令超时: {e}")
        raise HTTPException(status_code=504, detail=str(e))
    except CliNotFoundError as e:
        logger.error(f"[CLAUDE-CODE] CLI 未找到: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ClaudeCodeError as e:
        logger.error(f"[CLAUDE-CODE] 执行错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    对话接口（支持流式和非流式）

    - messages: 消息列表
    - session_id: 会话 ID（可选，不提供则创建新会话）
    - model: 模型名称
    - stream: 是否流式响应
    - response_format: 响应格式（openai 或 native）
    - timeout: 超时时间（秒）
    - include_tools: 是否启用 Agent 工具
    """
    await verify_claude_code_api_key(authorization)

    manager = await get_claude_code_manager()

    try:
        logger.info(
            f"[CLAUDE-CODE] 聊天请求: model={req.model} "
            f"stream={req.stream} session_id={req.session_id} "
            f"messages={len(req.messages)}"
        )

        if req.stream:
            # 流式响应
            streamer = await manager.chat(req)
            return StreamingResponse(
                streamer,
                media_type="text/event-stream",
            )
        else:
            # 非流式响应
            result = await manager.chat(req)
            logger.info(f"[CLAUDE-CODE] 聊天完成: session_id={result.session_id}")
            return result

    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProcessTimeout as e:
        logger.error(f"[CLAUDE-CODE] 聊天超时: {e}")
        raise HTTPException(status_code=504, detail=str(e))
    except ProcessFailed as e:
        logger.error(f"[CLAUDE-CODE] 进程失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ClaudeCodeError as e:
        logger.error(f"[CLAUDE-CODE] 聊天错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    authorization: Optional[str] = Header(None),
):
    """
    列出所有会话
    """
    await verify_claude_code_api_key(authorization)

    manager = await get_claude_code_manager()
    sessions = await manager.list_sessions()
    logger.info(f"[CLAUDE-CODE] 列出会话: {len(sessions)} 个")
    return sessions


@router.post("/sessions", response_model=SessionInfo)
async def create_session(
    req: CreateSessionRequest,
    authorization: Optional[str] = Header(None),
):
    """
    创建新会话

    - working_dir: 工作目录（可选）
    - model: 模型名称
    """
    await verify_claude_code_api_key(authorization)

    manager = await get_claude_code_manager()
    session = await manager.create_session(req)
    logger.info(f"[CLAUDE-CODE] 创建会话: {session.session_id}")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    删除会话
    """
    await verify_claude_code_api_key(authorization)

    manager = await get_claude_code_manager()

    try:
        await manager.delete_session(session_id)
        logger.info(f"[CLAUDE-CODE] 删除会话: {session_id}")
        return {"status": "success", "message": f"会话 {session_id} 已删除"}
    except SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/health")
async def health_check():
    """
    健康检查
    """
    try:
        manager = await get_claude_code_manager()
        # 简单检查配置是否有效
        config = manager.config
        has_api_key = bool(config.claude_api_key)
        return {
            "status": "ok",
            "has_api_key": has_api_key,
            "cli_path": config.cli_path,
            "max_concurrency": config.max_concurrency,
        }
    except Exception as e:
        logger.error(f"[CLAUDE-CODE] 健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
