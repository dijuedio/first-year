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
DEFAULT_BASE = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/chat/completions")
# 管理员账号：启动时按 .env 的 ADMIN_USER / ADMIN_PASSWORD 建或补全。
# 旧的共享 key（DEEPSEEK_API_KEY）只挂在这个管理员名下，普通账号必须自带 key。
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

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


def judge_action(ev, text, user=None):
    raw = call_llm(build_judge_messages(ev, text), timeout=12, user=user)
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


def call_llm(messages, timeout=20, user=None):
    """用这个账号自己的 key 调模型；没有 key 就返回 None（上层自动走兜底台词）。"""
    key, url, model = llm_settings(user)
    if not key:
        return None
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 1.15,
        "top_p": 0.95,
        "frequency_penalty": 0.5,
        "presence_penalty": 0.4,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
        text = payload["choices"][0]["message"]["content"]
        if user is not None and "id" in user.keys():
            with db_conn() as c:
                c.execute("UPDATE users SET calls = calls + 1, last_call_at = ? WHERE id = ?",
                          (int(time.time()), user["id"]))
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

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time

DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA_DIR, "users.db")   # 测试可用 DB_PATH 指到临时库
PW_ITER = 120000          # PBKDF2 迭代次数
SESSION_DAYS = 30
NICK_MAX = 8
IMG_MAX = 1200 * 1024     # 头像 dataURL 上限，约 900KB 原图


def _load_key_secret():
    """用户 API Key 的加密主密钥：优先 .env 的 KEY_SECRET，否则用 data/.keysecret（首次自动生成）。"""
    env = (os.environ.get("KEY_SECRET") or "").strip()
    if env:
        return env.encode("utf-8")
    path = os.path.join(DATA_DIR, ".keysecret")
    try:
        with open(path, "rb") as f:
            data = f.read().strip()
        if len(data) >= 32:
            return data
    except FileNotFoundError:
        pass
    data = secrets.token_hex(32).encode("ascii")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return data


KEY_SECRET = _load_key_secret()


def _keystream(secret, nonce, n):
    out = b""
    i = 0
    while len(out) < n:
        out += hmac.new(secret, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def encrypt_key(plain):
    """把用户的 key 加密成一串可入库的文本（HMAC-SHA256 计数器流 + 完整性校验）。"""
    if not plain:
        return ""
    nonce = os.urandom(12)
    data = plain.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(KEY_SECRET, nonce, len(data))))
    tag = hmac.new(KEY_SECRET, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + tag + ct).decode("ascii")


def decrypt_key(blob):
    if not blob:
        return ""
    try:
        raw = base64.b64decode(blob)
        nonce, tag, ct = raw[:12], raw[12:28], raw[28:]
        want = hmac.new(KEY_SECRET, nonce + ct, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, want):
            return ""
        return bytes(a ^ b for a, b in zip(ct, _keystream(KEY_SECRET, nonce, len(ct)))).decode("utf-8")
    except Exception:
        return ""


def verify_key(key, url=None, model=None, timeout=15):
    """拿这个 key 真打一次最小请求。返回 (能不能用, 人话原因)。"""
    url = url or DEFAULT_BASE
    model = model or MODEL
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
        if payload.get("choices"):
            return True, "ok"
        return False, "接口没返回内容"
    except urllib.error.HTTPError as e:
        code = e.code
        plain = {"401": "key 不对", "402": "余额不足", "403": "没有权限",
                 "404": "地址不对", "429": "被限流"}.get(str(code), "HTTP %d" % code)
        try:
            extra = e.read().decode("utf-8", "ignore")[:160]
        except Exception:
            extra = ""
        return False, plain + ("：" + extra if extra else "")
    except Exception as e:
        return False, "连不上（%s）" % type(e).__name__


def llm_settings(user):
    """返回 (key, url, model)。用户自己的优先；管理员没填时回落到 .env 的那个。"""
    if user is not None:
        cols = user.keys()
        enc = user["api_key_enc"] if "api_key_enc" in cols else ""
        key = decrypt_key(enc) if enc else ""
        if key:
            base = (user["api_base"] if "api_base" in cols else "") or DEFAULT_BASE
            model = (user["api_model"] if "api_model" in cols else "") or MODEL
            return key, base, model
        role = user["role"] if "role" in cols else "user"
        if role == "admin" and API_KEY:
            return API_KEY, DEFAULT_BASE, MODEL
    return "", DEFAULT_BASE, MODEL


def _add_cols(conn, table, cols):
    have = {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    for name, ddl in cols:
        if name not in have:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))


