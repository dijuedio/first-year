# -*- coding: utf-8 -*-
"""端到端跑一整局：按 story.json 的固定顺序走完 15 步，每步 5 拍。
运行：python test_flow.py
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8010"


def post(path, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


meta = get("/api/meta")
events = {e["id"]: e for e in meta["events"]}
order = meta["story"]["order"]
contacts = {c["id"]: c for c in meta["story"]["contacts"]}

problems = []
for i, step in enumerate(order):
    if step["event"] not in events:
        problems.append(f"第{i+1}步找不到事件 {step['event']}")
    if step["contact"] not in contacts:
        problems.append(f"第{i+1}步找不到联系人 {step['contact']}")
    if i and step["day"] < order[i - 1]["day"]:
        problems.append(f"第{i+1}步日期倒流 {step['day']} < {order[i-1]['day']}")
if problems:
    print("剧本自检出问题：")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print(f"剧本自检通过：{len(order)} 步，日期递增，人物与事件都对得上\n")

# 走一遍：好选择／坏选择交替，尽量覆盖两条路
state = {**meta["meta"]["start"], "flags": [], "day": 1, "kept": 0}
log = []

for i, step in enumerate(order):
    ev = events[step["event"]]
    mate = contacts[step["contact"]]
    state["day"] = step["day"]
    good = [a for a in ev["actions"] if a.get("good")]
    bad = [a for a in ev["actions"] if a.get("pit")]
    pick = (bad[0] if (i % 3 == 2 and bad) else (good[0] if good else ev["actions"][0]))

    print(f"[{i+1:2}/{len(order)}] 第{step['day']:2}天 {mate['name']}（{mate['group']}）· {ev['title']}")
    print(f"      旁白：{step.get('bridge','')[:34]}…")
    history = [{"who": "them", "text": ev["opening"]}]
    for beat in range(5):
        d = post("/api/talk", {"event_id": ev["id"], "beat": beat,
                               "text": pick["label"] if beat == 0 else "嗯",
                               "history": history[-8:], "state": state})
        history.append({"who": "player", "text": pick["label"] if beat == 0 else "嗯"})
        history.append({"who": "them", "text": d["reply"]})
    d = post("/api/settle", {"event_id": ev["id"], "action": pick["label"], "state": state})
    state = d["state"]
    log.append({"event": ev["id"], "action": pick["label"], "result": d["result"]})
    print(f"      「{pick['label']}」→ {d['result']} | 钱 {state['money']} 信任 {state['trust']} 警惕 {state['alert']}")

d = post("/api/review", {"state": state, "log": log})
print("\n" + "=" * 44)
print("结局：", d["ending"]["title"], "|", d["ending"]["line"])
print("分数：", d["score"], "| 踩坑：", "、".join(d["pits_hit"]) or "无")
print("身上还剩：", state["money"], "块 | 标记：", "、".join(state["flags"]) or "无")
