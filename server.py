# -*- coding: utf-8 -*-
"""
《第一年》—— 零依赖后端
运行：python server.py
打开：http://127.0.0.1:8000

不装任何第三方库。调用模型走 urllib，没有 key 就自动用兜底台词。
"""
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
STATIC_DIR = os.path.join(ROOT, "static")

def load_env_file(name=".env"):
    """读项目根目录的 .env，让双击 启动.bat 也能带上 key。不覆盖已有环境变量。"""
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and v and not os.environ.get(k):
                os.environ[k] = v


load_env_file()

API_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/chat/completions")
API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def load_json(name):
    with open(os.path.join(DATA_DIR, name), "rb") as f:
        return json.loads(f.read().decode("utf-8"))


EVENTS = load_json("events.json")
FALLBACK = load_json("fallback.json")
EVENT_MAP = {e["id"]: e for e in EVENTS["events"]}
STORY = load_json("story.json")


# ---------------------------------------------------------------- 提示词

ROLE_HINT = {
    "black": "你只关心自己的收益。你不违法，但会挑对方不懂的地方下手，语气可以热情，也可以不耐烦。",
    "good": "你自己做这一行，口碑对你重要。你可以提醒对方一个坑，但不会把话说满，也不替对方做决定。",
    "neutral": "你按规矩办事，把该说的说清楚，不热情也不刁难。",
    "scam": "你要的是对方的钱或者身份信息。你会先建立可信度，再制造紧急感。",
    "family": "你是他妈妈，你担心他，又怕他嫌你烦，说话会绕。",
}


def build_system(ev, beat_index, state, opening=False):
    beats = ev["beats"]
    if opening:
        beat = (f"你先开口，把话头递出去。你想让对方明白的是「{ev['opening']}」"
                f"——意思对就行，不要照抄这几个字。")
    else:
        beat = beats[beat_index] if beat_index < len(beats) else beats[-1]
    role = ROLE_HINT.get(ev["type"], ROLE_HINT["black"])
    return (
        f"你在扮演微信（或电话）另一头的真人，不是助手。\n"
        f"你是谁：{ev['opponent']}，场景是「{ev['scene']}」。\n{role}\n"
        f"你的目的：{ev['goal']}。\n"
        f"现在轮到你说话，这一轮你要做的：{beat}\n\n"
        f"规则：\n"
        f"1. 只说一到两句，像真人随手打字，每句不超过二十五个字。\n"
        f"2. 不解释自己在做什么，不说教，不总结，不写旁白。\n"
        f"3. 不要一次把目的说穿。对方追问时，用话绕过去，或者让一点。\n"
        f"4. 不要主动教对方怎么防骗，不要提真实公司名。\n"
        f"5. 不要用书名号、括号里的动作描写、markdown。\n"
        f"6. 聊天记录里你已经说过的句子，换一种说法，别复读同一句、别用同一个句式开头。\n"
        f"7. 允许口语、停顿、说半句、稍微跑题，像真的在打字。\n"
        f"只输出你要说的那句话。"
    )


def build_judge_messages(ev, text):
    labels = [a["label"] for a in ev["actions"]]
    lines = [
        "你在做一件事：把玩家随口说的一句话，归到下面这些行动里最接近的一个。",
        "场景：%s，对面是%s，他想要的是%s。" % (ev["scene"], ev["opponent"], ev["goal"]),
        "可选行动：",
    ]
    for idx, lab in enumerate(labels):
        lines.append("%d. %s" % (idx, lab))
    lines.append("意思接近就算，不要因为措辞不同就判成不匹配；真的完全不相干才输出 -1。")
    lines.append("只输出一个数字，不要解释。")
    sys = chr(10).join(lines)
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": text},
    ]


