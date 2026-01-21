"""
Claude Code CLI 请求/响应模型

定义与 claude-code 交互的数据结构
"""

from datetime import datetime
from typing import Literal, Union, List, Dict, Any, Optional
from pydantic import BaseModel, Field


# 复用现有的 Message 类型
class Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]


class ExecuteRequest(BaseModel):
    """执行 claude-code 命令请求"""

    command: str = Field(..., description="命令内容")
    args: List[str] = Field(default_factory=list, description="额外参数")
    timeout: float = Field(default=300.0, ge=1.0, le=3600.0, description="超时时间（秒）")
    response_format: Literal["openai", "native"] = Field(
        default="openai",
        description="响应格式：openai（兼容 OpenAI 格式）或 native（原生格式）"
    )
    working_dir: Optional[str] = Field(default=None, description="工作目录")


class ChatRequest(BaseModel):
    """聊天请求"""

    messages: List[Message] = Field(..., description="消息列表")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    model: str = Field(default="claude-3.5-sonnet", description="模型名称")
    stream: bool = Field(default=True, description="是否流式响应")
    response_format: Literal["openai", "native"] = Field(
        default="openai",
        description="响应格式"
    )
    timeout: float = Field(default=300.0, ge=1.0, le=3600.0, description="超时时间（秒）")
    include_tools: bool = Field(default=False, description="是否启用 Agent 工具")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0, description="Top-p 参数")
    working_dir: Optional[str] = Field(default=None, description="工作目录")


class SessionInfo(BaseModel):
    """会话信息"""

    session_id: str = Field(..., description="会话 ID")
    created_at: datetime = Field(..., description="创建时间")
    last_used_at: datetime = Field(..., description="最后使用时间")
    message_count: int = Field(default=0, ge=0, description="消息数量")
    working_dir: Optional[str] = Field(default=None, description="工作目录")
    model: str = Field(default="claude-3.5-sonnet", description="使用的模型")


class CreateSessionRequest(BaseModel):
    """创建会话请求"""

    working_dir: Optional[str] = Field(default=None, description="工作目录")
    model: str = Field(default="claude-3.5-sonnet", description="模型名称")


class ExecuteResponse(BaseModel):
    """执行响应"""

    success: bool = Field(..., description="是否成功")
    output: Union[str, Dict[str, Any]] = Field(default="", description="命令输出，字符串或 OpenAI 兼容格式")
    error: Optional[str] = Field(default=None, description="错误信息（如有）")
    exit_code: int = Field(default=0, description="进程退出码")
    duration: float = Field(default=0.0, description="执行耗时（秒）")


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""

    content: str = Field(..., description="响应内容")
    role: str = Field(default="assistant", description="角色")
    model: str = Field(..., description="使用的模型")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    finish_reason: Optional[str] = Field(default=None, description="结束原因")
    usage: Optional[Dict[str, int]] = Field(default=None, description="token 使用情况")


class ToolCall(BaseModel):
    """工具调用"""

    id: str = Field(..., description="工具调用 ID")
    type: str = Field(default="function", description="类型")
    function: Dict[str, str] = Field(..., description="函数信息")


class ChatChunk(BaseModel):
    """流式聊天响应块"""

    content: str = Field(default="", description="内容片段")
    role: str = Field(default="assistant", description="角色")
    finish_reason: Optional[str] = Field(default=None, description="结束原因")
    tool_calls: Optional[List[ToolCall]] = Field(default=None, description="工具调用")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
