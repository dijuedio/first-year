// 从真实 app.js 里抽出 push / choose 跑，验证串台是否被挡住
import fs from 'fs';
import vm from 'vm';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(ROOT, 'static/app.js'), 'utf8');

function cutFn(name) {
  const lines = src.split('\n');
  const start = lines.findIndex((l) => l.startsWith(`function ${name}(`) || l.startsWith(`async function ${name}(`));
  if (start < 0) throw new Error('找不到函数 ' + name);
  let end = start;
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i] === '}') { end = i; break; }
  }
  return lines.slice(start, end + 1).join('\n');
}

const pushSrc = cutFn('push');
const chooseSrc = cutFn('choose');
console.log('--- 抽到的 choose 头几行 ---');
console.log(chooseSrc.split('\n').slice(0, 8).join('\n'));

function makeCtx(S, calls) {
  const ctx = {
    S,
    calls,
    esc: (s) => String(s == null ? '' : s),
    render: () => {},
    markRead: () => {},
    sleep: async () => {},
    snap: () => ({}),
    settle: async () => { calls.push('SETTLE'); },
    saveSoon: () => {}, saveNow: async () => {}, api: async () => ({ ok: true, data: {} }),
    authToken: () => '', finish: async () => {},
    fetch: async (url, opt) => {
      calls.push(JSON.parse(opt.body));
      return { json: async () => ({ reply: '（模型回话）' }) };
    },
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(pushSrc + '\n' + chooseSrc, ctx);
  return ctx;
}

function freshS(ev, contact) {
  return {
    msgs: {}, unread: {}, seq: 0, busy: false, replyStage: 'act', beat: 0,
    ev, contact, chatWith: contact, draft: '', log: [], idx: 3,
  };
}

// ---------- 场景 1：同一个人（妈）跨两场，历史不能带上一场 ----------
{
  const S = freshS({ id: 'mom_arrive', actions: [] }, 'mom');
  const calls = [];
  const ctx = makeCtx(S, calls);
  ctx.push('mom', 'them', '【第一场·到站】到了就快出去吧');
  ctx.push('mom', 'me', '【第一场】我知道了');
  // 切到第二场
  S.ev = { id: 'mom_money', actions: [] };
  S.beat = 0;
  S.replyStage = 'act';
  ctx.push('mom', 'sys', '第 38 天 · 20:15');
  ctx.push('mom', 'them', '【第二场】你最近钱够不够');
  await ctx.choose('够用，你别担心', true);

  const sent = calls.find((c) => c && c.history);
  console.log('\n场景1 发给模型的 history：', JSON.stringify(sent && sent.history, null, 0));
  const leak = (sent.history || []).some((h) => h.text.includes('第一场'));
  console.log('场景1 判定：', leak ? '❌ 仍串台' : '✅ 只含本场，未串');

  const sent2 = calls.find((c) => c && c.event_id);
  console.log('   event_id =', sent2 && sent2.event_id, '| beat =', sent2 && sent2.beat);
}

// ---------- 场景 2：在别人的窗口打字，不能推进这一场 ----------
{
  const S = freshS({ id: 'mom_money', actions: [] }, 'mom');
  S.chatWith = 'zhe'; // 玩家点开阿哲的聊天窗
  const calls = [];
  const ctx = makeCtx(S, calls);
  ctx.push('mom', 'them', '你最近钱够不够');
  const beforeBeat = S.beat;
  const beforeLen = (S.msgs['zhe'] || []).length;
  await ctx.choose('随便说点什么', true);

  console.log('\n场景2 判定：', calls.length === 0 && S.beat === beforeBeat
    ? '✅ 未发请求、未推进 beat'
    : '❌ 仍被推进 (requests=' + calls.length + ', beat=' + S.beat + ')');
  console.log('   阿哲窗口消息数：', beforeLen, '->', (S.msgs['zhe'] || []).length,
    '| busy =', S.busy);
}

// ---------- 场景 3：正常在本人窗口推进，仍然要通 ----------
{
  const S = freshS({ id: 'mom_money', actions: [] }, 'mom');
  const calls = [];
  const ctx = makeCtx(S, calls);
  ctx.push('mom', 'them', '你最近钱够不够');
  await ctx.choose('够用，你别担心', true);
  const sent = calls.find((c) => c && c.event_id);
  console.log('\n场景3 判定：', sent && S.beat === 1
    ? '✅ 正常推进，history ' + sent.history.length + ' 条，回话已入窗'
    : '❌ 正常路径被误伤');
  console.log('   窗内最后一条：', (S.msgs['mom'] || []).slice(-1)[0]);
}
