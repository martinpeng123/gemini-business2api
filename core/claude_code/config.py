"""
Claude Code CLI 配置管理

从环境变量读取配置
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class ClaudeCodeConfig(BaseModel):
    """Claude Code CLI 配置类"""

    claude_api_key: str = Field(..., description="Claude API Key（从环境变量 CLAUDE_API_KEY 读取）")
    cli_path: str = Field(default="claude", description="claude-code 可执行文件路径")
    max_concurrency: int = Field(default=10, ge=1, le=100, description="最大并发数")
    default_timeout: float = Field(default=300.0, ge=1.0, le=3600.0, description="默认超时（秒）")
    session_dir: str = Field(default="data/claude_sessions", description="会话存储目录")
    allowed_commands: list[str] = Field(
        default=["chat", "ask", "code", "explain", "fix", "test", "review"],
        description="允许的子命令白名单"
    )

    @classmethod
    def from_env(cls, session_dir: Optional[str] = None) -> 'ClaudeCodeConfig':
        """从环境变量创建配置"""
        return cls(
            claude_api_key=os.getenv("CLAUDE_API_KEY", ""),
            cli_path=os.getenv("CLAUDE_CLI_PATH", "claude"),
            max_concurrency=int(os.getenv("CLAUDE_CLI_MAX_CONCURRENCY", "10")),
            default_timeout=float(os.getenv("CLAUDE_CLI_TIMEOUT", "300")),
            session_dir=session_dir or os.getenv("CLAUDE_CLI_SESSION_DIR", "data/claude_sessions"),
            allowed_commands=os.getenv("CLAUDE_CLI_ALLOWED_COMMANDS", "chat,ask,code,explain,fix,test,review").split(","),
        )

    def ensure_session_dir(self) -> Path:
        """确保会话目录存在"""
        path = Path(self.session_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


# 全局配置实例（延迟加载）
_global_config: Optional[ClaudeCodeConfig] = None


def get_claude_code_config() -> ClaudeCodeConfig:
    """获取全局 Claude Code CLI 配置"""
    global _global_config
    if _global_config is None:
        _global_config = ClaudeCodeConfig.from_env()
    return _global_config


def reset_claude_code_config():
    """重置全局配置（用于测试）"""
    global _global_config
    _global_config = None
