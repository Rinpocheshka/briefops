"""Send approved replies through a signed, send-only Google MailApp bridge."""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request

EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")


def is_email(value):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value):
        return False
    local, domain = value.rsplit("@", 1)
    return (len(local) <= 64 and not local.startswith(".") and not local.endswith(".") and ".." not in local
            and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in domain.split(".")))


class MailBridge:
    def __init__(self, url=None, secret=None):
        self.url = url if url is not None else os.getenv("BRIEFOPS_MAIL_BRIDGE_URL", "")
        self.secret = secret if secret is not None else os.getenv("BRIEFOPS_MAIL_BRIDGE_SECRET", "")

    @property
    def configured(self):
        return bool(re.fullmatch(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec", self.url)
                    and len(self.secret) >= 32)

    def send(self, delivery):
        if not self.configured:
            return "failed", "Отправка email ещё не подключена."
        payload = json.dumps({"id": delivery["id"], "to": delivery["contact"],
                              "subject": delivery["subject"], "body": delivery["body"],
                              "issued_at": int(time.time())}, ensure_ascii=False, separators=(",", ":"))
        signature = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        request = urllib.request.Request(self.url, data=json.dumps({"payload": payload, "signature": signature}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.loads(response.read(16000))
            if not isinstance(result, dict):
                return "retry", "Сервис отправки вернул неподтверждённый результат."
            if result.get("ok") is True and result.get("id") == delivery["id"] and result.get("status") == "sent":
                return "sent", "Google принял письмо к отправке."
            if result.get("status") == "uncertain":
                return "uncertain", "Статус отправки не подтверждён. Проверьте доставку, прежде чем отправлять повторно."
            if result.get("status") == "busy":
                return "retry", "Сервис отправки занят. Повторим запрос с тем же идентификатором."
            if result.get("status") in {"quota", "rejected"}:
                return "failed", "Письмо не принято. Проверьте подключение и доступную квоту Google, затем повторите отправку."
            return "uncertain", "Сервис не подтвердил результат. Автоповтор остановлен, чтобы не отправить второе письмо."
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            # A retry uses the same ID; the bridge keeps a persistent send ledger.
            return "retry", "Ответ сервиса отправки не получен. Проверим тот же идентификатор без повторной отправки."
