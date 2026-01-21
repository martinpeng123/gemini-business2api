"""
Claude Code CLI 会话管理

提供会话的创建、查询、更新和持久化功能
"""

import json
import asyncio
import secrets
from datetime import datetime
from typing import Optional
from pathlib import Path

from .models import SessionInfo, CreateSessionRequest
from .errors import SessionNotFound, SessionStorageError
from .config import get_claude_code_config


class SessionStore:
    """会话存储管理（内存 + JSON 文件持久化）"""

    def __init__(self, session_dir: Optional[str] = None):
        config = get_claude_code_config()
        self.session_dir = Path(session_dir or config.session_dir)
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = asyncio.Lock()
        self._metadata_file = self.session_dir / "sessions.json"

    async def initialize(self) -> None:
        """初始化会话存储"""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        await self._load_from_disk()

    async def create(self, req: CreateSessionRequest) -> SessionInfo:
        """创建新会话"""
        async with self._lock:
            session_id = self._generate_session_id()
            now = datetime.now()

            session = SessionInfo(
                session_id=session_id,
                created_at=now,
                last_used_at=now,
                message_count=0,
                working_dir=req.working_dir,
                model=req.model
            )

            self._sessions[session_id] = session
            await self._save_to_disk()
            return session

    async def get(self, session_id: str) -> Optional[SessionInfo]:
        """获取会话"""
        async with self._lock:
            return self._sessions.get(session_id)

    async def get_or_create(
        self,
        session_id: Optional[str],
        req: Optional[CreateSessionRequest] = None
    ) -> SessionInfo:
        """获取或创建会话"""
        if session_id:
            session = await self.get(session_id)
            if session:
                return session
            if req is None:
                req = CreateSessionRequest()

        req = req or CreateSessionRequest()
        return await self.create(req)

    async def list(self) -> list[SessionInfo]:
        """列出所有会话"""
        async with self._lock:
            return sorted(
                list(self._sessions.values()),
                key=lambda s: s.last_used_at,
                reverse=True
            )

    async def update(self, session_id: str, **kwargs) -> SessionInfo:
        """更新会话信息"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)

            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)

            if 'last_used_at' not in kwargs:
                session.last_used_at = datetime.now()

            await self._save_to_disk()
            return session

    async def increment_message_count(self, session_id: str) -> SessionInfo:
        """增加会话消息计数"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)

            session.message_count += 1
            session.last_used_at = datetime.now()
            await self._save_to_disk()
            return session

    async def delete(self, session_id: str) -> None:
        """删除会话"""
        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFound(session_id)

            del self._sessions[session_id]
            await self._save_to_disk()

    async def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """清理过期会话"""
        async with self._lock:
            now = datetime.now()
            to_delete = []

            for session_id, session in self._sessions.items():
                age = (now - session.last_used_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_delete.append(session_id)

            for session_id in to_delete:
                del self._sessions[session_id]

            if to_delete:
                await self._save_to_disk()

            return len(to_delete)

    async def _load_from_disk(self) -> None:
        """从磁盘加载会话"""
        if not self._metadata_file.exists():
            return

        try:
            with open(self._metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            sessions = {}
            for session_id, session_data in data.items():
                try:
                    session_data = session_data.copy()
                    if 'created_at' in session_data:
                        session_data['created_at'] = datetime.fromisoformat(session_data['created_at'])
                    if 'last_used_at' in session_data:
                        session_data['last_used_at'] = datetime.fromisoformat(session_data['last_used_at'])

                    sessions[session_id] = SessionInfo(**session_data)
                except Exception:
                    continue

            self._sessions = sessions

        except json.JSONDecodeError as e:
            raise SessionStorageError("load", f"Invalid JSON: {e}")
        except Exception as e:
            raise SessionStorageError("load", str(e))

    async def _save_to_disk(self) -> None:
        """保存会话到磁盘"""
        try:
            self._metadata_file.parent.mkdir(parents=True, exist_ok=True)

            data = {}
            for session_id, session in self._sessions.items():
                data[session_id] = session.model_dump(mode='json')

            temp_file = self._metadata_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            temp_file.replace(self._metadata_file)

        except Exception as e:
            raise SessionStorageError("save", str(e))

    def _generate_session_id(self) -> str:
        """生成唯一的会话 ID"""
        return secrets.token_urlsafe(16)


# 全局会话存储实例
_global_store: Optional[SessionStore] = None


async def get_session_store() -> SessionStore:
    """获取全局会话存储实例"""
    global _global_store
    if _global_store is None:
        _global_store = SessionStore()
        await _global_store.initialize()
    return _global_store


def reset_session_store():
    """重置全局会话存储（用于测试）"""
    global _global_store
    _global_store = None
