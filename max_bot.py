"""HTTPS endpoint for MAX and the existing technician dashboard."""
import os
import secrets
import sys
import httpx
from fastapi import HTTPException, Request
from app import app, db, chat, Message

API = "https://platform-api2.max.ru"
HELP = ("Привет! Это учебная техподдержка Колледжа связи № 54. "
        "Опиши проблему, например: «В кабинете 305 нет интернета». "
        "Команда /status покажет последние заявки, /cancel сбросит черновик.")

def respond(con, sender, text):
    login = f"max:{sender}"  # Colon is excluded from web registration and login.
    con.execute("INSERT OR IGNORE INTO users(login,hash,role) VALUES(?, '', 'student')",(login,))
    uid = con.execute("SELECT id FROM users WHERE login=?", (login,)).fetchone()[0]
    draft = con.execute("SELECT * FROM max_drafts WHERE uid=?", (uid,)).fetchone()
    if text in ("/start", "/help"):
        return HELP
    if text == "/cancel":
        con.execute("DELETE FROM max_drafts WHERE uid=?", (uid,))
        return "Черновик сброшен. Можешь описать новую проблему."
    if text == "/status":
        rows = con.execute("SELECT id,status,reply FROM tickets WHERE owner=? ORDER BY id DESC LIMIT 5",(uid,))
        return "\n".join(f"№{r[0]} · {r[1]} {r[2]}" for r in rows) or "Заявок пока нет."
    if not draft:
        if not 3 <= len(text) <= 500:
            return "Опиши проблему текстом от 3 до 500 символов."
        hint = chat(Message(text=text))
        con.execute("INSERT INTO max_drafts VALUES(?,?,?)",(uid,text,hint["room"]))
        return hint["question"] if hint["room"] else "В каком кабинете возникла проблема?"
    if not draft["room"]:
        if not 1 <= len(text) <= 30:
            return "Введи номер или название кабинета (до 30 символов)."
        con.execute("UPDATE max_drafts SET room=? WHERE uid=?", (text,uid))
        return chat(Message(text=draft["issue"]))["question"]
    if not 1 <= len(text) <= 300:
        return "Добавь короткое уточнение (до 300 символов)."
    number=con.execute("INSERT INTO tickets(owner,issue,room,scope) VALUES(?,?,?,?)",
                       (uid,draft["issue"],draft["room"],text)).lastrowid
    con.execute("DELETE FROM max_drafts WHERE uid=?", (uid,))
    return f"Заявка №{number} создана. Ответ техника появится по команде /status."

@app.post("/max/webhook", include_in_schema=False)
def webhook(event: dict, request: Request):
    secret=os.environ.get("MAX_WEBHOOK_SECRET","")
    token=os.environ.get("MAX_BOT_TOKEN","")
    if not secret or not token:
        raise HTTPException(503,"Канал MAX не настроен")
    if not secrets.compare_digest(secret,request.headers.get("X-Max-Bot-Api-Secret","")):
        raise HTTPException(403)
    kind=event.get("update_type")
    if kind == "bot_started":
        sender=event["user"]["user_id"]
        key=f"start:{sender}:{event['timestamp']}"
        text="/start"
    elif kind == "message_created":
        msg=event["message"]
        if msg["recipient"].get("chat_type")!="dialog" or msg["sender"].get("is_bot"):
            return {"ok":True}
        sender=msg["sender"]["user_id"]
        key=msg["body"]["mid"]
        text=(msg["body"].get("text") or "").strip()
    else:
        return {"ok":True}
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("CREATE TABLE IF NOT EXISTS max_drafts(uid INTEGER PRIMARY KEY REFERENCES users(id), issue TEXT NOT NULL, room TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS max_events(mid TEXT PRIMARY KEY, answer TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0)")
        prior=con.execute("SELECT answer,sent FROM max_events WHERE mid=?",(key,)).fetchone()
        if prior and prior["sent"]:
            return {"ok":True}
        if prior:
            answer=prior["answer"]
        else:
            answer=respond(con,sender,text)
            con.execute("INSERT INTO max_events(mid,answer) VALUES(?,?)",(key,answer))
    result=httpx.post(API+"/messages",params={"user_id":sender},json={"text":answer},
                      headers={"Authorization":token},timeout=8)
    result.raise_for_status()
    with db() as con:
        con.execute("UPDATE max_events SET sent=1 WHERE mid=?",(key,))
    return {"ok":True}

if __name__=="__main__":
    url=sys.argv[1]
    if not url.startswith("https://"):
        sys.exit("Укажите публичный HTTPS URL обработчика.")
    result=httpx.post(API+"/subscriptions",headers={"Authorization":os.environ["MAX_BOT_TOKEN"]},
                      json={"url":url,"secret":os.environ["MAX_WEBHOOK_SECRET"],
                            "update_types":["message_created","bot_started"]})
    result.raise_for_status()
    print("Подписка MAX зарегистрирована")
