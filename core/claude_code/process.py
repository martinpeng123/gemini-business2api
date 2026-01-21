"""
Claude Code CLI 子进程管理

提供安全的子进程执行和流式输出功能
"""

import asyncio
from asyncio.subprocess import Process, PIPE
from typing import AsyncIterator, Optional
from datetime import datetime

from .errors import ProcessTimeout, ProcessFailed
from .config import get_claude_code_config


class ProcessResult:
    """子进程执行结果"""

    def __init__(
        self,
        stdout: str,
        stderr: str,
        return_code: int,
        duration: float
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.duration = duration

    @property
    def success(self) -> bool:
        """是否执行成功"""
        return self.return_code == 0

    def __repr__(self) -> str:
        return (
            f"ProcessResult(success={self.success}, "
            f"return_code={self.return_code}, "
            f"duration={self.duration:.2f}s)"
        )


async def run_process(
    cmd: list[str],
    timeout: float,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None
) -> ProcessResult:
    """
    执行子进程命令

    Args:
        cmd: 命令列表（禁止使用 shell=True）
        timeout: 超时时间（秒）
        env: 环境变量
        cwd: 工作目录

    Returns:
        ProcessResult: 执行结果

    Raises:
        ProcessTimeout: 进程超时
        ProcessFailed: 进程执行失败
    """
    start_time = datetime.now()
    process: Optional[Process] = None

    try:
        # 创建子进程（禁止 shell=True）
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
            env=env,
            cwd=cwd
        )

        # 等待进程完成，带超时
        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # 超时后终止进程
            if process:
                process.kill()
                await process.wait()
            raise ProcessTimeout(timeout, " ".join(cmd))

        # 解码输出
        stdout = stdout_data.decode('utf-8', errors='replace')
        stderr = stderr_data.decode('utf-8', errors='replace')
        return_code = process.returncode or 0
        duration = (datetime.now() - start_time).total_seconds()

        result = ProcessResult(stdout, stderr, return_code, duration)

        # 如果进程返回非零退出码，抛出异常
        if return_code != 0:
            error_msg = stderr.strip() if stderr else f"Process exited with code {return_code}"
            raise ProcessFailed(return_code, error_msg)

        return result

    except ProcessTimeout:
        raise
    except ProcessFailed:
        raise
    except Exception as e:
        # 其他异常也作为进程失败处理
        if process and process.returncode:
            raise ProcessFailed(process.returncode, str(e))
        raise ProcessFailed(-1, str(e))


async def stream_process(
    cmd: list[str],
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout: float = 300
) -> AsyncIterator[str]:
    """
    流式执行子进程命令

    Args:
        cmd: 命令列表
        env: 环境变量
        cwd: 工作目录
        timeout: 超时时间（秒）

    Yields:
        str: 逐行输出

    Raises:
        ProcessTimeout: 进程超时
    """
    process: Optional[Process] = None

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
            env=env,
            cwd=cwd
        )

        # 逐行读取输出，保持超时控制
        while True:
            try:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                raise ProcessTimeout(timeout, " ".join(cmd))

            if not line:
                break

            yield line.decode('utf-8', errors='replace').rstrip('\n\r')

        # 等待进程结束
        return_code = await process.wait()

        if return_code != 0:
            # 读取 stderr
            stderr_data = await process.stderr.read() if process.stderr else b""
            stderr = stderr_data.decode('utf-8', errors='replace')
            error_msg = stderr.strip() if stderr else f"Process exited with code {return_code}"
            raise ProcessFailed(return_code, error_msg)

    except ProcessTimeout:
        raise
    except ProcessFailed:
        raise
    except asyncio.CancelledError:
        # 如果任务被取消，确保进程被终止
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    except Exception as e:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        raise ProcessFailed(-1, str(e))


def build_claude_command(
    prompt: str,
    model: str = "claude-3.5-sonnet",
    session_id: Optional[str] = None,
    include_tools: bool = False,
    output_format: str = "json",
    extra_args: Optional[list[str]] = None
) -> list[str]:
    """
    构建 claude-code 命令

    Args:
        prompt: 提示词
        model: 模型名称
        session_id: 会话 ID
        include_tools: 是否启用 Agent 工具
        output_format: 输出格式（json, text, markdown）
        extra_args: 额外参数

    Returns:
        list[str]: 命令列表

    Example:
        >>> build_claude_command("hello", model="claude-3.5-sonnet")
        ['claude', 'chat', '--prompt', 'hello', '--model', 'claude-3.5-sonnet']
    """
    config = get_claude_code_config()
    cmd = [config.cli_path, "chat"]

    # 添加提示词
    cmd.extend(["--prompt", prompt])

    # 添加模型
    if model:
        cmd.extend(["--model", model])

    # 添加会话 ID
    if session_id:
        cmd.extend(["--session", session_id])

    # 启用工具
    if include_tools:
        cmd.append("--tools")

    # 输出格式
    if output_format:
        cmd.extend(["--format", output_format])

    # API Key 通过环境变量传递，不在命令行中暴露

    # 额外参数
    if extra_args:
        cmd.extend(extra_args)

    return cmd


def validate_command_allowed(command: str) -> bool:
    """
    验证命令是否在允许的白名单中

    Args:
        command: 要验证的命令

    Returns:
        bool: 是否允许
    """
    config = get_claude_code_config()
    return command in config.allowed_commands
