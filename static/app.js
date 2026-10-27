/* 《第一年》—— 手机界面版
   桌面 / 微信 / 短信 / 通话记录 / 备忘录 / 钱包 / 相册
   剧情按 data/story.json 的固定顺序推进，每个角色一个会话。
*/
const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const ICON = {
  wechat: '<svg viewBox="0 0 24 24"><ellipse cx="9.2" cy="9.6" rx="7" ry="5.7"/><ellipse cx="16.4" cy="15" rx="5.4" ry="4.3" opacity=".82"/></svg>',
  phone: '<svg viewBox="0 0 24 24"><path d="M6.6 3.6c.4 0 .8.2 1 .6l1.6 2.6c.2.4.2.9-.1 1.2L8 9.3c1 2 2.7 3.7 4.7 4.7l1.3-1.1c.3-.3.8-.3 1.2-.1l2.6 1.6c.4.2.6.6.6 1v2.3c0 .9-.8 1.6-1.7 1.5C10.4 18.7 5.4 13.7 4.7 6.3c-.1-.9.6-1.7 1.5-1.7h.4z"/></svg>',
  sms: '<svg viewBox="0 0 24 24"><path d="M5 4.5h14a2.5 2.5 0 0 1 2.5 2.5v8A2.5 2.5 0 0 1 19 17.5H9.6L6 20.4V17.5h-1A2.5 2.5 0 0 1 2.5 15V7A2.5 2.5 0 0 1 5 4.5z"/></svg>'
};

const S = {
  meta: null, events: [], map: {}, story: null, steps: [],
  idx: -1, beat: 0, ev: null, contact: null, busy: false, over: false,
  day: 1, time: '06:40',
  money: 8000, trust: 50, alert: 50, blackout: 0, kept: 0, flags: [],
  msgs: {}, unread: {}, calls: [], sms: [], notes: [], ledger: [], log: [],
  view: 'home', chatWith: null, filter: '全部', tab: 'wx', seq: 0, toast: null,
  profile: null, edit: '', draft: '', login: null
};

const groups = () => (S.story ? S.story.groups : ['家人']);
const contact = (id) => (S.story.contacts.find((c) => c.id === id) || { id, name: id, group: '陌生人', avatar: '?', color: '#666', note: '' });
const unreadAll = () => Object.values(S.unread).reduce((a, b) => a + b, 0);
const DAY0 = new Date(2026, 8, 1); // 9 月 1 日落地

/* ------------------------------------------------ 玩家档案（名字 / 头像） */
const AVS = [
  { e: '🌱', bg: 'linear-gradient(135deg,#8fd0ac,#4c9a78)' },
  { e: '☕', bg: 'linear-gradient(135deg,#d4b08a,#9c6f4a)' },
  { e: '🌙', bg: 'linear-gradient(135deg,#9b9cc8,#5a5b8f)' },
  { e: '🐟', bg: 'linear-gradient(135deg,#8fc4dc,#3f7fa8)' },
  { e: '🍊', bg: 'linear-gradient(135deg,#f0bb85,#cf7a3a)' },
  { e: '📚', bg: 'linear-gradient(135deg,#b8aede,#7a6bb0)' },
  { e: '🌊', bg: 'linear-gradient(135deg,#87c8de,#3f8aa8)' },
  { e: '🍃', bg: 'linear-gradient(135deg,#b2cf93,#6f9a4e)' }
];
const PROFILE_KEY = 'firstyear.profile';

function loadProfile() {
  try {
    const p = JSON.parse(localStorage.getItem(PROFILE_KEY) || 'null');
    if (p && typeof p.name === 'string') return { name: p.name, av: p.av | 0, img: p.img || '' };
  } catch (e) {}
  return null;
}
function saveProfile(p) {
  S.profile = p;
  try { localStorage.setItem(PROFILE_KEY, JSON.stringify(p)); } catch (e) {}
}
function meName() { return (S.profile && S.profile.name) || '我'; }

function meAvatar(size) {
  const p = S.profile || { av: 0, img: '' };
  if (p.img) {
    return `<span class="avatar avimg" style="width:${size}px;height:${size}px;background-image:url('${p.img}')"></span>`;
  }
  const a = AVS[(p.av | 0) % AVS.length];
  return `<span class="avatar" style="width:${size}px;height:${size}px;background:${a.bg};font-size:${Math.round(size * 0.48)}px">${a.e}</span>`;
}

function avGridHtml(p) {
  const cur = p || { av: 0, img: '' };
  return AVS.map((a, i) =>
    `<button class="avPick ${cur.img ? '' : (i === (cur.av | 0) ? 'on' : '')}" data-av="${i}" style="background:${a.bg}">${a.e}</button>`
  ).join('') + `<label class="avPick upch" title="上传图片">＋<input type="file" data-avfile="1" accept="image/*" hidden></label>`;
}

