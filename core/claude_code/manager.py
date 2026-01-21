"""
Claude Code CLI 核心业务管理器

统一入口，编排业务流程：执行命令、启动/关闭会话、格式转换
"""

import asyncio
import uuid
from typing import AsyncIterator, Optional, Union
from datetime import datetime

from .config import ClaudeCodeConfig, get_claude_code_config
from .models import (
    ExecuteRequest, ExecuteResponse,
    ChatRequest, ChatResponse,
    SessionInfo, CreateSessionRequest,
    ChatChunk
)
from .sessions import SessionStore, get_session_store
from .process import run_process, stream_process, build_claude_command, ProcessResult
from .parser import (
    convert_to_openai_response,
    create_openai_stream_chunk,
    parse_stream_line,
    parse_claude_native_output,
    build_user_prompt,
    create_stream_end_chunk
)
from .errors import CommandNotAllowed, ProcessFailed, ProcessTimeout, SessionNotFound


class ClaudeCodeManager:
    """
    Claude Code CLI 核心管理器

    统一入口，编排业务流程：执行命令、启动/关闭会话、格式转换
    """

    def __init__(
        self,
        config: Optional[ClaudeCodeConfig] = None,
        session_store: Optional[SessionStore] = None
    ):
        self.config = config or get_claude_code_config()
        self.sessions = session_store
        self.sem = asyncio.Semaphore(self.config.max_concurrency)
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """确保管理器已初始化"""
        if not self._initialized:
            if self.sessions is None:
                self.sessions = await get_session_store()
            self._initialized = True

    async def execute(self, req: ExecuteRequest) -> ExecuteResponse:
        """
        执行 claude-code 命令

        - 验证命令白名单
        - 构建命令
        - 执行并返回结果
        """
        await self._ensure_initialized()

        # 验证命令白名单
        self._validate_command(req.command)

        # 构建命令
        cmd = [self.config.cli_path, req.command]
        cmd.extend(req.args)

        # 构建环境变量
        env = self._build_env()

        # 执行命令
        try:
            result = await asyncio.wait_for(
                self._run_with_semaphore(
                    run_process,
                    cmd,
                    req.timeout,
                    env,
                    req.working_dir
                ),
                timeout=req.timeout
            )
        except asyncio.TimeoutError:
            raise ProcessTimeout(req.timeout, " ".join(cmd))
        except ProcessFailed as e:
            return ExecuteResponse(
                success=False,
                output=e.output,
                error=str(e),
                exit_code=e.exit_code,
                duration=0.0
            )

        # 格式化响应
        if req.response_format == "openai":
            # 如果是 JSON 输出，尝试转换为 OpenAI 格式
            try:
                parsed = parse_claude_native_output(result.stdout)
                openai_response = convert_to_openai_response(
                    parsed,
                    model="claude-code",
                    request_id=f"exec-{uuid.uuid4().hex[:24]}"
                )
                return ExecuteResponse(
                    success=result.success,
                    output=openai_response,
                    error=result.stderr if not result.success else None,
                    exit_code=result.return_code,
                    duration=result.duration
                )
            except Exception:
                return ExecuteResponse(
                    success=result.success,
                    output=result.stdout,
                    error=result.stderr if not result.success else None,
                    exit_code=result.return_code,
                    duration=result.duration
                )
        else:
            return ExecuteResponse(
                success=result.success,
                output=result.stdout,
                error=result.stderr if not result.success else None,
                exit_code=result.return_code,
                duration=result.duration
            )

    async def chat(
        self,
        req: ChatRequest
    ) -> Union[AsyncIterator[str], ChatResponse]:
        """
        对话接口

        - 流式模式返回 AsyncIterator[str]（SSE 格式）
        - 非流式模式返回 ChatResponse
        """
        await self._ensure_initialized()

        # 获取或创建会话
        session = await self.sessions.get_or_create(
            req.session_id,
            CreateSessionRequest(working_dir=req.working_dir, model=req.model)
        )

        if req.stream:
            return self._stream_chat(req, session)
        else:
            return await self._non_stream_chat(req, session)

    async def _stream_chat(
        self,
        req: ChatRequest,
        session: SessionInfo
    ) -> AsyncIterator[str]:
        """
        流式对话内部实现
        """
        await self._ensure_initialized()

        # 构建提示词
        prompt = build_user_prompt([m.model_dump() for m in req.messages])

        # 构建命令
        cmd = build_claude_command(
            prompt=prompt,
            model=req.model,
            session_id=session.session_id,
            include_tools=req.include_tools,
            output_format="text"
        )

        # 添加温度参数（如果支持）
        if req.temperature is not None:
            cmd.extend(["--temperature", str(req.temperature)])
        if req.top_p is not None:
            cmd.extend(["--top-p", str(req.top_p)])

        # 构建环境变量
        env = self._build_env()

        # 生成请求 ID
        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        # OpenAI 格式发送开始 chunk
        if req.response_format == "openai":
            yield create_openai_stream_chunk(
                request_id=request_id,
                model=req.model,
                delta={"role": "assistant"}
            )

        try:
            # 流式执行 - 在 semaphore 内直接迭代异步生成器
            async with self.sem:
                async for line in stream_process(cmd, env, req.working_dir, req.timeout):
                    # 解析并转换输出
                    chunk = parse_stream_line(
                        line=line,
                        response_format=req.response_format,
                        request_id=request_id,
                        model=req.model
                    )
                    if chunk:
                        yield chunk

        except (ProcessTimeout, ProcessFailed) as e:
            # OpenAI 格式发送错误 chunk
            if req.response_format == "openai":
                error_chunk = create_openai_stream_chunk(
                    request_id=request_id,
                    model=req.model,
                    delta={"content": f"[Error: {str(e)}]"},
                    finish_reason="error"
                )
                yield error_chunk
            return

        # 更新会话
        await self.sessions.increment_message_count(session.session_id)

        # OpenAI 格式发送结束 chunk
        if req.response_format == "openai":
            yield create_stream_end_chunk(request_id, req.model)

    async def _non_stream_chat(
        self,
        req: ChatRequest,
        session: SessionInfo
    ) -> ChatResponse:
        """
        非流式对话内部实现
        """
        await self._ensure_initialized()

        # 构建提示词
        prompt = build_user_prompt([m.model_dump() for m in req.messages])

        # 构建命令
        cmd = build_claude_command(
            prompt=prompt,
            model=req.model,
            session_id=session.session_id,
            include_tools=req.include_tools,
            output_format="json"
        )

        # 添加温度参数（如果支持）
        if req.temperature is not None:
            cmd.extend(["--temperature", str(req.temperature)])
        if req.top_p is not None:
            cmd.extend(["--top-p", str(req.top_p)])

        # 构建环境变量
        env = self._build_env()

        try:
            result = await asyncio.wait_for(
                self._run_with_semaphore(
                    run_process,
                    cmd,
                    req.timeout,
                    env,
                    req.working_dir
                ),
                timeout=req.timeout
            )
        except asyncio.TimeoutError:
            raise ProcessTimeout(req.timeout, " ".join(cmd))

        # 解析输出
        parsed = parse_claude_native_output(result.stdout)

        # 提取内容
        content = ""
        if isinstance(parsed, dict):
            content = parsed.get("content") or parsed.get("text") or parsed.get("response", "")
        elif isinstance(parsed, str):
            content = parsed

        # 提取 finish_reason
        finish_reason = "stop"
        if isinstance(parsed, dict):
            finish_reason = parsed.get("finish_reason", "stop")

        # 提取 usage
        usage = None
        if isinstance(parsed, dict) and "usage" in parsed:
            usage_data = parsed["usage"]
            usage = {
                "prompt_tokens": usage_data.get("input_tokens", usage_data.get("prompt_tokens", 0)),
                "completion_tokens": usage_data.get("output_tokens", usage_data.get("completion_tokens", 0)),
                "total_tokens": 0,
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        # 更新会话
        await self.sessions.increment_message_count(session.session_id)

        return ChatResponse(
            content=content,
            role="assistant",
            model=req.model,
            session_id=session.session_id,
            finish_reason=finish_reason,
            usage=usage
        )

    async def list_sessions(self) -> list[SessionInfo]:
        """列出所有会话"""
        await self._ensure_initialized()
        return await self.sessions.list()

    async def create_session(self, req: CreateSessionRequest) -> SessionInfo:
        """创建新会话"""
        await self._ensure_initialized()
        return await self.sessions.create(req)

    async def delete_session(self, session_id: str) -> None:
        """删除会话"""
        await self._ensure_initialized()
        await self.sessions.delete(session_id)

    async def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """获取会话"""
        await self._ensure_initialized()
        return await self.sessions.get(session_id)

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """清理过期会话"""
        await self._ensure_initialized()
        return await self.sessions.cleanup_old_sessions(max_age_hours)

    def _validate_command(self, command: str) -> None:
        """验证命令是否在白名单中"""
        if command not in self.config.allowed_commands:
            raise CommandNotAllowed(command, self.config.allowed_commands)

    def _build_env(self) -> dict[str, str]:
        """构建子进程环境变量"""
        import os
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = self.config.claude_api_key
        return env

    async def _run_with_semaphore(self, func, *args, **kwargs):
        """使用信号量控制并发执行"""
        async with self.sem:
            return await func(*args, **kwargs)


# 全局管理器实例
_global_manager: Optional[ClaudeCodeManager] = None


async def get_claude_code_manager() -> ClaudeCodeManager:
    """获取全局管理器实例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = ClaudeCodeManager()
        await _global_manager._ensure_initialized()
    return _global_manager


def reset_claude_code_manager():
    """重置全局管理器（用于测试）"""
    global _global_manager
    _global_manager = None
