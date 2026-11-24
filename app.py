import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent

@contextmanager
def db():
    con = sqlite3.connect(os.getenv("HELPDESK_DB", "desk.sqlite"))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        with con:
            yield con
    finally:
        con.close()

def init():
    with db() as con:
        con.executescript((ROOT / "schema.sql").read_text())

@asynccontextmanager
async def lifespan(app):
    init()
    yield

app = FastAPI(title="Связь · Служба поддержки", version="1.0", lifespan=lifespan)

class Account(BaseModel):
    login: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,40}$")
    password: str = Field(min_length=10, max_length=128)

def digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384,r=8,p=1).hex()

def create(account, role):
    salt = secrets.token_hex(16)
    with db() as con:
        try:
            con.execute("INSERT INTO users(login,hash,role) VALUES(?,?,?)",
                        (account.login.lower(), salt+"."+digest(account.password,salt), role))
        except sqlite3.IntegrityError:
            raise HTTPException(409,"Логин занят")

@app.post("/api/register",status_code=201)
def register(a: Account):
    create(a,"student")
    return {"message":"Учётная запись создана"}

@app.post("/api/login")
def login(a: Account, response: Response, request: Request):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE login=?", (a.login.lower(),)).fetchone()
        if not row:
            raise HTTPException(401,"Проверьте логин и пароль")
        salt, hashed = row["hash"].split(".")
        if not secrets.compare_digest(digest(a.password,salt),hashed):
            raise HTTPException(401,"Проверьте логин и пароль")
        token = secrets.token_urlsafe(32)
        con.execute("DELETE FROM sessions WHERE expires<=?",(int(time.time()),))
        con.execute("INSERT INTO sessions VALUES(?,?,?)",(token,row["id"],int(time.time())+28800))
    response.set_cookie("desk",token,httponly=True,samesite="strict",secure=request.url.scheme=="https",max_age=28800)
    return {"role":row["role"]}

def user(request: Request):
    with db() as con:
        row = con.execute("SELECT users.* FROM users JOIN sessions ON uid=users.id WHERE token=? AND expires>?",(request.cookies.get("desk",""),int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401,"Войдите в систему")
    return dict(row)

@app.post("/api/logout")
def logout(request: Request,response: Response):
    with db() as con:
        con.execute("DELETE FROM sessions WHERE token=?",(request.cookies.get("desk",""),))
    response.delete_cookie("desk")
    return {"message":"Вы вышли"}

@app.get("/api/me")
def me(u=Depends(user)):
    return {"login":u["login"],"role":u["role"]}

class Message(BaseModel):
    text: str = Field(min_length=3,max_length=500)

@app.post("/api/chat")
def chat(m: Message,u=Depends(user)):
    text=m.text.lower()
    room=re.search(r"(?:каб(?:инет[еау]?)?\.?|аудитори[яию])\s*(\d{1,4}[а-яa-z]?)\b",text)
    prompts=[(("интернет","сеть","wi-fi"),"Нет связи на одном устройстве или во всей аудитории?"),
             (("проектор","экран"),"Что показывает экран и выбран ли нужный вход?"),
             (("принтер","печать"),"Есть ли сообщение на дисплее принтера?")]
    question=next((q for words,q in prompts if any(w in text for w in words)),"На каком оборудовании возникла проблема и что вы видите?")
    return {"room":room.group(1) if room else "", "question":question}

class Ticket(BaseModel):
    issue: str = Field(min_length=3,max_length=500,pattern=r"\S")
    room: str = Field(min_length=1,max_length=30,pattern=r"\S")
    scope: str = Field(min_length=1,max_length=300,pattern=r"\S")

@app.post("/api/tickets",status_code=201)
def add(t: Ticket,u=Depends(user)):
    with db() as con:
        cur=con.execute("INSERT INTO tickets(owner,issue,room,scope) VALUES(?,?,?,?)",(u["id"],t.issue,t.room,t.scope))
        return {"id":cur.lastrowid}

@app.get("/api/tickets")
def tickets(u=Depends(user)):
    with db() as con:
        rows=con.execute("SELECT * FROM tickets WHERE owner=? OR ?='tech' ORDER BY id DESC",(u["id"],u["role"]))
        return [dict(r) for r in rows]

class Decision(BaseModel):
    reply: str = Field(min_length=1,max_length=500,pattern=r"\S")

@app.patch("/api/tickets/{num}")
def advance(num:int,d:Decision,u=Depends(user)):
    if u["role"]!="tech":
        raise HTTPException(403,"Доступно технику")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        row=con.execute("SELECT status FROM tickets WHERE id=?",(num,)).fetchone()
        if not row:
            raise HTTPException(404,"Заявка не найдена")
        status={"Новая":"В работе","В работе":"Решена"}.get(row[0])
        if not status:
            raise HTTPException(409,"Заявка закрыта")
        con.execute("UPDATE tickets SET status=?,reply=? WHERE id=?",(status,d.reply,num))
        return {"status":status}

@app.delete("/api/tickets/{num}")
def cancel(num:int,u=Depends(user)):
    with db() as con:
        cur=con.execute("DELETE FROM tickets WHERE id=? AND owner=? AND status='Новая'",(num,u["id"]))
        if not cur.rowcount:
            raise HTTPException(409,"Можно отменить только свою новую заявку")
    return {"message":"Заявка отменена"}

@app.get("/",include_in_schema=False)
def home():
    return FileResponse(ROOT/"static/index.html")

if __name__=="__main__":
    import getpass
    init()
    create(Account(login=input("Логин техника: "), password=getpass.getpass("Пароль (от 10 символов): ")),"tech")
