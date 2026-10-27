# -*- coding: utf-8 -*-
"""接口自测：不需要浏览器，直接打后端。运行：python test_client.py"""
import json
import urllib.request

BASE = "http://127.0.0.1:8010"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read()


def post(path, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


st, body = get("/api/meta")
meta = json.loads(body.decode("utf-8"))
print("meta:", st, "事件", len(meta["events"]), "· 步骤", len(meta["story"]["order"]),
      "· 联系人", len(meta["story"]["contacts"]))

st, body = get("/")
print("index:", st, len(body), "字节", "| 手机界面:", b'class="phone"' in body)

st, body = get("/static/app.js")
print("app.js:", st, len(body), "字节")

state = {"money": 8000, "trust": 50, "alert": 50, "blackout": 0,
         "kept": 0, "flags": [], "day": 1}

st, d = post("/api/talk", {"event_id": "rent_agent", "beat": 0,
                           "text": "这房子多少钱", "history": [], "state": state})
print("talk:", st, "|", d["reply"], "| 兜底:", d.get("fallback"))

st, d = post("/api/settle", {"event_id": "rent_agent", "action": "问房产证和房东本人", "state": state})
print("settle 好选择:", d["result"], "| 警惕", d["state"]["alert"])

state2 = {**state, "flags": []}
st, d = post("/api/settle", {"event_id": "contract", "action": "扫了码，签了", "state": state2})
print("settle 踩坑:", d["result"], "| 标记", d["state"]["flags"], "| 钱", d["state"]["money"])

st, d = post("/api/review", {"state": {**state, "money": 5200, "alert": 72, "day": 90}, "log": []})
print("review:", d["score"], "分 →", d["ending"]["title"])

for s, label in [
    ({"money": 6000, "trust": 20, "alert": 60, "blackout": 65, "kept": 3, "flags": [], "day": 90}, "黑化"),
    ({"money": 2000, "trust": 40, "alert": 30, "blackout": 0, "kept": 0, "flags": ["gave_passport"], "day": 90}, "海外"),
    ({"money": 7000, "trust": 50, "alert": 60, "blackout": 0, "kept": 0, "flags": ["loan_signed"], "day": 90}, "租金贷"),
    ({"money": 200, "trust": 30, "alert": 30, "blackout": 10, "kept": 1, "flags": [], "day": 90}, "回家"),
]:
    st, d = post("/api/review", {"state": s, "log": []})
    print(f"  {label} → {d['ending']['key']} / {d['ending']['title']}")
