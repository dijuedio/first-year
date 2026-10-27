# -*- coding: utf-8 -*-
"""账号接口自测：注册 / 重名 / 密码错 / 会话 / 改资料 / 退出"""
import json, random, string, urllib.request, urllib.error

BASE = "http://127.0.0.1:8010"

def call(path, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if data else "GET"))
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

ok = 0
def chk(name, cond, extra=""):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + name + (("  " + str(extra)) if extra else ""))
    ok += 1 if cond else 0
    return cond

u = "t_" + "".join(random.choice(string.ascii_lowercase) for _ in range(6))
pw = "hello123"

print("1 注册")
st, d = call("/api/register", {"username": u, "password": pw})
chk("201 + token", st == 201 and d.get("token"), st)
tok = d.get("token")
chk("昵称默认为空", d.get("user", {}).get("nickname") == "")
chk("不泄露密码字段", "pass_hash" not in json.dumps(d))

print("2 重名")
st, d = call("/api/register", {"username": u, "password": pw})
chk("409", st == 409, d.get("error"))

print("3 短密码")
st, d = call("/api/register", {"username": u + "x", "password": "123"})
chk("400", st == 400, d.get("error"))

print("4 登录：密码错")
st, d = call("/api/login", {"username": u, "password": "wrongpass"})
chk("401", st == 401, d.get("error"))

print("5 登录：正确")
st, d = call("/api/login", {"username": u, "password": pw})
chk("200 + token", st == 200 and d.get("token"))
tok2 = d.get("token")
chk("两次登录 token 不同", tok2 != tok)

print("6 带 token 取资料")
st, d = call("/api/me", token=tok2)
chk("200", st == 200 and d.get("user", {}).get("username") == u)

print("7 无 token / 假 token")
st, _ = call("/api/me")
chk("无 token 401", st == 401)
st, _ = call("/api/me", token="fake-token-123")
chk("假 token 401", st == 401)

print("8 改昵称头像")
st, d = call("/api/profile", {"nickname": "阿念", "avatar": 3, "avatar_img": ""}, token=tok2)
chk("200 且昵称已改", st == 200 and d.get("user", {}).get("nickname") == "阿念", d.get("error"))
st, d = call("/api/me", token=tok2)
chk("重新读仍是阿念", d.get("user", {}).get("nickname") == "阿念")

print("9 名字超长会被截断")
st, d = call("/api/profile", {"nickname": "一二三四五六七八九十", "avatar": 1}, token=tok2)
chk("截到 8 字", len(d.get("user", {}).get("nickname", "")) == 8, d.get("user", {}).get("nickname"))

print("10 空名字被拒")
st, d = call("/api/profile", {"nickname": "  ", "avatar": 1}, token=tok2)
chk("400", st == 400)

print("11 退出后 token 失效")
st, _ = call("/api/logout", {}, token=tok2)
chk("200", st == 200)
st, _ = call("/api/me", token=tok2)
chk("401", st == 401)
st, _ = call("/api/me", token=tok)
chk("另一个会话仍有效", st == 200)

print("\n通过 %d 项" % ok)
