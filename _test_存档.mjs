// 从真实 app.js 抽出 packSave / unpackSave，验证存档往返
import fs from 'fs';
import vm from 'vm';

import path from 'path';
import { fileURLToPath } from 'url';
const ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(ROOT, 'static/app.js');
const src = fs.readFileSync(SRC, 'utf8');
const story = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/story.json'), 'utf8'));
const evData = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/events.json'), 'utf8'));
const steps = story.order;
const map = {};
evData.events.forEach((e) => { map[e.id] = e; });

function cutFn(name) {
  const lines = src.split('\n');
  const start = lines.findIndex((l) => l.startsWith(`function ${name}(`));
  if (start < 0) throw new Error('找不到 ' + name);
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i] === '}') return lines.slice(start, i + 1).join('\n');
  }
  throw new Error('没找到结尾 ' + name);
}

const S = {
  idx: 7, beat: 2, day: 38, time: '20:15', over: false,
  money: 6200, trust: 48, alert: 62, blackout: 10, kept: 1,
  flags: ['loan_signed'], seq: 3, replyStage: 'act', lastResult: 'pit', tab: 'wx', filter: '全部',
  msgs: {
    mom: [
      { who: 'sys', text: '第 38 天 · 20:15', seq: 0, ev: 'mom_money' },
      { who: 'them', text: '你最近钱够不够', seq: 1, ev: 'mom_money' },
      { who: 'me', text: '够用', seq: 2, ev: 'mom_money' },
      { who: 'typing', text: '', seq: 3, ev: 'mom_money' },
    ],
    zhe: [{ who: 'them', text: '来吃饭', seq: 0, ev: 'laoxiang' }],
    empty: [],
  },
  unread: { mom: 1 }, calls: [{ name: '老周', day: 12 }], sms: [{ title: '银行', text: 'x' }],
  notes: [{ text: '找住处', done: false }], ledger: [{ label: '看房', amount: -300 }],
  log: [{ event: 'contract', action: '签字', result: 'pit' }],
};

const ctx = vm.createContext({ S, console });
vm.runInContext(cutFn('packSave') + '\n' + cutFn('unpackSave'), ctx);

const pack = ctx.packSave();
let ok = 0, bad = 0;
const ck = (n, c, x) => { c ? (ok++, console.log('  ✓', n, x || '')) : (bad++, console.log('  ✗', n, x || '')); };

ck('typing 占位符不进存档', !(pack.msgs.mom || []).some((m) => m.who === 'typing'),
  '条数 ' + pack.msgs.mom.length);
ck('空数组被省掉', !('empty' in pack.msgs));
ck('关键字段都在', pack.idx === 7 && pack.money === 6200 && pack.flags[0] === 'loan_signed'
  && pack.replyStage === 'act' && pack.log.length === 1);
ck('打包体积小', JSON.stringify(pack).length < 4000, JSON.stringify(pack).length + ' 字节');

const r = ctx.unpackSave(pack, steps, map);
ck('idx/beat/day 一致', r.idx === 7 && r.beat === 2 && r.day === 38);
ck('事件由 idx 推回来', r.ev && r.ev.id === steps[7].event, 'ev=' + (r.ev && r.ev.id));
ck('联系人由 idx 推回来', r.contact === steps[7].contact, 'contact=' + r.contact);
ck('聊天窗开在当事人', r.chatWith === r.contact);
ck('钱和 flags 一致', r.money === 6200 && r.flags.includes('loan_signed'));
ck('消息按联系人还原', (r.msgs.mom || []).length === 3 && (r.msgs.zhe || []).length === 1);
ck('busy 归零、不回放 toast', r.busy === false && r.toast === null);

// 空档 / 越界不崩
const r2 = ctx.unpackSave({ idx: 999 }, steps, map);
ck('idx 越界不崩，退回桌面', r2.ev === null && r2.contact === null);
const r3 = ctx.unpackSave({}, steps, map);
ck('空对象也有默认值', r3.day === 1 && r3.money === 0 && Array.isArray(r3.flags) && r3.flags.length === 0);

// 二次往返：存→读→存 应稳定
const S2 = Object.assign({}, S, r);
Object.assign(S, r);
const pack2 = ctx.packSave();
ck('二次保存不漂移', pack2.idx === 7 && pack2.beat === 2 && pack2.money === 6200);

console.log(`\n通过 ${ok} 条，失败 ${bad} 条`);
