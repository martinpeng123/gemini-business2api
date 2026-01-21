"""
Claude Code CLI 错误类型

定义与 claude-code 交互过程中的异常
"""


class ClaudeCodeError(Exception):
    """Claude Code CLI 基础异常"""

    def __init__(self, message: str, details: str = ""):
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


class ProcessTimeout(ClaudeCodeError):
    """进程超时异常"""

    def __init__(self, timeout: float, command: str = ""):
        super().__init__(
            f"Process timeout after {timeout} seconds",
            command
        )
        self.timeout = timeout
        self.command = command


class CommandNotAllowed(ClaudeCodeError):
    """不允许的命令异常"""

    def __init__(self, command: str, allowed: list[str]):
        super().__init__(
            f"Command '{command}' is not allowed",
            f"Allowed commands: {', '.join(allowed)}"
        )
        self.command = command
        self.allowed = allowed


class SessionNotFound(ClaudeCodeError):
    """会话未找到异常"""

    def __init__(self, session_id: str):
        super().__init__(
            f"Session not found",
            session_id
        )
        self.session_id = session_id


class ProcessFailed(ClaudeCodeError):
    """进程执行失败异常"""

    def __init__(self, exit_code: int, output: str = ""):
        super().__init__(
            f"Process failed with exit code {exit_code}",
            output
        )
        self.exit_code = exit_code
        self.output = output


class CliNotFoundError(ClaudeCodeError):
    """claude-code 未找到异常"""

    def __init__(self, cli_path: str):
        super().__init__(
            f"claude-code executable not found",
            cli_path
        )
        self.cli_path = cli_path


class InvalidResponseFormat(ClaudeCodeError):
    """无效响应格式异常"""

    def __init__(self, expected: str, actual: str):
        super().__init__(
            f"Invalid response format",
            f"Expected: {expected}, Got: {actual}"
        )
        self.expected = expected
        self.actual = actual


class SessionStorageError(ClaudeCodeError):
    """会话存储异常"""

    def __init__(self, operation: str, details: str = ""):
        super().__init__(
            f"Session storage error: {operation}",
            details
        )
        self.operation = operation
