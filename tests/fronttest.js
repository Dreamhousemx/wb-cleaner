/* 前端渲染逻辑测试。
 *
 * 在 Node 里用一个最小 DOM 桩跑真实的 web/app.js，对每个视图调用 renderAll()，
 * 断言「渲染出来的确实是这个视图」——而不是掉进兜底分支又渲染了一遍概览。
 *
 * 为什么需要它：曾经给 app.js 加 deepseek 视图时，VIEWS / 侧栏 / 概览表格都改了，
 * 唯独漏了 renderAll 里 switch 的一个 case，点击后界面毫无反应；
 * 而当时只有『源码里出现过 deepseek 字样』这种静态检查，根本抓不到。
 *
 * 用法： node tests/fronttest.js [fixture.json]
 *   无 fixture 时用内置的最小数据自测。
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.dirname(__dirname);
const APP = path.join(ROOT, 'web', 'app.js');

const PASS = [];
const FAIL = [];

function check(name, cond, detail) {
  (cond ? PASS : FAIL).push(name);
  console.log(`${cond ? '  PASS' : '  FAIL'} ${name}${cond ? '' : '  ' + (detail || '')}`);
}

/* ---------------------------------------------------------------- DOM 桩 */

function makeEl(id) {
  const el = {
    id,
    innerHTML: '',
    textContent: '',
    className: '',
    value: '',
    disabled: false,
    style: {},
    dataset: {},
    children: [],
    scrollTop: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelectorAll: () => [],
    querySelector: () => makeEl(id + '-child'),
    appendChild() {},
    remove() {},
    focus() {},
    get lastChild() { return { click() {} }; },
  };
  return el;
}