function dateOf(day) {
  const d = new Date(DAY0.getTime() + (day - 1) * 86400000);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

/* ------------------------------------------------ 启动 */
async function boot() {
  try {
    const r = await fetch('/api/meta');
    const d = await r.json();
    S.meta = d.meta;
    S.events = d.events;
    S.story = d.story;
    d.events.forEach((e) => { S.map[e.id] = e; });
  } catch (e) {
    $('#app').innerHTML = '<div class="app"><div class="card">后端没起来。先双击「启动.bat」，或者运行 python server.py。</div></div>';
    return;
  }
  S.steps = S.story.order || [];
  S.profile = loadProfile();
  if (S.profile) splash(); else loginScreen();
}

function startGame() {
  const st = S.meta.start;
  Object.assign(S, {
    idx: -1, beat: 0, ev: null, contact: null, busy: false, over: false,
    day: 1, time: '06:40',
    money: st.money, trust: st.trust, alert: st.alert, blackout: 0, kept: 0, flags: [],
    msgs: {}, unread: {}, calls: [], ledger: [], log: [],
    sms: (S.story.sms || []).map((x) => ({ ...x, day: 1 })),
    notes: (S.story.notes || []).map((t) => ({ text: t, done: false })),
    view: 'home', chatWith: null, filter: '全部', tab: 'wx', seq: 0, toast: null, hint: true
  });
  render();
  setTimeout(nextStep, 900);
}

/* ------------------------------------------------ 渲染骨架 */
function setStatus() {
  $('#screen').classList.toggle('dark', S.view === 'home' || S.view === 'ending' || !!document.querySelector('.callmask'));
  $('#stTime').textContent = S.time;
}

function render() {
  setStatus();
  const app = $('#app');
  let html = '';
  if (S.view === 'home') html = viewHome();
  else if (S.view === 'wechat') html = viewWechat();
  else if (S.view === 'chat') html = viewChat();
  else if (S.view === 'sms') html = viewSms();
  else if (S.view === 'phone') html = viewPhone();
  else if (S.view === 'notes') html = viewNotes();
  else if (S.view === 'wallet') html = viewWallet();
  else if (S.view === 'photos') html = viewPhotos();
  else if (S.view === 'settings') html = viewSettings();
  app.innerHTML = html;
  if (S.toast && S.view !== 'chat') app.insertAdjacentHTML('beforeend', toastHtml());
  if (S.profile && S.view !== 'home' && S.view !== 'login' && S.view !== 'splash' && !S.over && S.hint) app.insertAdjacentHTML('beforeend', '<div class="barhint">点下面这条横线回桌面</div>');
  // 聊天页滚到底
  const m = app.querySelector('.msgs');
  if (m) m.scrollTop = m.scrollHeight;
  bind();
}

function toastHtml() {
  const c = contact(S.toast.cid);
  const low = S.view === 'home' ? '' : ' low';
  return `<div class="toast${low}" data-open="${c.id}">
    <span class="avatar" style="background:${c.color}">${esc(c.avatar)}</span>
    <span class="ts">
      <span class="tn">${esc(c.name)}<span class="tag">${esc(c.group)}</span></span>
      <span class="tt">${esc((S.toast.text || '').slice(0, 24))}</span>
    </span>
    <span class="tm">现在</span>
  </div>`;
}

function bind() {
  // 底部横条 = 回桌面
  const hb = document.querySelector('.homebar');
  if (hb) {
    hb.style.cursor = 'pointer';
    hb.onclick = () => {
      if (S.over || S.view === 'login' || S.view === 'splash') return;
      S.hint = false;
      S.toast = null;
      S.view = 'home';
      render();
    };
  }
  document.querySelectorAll('[data-go]').forEach((b) => {
    b.onclick = () => {
      S.view = b.dataset.go;
      if (b.dataset.clear) S.unread[b.dataset.clear] = 0;
      render();
    };
  });
  document.querySelectorAll('[data-open]').forEach((b) => {
    b.onclick = () => openChat(b.dataset.open);
  });
  document.querySelectorAll('[data-toast]').forEach((b) => {
    b.onclick = () => openChat(b.dataset.toast);
  });
  document.querySelectorAll('[data-filter]').forEach((b) => {
    b.onclick = () => { S.filter = b.dataset.filter; render(); };
  });
  document.querySelectorAll('[data-tab]').forEach((b) => {
    b.onclick = () => { S.tab = b.dataset.tab; render(); };
  });
  document.querySelectorAll('[data-rep]').forEach((b) => {
    b.onclick = () => choose(b.dataset.rep, false);
  });
  document.querySelectorAll('[data-keep]').forEach((b) => {
    b.onclick = () => {
      S.kept++;
      S.blackout = Math.min(100, S.blackout + 8);
      push(S.contact, 'sys', '〔你把这句记在心里了〕');
      render();
    };
  });
  document.querySelectorAll('[data-next]').forEach((b) => {
    b.onclick = () => nextStep();
  });
  document.querySelectorAll('[data-start]').forEach((b) => {
    b.onclick = () => startGame();
  });
  document.querySelectorAll('[data-send]').forEach((b) => {
    b.onclick = () => sendTyped();
  });
  const tin = document.querySelector('#typin');
  if (tin) {
    tin.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); sendTyped(); }
    });
    tin.addEventListener('input', () => { S.draft = tin.value; });
    // 发完一句不用再点输入框：每轮渲染后自动把光标放回去
    if (!S.busy && S.replyStage === 'act' && document.activeElement !== tin) {
      tin.focus();
      const n = tin.value.length;
      try { tin.setSelectionRange(n, n); } catch (e) {}
    }
  }
  const lgName = document.querySelector('#lgName');
  if (lgName) {
    lgName.addEventListener('input', () => { S.login.name = lgName.value; });
    if (document.activeElement !== lgName) { lgName.focus(); }
  }
  document.querySelectorAll('[data-av]').forEach((b) => {
    b.onclick = () => {
      const p = (S.view === 'login') ? S.login : (S.profile || { name: meName(), av: 0, img: '' });
      p.av = parseInt(b.dataset.av, 10) || 0;
      p.img = '';
      if (S.view === 'login') {
        document.querySelectorAll('#lgGrid .avPick').forEach((x) => x.classList.remove('on'));
        b.classList.add('on');
        $('#lgPreview').innerHTML = meAvatarOf(p, 62);
      } else {
        saveProfile({ name: meName(), av: p.av, img: '' });
        S.edit = '';
        render();
      }
    };
  });
  document.querySelectorAll('[data-avfile]').forEach((inp) => {
    inp.onchange = () => {
      const f = inp.files && inp.files[0];
      if (!f) return;
      if (f.size > 900 * 1024) { alert('图片太大了，换一张小于 900KB 的'); return; }
      const fr = new FileReader();
      fr.onload = () => {
        const p = (S.view === 'login') ? S.login : (S.profile || { name: meName(), av: 0, img: '' });
        p.img = String(fr.result);
        if (S.view === 'login') {
          document.querySelectorAll('#lgGrid .avPick').forEach((x) => x.classList.remove('on'));
          $('#lgPreview').innerHTML = meAvatarOf(p, 62);
        } else {
          saveProfile({ name: meName(), av: p.av | 0, img: p.img });
          S.edit = '';
          render();
        }
      };
      fr.readAsDataURL(f);
    };
  });
  document.querySelectorAll('[data-login]').forEach((b) => {
    b.onclick = () => {
      const p = S.login || { name: '', av: 0, img: '' };
      const nm = (p.name || '').trim() || '无名的人';
      saveProfile({ name: nm.slice(0, 8), av: p.av | 0, img: p.img || '' });
      S.login = null;
      splash();
    };
  });
  document.querySelectorAll('[data-save-name]').forEach((b) => {
    b.onclick = () => {
      const v = (document.querySelector('#editName') || {}).value || '';
      const nm = v.trim().slice(0, 8);
      if (!nm) { alert('名字总得有一个'); return; }
      saveProfile({ name: nm, av: (S.profile || {}).av | 0, img: (S.profile || {}).img || '' });
      S.edit = '';
      render();
    };
  });
  document.querySelectorAll('[data-edit]').forEach((b) => {
    b.onclick = () => { S.edit = (b.dataset.edit === 'close') ? '' : b.dataset.edit; render(); };
  });
  document.querySelectorAll('[data-logout]').forEach((b) => {
    b.onclick = () => {
      try { localStorage.removeItem(PROFILE_KEY); } catch (e) {}
      location.reload();
    };
  });
  document.querySelectorAll('[data-answer]').forEach((b) => {
    b.onclick = () => answerCall();
  });
  document.querySelectorAll('[data-reject]').forEach((b) => {
    b.onclick = () => rejectCall();
  });
  document.querySelectorAll('[data-again]').forEach((b) => {
    b.onclick = () => { document.querySelector('.endmask')?.remove(); startGame(); };
  });
}