def ensure_admin():
    """建/补管理员账号，并把 .env 里的共享 key 收进它名下（普通账号不再偷偷用）。"""
    if not ADMIN_PASSWORD:
        return
    now = int(time.time())
    with db_conn() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (ADMIN_USER,)).fetchone()
        if not row:
            ph, salt = hash_password(ADMIN_PASSWORD)
            enc = encrypt_key(API_KEY) if API_KEY else ""
            c.execute(
                "INSERT INTO users(username, pass_hash, salt, created_at, role, api_key_enc, key_status) "
                "VALUES(?,?,?,?,?,?,?)",
                (ADMIN_USER, ph, salt, now, "admin", enc, "ok" if enc else ""))
            print("[admin] 已创建管理员账号：" + ADMIN_USER)
            return
        if (row["role"] or "user") != "admin":
            c.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
        if API_KEY and not (row["api_key_enc"] or ""):
            c.execute("UPDATE users SET api_key_enc = ?, key_status = 'ok' WHERE id = ?",
                      (encrypt_key(API_KEY), row["id"]))
            print("[admin] 已把 .env 的 key 收到管理员名下")


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
        # 2026-10-28：账号自带的 API Key 与后台所需的字段（老库直接 ALTER 补上）
        _add_cols(c, "users", [
            ("role", "TEXT NOT NULL DEFAULT 'user'"),
            ("api_key_enc", "TEXT NOT NULL DEFAULT ''"),
            ("api_base", "TEXT NOT NULL DEFAULT ''"),
            ("api_model", "TEXT NOT NULL DEFAULT ''"),
            ("key_status", "TEXT NOT NULL DEFAULT ''"),
            ("calls", "INTEGER NOT NULL DEFAULT 0"),
            ("last_call_at", "INTEGER NOT NULL DEFAULT 0"),
            ("banned", "INTEGER NOT NULL DEFAULT 0"),
        ])


def hash_password(password, salt_hex=None):
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PW_ITER)
    return digest.hex(), salt_hex


def verify_password(password, salt_hex, expected):
    digest, _ = hash_password(password, salt_hex)
    return secrets.compare_digest(digest, expected)