const els = {};
const document = {
  getElementById(id) {
    if (!els[id]) els[id] = makeEl(id);
    return els[id];
  },
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

const sandbox = {
  document,
  console,
  JSON, Date, Math, Number, String, Array, Object, Boolean, RegExp, Error,
  URLSearchParams,
  setTimeout, clearTimeout,
  localStorage: { getItem: () => null, setItem() {} },
  location: { hash: '', port: '8791', search: '?t=test' },
  history: { replaceState() {} },
  fetch: () => Promise.reject(new Error('测试环境不发请求')),
  EventSource: function EventSource() { this.close = () => {}; },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

/* ---------------------------------------------------------------- 载入 app.js */

let code = fs.readFileSync(APP, 'utf8');
// 去掉文件末尾自启动的 main()，我们要自己控制调用时机
const bootAt = code.indexOf('(async function main()');
if (bootAt < 0) {
  console.log('  FAIL 找不到 app.js 的启动函数，测试脚本需要同步更新');
  process.exit(1);
}
code = code.slice(0, bootAt);
// 顶层 const 不会挂到全局对象上，这里在同一个脚本作用域里追加一行导出，供测试调用。
// （不改生产代码，测试自己补这一行。）
code += '\n;window.__exp = { S, VIEWS, GROUP_VIEWS, renderAll, goto, viewGroup };';

vm.createContext(sandbox);
try {
  vm.runInContext(code, sandbox, { filename: 'app.js' });
} catch (err) {
  console.log('  FAIL 载入 app.js 失败：' + err.message);
  process.exit(1);
}

/* ---------------------------------------------------------------- 数据 */

function fixture() {
  if (process.argv[2] && fs.existsSync(process.argv[2])) {
    return JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  }
  const item = (rid, title, level, extra) => Object.assign({
    rid, group: 'deepseek', title, level,
    levelLabel: { safe: '安全', caution: '注意', danger: '危险', keep: '保护' }[level],
    kind: 'contents', action: '', size: 1024, sizeHuman: '1 KB', files: 3, count: 1,
    targets: ['~/.dsh/x'], targetsMore: 0, desc: title + ' 说明', impact: title + ' 影响',
    minAgeDays: 0, defaultOn: level === 'safe', actionable: level !== 'keep',
    note: '', requiresAdmin: false, freesSpace: true, protected: level === 'keep',
  }, extra || {});
  const mk = (key, title) => ({
    key, title, total: 2048, totalHuman: '2 KB',
    safe: 1024, caution: 0, danger: 0, safeHuman: '1 KB',
    cautionHuman: '0 B', dangerHuman: '0 B',
    items: [item(key + '-a', key + ' 缓存', 'safe'), item(key + '-b', key + ' 备份', 'caution')],
    defaultRids: [key + '-a'],
  });
  return {
    workbuddy: mk('workbuddy', '1. WorkBuddy 文件清理'),
    codex: mk('codex', '2. Codex 文件清理'),
    deepseek: mk('deepseek', '3. DeepSeek Harness 文件清理'),
    system: mk('system', '4. C 盘无用文件清理（系统级）'),
  };
}

const EXP = sandbox.__exp;
if (!EXP) {
  console.log('  FAIL app.js 没有导出内部符号，测试脚本需要同步更新');
  process.exit(1);
}

const groups = fixture();
EXP.S.groups = groups;
EXP.S.env = {
  version: '1.0.0', user: 'tester', admin: true, python: '3.13',
  disk: { free: 1e11, total: 2e11, used: 1e11, freeHuman: '93 GB',
          totalHuman: '186 GB', usedHuman: '93 GB', usedPct: 50 },
  dism: null, trash: [], trashTotal: 0, trashTotalHuman: '0 B',
};
EXP.S.days = '';
EXP.S.permanent = false;
EXP.S.filter = 'all';
EXP.S.sel = new Set();
EXP.S.expanded = new Set();

/* ---------------------------------------------------------------- 测试 */

console.log('\n[1] 每个视图都要渲染出「自己」的内容');
const content = document.getElementById('content');

// 分组视图的期望值从数据里推导（而不是写死），这样真实扫描结果和合成数据都能用
function expectFor(view) {
  if (!EXP.GROUP_VIEWS.includes(view)) {
    return {
      winsxs: ['WinSxS 组件存储'],
      trash: ['隔离区'],
      protected: ['保护名单'],
      overview: ['三大清理功能'],
    }[view];
  }
  const g = groups[view];
  if (!g) return null;
  const marks = [g.title.replace(/^\d+\.\s*/, '')];
  if (g.items && g.items.length) marks.push(g.items[0].title);
  return marks;
}

// 概览独有的标记：分组视图里出现它，说明掉进了兜底分支
const OVERVIEW_MARK = '三大清理功能';

const views = EXP.VIEWS;
check('VIEWS 已导出且非空', Array.isArray(views) && views.length >= 5, String(views));

for (const view of views) {
  const want = expectFor(view);
  if (!want) {
    check(`视图 ${view} 在测试里有预期标记`, false, '数据里没有这个分组');
    continue;
  }
  EXP.S.view = view;
  let err = null;
  try {
    EXP.renderAll();
  } catch (e) {
    err = e;
  }
  const html = content.innerHTML || '';
  if (err) {
    check(`渲染 ${view} 不报错`, false, err.message);
    continue;
  }
  const missing = want.filter((w) => !html.includes(w));
  check(`渲染 ${view} 内容正确`, missing.length === 0,
        missing.length ? `缺少 ${JSON.stringify(missing)}` : '');
  if (view !== 'overview') {
    check(`渲染 ${view} 没有掉进概览兜底`,
          !html.includes(OVERVIEW_MARK), '内容里出现了概览标记');
  }
}

console.log('\n[2] 分组视图清单与渲染分支一致（防漏项回归）');
const gv = EXP.GROUP_VIEWS;
check('GROUP_VIEWS 已导出', Array.isArray(gv), String(gv));
for (const v of gv) {
  EXP.S.view = v;
  content.innerHTML = '';
  EXP.renderAll();
  const html = content.innerHTML || '';
  check(`点击「${v}」会切到该分组（而不是原样重渲染概览）`,
        html.includes(groups[v].title.replace(/^\d+\.\s*/, '')), html.slice(0, 60));
}
check('每个分组视图都在 VIEWS 里',
      gv.every((v) => views.includes(v)), `${gv} vs ${views}`);

console.log('\n[3] 侧栏 / 概览按钮走的是同一条跳转路径');
// 侧栏不依赖渲染结果，这里直接验证 goto() 生效
EXP.S.view = 'overview';
EXP.goto('deepseek');
check('goto("deepseek") 切换了视图', EXP.S.view === 'deepseek', EXP.S.view);
const dsMark = expectFor('deepseek')[0];
check('goto("deepseek") 渲染了分组内容',
      (content.innerHTML || '').includes(dsMark), (content.innerHTML || '').slice(0, 60));
EXP.goto('不存在的视图');
check('goto(未知视图) 回退到概览', EXP.S.view === 'overview', EXP.S.view);

console.log('\n[4] 概览里的按钮都带 data-goto 且指向真实视图');
EXP.S.view = 'overview';
EXP.renderAll();
const overviewHtml = content.innerHTML || '';
const gotos = [...overviewHtml.matchAll(/data-goto="([^"]+)"/g)].map((m) => m[1]);
check('概览含 data-goto 按钮', gotos.length > 0, String(gotos));
check('data-goto 目标都是有效视图',
      gotos.every((g) => views.includes(g)),
      String(gotos.filter((g) => !views.includes(g))));

console.log('\n' + '='.repeat(56));
console.log(` 通过 ${PASS.length} 项，失败 ${FAIL.length} 项`);
if (FAIL.length) FAIL.forEach((f) => console.log('   失败：' + f));
console.log('='.repeat(56));
process.exit(FAIL.length ? 1 : 0);