def judge_action(ev, text):
    raw = call_llm(build_judge_messages(ev, text), timeout=12)
    if not raw:
        return None
    m = re.search(r"-1|[0-9]+", raw)
    if not m:
        return None
    i = int(m.group(0))
    acts = ev["actions"]
    if 0 <= i < len(acts):
        return acts[i]["label"]
    return None


def build_open_messages(ev, state):
    return [
        {"role": "system", "content": build_system(ev, -1, state, opening=True)},
        {"role": "user", "content": "（对方刚走过来，还没说话）"},
    ]


def build_messages(ev, beat_index, player_text, history, state):
    msgs = [{"role": "system", "content": build_system(ev, beat_index, state)}]
    for h in (history or [])[-8:]:
        role = "user" if h.get("who") == "player" else "assistant"
        text = (h.get("text") or "").strip()
        if text:
            msgs.append({"role": role, "content": text})
    if player_text:
        msgs.append({"role": "user", "content": player_text})
    else:
        msgs.append({"role": "user", "content": "（对方没说话，只是看着你）"})
    return msgs


def call_llm(messages, timeout=20):
    if not API_KEY:
        return None
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "temperature": 1.15,
        "top_p": 0.95,
        "frequency_penalty": 0.5,
        "presence_penalty": 0.4,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
        text = payload["choices"][0]["message"]["content"]
        return clean(text)
    except Exception as e:  # 网络、额度、格式，全走兜底
        print("[llm] 调用失败，用兜底台词：", repr(e)[:160], file=sys.stderr)
        return None


def clean(text):
    text = (text or "").strip()
    text = re.sub(r"^[\"“”'‘’]+|[\"“”'‘’]+$", "", text)
    text = re.sub(r"[（(][^）)]{1,30}[）)]", "", text)      # 括号旁白
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"\n+", "\n", text).strip()
    return text[:120]


def fallback_line(ev, beat_index, history=None):
    pool = ((FALLBACK.get("events") or {}).get(ev["id"])
            or (FALLBACK.get("types") or {}).get(ev["type"])
            or FALLBACK["types"]["black"])
    said = {(h.get("text") or "").strip() for h in (history or []) if h.get("who") != "player"}
    fresh = [x for x in pool if x.strip() not in said]
    pool = fresh or pool
    return random.choice(pool)


# ---------------------------------------------------------------- 结算

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def apply_delta(state, delta):
    for k in ("money", "trust", "alert", "blackout"):
        if k in delta:
            state[k] = state.get(k, 0) + delta[k]
    state["trust"] = clamp(state["trust"])
    state["alert"] = clamp(state["alert"])
    state["blackout"] = clamp(state["blackout"])
    state["money"] = max(0, state["money"])
    return state


def judge_ending(state):
    flags = state.get("flags", [])
    money = state.get("money", 0)
    alert = state.get("alert", 0)
    blackout = state.get("blackout", 0)
    kept = state.get("kept", 0)

    if "gave_passport" in flags and money < 3000:
        return "overseas"
    if (kept >= 3 or "helped_agent" in flags or blackout >= 60) and money >= 3000:
        return "black"
    if "loan_signed" in flags:
        return "loan"
    if money >= 3000 and alert >= 70:
        return "home_ok"
    return "back"


def score_of(state):
    money_part = min(state.get("money", 0), 8000) / 8000 * 100
    s = state.get("alert", 50) * 0.5 + money_part * 0.3 + state.get("trust", 50) * 0.2
    s -= state.get("blackout", 0) * 0.3
    return int(clamp(round(s)))


