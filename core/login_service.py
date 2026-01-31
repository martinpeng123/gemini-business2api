import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from core.account import load_accounts_from_source
from core.base_task_service import BaseTask, BaseTaskService, TaskCancelledError, TaskStatus
from core.config import config
from core.mail_providers import create_temp_mail_client
from core.gemini_automation import GeminiAutomation
from core.gemini_automation_uc import GeminiAutomationUC
from core.microsoft_mail_client import MicrosoftMailClient

logger = logging.getLogger("gemini.login")

# 常量定义
CONFIG_CHECK_INTERVAL_SECONDS = 60  # 配置检查间隔（秒）
REFRESH_COOLDOWN_SECONDS = 3600  # 刷新完成后的冷却时间（1小时内不重复刷新）


@dataclass
class LoginTask(BaseTask):
    """登录任务数据类"""
    account_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典"""
        base_dict = super().to_dict()
        base_dict["account_ids"] = self.account_ids
        return base_dict


class LoginService(BaseTaskService[LoginTask]):
    """登录服务类"""

    def __init__(
        self,
        multi_account_mgr,
        http_client,
        user_agent: str,
        retry_policy,
        session_cache_ttl_seconds: int,
        global_stats_provider: Callable[[], dict],
        set_multi_account_mgr: Optional[Callable[[Any], None]] = None,
    ) -> None:
        super().__init__(
            multi_account_mgr,
            http_client,
            user_agent,
            retry_policy,
            session_cache_ttl_seconds,
            global_stats_provider,
            set_multi_account_mgr,
            log_prefix="REFRESH",
        )
        self._is_polling = False
        # 账户级别的刷新状态追踪
        self._refreshing_accounts: Set[str] = set()  # 正在刷新的账户ID
        self._last_refresh_time: Dict[str, float] = {}  # 账户上次刷新完成时间
        self._refresh_lock = asyncio.Lock()  # 刷新状态锁

    def is_account_refreshing(self, account_id: str) -> bool:
        """检查账户是否正在刷新"""
        return account_id in self._refreshing_accounts

    def get_refreshing_accounts(self) -> List[str]:
        """获取正在刷新的账户列表"""
        return list(self._refreshing_accounts)

    def _can_refresh_account(self, account_id: str) -> bool:
        """检查账户是否可以刷新（未在刷新中且不在冷却期内）"""
        # 正在刷新中
        if account_id in self._refreshing_accounts:
            return False
        # 检查冷却期
        last_time = self._last_refresh_time.get(account_id)
        if last_time and (time.time() - last_time) < REFRESH_COOLDOWN_SECONDS:
            return False
        return True

    async def start_login(self, account_ids: List[str]) -> LoginTask:
        """启动登录任务（无排队，直接执行，过滤已在刷新的账户）。"""
        async with self._lock:
            # 过滤掉正在刷新或在冷却期的账户
            filtered_ids = [
                aid for aid in (account_ids or [])
                if self._can_refresh_account(aid)
            ]

            if not filtered_ids:
                # 所有账户都在刷新中或冷却期，返回一个空任务
                task = LoginTask(id=str(uuid.uuid4()), account_ids=[])
                task.status = TaskStatus.SUCCESS
                task.finished_at = time.time()
                self._tasks[task.id] = task
                self._append_log(task, "info", "📝 所有账户已在刷新中或冷却期内，跳过")
                return task

            # 检查是否有正在运行的任务包含这些账户
            for existing in self._tasks.values():
                if (
                    isinstance(existing, LoginTask)
                    and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                ):
                    # 从 filtered_ids 中移除已在任务中的账户
                    filtered_ids = [
                        aid for aid in filtered_ids
                        if aid not in existing.account_ids
                    ]

            if not filtered_ids:
                # 所有账户都已在现有任务中
                for existing in self._tasks.values():
                    if existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                        return existing
                # 返回空任务
                task = LoginTask(id=str(uuid.uuid4()), account_ids=[])
                task.status = TaskStatus.SUCCESS
                task.finished_at = time.time()
                self._tasks[task.id] = task
                return task

            # 标记这些账户为正在刷新
            for aid in filtered_ids:
                self._refreshing_accounts.add(aid)

            task = LoginTask(id=str(uuid.uuid4()), account_ids=filtered_ids)
            self._tasks[task.id] = task
            self._append_log(task, "info", f"📝 创建刷新任务 (账号数量: {len(task.account_ids)})")

            # 直接启动任务，不排队
            self._current_task_id = task.id
            asyncio.create_task(self._run_task_directly(task))
            return task

    async def _run_task_directly(self, task: LoginTask) -> None:
        """直接执行任务（不通过队列）"""
        try:
            await self._run_one_task(task)
        finally:
            # 任务完成后，更新刷新状态
            async with self._lock:
                now = time.time()
                for aid in task.account_ids:
                    self._refreshing_accounts.discard(aid)
                    # 记录刷新完成时间（无论成功失败）
                    self._last_refresh_time[aid] = now
                if self._current_task_id == task.id:
                    self._current_task_id = None

    def _execute_task(self, task: LoginTask):
        return self._run_login_async(task)

    async def _run_login_async(self, task: LoginTask) -> None:
        """异步执行登录任务（支持取消）。"""
        loop = asyncio.get_running_loop()
        self._append_log(task, "info", f"🚀 刷新任务已启动 (共 {len(task.account_ids)} 个账号)")

        for idx, account_id in enumerate(task.account_ids, 1):
            # 检查是否请求取消
            if task.cancel_requested:
                self._append_log(task, "warning", f"login task cancelled: {task.cancel_reason or 'cancelled'}")
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return

            try:
                self._append_log(task, "info", f"📊 进度: {idx}/{len(task.account_ids)}")
                self._append_log(task, "info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._append_log(task, "info", f"🔄 开始刷新账号: {account_id}")
                self._append_log(task, "info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                result = await loop.run_in_executor(self._executor, self._refresh_one, account_id, task)
            except TaskCancelledError:
                # 线程侧已触发取消，直接结束任务
                task.status = TaskStatus.CANCELLED
                task.finished_at = time.time()
                return
            except Exception as exc:
                result = {"success": False, "email": account_id, "error": str(exc)}
            task.progress += 1
            task.results.append(result)

            if result.get("success"):
                task.success_count += 1
                self._append_log(task, "info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._append_log(task, "info", f"🎉 刷新成功: {account_id}")
                self._append_log(task, "info", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            else:
                task.fail_count += 1
                error = result.get('error', '未知错误')
                self._append_log(task, "error", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                self._append_log(task, "error", f"❌ 刷新失败: {account_id}")
                self._append_log(task, "error", f"❌ 失败原因: {error}")
                self._append_log(task, "error", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if task.cancel_requested:
            task.status = TaskStatus.CANCELLED
        else:
            task.status = TaskStatus.SUCCESS if task.fail_count == 0 else TaskStatus.FAILED
        task.finished_at = time.time()
        self._append_log(task, "info", f"login task finished ({task.success_count}/{len(task.account_ids)})")
        self._current_task_id = None
        self._append_log(task, "info", f"🏁 刷新任务完成 (成功: {task.success_count}, 失败: {task.fail_count}, 总计: {len(task.account_ids)})")

    def _refresh_one(self, account_id: str, task: LoginTask) -> dict:
        """刷新单个账户"""
        accounts = load_accounts_from_source()
        account = next((acc for acc in accounts if acc.get("id") == account_id), None)
        if not account:
            return {"success": False, "email": account_id, "error": "账号不存在"}

        if account.get("disabled"):
            return {"success": False, "email": account_id, "error": "账号已禁用"}

        # 获取邮件提供商
        mail_provider = (account.get("mail_provider") or "").lower()
        if not mail_provider:
            if account.get("mail_client_id") or account.get("mail_refresh_token"):
                mail_provider = "microsoft"
            else:
                mail_provider = "duckmail"

        # 获取邮件配置
        mail_password = account.get("mail_password") or account.get("email_password")
        mail_client_id = account.get("mail_client_id")
        mail_refresh_token = account.get("mail_refresh_token")
        mail_tenant = account.get("mail_tenant") or "consumers"

        def log_cb(level, message):
            self._append_log(task, level, f"[{account_id}] {message}")

        log_cb("info", f"📧 邮件提供商: {mail_provider}")

        # 创建邮件客户端
        if mail_provider == "microsoft":
            if not mail_client_id or not mail_refresh_token:
                return {"success": False, "email": account_id, "error": "Microsoft OAuth 配置缺失"}
            mail_address = account.get("mail_address") or account_id
            client = MicrosoftMailClient(
                client_id=mail_client_id,
                refresh_token=mail_refresh_token,
                tenant=mail_tenant,
                proxy=config.basic.proxy_for_auth,
                log_callback=log_cb,
            )
            client.set_credentials(mail_address)
        elif mail_provider in ("duckmail", "moemail", "freemail", "gptmail"):
            if mail_provider not in ("freemail", "gptmail") and not mail_password:
                error_message = "邮箱密码缺失" if mail_provider == "duckmail" else "mail password (email_id) missing"
                return {"success": False, "email": account_id, "error": error_message}
            if mail_provider == "freemail" and not account.get("mail_jwt_token") and not config.basic.freemail_jwt_token:
                return {"success": False, "email": account_id, "error": "Freemail JWT Token 未配置"}

            # 创建邮件客户端，优先使用账户级别配置
            mail_address = account.get("mail_address") or account_id

            # 构建账户级别的配置参数
            account_config = {}
            if account.get("mail_base_url"):
                account_config["base_url"] = account["mail_base_url"]
            if account.get("mail_api_key"):
                account_config["api_key"] = account["mail_api_key"]
            if account.get("mail_jwt_token"):
                account_config["jwt_token"] = account["mail_jwt_token"]
            if account.get("mail_verify_ssl") is not None:
                account_config["verify_ssl"] = account["mail_verify_ssl"]
            if account.get("mail_domain"):
                account_config["domain"] = account["mail_domain"]

            # 创建客户端（工厂会优先使用传入的参数，其次使用全局配置）
            client = create_temp_mail_client(
                mail_provider,
                log_cb=log_cb,
                **account_config
            )
            client.set_credentials(mail_address, mail_password)
            if mail_provider == "moemail":
                client.email_id = mail_password  # 设置 email_id 用于获取邮件
        else:
            return {"success": False, "email": account_id, "error": f"不支持的邮件提供商: {mail_provider}"}

        # 根据配置选择浏览器引擎
        browser_engine = (config.basic.browser_engine or "dp").lower()
        headless = config.basic.browser_headless

        log_cb("info", f"🌐 启动浏览器 (引擎={browser_engine}, 无头模式={headless})...")

        if browser_engine == "dp":
            # DrissionPage 引擎：支持有头和无头模式
            automation = GeminiAutomation(
                user_agent=self.user_agent,
                proxy=config.basic.proxy_for_auth,
                headless=headless,
                log_callback=log_cb,
            )
        else:
            # undetected-chromedriver 引擎：无头模式反检测能力弱，强制使用有头模式
            if headless:
                log_cb("warning", "⚠️ UC 引擎无头模式反检测能力弱，强制使用有头模式")
                headless = False
            automation = GeminiAutomationUC(
                user_agent=self.user_agent,
                proxy=config.basic.proxy_for_auth,
                headless=headless,
                log_callback=log_cb,
            )
        # 允许外部取消时立刻关闭浏览器
        self._add_cancel_hook(task.id, lambda: getattr(automation, "stop", lambda: None)())
        try:
            log_cb("info", "🔐 执行 Gemini 自动登录...")
            result = automation.login_and_extract(account_id, client)
        except Exception as exc:
            log_cb("error", f"❌ 自动登录异常: {exc}")
            return {"success": False, "email": account_id, "error": str(exc)}
        if not result.get("success"):
            error = result.get("error", "自动化流程失败")
            log_cb("error", f"❌ 自动登录失败: {error}")
            return {"success": False, "email": account_id, "error": error}

        log_cb("info", "✅ Gemini 登录成功，正在保存配置...")

        # 更新账户配置
        config_data = result["config"]
        config_data["mail_provider"] = mail_provider
        if mail_provider in ("freemail", "gptmail"):
            config_data["mail_password"] = ""
        else:
            config_data["mail_password"] = mail_password
        if mail_provider == "microsoft":
            config_data["mail_address"] = account.get("mail_address") or account_id
            config_data["mail_client_id"] = mail_client_id
            config_data["mail_refresh_token"] = mail_refresh_token
            config_data["mail_tenant"] = mail_tenant
        config_data["disabled"] = account.get("disabled", False)

        for acc in accounts:
            if acc.get("id") == account_id:
                acc.update(config_data)
                break

        self._apply_accounts_update(accounts)
        log_cb("info", "✅ 配置已保存到数据库")
        return {"success": True, "email": account_id, "config": config_data}


    def _get_expiring_accounts(self) -> List[str]:
        """获取即将过期且可以刷新的账户列表"""
        accounts = load_accounts_from_source()
        expiring = []
        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)

        for account in accounts:
            account_id = account.get("id")
            if not account_id:
                continue

            # 检查是否可以刷新（未在刷新中且不在冷却期）
            if not self._can_refresh_account(account_id):
                logger.debug(f"[LOGIN] 跳过账户 {account_id}：正在刷新或在冷却期内")
                continue

            if account.get("disabled"):
                continue
            mail_provider = (account.get("mail_provider") or "").lower()
            if not mail_provider:
                if account.get("mail_client_id") or account.get("mail_refresh_token"):
                    mail_provider = "microsoft"
                else:
                    mail_provider = "duckmail"

            mail_password = account.get("mail_password") or account.get("email_password")
            if mail_provider == "microsoft":
                if not account.get("mail_client_id") or not account.get("mail_refresh_token"):
                    continue
            elif mail_provider in ("duckmail", "moemail"):
                if not mail_password:
                    continue
            elif mail_provider == "freemail":
                if not config.basic.freemail_jwt_token:
                    continue
            elif mail_provider == "gptmail":
                # GPTMail 不需要密码，允许直接刷新
                pass
            else:
                continue
            expires_at = account.get("expires_at")
            if not expires_at:
                continue

            try:
                expire_time = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
                expire_time = expire_time.replace(tzinfo=beijing_tz)
                remaining = (expire_time - now).total_seconds() / 3600
            except Exception:
                continue

            if remaining <= config.basic.refresh_window_hours:
                expiring.append(account_id)

        return expiring

    async def check_and_refresh(self) -> Optional[LoginTask]:
        if os.environ.get("ACCOUNTS_CONFIG"):
            logger.info("[LOGIN] ACCOUNTS_CONFIG set, skipping refresh")
            return None
        expiring_accounts = self._get_expiring_accounts()
        if not expiring_accounts:
            logger.debug("[LOGIN] no accounts need refresh")
            return None

        try:
            return await self.start_login(expiring_accounts)
        except Exception as exc:
            logger.warning("[LOGIN] refresh enqueue failed: %s", exc)
            return None

    async def start_polling(self) -> None:
        if self._is_polling:
            logger.warning("[LOGIN] polling already running")
            return

        self._is_polling = True
        logger.info("[LOGIN] refresh polling started")
        try:
            while self._is_polling:
                # 检查配置是否启用定时刷新
                if not config.retry.scheduled_refresh_enabled:
                    logger.debug("[LOGIN] scheduled refresh disabled, skipping check")
                    await asyncio.sleep(CONFIG_CHECK_INTERVAL_SECONDS)
                    continue

                # 执行刷新检查
                await self.check_and_refresh()

                # 使用配置的间隔时间
                interval_seconds = config.retry.scheduled_refresh_interval_minutes * 60
                logger.debug(f"[LOGIN] next check in {config.retry.scheduled_refresh_interval_minutes} minutes")
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("[LOGIN] polling stopped")
        except Exception as exc:
            logger.error("[LOGIN] polling error: %s", exc)
        finally:
            self._is_polling = False

    def stop_polling(self) -> None:
        self._is_polling = False
        logger.info("[LOGIN] stopping polling")