/* ------------------------------------------------ 桌面 */
function viewHome() {
  const apps = [
    { id: 'wechat', lb: '微信', color: '#07c160', ic: ICON.wechat, badge: unreadAll() },
    { id: 'phone', lb: '电话', color: '#42b154', ic: ICON.phone, badge: 0 },
    { id: 'sms', lb: '信息', color: '#4fbf61', ic: ICON.sms, badge: S.sms.filter((x) => !x.read).length },
    { id: 'notes', lb: '备忘录', color: '#f0b429', ic: '', ph: '≡' },
    { id: 'wallet', lb: '钱包', color: '#2f9e8f', ic: '', ph: '¥' },
    { id: 'photos', lb: '相册', color: '#6a7fa8', ic: '', ph: '◧' },
    { id: 'settings', lb: '设置', color: '#6e6e73', ic: '', ph: '⚙' }
  ];
  const cell = (a) => `
    <button class="app-i" data-go="${a.id}">
      <span class="icon" style="background:${a.color}">
        ${a.ic ? a.ic : `<span class="ph">${a.ph}</span>`}
        ${a.badge ? `<span class="badge">${a.badge > 99 ? '99+' : a.badge}</span>` : ''}
      </span>
      <span class="lb">${a.lb}</span>
    </button>`;
  return `
  <div class="home">
    <div class="homeClock">${S.time}</div>
    <div class="homeDate">第 ${S.day} 天 · ${dateOf(S.day)}</div>
    <div class="grid">${apps.map(cell).join('')}</div>
    <div class="homeFoot">第 ${S.day} 天 · 还有 ${Math.max(0, 90 - S.day)} 天</div>
  </div>`;
}