def build_review(state, log):
    hits, avoided = [], []
    for row in log or []:
        if row.get("result") == "pit":
            hits.append(row.get("action", ""))
        elif row.get("result") == "good":
            avoided.append(row.get("action", ""))
    flags = state.get("flags", [])
    if "loan_signed" in flags:
        hits.append("签了租金贷")
    if "deposit_lost" in flags:
        hits.append("押金没要回来")
    if "scammed_code" in flags:
        hits.append("把验证码念出去了")

    best = avoided[0] if avoided else "你最后还是走了"
    review = (
        f"你走到了第 {state.get('day', 90)} 天。"
        f"踩了 {len(hits)} 个坑，躲过 {len(avoided)} 次。"
        + ("合同里有你看漏的东西。" if "loan_signed" in flags else "")
    )
    hits = list(dict.fromkeys(hits))
    avoided = list(dict.fromkeys(avoided))
    return {
        "score": score_of(state),
        "pits_hit": hits[:8],
        "best_move": best,
        "review": review,
    }


ENDINGS = {
    "home_ok": {"title": "安家", "line": "你留下来了。房租不便宜，但合同你自己看懂了。"},
    "back": {"title": "回家", "line": "你买了回家的票。妈没问为什么。"},
    "loan": {"title": "租金贷", "line": "你每月还着一笔租来的钱。"},
    "overseas": {"title": "海外", "line": "你在一个陌生的园区醒来，手机没有信号。"},
    "black": {"title": "你成了他们", "line": "你现在说的话，和当初那个人一模一样。"},
}



# ---------------------------------------------------------------- 账号（SQLite，标准库）

import hashlib
import secrets
import sqlite3
import time

DB_PATH = os.path.join(DATA_DIR, "users.db")
PW_ITER = 120000          # PBKDF2 迭代次数
SESSION_DAYS = 30
NICK_MAX = 8
IMG_MAX = 1200 * 1024     # 头像 dataURL 上限，约 900KB 原图


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT UNIQUE NOT NULL,
                pass_hash   TEXT NOT NULL,
                salt        TEXT NOT NULL,
                nickname    TEXT NOT NULL DEFAULT '',
                avatar      INTEGER NOT NULL DEFAULT 0,
                avatar_img  TEXT NOT NULL DEFAULT '',
                created_at  INTEGER NOT NULL
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions(
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                created_at  INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def hash_password(password, salt_hex=None):
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PW_ITER)
    return digest.hex(), salt_hex


def verify_password(password, salt_hex, expected):
    digest, _ = hash_password(password, salt_hex)
    return secrets.compare_digest(digest, expected)


def public_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "avatar": row["avatar"],
        "avatar_img": row["avatar_img"],
        "created_at": row["created_at"],
    }


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db_conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?)",
            (token, user_id, now, now + SESSION_DAYS * 86400),
        )
    return token


def user_from_token(token):
    if not token:
        return None
    now = int(time.time())
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?", (token, now)).fetchone()
        return row
    finally:
        conn.close()


def drop_session(token):
    if not token:
        return
    with db_conn() as c:
        c.execute("DELETE FROM sessions WHERE token = ?", (token,))


