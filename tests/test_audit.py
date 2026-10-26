"""Regression cases found during the queue, UX and security audit."""
import http.client
import csv
import io
import json
import os
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from access import WorkspaceAccess
from app import Conflict, RateLimited, analyze
from email_delivery import is_email
from security import RequestLimiter, remote_address
import test_integration as integration
from test_integration import form


class AuditTests(unittest.TestCase):
    setUp = integration.LiveIntegrationTests.setUp
    tearDown = integration.LiveIntegrationTests.tearDown
    request = integration.LiveIntegrationTests.request
    approved = integration.LiveIntegrationTests.approved

    def test_counters_match_queues_through_failure_and_real_send(self):
        lead_id = self.live.intake_wov(form())["id"]
        self.assertEqual(self.live.state()["stats"]["review"], 1)
        for status in ("queued", "processing", "retry", "failed", "ready", "needs_info"):
            with self.live.db() as db:
                db.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
            self.assertEqual(self.live.state()["stats"]["review"], 1, status)
        with self.live.db() as db:
            db.execute("UPDATE leads SET status='queued' WHERE id=?", (lead_id,))
        self.live.process_one(lead_id)
        self.live.review(lead_id, {}, approve=True)
        self.assertEqual(self.live.state()["stats"]["approved"], 1)
        self.assertEqual(self.live.state()["stats"]["review"], 0)
        delivery = self.live.queue_email(lead_id)
        self.mailer.send.return_value = ("failed", "Quota")
        self.live.deliver_one()
        self.assertEqual(self.live.state()["stats"]["errors"], 1)
        self.assertEqual(self.live.state()["stats"]["approved"], 1)
        self.assertEqual(self.live.queue_email(lead_id)["id"], delivery["id"])
        self.mailer.send.return_value = ("sent", "Accepted")
        self.live.deliver_one()
        stats = self.live.state()["stats"]
        self.assertEqual((stats["review"], stats["approved"], stats["sent"], stats["pending"]), (0, 0, 1, 0))
        duplicate = self.live.intake_wov(form(submission_id="duplicate-submission-123"))["id"]
        self.live.process_one(duplicate)
        stats = self.live.state()["stats"]
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(stats["total"], stats["review"] + stats["approved"] + stats["sent"] + stats["duplicates"])

    def test_live_deadline_ends_after_send_not_approval(self):
        lead_id = self.approved()
        with self.live.db() as db:
            db.execute("UPDATE leads SET sla_at=? WHERE id=?", (time.time()-1, lead_id))
        self.assertEqual(self.live.sweep()["created"], 1)
        self.assertEqual(self.live.state()["stats"]["sla"], 1)
        self.live.queue_email(lead_id)
        self.live.deliver_one()
        self.assertEqual(self.live.state()["stats"]["sla"], 0)
        self.assertTrue(all(t["done"] for t in self.live.get_lead(lead_id)["tasks"]))

    def test_reopen_before_send_and_prevent_changes_after_queue(self):
        lead_id = self.approved()
        self.live.reopen(lead_id)
        long_email = "a"*64 + "@" + "b"*63 + "." + "c"*63 + ".com"
        self.live.review(lead_id, {"contact": long_email, "draft": "Corrected approved response"}, approve=True)
        self.assertEqual(self.live.get_lead(lead_id)["analysis"]["contact"], long_email)
        self.live.queue_email(lead_id)
        with self.assertRaises(Conflict):
            self.live.reopen(lead_id)
        with self.assertRaises(Conflict):
            self.live.review(lead_id, {"draft": "Unreviewed replacement"}, approve=True)
        self.live.deliver_one()
        self.assertEqual(self.mailer.send.call_args.args[0]["body"], "Corrected approved response")

    def test_concurrent_editor_does_not_overwrite_newer_fields(self):
        lead_id = self.approved()
        self.live.reopen(lead_id)
        version = self.live.get_lead(lead_id)["updated_at"]
        self.live.review(lead_id, {"budget": 120000, "version": version})
        with self.assertRaises(Conflict):
            self.live.review(lead_id, {"budget": 90000, "version": version})
        self.assertEqual(self.live.get_lead(lead_id)["analysis"]["budget"], 120000)

    def test_idempotent_replay_does_not_spend_business_quota(self):
        limits = (("audit-limit", 1),)
        first = self.live.intake_wov(form(), quota_keys=limits)
        self.assertTrue(self.live.intake_wov(form(), quota_keys=limits)["replayed"])
        with self.assertRaises(RateLimited):
            self.live.intake_wov(form(submission_id="different-submission-123"), quota_keys=limits)
        self.assertEqual(self.live.state()["stats"]["total"], 1)
        with self.assertRaises(RateLimited):
            self.live.intake_wov(form(submission_id="third-submission-1234"), quota_keys=(("must-rollback", 5), ("blocked", 0)))
        with self.live.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM quotas WHERE name LIKE 'must-rollback%' ").fetchone())
        self.assertEqual(first["id"], self.live.get_lead(first["id"])["id"])

    def test_etag_never_skips_authentication_or_hides_changed_state(self):
        def call(headers):
            req = urllib.request.Request(self.url+"/api/workspace/state", headers=headers)
            try:
                with urllib.request.urlopen(req) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as error:
                with error:return error.code,error.headers,error.read()
        auth = {"Authorization":"Bearer owner-token"}
        status, headers, _ = call(auth)
        self.assertEqual(status, 200)
        tag = headers["ETag"]
        self.assertEqual(call({**auth,"If-None-Match":tag})[0], 304)
        self.assertEqual(call({"If-None-Match":tag})[0], 401)
        self.live.intake_wov(form())
        changed = call({**auth,"If-None-Match":tag})
        self.assertEqual(changed[0], 200)
        self.assertNotEqual(changed[1]["ETag"], tag)
        self.assertEqual(json.loads(changed[2])["stats"]["review"], 1)

    def test_form_requires_origin_real_contact_and_preserves_text(self):
        req = urllib.request.Request(self.url+"/api/integrations/wov",data=json.dumps(form()).encode(),headers={"Content-Type":"application/json"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(self.request("/api/integrations/wov",form(contact=""))[0],400)
        self.assertEqual(self.request("/api/integrations/wov",form(_honey="filled"))[0],400)
        idea="Нужен пример <script> как текст, цена $150, настройки {name: `value`}."
        lead_id=self.live.intake_wov(form(idea=idea))["id"]
        self.assertEqual(self.live.get_lead(lead_id)["text"],idea)

    def test_native_form_blank_id_and_long_cyrillic_description(self):
        fields = form(idea="Я"*2000,submission_id="")["form_data"]
        req=urllib.request.Request(self.url+"/api/integrations/wov",data=urllib.parse.urlencode(fields).encode(),headers={"Origin":"https://rinpocheshka.github.io","Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status,200)
            self.assertIn("text/html",response.headers["Content-Type"])
        self.assertEqual(self.live.state()["stats"]["total"],1)
        self.assertEqual(self.live.state()["leads"][0]["text"],"Я"*2000)

    def test_invalid_http_bodies_are_rejected_without_stack_traces(self):
        headers={"Authorization":"Bearer owner-token","X-Briefops-CSRF":self.live.csrf,"Content-Type":"application/json"}
        for body in (b"\xff",b"{",b"[]"):
            req=urllib.request.Request(self.url+"/api/workspace/intake",data=body,headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code,400)
            self.assertNotIn(b"Traceback",error.exception.read())
            error.exception.close()
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        conn.putrequest("POST","/api/workspace/intake")
        for key,value in headers.items():conn.putheader(key,value)
        conn.putheader("Content-Length","2");conn.putheader("Content-Length","2");conn.endheaders(b"{}")
        response=conn.getresponse();self.assertEqual(response.status,400);response.read();conn.close()

    def test_get_one_lead_does_not_read_other_customers(self):
        first=self.live.intake_wov(form())["id"]
        self.live.intake_wov(form(submission_id="second-customer-123456",name="Другой клиент",contact="other@example.com"))
        state=self.live.state(first)
        self.assertEqual(len(state["leads"]),1)
        self.assertNotIn("other@example.com",json.dumps(state))

    def test_security_headers_and_private_files(self):
        with urllib.request.urlopen(self.url+"/styles.css") as response:
            self.assertEqual(len(response.headers.get_all("Cache-Control")),1)
            self.assertIn("max-age",response.headers["Cache-Control"])
            self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
            self.assertNotIn("Python",response.headers["Server"])
        for path in ("/data/live-production-env.json","/.env.local","/../app.py","/access.py"):
            self.assertEqual(self.request(path)[0],404)

    def test_csv_separates_approval_from_confirmed_sending(self):
        lead_id = self.approved(name="=FORMULA()")
        self.live.queue_email(lead_id)
        self.live.deliver_one()
        request = urllib.request.Request(self.url+"/api/workspace/export",headers={"Authorization":"Bearer owner-token"})
        with urllib.request.urlopen(request) as response:
            rows = list(csv.reader(io.StringIO(response.read().decode("utf-8-sig"))))
        self.assertEqual(rows[1][-3:], ["approved", "sent", "sent"])
        self.assertEqual(rows[1][1], "'=FORMULA()")

    def test_explicit_notification_retry_keeps_same_delivery_id(self):
        with patch.dict(os.environ,{"BRIEFOPS_OWNER_EMAIL":"owner@example.com"}):
            lead_id=self.live.intake_wov(form())["id"]
        self.mailer.send.return_value=("failed","Quota")
        self.live.deliver_one()
        first_id=self.mailer.send.call_args.args[0]["id"]
        self.live.retry_notification(lead_id)
        self.mailer.send.return_value=("sent","Accepted")
        self.live.deliver_one()
        self.assertEqual(self.mailer.send.call_args.args[0]["id"],first_id)


class SecurityUnitTests(unittest.TestCase):
    def test_email_validation_rejects_header_and_domain_tricks(self):
        for value in ("a@foo..com","a@-foo.com",".a@foo.com","a..b@foo.com","a@foo.com\r\nBcc: victim@example.com","a@foo.com,b@bar.com"):
            self.assertFalse(is_email(value),value)
        self.assertTrue(is_email("o'connor+tag@sub.example.com"))

    def test_unknown_jwt_keys_do_not_force_repeated_remote_fetches(self):
        private=Ed25519PrivateKey.generate()
        with patch.dict(os.environ,{"NEON_AUTH_BASE_URL":"https://auth.example/auth","BRIEFOPS_OWNER_EMAIL":"owner@example.com"}):
            access=WorkspaceAccess()
        access.client=Mock();access.client.get_signing_keys.return_value=[Mock(key_id="real",key=private.public_key())]
        for number in range(15):
            token=jwt.encode({"sub":"fake"},private,algorithm="EdDSA",headers={"kid":"unknown-"+str(number)})
            self.assertFalse(access.authorized("Bearer "+token))
        self.assertEqual(access.client.get_signing_keys.call_count,1)

    def test_limiter_is_bounded_and_local_proxy_headers_are_not_trusted(self):
        limiter=RequestLimiter(max_keys=8)
        for number in range(100):limiter.allow(str(number),1)
        self.assertEqual(len(limiter.entries),8)
        self.assertTrue(limiter.allow("same",1));self.assertFalse(limiter.allow("same",1))
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(remote_address({"X-Forwarded-For":"8.8.8.8"},"127.0.0.1"),"127.0.0.1")

    def test_contacts_are_masked_for_ai_but_preserved_for_reply(self):
        with patch.dict(os.environ,{"NVIDIA_API_KEY":"test-key","BRIEFOPS_LLM_PROVIDER":"nvidia"}),patch("app.complete_json",return_value=({"service":"website","summary":"Нужен сайт","urgent":False},{"provider":"nvidia","model":"test","latency_ms":1})) as complete:
            result,_=analyze("Нужен сайт. client@example.com, +7 999 123-45-67, @test_contact",use_llm=True)
        model_text=complete.call_args.args[1]
        self.assertNotIn("client@example.com",model_text)
        self.assertNotIn("999",model_text)
        self.assertNotIn("@test_contact",model_text)
        self.assertEqual(result["contact"],"client@example.com")