function loginScreen() {
  S.view = 'login';
  const cur = S.login || S.profile || { name: '', av: 0, img: '' };
  S.login = cur;
  $('#screen').classList.add('dark');
  $('#app').innerHTML = `
  <div class="home login">
    <div class="lgTop">
      <div class="lgSub">九 十 天</div>
      <h1>第一年</h1>
      <p>先给自己留个名字。<br>往后这一年，别人叫你的时候，用的就是它。</p>
    </div>
    <div class="lgCard">
      <div class="lgAv" id="lgPreview">${meAvatarOf(cur, 62)}</div>
      <input id="lgName" class="lgin" maxlength="8" autocomplete="off"
             placeholder="给自己起个名字" value="${esc(cur.name)}">
      <div class="avGrid" id="lgGrid">${avGridHtml(cur)}</div>
      <button class="rep go" data-login="1" style="width:100%;margin-top:12px;padding:12px 0">进入这座城</button>
    </div>
    <p class="lgFoot">人物与事件均为虚构</p>
  </div>`;
  bind();
}

function splash() {
  S.view = 'splash';
  $('#screen').classList.add('dark');
  $('#app').innerHTML = `
  <div class="home" style="justify-content:center;align-items:center;text-align:center;padding:0 30px">
    <div style="font-size:13px;letter-spacing:6px;color:#7d99a8">九 十 天</div>
    <h1 style="font-size:40px;font-weight:200;letter-spacing:6px;margin:16px 0 8px">第一年</h1>
    <p style="font-size:12.5px;color:#8fa3ae;line-height:2;margin:0">一座城，八千块。<br>这一年发生的事，都在手机里。</p>
    <div style="margin-top:26px;display:flex;align-items:center;gap:10px;justify-content:center">
      ${meAvatar(30)}
      <span style="font-size:13px;color:#9fb3bd">以「${esc(meName())}」的身份</span>
    </div>
    <button class="rep go" data-start="1" style="margin-top:20px;padding:11px 30px">开始</button>
    <p style="font-size:11px;color:#5f707a;margin-top:30px">人物与事件均为虚构</p>
    <p style="font-size:11px;color:#4a5a63;margin-top:14px"><span data-logout="1" style="cursor:pointer;text-decoration:underline">换个身份</span></p>
  </div>`;
  bind();
}

/* 登录页预览头像（用临时档案，不写 S.profile） */
function meAvatarOf(p, size) {
  if (p.img) return `<span class="avatar avimg" style="width:${size}px;height:${size}px;background-image:url('${p.img}')"></span>`;
  const a = AVS[(p.av | 0) % AVS.length];
  return `<span class="avatar" style="width:${size}px;height:${size}px;background:${a.bg};font-size:${Math.round(size * 0.48)}px">${a.e}</span>`;
}

/* ------------------------------------------------ 微信 */
function sessionsList() {
  const list = Object.keys(S.msgs)
    .map((id) => {
      const ms = S.msgs[id];
      const last = [...ms].reverse().find((m) => m.who !== 'sys' && m.who !== 'typing');
      return { id, last, n: ms.length, unread: S.unread[id] || 0 };
    })
    .filter((x) => x.last)
    .sort((a, b) => b.n - a.n);
  return list;
}

function viewWechat() {
  if (S.tab === 'contacts') return viewContacts();
  if (S.tab === 'me') return viewMe();
  const list = sessionsList().filter((x) => S.filter === '全部' || contact(x.id).group === S.filter);
  const rows = list.map((x) => {
    const c = contact(x.id);
    const txt = (x.last.text || '').replace(/\s+/g, ' ').slice(0, 26);
    return `
    <button class="sess" data-open="${c.id}">
      <span class="avatar" style="background:${c.color}">${esc(c.avatar)}</span>
      <span class="mid">
        <span class="nm">${esc(c.name)} <span class="tag">${esc(c.group)}</span></span>
        <span class="last">${x.last.who === 'me' ? '我：' : ''}${esc(txt)}</span>
      </span>
      <span class="right">
        <span>${esc(S.time)}</span>
        ${x.unread ? `<span class="dot">${x.unread}</span>` : ''}
      </span>
    </button>`;
  }).join('');
  return `
  <div class="wx">
    <div class="nav">微信${unreadAll() ? `（${unreadAll()}）` : ''}</div>
    <div class="search"><i>⌕</i> 搜索</div>
    <div class="filters">
      ${['全部', ...groups()].map((g) => `<button data-filter="${g}" class="${S.filter === g ? 'on' : ''}">${g}</button>`).join('')}
    </div>
    <div class="sessions">${rows || '<div class="empty">还没有消息。等等看。</div>'}</div>
    ${tabbar()}
  </div>`;
}

function viewContacts() {
  const body = groups().map((g) => {
    const cs = S.story.contacts.filter((c) => c.group === g);
    if (!cs.length) return '';
    return `<div class="groupHead">${g}</div>
      <div style="background:#fff">
      ${cs.map((c) => `
        <button class="sess" data-open="${c.id}">
          <span class="avatar" style="background:${c.color}">${esc(c.avatar)}</span>
          <span class="mid">
            <span class="nm">${esc(c.name)}</span>
            <span class="last">${esc(c.note || '')}</span>
          </span>
          ${(S.unread[c.id] || 0) ? `<span class="right"><span class="dot">${S.unread[c.id]}</span></span>` : ''}
        </button>`).join('')}
      </div>`;
  }).join('');
  return `
  <div class="wx">
    <div class="nav">通讯录</div>
    <div class="sessions" style="background:#f7f7f7">${body}</div>
    ${tabbar()}
  </div>`;
}