def public_user(row):
    """给前端的用户信息。API Key 只回末四位掩码，明文永不出服务端。"""
    cols = row.keys()

    def g(name, default=""):
        return row[name] if name in cols else default

    plain = decrypt_key(g("api_key_enc", "") or "")
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "avatar": row["avatar"],
        "avatar_img": row["avatar_img"],
        "created_at": row["created_at"],
        "role": g("role", "user") or "user",
        "has_key": bool(plain),
        "key_hint": ("****" + plain[-4:]) if len(plain) >= 8 else ("****" if plain else ""),
        "key_status": g("key_status", "") or "",
        "calls": g("calls", 0) or 0,
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
ensure_admin()


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

    def _user(self):
        return user_from_token(self._token())

    def _admin(self):
        row = self._user()
        if not row or (row["role"] or "user") != "admin":
            return None
        return row

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._file(os.path.join(STATIC_DIR, "index.html"))
        if path == "/admin":
            return self._file(os.path.join(STATIC_DIR, "admin.html"))
        if path.startswith("/static/"):
            rel = path[len("/static/"):].replace("..", "")
            return self._file(os.path.join(STATIC_DIR, rel))
        if path == "/api/meta":
            return self._json({"meta": EVENTS["meta"], "events": EVENTS["events"], "story": STORY})
        if path == "/api/admin/overview":
            admin = self._admin()
            if not admin:
                return self._json({"error": "只有管理员能看"}, 403)
            with db_conn() as c:
                users = c.execute("SELECT * FROM users ORDER BY id").fetchall()
            lst = []
            for u in users:
                d = public_user(u)
                d["banned"] = int(u["banned"] or 0)
                d["last_call_at"] = int(u["last_call_at"] or 0)
                d["api_base"] = u["api_base"] or ""
                d["api_model"] = u["api_model"] or ""
                lst.append(d)
            return self._json({
                "total": len(lst),
                "with_key": sum(1 for x in lst if x["has_key"]),
                "admins": sum(1 for x in lst if x["role"] == "admin"),
                "calls_total": sum(int(x["calls"] or 0) for x in lst),
                "banned": sum(1 for x in lst if x["banned"]),
                "server_key": bool(API_KEY),
                "game_events": len(EVENTS.get("events") or []),
                "users": lst,
            })

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
                    # 用户自己的模型 key：填了就当场验一次，验不过不让注册（避免存一个坏 key）
                    api_key = (payload.get("api_key") or "").strip()
                    api_base = (payload.get("api_base") or "").strip()
                    api_model = (payload.get("api_model") or "").strip()
                    if api_key:
                        ok, why = verify_key(api_key, api_base or DEFAULT_BASE, api_model or MODEL)
                        if not ok:
                            return self._json({"error": "这个 API Key 用不了：" + why}, 400)
                    key_enc = encrypt_key(api_key) if api_key else ""
                    cur = conn.execute(
                        "INSERT INTO users(username, pass_hash, salt, created_at, role, api_key_enc, api_base, api_model, key_status) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (username, ph, salt, int(time.time()), "user", key_enc, api_base, api_model,
                         "ok" if api_key else ""))
                    conn.commit()
                    uid = cur.lastrowid
                else:
                    if not row or not verify_password(password, row["salt"], row["pass_hash"]):
                        return self._json({"error": "用户名或密码不对"}, 401)
                    if int(row["banned"] or 0):
                        return self._json({"error": "这个账号被管理员封了"}, 403)
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

        if path == "/api/key":
            row = self._user()
            if not row:
                return self._json({"error": "没有登录"}, 401)
            action = (payload.get("action") or "set").strip()
            if action == "clear":
                with db_conn() as c:
                    c.execute("UPDATE users SET api_key_enc = '', key_status = '' WHERE id = ?", (row["id"],))
                return self._json({"ok": True, "user": public_user(self._user())})
            new_key = (payload.get("api_key") or "").strip()
            base = (payload.get("api_base") or "").strip()
            model = (payload.get("api_model") or "").strip()
            if not new_key:
                return self._json({"error": "key 不能为空"}, 400)
            ok, why = verify_key(new_key, base or DEFAULT_BASE, model or MODEL)
            if not ok:
                with db_conn() as c:
                    c.execute("UPDATE users SET key_status = 'invalid' WHERE id = ?", (row["id"],))
                return self._json({"error": "这个 key 用不了：" + why}, 400)
            with db_conn() as c:
                c.execute("UPDATE users SET api_key_enc = ?, api_base = ?, api_model = ?, key_status = 'ok' WHERE id = ?",
                          (encrypt_key(new_key), base, model, row["id"]))
            return self._json({"ok": True, "user": public_user(self._user())})

        if path == "/api/admin/overview":
            admin = self._admin()
            if not admin:
                return self._json({"error": "只有管理员能看"}, 403)
            with db_conn() as c:
                users = c.execute("SELECT * FROM users ORDER BY id").fetchall()
            lst = []
            for u in users:
                d = public_user(u)
                d["banned"] = int(u["banned"] or 0)
                d["last_call_at"] = int(u["last_call_at"] or 0)
                d["api_base"] = u["api_base"] or ""
                d["api_model"] = u["api_model"] or ""
                lst.append(d)
            return self._json({
                "total": len(lst),
                "with_key": sum(1 for x in lst if x["has_key"]),
                "admins": sum(1 for x in lst if x["role"] == "admin"),
                "calls_total": sum(int(x["calls"] or 0) for x in lst),
                "banned": sum(1 for x in lst if x["banned"]),
                "server_key": bool(API_KEY),
                "game_events": len(EVENTS.get("events") or []),
                "users": lst,
            })

        if path == "/api/admin/act":
            admin = self._admin()
            if not admin:
                return self._json({"error": "只有管理员能操作"}, 403)
            uid = int(payload.get("user_id") or 0)
            act = (payload.get("action") or "").strip()
            if uid == admin["id"] and act in ("ban", "demote"):
                return self._json({"error": "别把自己关掉"}, 400)
            if act == "ban":
                sql, args = "UPDATE users SET banned = 1 WHERE id = ?", (uid,)
            elif act == "unban":
                sql, args = "UPDATE users SET banned = 0 WHERE id = ?", (uid,)
            elif act == "reset_key":
                sql, args = "UPDATE users SET api_key_enc = '', key_status = '' WHERE id = ?", (uid,)
            elif act == "set_role":
                role = "admin" if (payload.get("role") or "") == "admin" else "user"
                sql, args = "UPDATE users SET role = ? WHERE id = ?", (role, uid)
            else:
                return self._json({"error": "不认识这个操作"}, 400)
            with db_conn() as c:
                c.execute(sql, args)
            return self._json({"ok": True})

        if path == "/api/admin/test":
            admin = self._admin()
            if not admin:
                return self._json({"error": "只有管理员能测"}, 403)
            key, url, model = llm_settings(admin)
            if not key:
                return self._json({"error": "管理员名下还没有 key：在 .env 写 DEEPSEEK_API_KEY，或后台给管理员设一个"}, 400)
            t0 = time.time()
            reply = call_llm([{"role": "user", "content": "用一句话说你准备好了"}], timeout=25, user=admin)
            ms = int((time.time() - t0) * 1000)
            return self._json({"ok": bool(reply), "latency_ms": ms, "model": model,
                               "url": url, "reply": reply or "（模型没返回，已走兜底台词）"})

        if path == "/api/talk":
            user = self._user()
            if user is not None and int(user["banned"] or 0):
                return self._json({"error": "这个账号被管理员封了"}, 403)
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            beat = int(payload.get("beat") or 0)
            state = payload.get("state") or {}
            text = call_llm(build_messages(
                ev, beat, payload.get("text", ""), payload.get("history", []), state
            ), user=user)
            if not text:
                return self._json({"reply": fallback_line(ev, beat, payload.get("history")), "fallback": True})
            return self._json({"reply": text, "fallback": False})

        if path == "/api/judge":
            user = self._user()
            if user is not None and int(user["banned"] or 0):
                return self._json({"error": "这个账号被管理员封了"}, 403)
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            label = judge_action(ev, (payload.get("text") or "").strip(), user=user)
            return self._json({"label": label, "matched": bool(label)})

        if path == "/api/open":
            user = self._user()
            if user is not None and int(user["banned"] or 0):
                return self._json({"error": "这个账号被管理员封了"}, 403)
            ev = EVENT_MAP.get(payload.get("event_id"))
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            text = call_llm(build_open_messages(ev, payload.get("state") or {}), user=user)
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
    print("  账号：每个玩家用自己的 API Key；管理员后台 http://127.0.0.1:%d/admin" % port)
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
