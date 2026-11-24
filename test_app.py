import os, tempfile, unittest
from fastapi.testclient import TestClient
from app import app, Account, create

class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.environ["HELPDESK_DB"]=self.tmp.name+"/test.sqlite"
        self.client=TestClient(app).__enter__()
        self.tech=TestClient(app)
        self.a={"login":"student","password":"example-pass-1"}
        self.client.post("/api/register",json=self.a)
        self.client.post("/api/login",json=self.a)
        create(Account(login="operator",password="example-pass-2"),"tech")
        self.tech.post("/api/login",json={"login":"operator","password":"example-pass-2"})

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.tech.close()
        del os.environ["HELPDESK_DB"]
        self.tmp.cleanup()

    def ticket(self):
        return self.client.post("/api/tickets",json={"issue":"Нет сети","room":"305","scope":"Весь кабинет"}).json()["id"]

    def test_dialog(self):
        r=self.client.post("/api/chat",json={"text":"В кабинете 305 нет интернета"}).json()
        self.assertEqual(r["room"],"305")
        self.assertIn("аудитории",r["question"])

    def test_lifecycle(self):
        url="/api/tickets/"+str(self.ticket())
        for expected in ["В работе","Решена"]:
            self.assertEqual(self.tech.patch(url,json={"reply":"Проверено"}).json()["status"],expected)
        self.assertEqual(self.client.get("/api/tickets").json()[0]["reply"],"Проверено")
        self.assertEqual(self.tech.patch(url,json={"reply":"Повтор"}).status_code,409)

    def test_access(self):
        num=self.ticket()
        self.assertEqual(self.client.patch(f"/api/tickets/{num}",json={"reply":"Тест"}).status_code,403)
        guest=TestClient(app)
        self.assertEqual(guest.get("/api/tickets").status_code,401)
        b=dict(self.a,login="other")
        guest.post("/api/register",json=b)
        guest.post("/api/login",json=b)
        self.assertEqual(guest.get("/api/tickets").json(),[])
        self.assertEqual(guest.delete(f"/api/tickets/{num}").status_code,409)
        guest.close()

    def test_cancel(self):
        self.assertEqual(self.client.delete(f"/api/tickets/{self.ticket()}").status_code,200)
        self.assertEqual(self.client.get("/api/tickets").json(),[])

    def test_validation(self):
        self.assertEqual(self.client.post("/api/register",json=self.a).status_code,409)
        self.assertEqual(self.client.post("/api/tickets",json={}).status_code,422)