function viewMe() {
  const pct = (v) => Math.max(0, Math.min(100, v));
  return `
  <div class="wx">
    <div class="nav">我</div>
    <div class="app" style="padding-top:6px">
      <div class="card" style="display:flex;gap:13px;align-items:center">
        ${meAvatar(52)}
        <div style="flex:1">
          <div style="font-size:17px">${esc(meName())}</div>
          <div class="muted">二十二岁 · 刚毕业 · 第 ${S.day} 天</div>
        </div>
        <button class="mini" data-edit="name">改</button>
      </div>
      ${S.edit === 'name' ? `
      <div class="card">
        <div class="muted" style="margin-bottom:8px">改个名字，最多八个字</div>
        <input id="editName" class="lgin" maxlength="8" autocomplete="off" value="${esc(meName())}">
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="rep go" data-save-name="1">保存</button>
          <button class="rep" data-edit="close">算了</button>
        </div>
      </div>` : ''}
      ${S.edit === 'av' ? `
      <div class="card">
        <div class="muted" style="margin-bottom:8px">换张头像，也可以传自己的图</div>
        <div class="avGrid" id="meGrid">${avGridHtml(S.profile)}</div>
        <div style="margin-top:10px"><button class="rep" data-edit="close">收起</button></div>
      </div>` : ''}
      <div class="card">
        <div class="row"><span class="k">身上还有</span><span class="v">¥ ${S.money.toLocaleString('zh-CN')}</span></div>
        <div class="row"><span class="k">警惕</span><span class="v">${pct(S.alert)}</span></div>
        <div class="bar"><i style="width:${pct(S.alert)}%"></i></div>
        <div class="row" style="margin-top:8px"><span class="k">和人之间的信任</span><span class="v">${pct(S.trust)}</span></div>
        <div class="bar"><i style="width:${pct(S.trust)}%;background:#4a9edb"></i></div>
        <div class="row" style="margin-top:8px"><span class="k">变成他们</span><span class="v">${pct(S.blackout)}</span></div>
        <div class="bar"><i style="width:${pct(S.blackout)}%;background:#c25a4a"></i></div>
      </div>
      <div class="card">
        <div class="row"><span class="k">记下来的话</span><span class="v">${S.kept} 句</span></div>
        <div class="row"><span class="k">走过的天</span><span class="v">${S.day} / 90</span></div>
      </div>
      <div class="card">
        <button class="rowbtn" data-edit="name"><span class="k">名字</span><span class="v">${esc(meName())} ›</span></button>
        <button class="rowbtn" data-edit="av"><span class="k">头像</span><span class="v">换一张 ›</span></button>
        <button class="rowbtn" data-logout="1"><span class="k">退出登录</span><span class="v">›</span></button>
      </div>
    </div>
    ${tabbar()}
  </div>`;
}

function tabbar() {
  const b = unreadAll();
  return `<div class="tabs">
    <button data-tab="wx" class="${S.tab === 'wx' ? 'on' : ''}">微信${b ? `<b>${b}</b>` : ''}</button>
    <button data-tab="contacts" class="${S.tab === 'contacts' ? 'on' : ''}">通讯录</button>
    <button data-tab="me" class="${S.tab === 'me' ? 'on' : ''}">我</button>
  </div>`;
}

/* ------------------------------------------------ 聊天 */
function viewChat() {
  const c = contact(S.chatWith);
  const ms = S.msgs[c.id] || [];
  const bubbles = ms.map((m) => {
    if (m.who === 'sys') return `<div class="sys ${m.kind || ''}">${esc(m.text)}</div>`;
    if (m.who === 'typing') return `<div class="typing"><span class="avatar" style="background:${c.color}">${esc(c.avatar)}</span><span class="dots"><span></span><span></span><span></span></span></div>`;
    const cls = m.who === 'me' ? 'me' : '';
    return `<div class="msg ${cls} ${m.fresh ? 'new' : ''}">
      ${m.who === 'me' ? meAvatar(34) : `<span class="avatar" style="background:${c.color}">${esc(c.avatar)}</span>`}
      <div class="bub">${esc(m.text)}</div>
    </div>`;
  }).join('');

  let replies = '';
  if (S.ev && S.contact === c.id && !S.busy && S.idx >= 0 && S.steps[S.idx] && S.steps[S.idx].event === S.ev.id && S.replyStage === 'act') {
    replies = `<div class="replies">${S.ev.actions.map((a) => `<button class="rep" data-rep="${esc(a.label)}">${esc(a.label)}</button>`).join('')}</div>`;
  }
  if (S.replyStage === 'settle' && S.contact === c.id) {
    replies = `<div class="replies">
      ${S.lastResult === 'pit' ? `<button class="rep keep" data-keep="1">这句话记下了</button>` : ''}
      <button class="rep go" data-next="1">${S.idx >= S.steps.length - 1 ? '过完这一年' : '继续'}</button>
    </div>`;
  }

  return `
  <div class="chat">
    <div class="chatNav">
      <button class="back" data-go="wechat">‹</button>
      
      <div>
        <div class="t">${esc(c.name)}</div>
        <div class="s">${esc(c.group)}${S.ev && S.contact === c.id ? ' · ' + esc(S.ev.scene) : ''}</div>
      </div>
    </div>
    <div class="msgs">${bubbles || '<div class="empty">还没有消息</div>'}</div>
    ${replies}
    <div class="inputbar">
      <input id="typin" class="realin" autocomplete="off" value="${esc(S.draft || '')}"
             placeholder="${replies ? '点上面的句子，或者自己打字' : '自己打字也可以'}">
      <button class="sendbtn" data-send="1">发送</button>
    </div>
  </div>`;
}