init_db()


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _token(self):
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._file(os.path.join(STATIC_DIR, "index.html"))
        if path.startswith("/static/"):
            rel = path[len("/static/"):].replace("..", "")
            return self._file(os.path.join(STATIC_DIR, rel))
        if path == "/api/meta":
            return self._json({"meta": EVENTS["meta"], "events": EVENTS["events"], "story": STORY})
        if path == "/api/me":
            row = user_from_token(self._token())
            if not row:
                return self._json({"error": "没有登录"}, 401)
            return self._json({"user": public_user(row)})
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def _file(self, full):
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self._json({"error": "bad json"}, 400)

        path = self.path.split("?")[0]

        if path in ("/api/register", "/api/login"):
            username = (payload.get("username") or "").strip()
            password = payload.get("password") or ""
            if not (3 <= len(username) <= 20):
                return self._json({"error": "用户名要 3 到 20 个字"}, 400)
            if len(password) < 6:
                return self._json({"error": "密码至少 6 位"}, 400)
            reg = path == "/api/register"
            conn = db_conn()
            try:
                row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                if reg:
                    if row:
                        return self._json({"error": "这个用户名已经有人用了"}, 409)
                    ph, salt = hash_password(password)
                    cur = conn.execute(
                        "INSERT INTO users(username, pass_hash, salt, created_at) VALUES(?,?,?,?)",
                        (username, ph, salt, int(time.time())))
                    conn.commit()
                    uid = cur.lastrowid
                else:
                    if not row or not verify_password(password, row["salt"], row["pass_hash"]):
                        return self._json({"error": "用户名或密码不对"}, 401)
                    uid = row["id"]
                token = create_session(uid)
                fresh = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
                return self._json({"token": token, "user": public_user(fresh)}, 201 if reg else 200)
            finally:
                conn.close()

        if path == "/api/logout":
            drop_session(self._token())
            return self._json({"ok": True})

        if path == "/api/profile":
            row = user_from_token(self._token())
            if not row:
                return self._json({"error": "没有登录"}, 401)
            nickname = (payload.get("nickname") or "").strip()[:NICK_MAX]
            avatar = payload.get("avatar")
            avatar = int(avatar) if isinstance(avatar, int) or str(avatar).isdigit() else 0
            avatar = max(0, min(7, avatar))
            img = payload.get("avatar_img") or ""
            if len(img) > IMG_MAX:
                return self._json({"error": "头像图片太大了"}, 413)
            if not nickname:
                return self._json({"error": "名字不能是空的"}, 400)
            with db_conn() as c:
                c.execute("UPDATE users SET nickname = ?, avatar = ?, avatar_img = ? WHERE id = ?",
                          (nickname, avatar, img, row["id"]))
            conn = db_conn()
            try:
                fresh = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
            finally:
                conn.close()
            return self._json({"user": public_user(fresh)})

        if path == "/api/talk":
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            beat = int(payload.get("beat") or 0)
            state = payload.get("state") or {}
            text = call_llm(build_messages(
                ev, beat, payload.get("text", ""), payload.get("history", []), state
            ))
            if not text:
                return self._json({"reply": fallback_line(ev, beat, payload.get("history")), "fallback": True})
            return self._json({"reply": text, "fallback": False})

        if path == "/api/judge":
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            label = judge_action(ev, (payload.get("text") or "").strip())
            return self._json({"label": label, "matched": bool(label)})

        if path == "/api/open":
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            text = call_llm(build_open_messages(ev, payload.get("state") or {}))
            if not text:
                return self._json({"reply": ev["opening"], "fallback": True})
            return self._json({"reply": text, "fallback": False})

        if path == "/api/settle":
            ev = EVENT_MAP.get(payload.get("event_id"))
            action = payload.get("action")
            state = payload.get("state") or {}
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            hit = next((a for a in ev["actions"] if a["label"] == action), None)
            result = "neutral"
            if hit:
                apply_delta(state, hit.get("delta") or {})
                if hit.get("flag"):
                    state.setdefault("flags", []).append(hit["flag"])
                if hit.get("pit"):
                    result = "pit"
                elif hit.get("good"):
                    result = "good"
            return self._json({"state": state, "result": result})

        if path == "/api/review":
            state = payload.get("state") or {}
            log = payload.get("log") or []
            key = judge_ending(state)
            body = build_review(state, log)
            body["ending"] = dict(ENDINGS[key], key=key)
            return self._json(body)

        return self._json({"error": "not found"}, 404)


def main():
    port = int(os.environ.get("PORT", "8000"))
    has_key = "有" if API_KEY else "无（走兜底台词）"
    print("=" * 46)
    print("  《第一年》已启动")
    print(f"  打开：http://127.0.0.1:{port}")
    print(f"  模型：{MODEL}   key：{has_key}")
    print("  Ctrl+C 结束")
    print("=" * 46)
    ThreadingHTTPServer.allow_reuse_address = False   # Windows 上允许复用会导致两个实例同时监听
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        srv.serve_forever()
    except OSError as e:
        print("端口", port, "已被占用，先关掉上一个实例：", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
