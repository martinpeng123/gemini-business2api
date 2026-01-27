"""
Moemail临时邮箱客户端

API文档参考:
- 获取系统配置: GET /api/config
- 生成临时邮箱: POST /api/emails/generate
- 获取邮件列表: GET /api/emails/{emailId}
- 获取单封邮件: GET /api/emails/{emailId}/{messageId}
"""

import random
import string
import time
from typing import Optional

import requests

from core.mail_utils import extract_verification_code


class MoemailClient:
    """Moemail临时邮箱客户端"""

    def __init__(
        self,
        base_url: str = "https://moemail.app",
        proxy: str = "",
        api_key: str = "",
        domain: str = "",
        log_callback=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.api_key = api_key.strip()
        self.domain = domain.strip() if domain else ""
        self.log_callback = log_callback

        self.email: Optional[str] = None
        self.email_id: Optional[str] = None
        self.password: Optional[str] = None  # 兼容 DuckMailClient 接口

        # 缓存可用域名列表
        self._available_domains: list = []

    def set_credentials(self, email: str, password: str = "") -> None:
        """设置凭据（兼容 DuckMailClient 接口）"""
        self.email = email
        self.password = password
        # 尝试从邮箱地址提取 email_id（格式：name@domain -> email_id）
        # 注意：Moemail 的 email_id 是创建时返回的 id，不是邮箱地址
        # 这里只是为了兼容接口，实际使用时需要正确设置 email_id

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """发送请求并打印详细日志"""
        headers = kwargs.pop("headers", None) or {}
        if self.api_key and "X-API-Key" not in headers:
            headers["X-API-Key"] = self.api_key
        headers.setdefault("Content-Type", "application/json")
        kwargs["headers"] = headers

        self._log("info", f"[HTTP] {method} {url}")
        if "json" in kwargs:
            self._log("info", f"[HTTP] Request body: {kwargs['json']}")

        try:
            res = requests.request(
                method,
                url,
                proxies=self.proxies,
                timeout=kwargs.pop("timeout", 30),
                **kwargs,
            )
            self._log("info", f"[HTTP] Response: {res.status_code}")
            if res.content and res.status_code >= 400:
                try:
                    self._log("error", f"[HTTP] Response body: {res.text[:500]}")
                except Exception:
                    pass
            return res
        except Exception as e:
            self._log("error", f"[HTTP] Request failed: {e}")
            raise

    def _get_available_domains(self) -> list:
        """获取可用的邮箱域名列表"""
        if self._available_domains:
            return self._available_domains

        try:
            res = self._request("GET", f"{self.base_url}/api/config")
            if res.status_code == 200:
                data = res.json()
                email_domains_str = data.get("emailDomains", "")
                if email_domains_str:
                    self._available_domains = [d.strip() for d in email_domains_str.split(",") if d.strip()]
                    self._log("info", f"Moemail available domains: {self._available_domains}")
                    return self._available_domains
        except Exception as e:
            self._log("error", f"Failed to get available domains: {e}")

        # 默认域名
        self._available_domains = ["moemail.app"]
        return self._available_domains

    def register_account(self, domain: Optional[str] = None) -> bool:
        """注册新邮箱账号

        API: POST /api/emails/generate
        """
        # 确定使用的域名
        selected_domain = domain
        if not selected_domain:
            selected_domain = self.domain

        if not selected_domain:
            # 从可用域名中随机选择
            available = self._get_available_domains()
            if available:
                selected_domain = random.choice(available)
            else:
                selected_domain = "moemail.app"

        self._log("info", f"Moemail using domain: {selected_domain}")

        # 生成随机邮箱名称
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        timestamp = str(int(time.time()))[-4:]
        name = f"t{timestamp}{rand}"

        self._log("info", f"Moemail registering email: {name}@{selected_domain}")

        try:
            res = self._request(
                "POST",
                f"{self.base_url}/api/emails/generate",
                json={
                    "name": name,
                    "expiryTime": 3600000,  # 1小时
                    "domain": selected_domain,
                },
            )

            if res.status_code in (200, 201):
                data = res.json() if res.content else {}
                self.email = data.get("email", "")
                self.email_id = data.get("id", "")
                self.password = self.email_id  # 用 email_id 作为 password 存储

                if self.email and self.email_id:
                    self._log("info", f"Moemail register success: {self.email}")
                    self._log("info", f"Moemail email_id: {self.email_id}")
                    return True

            self._log("error", f"Moemail register failed: {res.status_code}")
            if res.content:
                self._log("error", f"Response: {res.text[:500]}")
            return False

        except Exception as e:
            self._log("error", f"Moemail register failed: {e}")
            return False

    def login(self) -> bool:
        """登录（Moemail 无需登录，返回 True）"""
        # Moemail 使用 API Key 认证，无需单独登录
        return True

    def fetch_verification_code(self, since_time=None) -> Optional[str]:
        """获取验证码

        API: GET /api/emails/{emailId}
        API: GET /api/emails/{emailId}/{messageId}
        """
        if not self.email_id:
            self._log("error", "No email_id, cannot fetch messages")
            return None

        try:
            self._log("info", "Fetching verification code from Moemail")

            # 获取邮件列表
            res = self._request(
                "GET",
                f"{self.base_url}/api/emails/{self.email_id}",
            )

            if res.status_code != 200:
                self._log("error", f"Failed to get messages: {res.status_code}")
                return None

            data = res.json() if res.content else {}
            
            # 调试：打印完整响应结构
            self._log("info", f"[DEBUG] Email list response keys: {list(data.keys())}")
            self._log("info", f"[DEBUG] Full response: {str(data)[:500]}")
            
            messages = data.get("messages", [])

            if not messages:
                self._log("info", "No messages found")
                return None

            self._log("info", f"Found {len(messages)} messages")

            # 遍历邮件
            for msg in messages:
                msg_id = msg.get("id")
                if not msg_id:
                    continue

                # 时间过滤
                if since_time:
                    created_at = msg.get("createdAt") or msg.get("receivedAt")
                    if created_at:
                        try:
                            from datetime import datetime
                            import re
                            # 截断纳秒到微秒
                            created_at = re.sub(r'(\.\d{6})\d+', r'\1', created_at)
                            msg_time = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                            if msg_time < since_time:
                                continue
                        except Exception:
                            pass

                # 优先从邮件列表的 content 字段提取验证码（更高效）
                list_content = msg.get("content") or ""
                if list_content:
                    self._log("info", f"[DEBUG] Trying to extract from list content, length: {len(list_content)}")
                    code = extract_verification_code(list_content)
                    if code:
                        self._log("info", f"Verification code found from list: {code}")
                        return code

                # 如果列表没有 content，则获取邮件详情
                detail_res = self._request(
                    "GET",
                    f"{self.base_url}/api/emails/{self.email_id}/{msg_id}",
                )

                if detail_res.status_code != 200:
                    continue

                detail = detail_res.json() if detail_res.content else {}

                # 处理 {'message': {...}} 格式
                if "message" in detail and isinstance(detail["message"], dict):
                    detail = detail["message"]

                # 获取邮件内容
                text_content = detail.get("text") or detail.get("textContent") or detail.get("content") or ""
                html_content = detail.get("html") or detail.get("htmlContent") or ""

                if isinstance(html_content, list):
                    html_content = "".join(str(item) for item in html_content)
                if isinstance(text_content, list):
                    text_content = "".join(str(item) for item in text_content)

                content = text_content + html_content
                if content:
                    self._log("info", f"[DEBUG] Detail content length: {len(content)}")
                    code = extract_verification_code(content)
                    if code:
                        self._log("info", f"Verification code found from detail: {code}")
                        return code

            return None

        except Exception as e:
            self._log("error", f"Fetch code failed: {e}")
            return None

    def poll_for_code(
        self,
        timeout: int = 120,
        interval: int = 4,
        since_time=None,
    ) -> Optional[str]:
        """轮询获取验证码"""
        max_retries = timeout // interval

        for i in range(1, max_retries + 1):
            code = self.fetch_verification_code(since_time=since_time)
            if code:
                return code

            if i < max_retries:
                self._log("info", f"Waiting for verification code... ({i}/{max_retries})")
                time.sleep(interval)

        self._log("error", "Verification code timeout")
        return None

    def _log(self, level: str, message: str) -> None:
        if self.log_callback:
            try:
                self.log_callback(level, message)
            except Exception:
                pass

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        return extract_verification_code(text)