function openChat(id) {
  S.chatWith = id;
  S.draft = '';
  S.unread[id] = 0;
  S.toast = null;
  S.view = 'chat';
  render();
}

/* ------------------------------------------------ 其它 App */
function viewSms() {
  const items = S.sms.map((s) => `
    <div class="smsItem">
      <div class="h"><b>${esc(s.title)}</b><span>第 ${s.day} 天</span></div>
      <div class="t">${esc(s.text)}</div>
    </div>`).join('');
  S.sms.forEach((s) => { s.read = true; });
  return `<div class="app">
    <h1>信息</h1>
    <div class="card">${items || '<div class="muted">没有新短信</div>'}</div>
    <div class="muted">银行的、验证码的、催缴的，都会落在这里。</div>
  </div>`;
}

function viewPhone() {
  const items = S.calls.slice().reverse().map((c) => `
    <div class="row"><span class="k">${esc(c.name)} <span class="tag">${esc(c.kind || '来电')}</span></span><span class="v">第 ${c.day} 天 ${esc(c.time || '')}</span></div>`).join('');
  return `<div class="app">
    <h1>电话</h1>
    <div class="card">${items || '<div class="muted">还没有通话记录</div>'}</div>
    <div class="muted">陌生号码打来的时候，先想一秒：他为什么知道你的名字。</div>
  </div>`;
}

function viewNotes() {
  const items = S.notes.map((n) => `
    <div class="todo ${n.done ? 'done' : ''}"><span class="check"></span><span>${esc(n.text)}</span></div>`).join('');
  return `<div class="app">
    <h1>备忘录</h1>
    <div class="card">${items || '<div class="muted">空的</div>'}</div>
  </div>`;
}

function viewWallet() {
  const rows = S.ledger.slice().reverse().map((l) => `
    <div class="row"><span class="k">${esc(l.label)}</span>
      <span class="v" style="color:${l.amount > 0 ? '#2f8a5b' : '#c25a4a'}">${l.amount > 0 ? '+' : ''}${l.amount.toLocaleString('zh-CN')}</span></div>`).join('');
  return `<div class="app">
    <h1>钱包</h1>
    <div class="card">
      <div class="muted">余额</div>
      <div class="money">¥ ${S.money.toLocaleString('zh-CN')}</div>
      <div class="muted">第 ${S.day} 天 · 一共 90 天</div>
    </div>
    <div class="card">${rows || '<div class="muted">还没有流水</div>'}</div>
  </div>`;
}

function viewPhotos() {
  const shots = [
    { day: 1, cap: '出站口，天刚亮', bg: 'linear-gradient(160deg,#2b3a4a,#101820)' },
    { day: 6, cap: '中介说的「刚出的好房」', bg: 'linear-gradient(160deg,#4a4030,#1a1712)' },
    { day: 18, cap: '面试的那栋楼', bg: 'linear-gradient(160deg,#3a4658,#141a22)' },
    { day: 46, cap: '和小哲吃的那顿', bg: 'linear-gradient(160deg,#5a3f3a,#201514)' },
    { day: 76, cap: '搬走的早上', bg: 'linear-gradient(160deg,#3d4a3a,#121810)' },
    { day: 90, cap: '这一年的最后一天', bg: 'linear-gradient(160deg,#556070,#1a2028)' }
  ].filter((s) => s.day <= S.day);
  const cells = shots.map((s) => `<div class="photo" style="background:${s.bg}">${esc(s.cap)}</div>`).join('');
  return `<div class="app">
    <h1>相册</h1>
    <div class="grid3">${cells}</div>
  </div>`;
}

function viewSettings() {
  return `<div class="app">
    <h1>设置</h1>
    <div class="card">
      <div class="row"><span class="k">这一局</span><span class="v">第 ${S.day} 天</span></div>
      <div class="row"><span class="k">踩过的坑</span><span class="v">${S.log.filter((x) => x.result === 'pit').length} 次</span></div>
      <div class="row"><span class="k">版本</span><span class="v">手机界面版 v2</span></div>
    </div>
    <div class="card">
      <div class="muted">人物和事件是虚构的。真遇到事，打 12315、12345，或找当地住建部门、劳动监察。</div>
    </div>
  </div>`;
}

/* ------------------------------------------------ 剧情推进 */
function push(cid, who, text, extra) {
  if (!S.msgs[cid]) S.msgs[cid] = [];
  S.msgs[cid].push({ who, text, seq: S.seq++, ...(extra || {}) });
}

function lastEventFor(cid) {
  const step = S.steps[S.idx];
  return step && step.contact === cid ? S.map[step.event] : null;
}

