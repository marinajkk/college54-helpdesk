import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from max_bot import app
from app import db

class MaxDialog(unittest.TestCase):
    def test_ticket_and_status(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,HELPDESK_DB=tmp+"/db",MAX_WEBHOOK_SECRET="demo",MAX_BOT_TOKEN="demo"), TestClient(app) as client, patch("max_bot.httpx.post") as send:
            def event(mid,text,user=8):
                payload={"update_type":"message_created","message":{"recipient":{"chat_type":"dialog"},"sender":{"user_id":user},"body":{"mid":mid,"text":text}}}
                return client.post("/max/webhook",headers={"X-Max-Bot-Api-Secret":"demo"},json=payload)
            self.assertEqual(client.post("/max/webhook",json={}).status_code,403)
            for mid,text in enumerate(("Сломался проектор","203","Нет изображения")):
                self.assertEqual(event(str(mid),text).status_code,200)
            event("2","Нет изображения")
            self.assertEqual(send.call_count,3)
            with db() as con:
                self.assertEqual(con.execute("SELECT room,scope FROM tickets").fetchone()["room"],"203")
                con.execute("UPDATE tickets SET status='Решена',reply='Заменён кабель'")
            event("4","/status")
            self.assertIn("Заменён кабель",send.call_args.kwargs["json"]["text"])
            event("5","/status",9)
            self.assertIn("пока нет",send.call_args.kwargs["json"]["text"])
