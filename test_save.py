# -*- coding: utf-8 -*-
"""存档接口的端到端测试：多账号隔离、覆盖、清档、未登录、超大。"""
import json
import random
import string
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def call(path, body=None, token=None, method=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def rnd(n=6):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


ok = 0
bad = 0


def check(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print("  ✓", name, extra)
    else:
        bad += 1
        print("  ✗", name, extra)


ua, ub = "t" + rnd(7), "t" + rnd(7)
sa, da = call("/api/register", {"username": ua, "password": "pass123456"})
sb, db = call("/api/register", {"username": ub, "password": "pass123456"})
check("注册两个测试号", sa in (200, 201) and sb in (200, 201), ua + " / " + ub)
ta, tb = da.get("token"), db.get("token")

# 1. 没存过时是 null
st, r = call("/api/save", token=ta)
check("新号读档为 null", st == 200 and r.get("save") is None, str(r))

# 2. 写一份
SAVE = {"v": 1, "idx": 3, "beat": 2, "day": 12, "time": "19:05", "money": 7300,
        "trust": 55, "alert": 40, "blackout": 0, "kept": 1, "flags": ["loan_signed"],
        "msgs": {"mom": [{"who": "them", "text": "到了就快出去吧", "seq": 0, "ev": "mom_arrive"}]},
        "seq": 2, "replyStage": "act"}
st, r = call("/api/save", {"data": SAVE}, token=ta)
check("A 写档 200", st == 200 and r.get("ok"), str(r))

st, r = call("/api/save", token=ta)
got = (r.get("save") or {}).get("data") or {}
check("A 读回来一致", got.get("idx") == 3 and got.get("day") == 12
      and got.get("flags") == ["loan_signed"] and got.get("msgs", {}).get("mom", [{}])[0].get("text") == "到了就快出去吧",
      "idx=%s day=%s" % (got.get("idx"), got.get("day")))
check("存档带 saved_at", isinstance((r.get("save") or {}).get("saved_at"), int))

# 3. B 读不到 A 的
st, r = call("/api/save", token=tb)
check("B 看不到 A 的档", st == 200 and r.get("save") is None, str(r))

# 4. 覆盖
SAVE2 = dict(SAVE, idx=7, day=30, money=5000)
st, r = call("/api/save", {"data": SAVE2}, token=ta)
st2, r2 = call("/api/save", token=ta)
check("覆盖生效", (r2.get("save") or {}).get("data", {}).get("idx") == 7)

# 5. 未登录
st, r = call("/api/save")
check("未登录读档 401", st == 401, str(st))
st, r = call("/api/save", {"data": SAVE})
check("未登录写档 401", st == 401, str(st))

# 6. 脏数据
st, r = call("/api/save", {"data": "不是对象"}, token=ta)
check("非对象存档 400", st == 400, str(st))

# 7. 超大
big = {"v": 1, "blob": "x" * (2 * 1024 * 1024 + 100)}
st, r = call("/api/save", {"data": big}, token=ta)
check("超 2MB 被拒 413", st == 413, str(st))

# 8. 清档
st, r = call("/api/save/reset", {}, token=ta)
st2, r2 = call("/api/save", token=ta)
check("清档后为 null", st == 200 and r2.get("save") is None, str(r2))

# 9. 清档不影响别人（先给 B 写一份，再清 A）
call("/api/save", {"data": SAVE2}, token=tb)
call("/api/save/reset", {}, token=ta)
st, r = call("/api/save", token=tb)
check("清 A 的档不动 B 的", (r.get("save") or {}).get("data", {}).get("idx") == 7)

print("\n通过 %d 条，失败 %d 条" % (ok, bad))
print("测试账号：%s / %s（密码 pass123456，可后台删）" % (ua, ub))