async function nextStep() {
  S.idx++;
  if (S.idx >= S.steps.length) return finish();
  const step = S.steps[S.idx];
  const ev = S.map[step.event];
  S.ev = ev;
  S.contact = step.contact;
  S.beat = 0;
  S.day = step.day;
  S.time = step.time || '10:00';
  S.replyStage = '';
  S.lastResult = '';

  // 每一步都先回到桌面：消息到了，自己点开
  S.chatWith = step.contact;
  S.toast = null;
  if (contact(step.contact).kind !== 'call') S.view = 'home';

  // 前情：固定旁白 + 有条件的旁白
  const bridge = pickBridge(step);
  push(step.contact, 'sys', `第 ${step.day} 天 · ${S.time}`);
  push(step.contact, 'sys', bridge);

  // 短信的伏笔：验证码、分期生效
  if (step.event === 'kefu') {
    addSms('服务号', '【平台安全】验证码 631428，5 分钟内有效。任何人索要都不要给。');
  }
  if (step.event === 'credit' && S.flags.includes('loan_signed')) {
    addSms('分期平台', '您的租金分期已还 1 期，剩余 23 期，每期 1,250 元。');
  }
  updateNotes(step.event, null);

  render();
  const c = contact(step.contact);
  if (c.kind === 'call') {
    showCall(c);
  } else {
    await deliverOpening(step, ev);
  }
}

function pickBridge(step) {
  if (step.bridge_if) {
    for (const k of Object.keys(step.bridge_if)) {
      if (S.flags.includes(k)) return step.bridge_if[k];
    }
  }
  return step.bridge || '';
}

function addSms(title, text) {
  S.sms.unshift({ title, text, day: S.day, read: false });
}

function updateNotes(evId, result) {
  const map = {
    rent_agent: '看房：问清定金退不退、中介费多少',
    contract: '签合同前：逐条看完，特别是那个 App',
    job_small: '面试：社保从哪个月开始缴',
    kefu: '任何要验证码的电话，一律挂掉',
    credit: '征信只在央行征信中心查',
    overseas: '不说公司全名的招工，不去',
    checkout: '退租：当场验收，扣款要书面'
  };
  if (map[evId] && !S.notes.some((n) => n.text === map[evId])) {
    S.notes.push({ text: map[evId], done: result === 'good' });
  }
}

async function fetchOpen(ev) {
  // 开场这句由模型现场说；模型不可用时才退回剧本里的那句话
  try {
    const r = await fetch('/api/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: ev.id, state: snap() })
    });
    const d = await r.json();
    return (d.reply || '').trim() || ev.opening;
  } catch (e) {
    return ev.opening;
  }
}

async function deliverOpening(step, ev) {
  const cid = step.contact;
  push(cid, 'typing', '');
  render();
  const line = await fetchOpen(ev);
  await sleep(450);
  const i = S.msgs[cid].findIndex((m) => m.who === 'typing');
  if (i >= 0) S.msgs[cid].splice(i, 1);
  push(cid, 'them', line, { fresh: true });
  S.replyStage = 'act';
  if (S.view !== 'chat' || S.chatWith !== cid) {
    S.unread[cid] = (S.unread[cid] || 0) + 1;
    S.toast = { cid, text: line };
    const mine = cid;
    setTimeout(() => {
      if (S.toast && S.toast.cid === mine) { S.toast = null; render(); }
    }, 4200);
  }
  render();
  markRead();
}

function markRead() {
  S.msgs[S.chatWith]?.forEach((m) => { m.fresh = false; });
}

/* ------------------------------------------------ 来电 */
function showCall(c) {
  const app = $('#app');
  app.insertAdjacentHTML('beforeend', `
    <div class="callmask">
      <div class="cav" style="background:${c.color}">${esc(c.avatar)}</div>
      <div class="cname">${esc(c.name)}</div>
      <div class="cnum">${esc(c.id === 'kefu' ? '400-6351 · 未知机构' : c.id === 'credit' ? '未知号码 · 归属地不明' : '陌生来电')}</div>
      <div class="hintx">第 ${S.day} 天 · ${S.time}</div>
      <div class="btns">
        <button class="cbtn end" data-reject="1">拒接</button>
        <button class="cbtn ans" data-answer="1">接听</button>
      </div>
    </div>`);
  bind();
  S.callPending = c;
}

async function answerCall() {
  const c = S.callPending;
  document.querySelector('.callmask')?.remove();
  S.calls.push({ name: c.name, day: S.day, time: S.time, kind: '已接' });
  S.chatWith = c.id;
  S.unread[c.id] = 0;
  S.view = 'chat';
  render();
  await deliverOpening(S.steps[S.idx], S.map[S.steps[S.idx].event]);
}

async function rejectCall() {
  const c = S.callPending;
  document.querySelector('.callmask')?.remove();
  S.calls.push({ name: c.name, day: S.day, time: S.time, kind: '已拒接' });
  push(c.id, 'sys', '你挂了。三十秒后，同一个号码又打进来。');
  render();
  await sleep(1100);
  showCall(c);
}

/* ------------------------------------------------ 回复 */
function sendTyped() {
  const inp = document.querySelector('#typin');
  if (!inp || S.busy || S.replyStage !== 'act') return;
  const v = (inp.value || S.draft || '').trim();
  if (!v) return;
  inp.value = '';
  S.draft = '';
  choose(v, true);
}

