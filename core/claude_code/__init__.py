"""
Claude Code CLI 集成模块

提供 Claude Code CLI 的完整支持，包括：
- 命令执行
- 会话管理
- 格式转换
"""

from .config import ClaudeCodeConfig, get_claude_code_config
from .manager import ClaudeCodeManager
from .models import (
    ExecuteRequest,
    ChatRequest,
    SessionInfo,
    CreateSessionRequest,
    ExecuteResponse,
    ChatResponse,
    ChatChunk,
    Message,
)
from .errors import (
    ClaudeCodeError,
    ProcessTimeout,
    CommandNotAllowed,
    SessionNotFound,
    ProcessFailed,
    CliNotFoundError,
    InvalidResponseFormat,
    SessionStorageError,
)

__all__ = [
    # 配置
    "ClaudeCodeConfig",
    "get_claude_code_config",
    # 管理器
    "ClaudeCodeManager",
    # 模型
    "ExecuteRequest",
    "ChatRequest",
    "SessionInfo",
    "CreateSessionRequest",
    "ExecuteResponse",
    "ChatResponse",
    "ChatChunk",
    "Message",
    # 错误
    "ClaudeCodeError",
    "ProcessTimeout",
    "CommandNotAllowed",
    "SessionNotFound",
    "ProcessFailed",
    "CliNotFoundError",
    "InvalidResponseFormat",
    "SessionStorageError",
]
