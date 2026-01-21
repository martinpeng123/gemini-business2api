"""
Gemini CLI 配置管理

从环境变量读取配置，集成到现有的 config_manager
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class GeminiCliConfig(BaseModel):
    """Gemini CLI 配置类"""

    gemini_api_key: str = Field(..., description="Gemini API Key（从环境变量 GEMINI_API_KEY 读取）")
    cli_path: str = Field(default="gemini", description="gemini-cli 可执行文件路径")
    max_concurrency: int = Field(default=10, ge=1, le=100, description="最大并发数")
    default_timeout: float = Field(default=300.0, ge=1.0, le=3600.0, description="默认超时（秒）")
    session_dir: str = Field(default="data/gemini_sessions", description="会话存储目录")
    allowed_commands: list[str] = Field(
        default=["chat", "ask", "code", "explain", "fix", "test"],
        description="允许的子命令白名单"
    )

    @classmethod
    def from_env(cls, session_dir: Optional[str] = None) -> 'GeminiCliConfig':
        """从环境变量创建配置"""
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            cli_path=os.getenv("GEMINI_CLI_PATH", "gemini"),
            max_concurrency=int(os.getenv("GEMINI_CLI_MAX_CONCURRENCY", "10")),
            default_timeout=float(os.getenv("GEMINI_CLI_TIMEOUT", "300")),
            session_dir=session_dir or os.getenv("GEMINI_CLI_SESSION_DIR", "data/gemini_sessions"),
            allowed_commands=os.getenv("GEMINI_CLI_ALLOWED_COMMANDS", "chat,ask,code,explain,fix,test").split(","),
        )

    def ensure_session_dir(self) -> Path:
        """确保会话目录存在"""
        path = Path(self.session_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


# 全局配置实例（延迟加载）
_global_config: Optional[GeminiCliConfig] = None


def get_gemini_cli_config() -> GeminiCliConfig:
    """获取全局 Gemini CLI 配置"""
    global _global_config
    if _global_config is None:
        _global_config = GeminiCliConfig.from_env()
    return _global_config


def reset_gemini_cli_config():
    """重置全局配置（用于测试）"""
    global _global_config
    _global_config = None