async function choose(label, typed) {
  if (S.busy) return;
  S.busy = true;
  S.replyStage = '';
  push(S.chatWith, 'me', label, { fresh: true });
  push(S.chatWith, 'typing', '');
  render();

  const hist = (S.msgs[S.chatWith] || [])
    .filter((m) => m.who === 'me' || m.who === 'them')
    .map((m) => ({ who: m.who === 'me' ? 'player' : 'them', text: m.text }))
    .slice(-8);

  let reply = '……';
  try {
    const r = await fetch('/api/talk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: S.ev.id, beat: S.beat, text: label, history: hist, state: snap() })
    });
    const d = await r.json();
    reply = d.reply || '……';
  } catch (e) { /* 走兜底 */ }

  await sleep(560);
  const arr = S.msgs[S.chatWith];
  const i = arr.findIndex((m) => m.who === 'typing');
  if (i >= 0) arr.splice(i, 1);
  push(S.chatWith, 'them', reply, { fresh: true });
  S.beat++;
  S.busy = false;
  markRead();

  if (S.beat >= 5) return settle(label, typed);
  S.replyStage = 'act';
  render();
  markRead();
}

function snap() {
  return { day: S.day, money: S.money, trust: S.trust, alert: S.alert, blackout: S.blackout, kept: S.kept, flags: S.flags.slice() };
}

async function mapAction(label) {
  if (!S.ev) return label;
  if (S.ev.actions.some((a) => a.label === label)) return label;
  try {
    const r = await fetch('/api/judge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: S.ev.id, text: label })
    });
    const d = await r.json();
    if (d.label) return d.label;
  } catch (e) { /* 归不了类就当没选 */ }
  return label;
}

async function settle(label) {
  const act = await mapAction(label);
  if (act !== label) push(S.contact, 'sys', '〔按「' + act + '」结算〕');
  let d = null;
  const before = S.money;
  try {
    const r = await fetch('/api/settle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: S.ev.id, action: act, state: snap() })
    });
    d = await r.json();
  } catch (e) { /* 忽略 */ }

  if (d && d.state) {
    S.money = d.state.money;
    S.trust = d.state.trust;
    S.alert = d.state.alert;
    S.blackout = d.state.blackout;
    S.flags = d.state.flags || S.flags;
  }
  const result = (d && d.result) || 'neutral';
  S.lastResult = result;
  S.log.push({ event: S.ev.id, action: act, result });

  if (S.money !== before) {
    S.ledger.push({ label: `${S.ev.scene} · ${act}`, amount: S.money - before });
  }
  if (result === 'pit') {
    push(S.contact, 'sys', '〔这句话你记住了〕', { kind: 'pit' });
    updateNotes(S.ev.id, 'pit');
    if (S.flags.includes('loan_signed')) addSms('分期平台', '您的租金分期已生效，共 24 期，每期 1,250 元，逾期将上报征信。');
    if (S.flags.includes('scammed_code')) addSms('银行', `您尾号 3847 的账户转出 ${Math.abs(S.money - before).toLocaleString('zh-CN')} 元，余额 ${S.money.toLocaleString('zh-CN')} 元。`);
  } else if (result === 'good') {
    push(S.contact, 'sys', '〔这一关你躲过去了〕', { kind: 'good' });
    updateNotes(S.ev.id, 'good');
  }

  S.replyStage = 'settle';
  render();
}

/* ------------------------------------------------ 结局 */
async function finish() {
  let data = null;
  try {
    const r = await fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: snap(), log: S.log })
    });
    data = await r.json();
  } catch (e) { /* 忽略 */ }

  const ending = (data && data.ending) || { title: '结束', line: '这一年过完了。' };
  const hits = (data && data.pits_hit) || [];
  const all = Object.values(S.msgs).flat()
    .filter((m) => m.who === 'me' || m.who === 'them')
    .sort((a, b) => a.seq - b.seq);
  const firstLine = all.find((m) => m.who === 'them');
  const lastMine = [...all].reverse().find((m) => m.who === 'me');

  S.over = true;
  S.view = 'ending';
  S.time = '23:58';
  setStatus();
  $('#app').innerHTML = `
    <div class="endmask">
      <div class="tag2">第 ${Math.min(S.day, 90)} 天</div>
      <h2>${esc(ending.title)}</h2>
      <div class="line">${esc(ending.line)}</div>
      ${firstLine ? `<div class="q">「${esc(firstLine.text)}」<br><span style="opacity:.5">九十天前，有人对你说的</span></div>` : ''}
      ${lastMine ? `<div class="q">「${esc(lastMine.text)}」<br><span style="opacity:.5">今天，你说出去的</span></div>` : ''}
      <div class="stats">
        <div><b>${data ? data.score : 0}</b>分</div>
        <div><b>¥${S.money.toLocaleString('zh-CN')}</b>剩下的钱</div>
        <div><b>${hits.length}</b>踩的坑</div>
      </div>
      ${hits.length ? `<ul>${hits.map((h) => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}
      <button class="again" data-again="1">重来一次</button>
    </div>`;
  bind();
}

boot();
