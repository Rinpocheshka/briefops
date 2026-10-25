import concurrent.futures
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from access import WorkspaceAccess
from app import Conflict, Store, handler_for


def form(**changes):
    value = {"form_id":"wov-v1", "site_url":"https://rinpocheshka.github.io/wov/",
             "submission_id":"test_submission_123456", "name":"Тест", "contact":"client@example.com",
             "idea":"Нужен сайт для бизнеса. Бюджет пока не определён."}
    value.update(changes)
    return {"form_data":value}


class LiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "artifacts" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.mailer = Mock(configured=True)
        self.mailer.send.return_value = ("sent", "Google принял письмо")
        self.demo = Store(Path(self.temp.name) / "demo.sqlite3")
        self.live = Store(Path(self.temp.name) / "live.sqlite3", demo=False, workspace=True, mailer=self.mailer)
        self.access = Mock(configured=True, base_url="https://auth.example/neondb/auth")
        self.access.authorized.side_effect = lambda value: value == "Bearer owner-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.demo, self.live, self.access))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.live.database.close(); self.demo.database.close(); self.temp.cleanup()

    def request(self, path, data=None, owner=False, csrf=True):
        headers={"Content-Type":"application/json"}
        if owner:
            headers["Authorization"]="Bearer owner-token"
        if csrf:
            headers["X-Briefops-CSRF"]=self.live.csrf
        request=urllib.request.Request(self.url+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def approved(self, **changes):
        lead_id=self.live.intake_wov(form(**changes))["id"]
        self.live.process_one(lead_id)
        self.live.review(lead_id, {}, approve=True)
        return lead_id

    def test_only_dedicated_website_form_is_accepted(self):
        for invalid in ({"from":"someone@example.com", "subject":"New mail", "body":"private mail"},
                        form(form_id="other-form"), form(site_url="https://other.example/"), {"form_data":[]}):
            self.assertEqual(self.request("/api/integrations/wov", invalid)[0],400)
        self.assertFalse(self.live.state()["leads"])
        self.assertEqual(self.request("/api/integrations/wov", form())[0],202)
        self.assertEqual(self.request("/api/integrations/wov", form())[1],{"accepted":True,"replayed":True})
        self.assertFalse(self.demo.state()["leads"])

    def test_live_data_never_enters_public_state_or_export(self):
        self.approved()
        self.assertEqual(self.request("/api/state")[1]["leads"],[])
        self.assertEqual(self.request("/api/workspace/state")[0],401)
        self.assertEqual(self.request("/api/workspace/export")[0],401)
        self.assertEqual(len(self.request("/api/workspace/state",owner=True)[1]["leads"]),1)
        self.assertEqual(self.request("/api/workspace/sweep",{},owner=True,csrf=False)[0],403)

    def test_explicit_contact_overrides_any_address_in_message(self):
        lead_id=self.approved(idea="Нужен сайт. Пример текста содержит other@example.com, но это не контакт клиента.")
        lead=self.live.get_lead(lead_id)
        self.assertEqual(lead["analysis"]["contact"],"client@example.com")
        self.assertEqual(lead["analysis"]["owner"],"Илья Крючков")
        self.assertFalse(lead["analysis"]["below_floor"])
        self.assertEqual(lead["context"]["form_id"],"wov-v1")

    def test_approval_does_not_send_and_explicit_send_is_once(self):
        lead_id=self.approved()
        self.assertFalse(self.live.deliver_one())
        self.mailer.send.assert_not_called()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            queued=list(pool.map(lambda _:self.live.queue_email(lead_id), range(10)))
        self.assertEqual(len({q["id"] for q in queued}),1)
        self.assertEqual(sum(not q["replayed"] for q in queued),1)
        self.assertTrue(self.live.deliver_one())
        self.assertFalse(self.live.deliver_one())
        self.mailer.send.assert_called_once()
        self.assertEqual(self.live.get_lead(lead_id)["email_delivery"]["status"],"sent")
        self.assertTrue(self.live.queue_email(lead_id)["replayed"])

    def test_send_route_needs_owner_csrf_and_approved_email(self):
        lead_id=self.approved()
        path="/api/workspace/leads/"+lead_id+"/send-email"
        self.assertEqual(self.request(path,{})[0],401)
        self.assertEqual(self.request(path,{},owner=True,csrf=False)[0],403)
        self.assertEqual(self.request(path,{},owner=True)[0],202)
        self.assertEqual(self.request("/api/leads/"+lead_id+"/send-email",{})[0],403)
        tg=self.approved(submission_id="telegram_submission_123", contact="@test_contact")
        with self.assertRaises(ValueError):
            self.live.queue_email(tg)

    def test_retry_preserves_delivery_id_and_uncertainty_stops_retries(self):
        lead_id=self.approved()
        self.live.queue_email(lead_id)
        self.mailer.send.return_value=("retry","timeout")
        self.live.deliver_one()
        first_id=self.mailer.send.call_args.args[0]["id"]
        with self.live.db() as db:
            db.execute("UPDATE email_deliveries SET run_after=0")
        self.mailer.send.return_value=("uncertain","needs manual check")
        self.live.deliver_one()
        self.assertEqual(first_id,self.mailer.send.call_args.args[0]["id"])
        self.assertFalse(self.live.deliver_one())
        self.assertEqual(self.live.get_lead(lead_id)["email_delivery"]["status"],"uncertain")

    def test_webhook_disabled_until_private_access_is_configured(self):
        self.access.configured=False
        self.assertEqual(self.request("/api/integrations/wov",form())[0],503)
        self.assertFalse(self.live.state()["leads"])


class AccessTests(unittest.TestCase):
    def test_signed_tokens_require_verified_owner_expiry_issuer_and_audience(self):
        private=Ed25519PrivateKey.generate()
        with patch.dict(os.environ,{"NEON_AUTH_BASE_URL":"https://auth.example/neondb/auth","BRIEFOPS_OWNER_EMAIL":"owner@example.com"}):
            access=WorkspaceAccess()
        access.client=Mock()
        access.client.get_signing_key_from_jwt.return_value=Mock(key=private.public_key())
        good={"email":"owner@example.com","emailVerified":True,"sub":"owner-id", "iat":int(time.time()),
              "exp":int(time.time())+300,"iss":"https://auth.example","aud":"https://auth.example"}
        def permitted(claims):
            return access.authorized("Bearer "+jwt.encode(claims,private,algorithm="EdDSA"))
        self.assertTrue(permitted(good))
        for change in ({"email":"stranger@example.com"},{"emailVerified":False},{"emailVerified":None},
                       {"banned":True},{"exp":1},{"iss":"https://other.example"},{"aud":"https://other.example"}):
            self.assertFalse(permitted({**good,**change}))
        self.assertFalse(access.authorized("Bearer invalid"))
