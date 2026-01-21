"""
Gemini CLI 服务接口核心模块

提供 gemini-cli 命令行工具的服务化封装
"""

from .config import GeminiCliConfig
from .models import (
    ExecuteRequest,
    ExecuteResponse,
    ChatRequest,
    ChatResponse,
    SessionInfo,
    CreateSessionRequest,
)
from .errors import (
    GeminiCliError,
    ProcessTimeout,
    CommandNotAllowed,
    SessionNotFound,
    ProcessFailed,
    CliNotFoundError,
)
from .manager import GeminiCliManager

__all__ = [
    'GeminiCliConfig',
    'GeminiCliManager',
    'ExecuteRequest',
    'ExecuteResponse',
    'ChatRequest',
    'ChatResponse',
    'SessionInfo',
    'CreateSessionRequest',
    'GeminiCliError',
    'ProcessTimeout',
    'CommandNotAllowed',
    'SessionNotFound',
    'ProcessFailed',
    'CliNotFoundError',
]