# -*- coding: utf-8 -*-
"""真机冒烟：用真库真 key 起一次服务，验登录、后台、管理员测试接口、无 key 用户的兜底。
跑完停服务并删掉临时测试账号。
"""
import json
import os
import random
import sqlite3
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8021
BASE = "http://127.0.0.1:%d" % PORT
ok, fail = 0, []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print("  ✓ " + name)
    else:
        fail.append(name)
        print("  ✗ " + name + ("  " + str(extra) if extra else ""))


def call(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode("utf-8", "ignore")
            try:
                return r.status, json.loads(raw or "{}")
            except Exception:
                return r.status, {"_raw": raw[:200]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"_raw": raw[:200]}


env = os.environ.copy()
env["PORT"] = str(PORT)
log = open(os.path.join(ROOT, "data", "smoke_live.log"), "wb")
proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                        stdout=log, stderr=subprocess.STDOUT)
tmp_user = "tmp_" + "".join(random.choice(string.ascii_lowercase) for _ in range(5))
try:
    up = False
    for _ in range(40):
        time.sleep(0.5)
        try:
            if call("/api/meta")[0] == 200:
                up = True
                break
        except Exception:
            pass
    chk("服务起来（真库）", up)

    st, d = call("/")
    chk("/ 首页", st == 200, st)
    html = ""
    try:
        with urllib.request.urlopen(BASE + "/", timeout=10) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception:
        pass
    chk("首页是《第一年》", "第一年" in html)

    st, d = call("/admin")
    chk("/admin 200", st == 200, st)

    st, d = call("/api/login", {"username": "admin", "password": "firstyear2026"})
    chk("管理员登录", st == 200 and d.get("user", {}).get("role") == "admin", d.get("error"))
    atok = d.get("token")
    chk("管理员继承了 .env 的 key", d.get("user", {}).get("has_key") is True)

    st, d = call("/api/admin/test", {}, token=atok)
    chk("测试接口 200", st == 200, d)
    chk("真模型调通", d.get("ok") is True, d.get("reply"))
    print("     ↳ 耗时 %sms，模型 %s，回复：%s" % (d.get("latency_ms"), d.get("model"), str(d.get("reply"))[:40]))

    st, d = call("/api/register", {"username": tmp_user, "password": "hello123"})
    chk("注册无 key 用户", st == 201, d.get("error"))
    utok = d.get("token")

    st, meta = call("/api/meta")
    eid = ((meta.get("events") or [{}])[0] or {}).get("id", "")
    chk("能拿到关卡 id", bool(eid), eid)

    st, d = call("/api/talk", {"event_id": eid, "beat": 0, "text": "你好，我来看房",
                               "history": [], "state": {}}, token=utok)
    chk("无 key 用户走兜底", st == 200 and d.get("fallback") is True, d)

finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    log.close()
    db = os.path.join(ROOT, "data", "users.db")
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM users WHERE username = ?", (tmp_user,))
        conn.commit()
        conn.close()

print()
print("通过 %d 条，失败 %d 条" % (ok, len(fail)))
if fail:
    print("失败项：", "；".join(fail))
sys.exit(1 if fail else 0)
