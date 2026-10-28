# -*- coding: utf-8 -*-
"""账号自带 API Key + 管理员后台 的自测。
自己起一个临时实例（临时 DB、临时管理员），跑完就删，不碰 data/users.db。
运行：python test_admin.py
"""
import json
import os
import random
import shutil
import sqlite3
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 8013
BASE = "http://127.0.0.1:%d" % PORT
TMP_DB = os.path.join(ROOT, "data", "test_users_%d.db" % int(time.time() * 1000))
SUF = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
ADM = "adm_" + SUF
USR = "usr_" + SUF
PW = "hello123"

ok = 0
fail = []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print("  ✓ " + name)
    else:
        fail.append(name)
        print("  ✗ " + name + ("  " + str(extra) if extra else ""))
    return cond


def call(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# ---------------------------------------------------------------- 单元
print("0 单元：加密与掩码")
os.environ["DB_PATH"] = TMP_DB
os.environ["KEY_SECRET"] = "unit-test-secret"
sys.path.insert(0, ROOT)
import server  # noqa: E402

for plain in ("sk-abcdef123456", "sk-中文-key-测试", ""):
    blob = server.encrypt_key(plain)
    chk("往返 " + (plain[:10] or "(空)"), server.decrypt_key(blob) == plain)
blob = server.encrypt_key("sk-abcdef123456")
tampered = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
chk("篡改后解不出来", server.decrypt_key(tampered) == "")
chk("空串解出空串", server.decrypt_key("") == "")

conn = sqlite3.connect(TMP_DB)
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, pass_hash TEXT, salt TEXT,"
             " nickname TEXT DEFAULT '', avatar INTEGER DEFAULT 0, avatar_img TEXT DEFAULT '', created_at INTEGER,"
             " role TEXT DEFAULT 'user', api_key_enc TEXT DEFAULT '', api_base TEXT DEFAULT '', api_model TEXT DEFAULT '',"
             " key_status TEXT DEFAULT '', calls INTEGER DEFAULT 0, last_call_at INTEGER DEFAULT 0, banned INTEGER DEFAULT 0)")
conn.execute("INSERT INTO users(username, pass_hash, salt, created_at, role, api_key_enc) VALUES(?,?,?,?,?,?)",
             ("u1", "x", "y", 0, "user", server.encrypt_key("sk-1234567890abcd")))
row = conn.execute("SELECT * FROM users WHERE username='u1'").fetchone()
pu = server.public_user(row)
chk("掩码只露末四位", pu["key_hint"] == "****abcd", pu["key_hint"])
chk("has_key 为真", pu["has_key"] is True)
chk("明文不出现在返回里", "1234567890" not in json.dumps(pu))
conn.close()

# ---------------------------------------------------------------- 起临时实例
print("1 起临时实例（临时库 + 临时管理员）")
env = os.environ.copy()
env.update({
    "PORT": str(PORT),
    "DB_PATH": TMP_DB,
    "ADMIN_USER": ADM,
    "ADMIN_PASSWORD": PW,
    "KEY_SECRET": "unit-test-secret",
    # 故意指一个打不通的地址：所有"验 key"都会快速失败，测试不会真的花钱
    "LLM_BASE_URL": "http://127.0.0.1:9/v1/chat/completions",
    "DEEPSEEK_API_KEY": "sk-test-not-real",
})
log = open(os.path.join(ROOT, "data", "test_admin_server.log"), "wb")
proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                        stdout=log, stderr=subprocess.STDOUT)
try:
    up = False
    for _ in range(60):
        time.sleep(0.5)
        try:
            if call("/api/meta")[0] == 200:
                up = True
                break
        except Exception:
            pass
    chk("实例起来了", up)

    print("2 注册不带 key")
    st, d = call("/api/register", {"username": USR, "password": PW})
    chk("201", st == 201, d)
    utok = d.get("token")
    chk("has_key=False", d.get("user", {}).get("has_key") is False)
    chk("role=user", d.get("user", {}).get("role") == "user")

    print("3 注册带坏 key → 拒绝且不落库")
    bad = "bad_" + SUF
    st, d = call("/api/register", {"username": bad, "password": PW, "api_key": "sk-bad-key-123"})
    chk("400", st == 400, d)
    chk("提示带上原因", "用不了" in (d.get("error") or ""), d.get("error"))

    print("4 管理员登录")
    st, d = call("/api/login", {"username": ADM, "password": PW})
    chk("200", st == 200, d)
    atok = d.get("token")
    chk("role=admin", d.get("user", {}).get("role") == "admin")
    chk("管理员继承 .env 的 key", d.get("user", {}).get("has_key") is True)

    print("5 权限")
    st, d = call("/api/admin/overview", token=utok)
    chk("普通用户 403", st == 403, d)
    st, d = call("/api/admin/overview", token=atok)
    chk("管理员 200", st == 200, d)
    chk("统计字段齐", all(k in d for k in ("total", "with_key", "admins", "calls_total", "users")), list(d)[:8])
    chk("列表里能看到两个账号", d.get("total", 0) >= 2, d.get("total"))

    print("6 用户自己设置 key（坏 key 被拒）")
    st, d = call("/api/key", {"api_key": "sk-another-bad"}, token=utok)
    chk("400", st == 400, d)

    print("7 管理员测试接口（key 是坏的，应如实报失败）")
    st, d = call("/api/admin/test", {}, token=atok)
    chk("200 且在响应里说明", st == 200, d)
    chk("ok=False", d.get("ok") is False, d)
    chk("有耗时", isinstance(d.get("latency_ms"), int), d.get("latency_ms"))

    print("8 封禁 / 解封")
    st, ov = call("/api/admin/overview", token=atok)
    tgt = next(u for u in ov["users"] if u["username"] == USR)
    st, d = call("/api/admin/act", {"user_id": tgt["id"], "action": "ban"}, token=atok)
    chk("封禁 200", st == 200, d)
    st, d = call("/api/login", {"username": USR, "password": PW})
    chk("被封后登录 403", st == 403, d)
    st, d = call("/api/talk", {"event_id": "e1", "beat": 0, "text": "你好"}, token=utok)
    chk("被封后游戏接口 403", st == 403, d)
    st, d = call("/api/admin/act", {"user_id": tgt["id"], "action": "unban"}, token=atok)
    chk("解封 200", st == 200, d)

    print("9 管理员不能封自己")
    me = next(u for u in ov["users"] if u["username"] == ADM)
    st, d = call("/api/admin/act", {"user_id": me["id"], "action": "ban"}, token=atok)
    chk("400", st == 400, d)

    print("10 后台页面")
    st, body = 0, ""
    try:
        with urllib.request.urlopen(BASE + "/admin", timeout=10) as r:
            st, body = r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        st = e.code
    chk("/admin 200", st == 200, st)
    chk("页面里有关键词", ("后台" in body) or ("admin" in body.lower()), st)

finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    log.close()
    for suffix in ("", "-wal", "-shm"):
        p = TMP_DB + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

print()
print("通过 %d 条，失败 %d 条" % (ok, len(fail)))
if fail:
    print("失败项：", "；".join(fail))
sys.exit(1 if fail else 0)
