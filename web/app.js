/* ============================================================
   WBCleaner 可视化界面 —— 前端逻辑
   ============================================================ */

const TOKEN = new URLSearchParams(location.search).get('t') || '';

const S = {
  env: null,
  groups: {},          // key -> group payload
  rules: null,
  protectedList: null,
  sel: new Set(),      // 选中的 rid
  expanded: new Set(),
  days: '',
  permanent: false,
  filter: 'all',
  view: 'overview',
  scannedAt: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => (n || 0).toLocaleString('zh-CN');

/* ---------------------------------------------------------- API */

async function api(path, opts = {}) {
  const sep = path.includes('?') ? '&' : '?';
  const res = await fetch(`${path}${sep}t=${encodeURIComponent(TOKEN)}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败（${res.status}）`);
  return data;
}

function streamJob(jobId, onEvent) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const es = new EventSource(`/api/events?job=${jobId}&t=${encodeURIComponent(TOKEN)}`);
    const finish = (fn, v) => { if (!settled) { settled = true; es.close(); fn(v); } };
    es.onmessage = (ev) => {
      let d;
      try { d = JSON.parse(ev.data); } catch { return; }
      if (onEvent) onEvent(d);
      if (d.type === 'done') finish(resolve, d.result);
      if (d.type === 'error') finish(reject, new Error(d.message || '任务失败'));
    };
    es.addEventListener('end', () => finish(resolve, null));
    es.onerror = () => {
      if (settled) return;
      setTimeout(() => {
        if (!settled) finish(reject, new Error('与后台的连接中断'));
      }, 900);
    };
  });
}

/* ---------------------------------------------------------- 提示 */

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => el.remove(), kind === 'err' ? 7000 : 4200);
}

/* ---------------------------------------------------------- 日志抽屉 */

function logLine(level, text) {
  const body = $('drawerBody');
  const el = document.createElement('div');
  el.className = `l l-${level || 'info'}`;
  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  el.textContent = `${time}  ${text}`;
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
}

const drawer = {
  open(title) { $('drawerTitle').textContent = title; $('drawer').classList.add('open'); },
  close() { $('drawer').classList.remove('open'); },
  clear() { $('drawerBody').innerHTML = ''; },
};

/* ---------------------------------------------------------- 弹窗 */

function modal({ title, body, buttons, onOpen }) {
  $('modalTitle').textContent = title;
  $('modalBody').innerHTML = body;
  const foot = $('modalFoot');
  foot.innerHTML = '';
  (buttons || []).forEach((b) => {
    const el = document.createElement('button');
    el.className = `btn ${b.cls || 'btn-ghost'}`;
    el.textContent = b.label;
    el.disabled = !!b.disabled;
    el.onclick = () => b.onClick ? b.onClick(el) : closeModal();
    foot.appendChild(el);
  });
  $('modalMask').classList.add('on');
  if (onOpen) onOpen();
}

function closeModal() { $('modalMask').classList.remove('on'); }

/* ---------------------------------------------------------- 侧栏 / 顶栏 */

function renderSidebar() {
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === S.view);
  });
  document.querySelectorAll('.ni-size[data-size]').forEach((el) => {
    const g = S.groups[el.dataset.size];
    el.textContent = g ? g.totalHuman : '';
  });
  $('trashNavSize').textContent = S.env ? (S.env.trashTotal ? S.env.trashTotalHuman : '') : '';
}

function renderTitlebar() {
  const e = S.env;
  if (!e) return;
  const usedPct = e.disk.usedPct;
  $('diskText').textContent = `${e.disk.usedHuman} / ${e.disk.totalHuman} 已用 · 剩余 ${e.disk.freeHuman}`;
  const fill = $('diskFill');
  fill.style.width = `${usedPct}%`;
  fill.className = 'disk-fill' + (usedPct > 92 ? ' hot' : usedPct > 80 ? ' warn' : '');

  const pill = $('adminPill');
  if (e.admin) {
    pill.textContent = '● 管理员';
    pill.className = 'pill ok';
    pill.title = '已具备管理员权限，可执行 DISM 与系统级清理';
  } else {
    pill.textContent = '● 普通用户 · 点此提权';
    pill.className = 'pill no';
    pill.title = '系统级清理（WinSxS / 更新缓存 / 休眠文件）需要管理员权限，点击一键提权重启';
    pill.style.cursor = 'pointer';
    pill.onclick = elevate;
  }
}

function renderActionbar() {
  const show = ['overview', ...GROUP_VIEWS].includes(S.view);
  $('actionbar').classList.toggle('hide', !show);
  if (!show) return;

  const info = selInfo();
  $('selCount').textContent = `已选 ${info.count} 项`;
  $('selTotal').textContent = info.human;
  $('selTotal').classList.toggle('zero', info.count === 0);
  $('btnRun').disabled = info.count === 0 || S.busy;
  $('btnPreview').disabled = info.count === 0 || S.busy;

  const chip = $('modeChip');
  chip.textContent = S.permanent ? '永久删除（不可恢复）' : '隔离区（可还原）';
  chip.className = 'ab-mode' + (S.permanent ? ' perm' : '');
}

/* ---------------------------------------------------------- 选择集 */

function allItems() {
  return Object.values(S.groups).flatMap((g) => g.items);
}

function selInfo() {
  let bytes = 0, count = 0;
  allItems().forEach((it) => {
    if (S.sel.has(it.rid) && it.actionable) { bytes += it.size; count += 1; }
  });
  return { bytes, count, human: human(bytes) };
}

function human(n) {
  n = Number(n) || 0;
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i += 1; }
  return `${i === 0 ? n : n.toFixed(n >= 100 ? 0 : 2)} ${u[i]}`;
}

function applyRecommendation() {
  S.sel = new Set();
  Object.values(S.groups).forEach((g) => {
    g.items.forEach((it) => {
      if (it.defaultOn && it.actionable && !it.protected) S.sel.add(it.rid);
    });
  });
}

function toggle(rid) {
  const it = allItems().find((x) => x.rid === rid);
  if (!it || it.protected) return;
  if (!it.actionable && it.kind !== 'action') return;
  S.sel.has(rid) ? S.sel.delete(rid) : S.sel.add(rid);
}

/* ---------------------------------------------------------- 扫描 */

async function scan(silent = false) {
  if (S.busy) return;
  S.busy = true;
  $('btnScan').disabled = true;
  $('btnScan').innerHTML = '<span class="spin"></span>扫描中';
  $('scanProgress').classList.add('on');
  $('spText').textContent = '正在准备…';
  $('spFill').style.width = '2%';
  renderActionbar();

  try {
    const { job } = await api('/api/scan', {
      method: 'POST',
      body: JSON.stringify({ days: S.days || null }),
    });
    const result = await streamJob(job, (ev) => {
      if (ev.type === 'progress') {
        const total = ev.total || 1;
        $('spFill').style.width = `${Math.min(100, (ev.index / total) * 100)}%`;
        $('spText').textContent = `${ev.index}/${total}  ${ev.text}`;
      } else if (ev.type === 'log') {
        logLine(ev.level, ev.text);
      }
    });
    if (result) {
      S.groups = result.groups;
      S.scannedAt = result.scannedAt;
      if (result.env) S.env = result.env;
      S.sel = new Set();
      applyRecommendation();
      renderAll();
      if (!silent) toast(`扫描完成，可回收 ${human(Object.values(S.groups).reduce((a, g) => a + g.total, 0))}`, 'ok');
    }
  } catch (err) {
    toast(`扫描失败：${err.message}`, 'err');
    $('spText').textContent = `扫描失败：${err.message}`;
  } finally {
    S.busy = false;
    $('btnScan').disabled = false;
    $('btnScan').textContent = '扫描';
    $('scanProgress').classList.remove('on');
    renderAll();
  }
}

async function loadEnv() {
  try {
    S.env = await api('/api/env');
    renderTitlebar();
    renderSidebar();
  } catch (err) {
    toast(`无法连接后台：${err.message}`, 'err');
  }
}

/* ---------------------------------------------------------- 执行清理 */

function openRunDialog(simulate) {
  const info = selInfo();
  if (!info.count) return toast('请先勾选要清理的项目', 'warn');
  if (S.busy) return;

  const picked = allItems().filter((it) => S.sel.has(it.rid) && it.actionable);
  const needAdmin = picked.some((it) => it.requiresAdmin);
  const sysActions = picked.filter((it) => it.kind === 'action');
  const hasDanger = picked.some((it) => it.level === 'danger');
  const word = S.permanent ? 'DELETE' : 'CLEAN';

  const risky = picked.filter((it) => it.level === 'caution' || it.level === 'danger');
  const rows = picked.map((it) => `
    <div class="li">
      <div class="li-main">
        <div class="li-title"><span class="t">${esc(it.title)}</span></div>
        ${it.impact && it.level !== 'safe'
          ? `<div class="li-impact">⚠ ${esc(it.impact)}</div>` : ''}
      </div>
      <span class="badge ${it.level}">${esc(it.levelLabel)}</span>
      <div class="li-size">${esc(it.sizeHuman)}</div>
    </div>`).join('');

  const body = `
    ${simulate ? '<div class="notice">预览模式：只会列出将处理的目标，不会修改任何文件。</div>' : ''}
    <div class="result-cards">
      <div class="stat"><div class="k">选中项目</div><div class="v">${info.count}</div></div>
      <div class="stat"><div class="k">预计释放</div><div class="v" style="color:var(--safe)">${info.human}</div></div>
      <div class="stat ${S.permanent ? 'danger' : 'safe'}">
        <div class="k">执行模式</div>
        <div class="v" style="font-size:15px">${S.permanent ? '永久删除' : '隔离区'}</div>
      </div>
    </div>
    <div class="mlist" style="max-height:260px;overflow:auto">${rows}</div>
    ${risky.length && !simulate ? `<div class="warn-box ${hasDanger ? 'danger' : ''}">
      ⚠ 选中的项目里有 <b>${risky.length}</b> 项属于「需注意 / 高风险」——这些是<b>默认不勾选</b>的，
      请你确认下面的影响后再继续：<br>
      ${risky.map((it) => `· <b>${esc(it.title)}</b>：${esc(it.impact || '')}`).join('<br>')}
    </div>` : ''}
    ${hasDanger && !simulate ? `<div class="warn-box danger">⚠ 选中项里包含<b>高风险</b>内容，请确认影响已了解。</div>` : ''}
    ${simulate && sysActions.length ? `<div class="warn-box">包含 ${sysActions.length} 个系统动作，实际执行时会再单独确认。</div>` : ''}
    ${!simulate && needAdmin && S.env && !S.env.admin
      ? '<div class="warn-box">选中项需要管理员权限。可先点顶栏「普通用户 · 点此提权」重启为管理员实例。</div>' : ''}
    ${!simulate ? `
      <div class="warn-box ${S.permanent ? 'danger' : ''}">
        ${S.permanent
          ? '⚠ 永久删除不进隔离区，删除后<b>无法恢复</b>。'
          : '清理项会移动到隔离区，执行后可随时一键还原。被占用的文件会自动跳过。'}
      </div>
      <div style="margin-top:12px;font-size:12.5px;color:var(--text-2)">
        请输入 <b>${word}</b> 以确认执行：
        <input class="confirm-input" id="confirmWord" placeholder="${word}" autocomplete="off">
      </div>
      ${sysActions.length ? `
        <label class="switch" style="margin-top:12px">
          <input type="checkbox" id="allowSys" checked>
          <span class="switch-box"></span>
          <span class="switch-text"><b>允许执行系统动作（DISM / 回收站 / 休眠文件）</b>
          <em>取消勾选则本次只处理普通文件，跳过系统动作</em></span>
        </label>` : ''}
    ` : ''}
  `;

  modal({
    title: simulate ? '预览清理目标' : '确认执行清理',
    body,
    buttons: simulate
      ? [{ label: '关闭', cls: 'btn-outline' }]
      : [
          { label: '取消', cls: 'btn-ghost' },
          {
            label: S.permanent ? '永久删除' : '开始清理',
            cls: S.permanent ? 'btn-danger' : 'btn-primary',
            onClick: (btn) => {
              const input = $('confirmWord');
              const typed = (input.value || '').trim().toUpperCase();
              if (typed !== word) {
                input.classList.add('bad');
                input.focus();
                return toast(`请输入 ${word} 以确认`, 'warn');
              }
              const allowSys = $('allowSys') ? $('allowSys').checked : false;
              closeModal();
              runClean({ allowSystem: allowSys });
            },
          },
        ],
    onOpen: () => {
      const input = $('confirmWord');
      if (input) {
        input.focus();
        input.oninput = () => input.classList.remove('bad');
        input.onkeydown = (e) => { if (e.key === 'Enter') $('modalFoot').lastChild.click(); };
      }
    },
  });
}

async function runClean({ allowSystem }) {
  const rids = allItems().filter((it) => S.sel.has(it.rid) && it.actionable).map((it) => it.rid);
  S.busy = true;
  renderActionbar();
  drawer.clear();
  drawer.open(S.permanent ? '执行清理（永久删除）' : '执行清理（隔离区）');
  logLine('info', `开始处理 ${rids.length} 个清理项…`);

  try {
    const { job } = await api('/api/clean', {
      method: 'POST',
      body: JSON.stringify({
        rids,
        permanent: S.permanent,
        dryRun: false,
        days: S.days || null,
        allowSystem,
      }),
    });
    const result = await streamJob(job, (ev) => {
      if (ev.type === 'log') logLine(ev.level, ev.text);
      if (ev.type === 'progress') logLine('debug', `▸ ${ev.text}`);
    });
    if (result) showResult(result);
  } catch (err) {
    logLine('error', err.message);
    toast(`清理失败：${err.message}`, 'err');
  } finally {
    S.busy = false;
    await loadEnv();
    renderAll();
  }
}

function showResult(r) {
  const cards = `
    <div class="result-cards">
      <div class="stat safe"><div class="k">释放空间</div><div class="v">${esc(r.freedHuman)}</div>
        <div class="s">${fmt(r.files)} 个文件</div></div>
      <div class="stat"><div class="k">${r.permanent ? '永久删除' : '移入隔离区'}</div>
        <div class="v">${r.permanent ? r.deleted : r.moved}</div><div class="s">个目标</div></div>
      <div class="stat ${r.skippedCount ? 'caution' : ''}"><div class="k">跳过</div>
        <div class="v">${r.skippedCount}</div><div class="s">被占用 / 权限不足</div></div>
      <div class="stat"><div class="k">C 盘剩余</div><div class="v" style="font-size:16px">${esc(r.diskFreeHuman)}</div></div>
    </div>`;

  const actions = (r.actions || []).map((a) => `
    <div class="row"><span class="k">${a.ok ? '✓' : '✗'} ${esc(a.action)}</span>
    <span class="v">${esc(a.detail)}</span></div>`).join('');

  const skipped = (r.skipped || []).slice(0, 12).map((s) => `
    <div class="row"><span class="v mono">${esc(s.path)}</span></div>
    <div class="row"><span class="k">原因</span><span class="v">${esc(s.why)}</span></div>`).join('');

  const body = `
    ${cards}
    ${r.permanent ? '<div class="warn-box danger">本次为永久删除，未保留隔离备份。</div>'
      : `<div class="warn-box ok">已移入隔离区${r.trashTs ? `（批次 ${esc(r.trashTs)}）` : ''}，
         可随时还原。还原命令：<code>python wbcleaner.py trash restore ${esc(r.trashTs || '<时间戳>')}</code></div>`}
    ${actions ? `<div class="section-title">系统动作</div><div class="li-expand">${actions}</div>` : ''}
    ${r.skippedCount ? `<div class="section-title">跳过的目标（${r.skippedCount}）</div>
      <div class="li-expand">${skipped}${r.skippedCount > 12 ? '<div class="row"><span class="v">…其余见日志</span></div>' : ''}</div>` : ''}
    ${r.errors && r.errors.length ? `<div class="warn-box danger">${esc(r.errors.join('；'))}</div>` : ''}
  `;

  modal({
    title: '清理完成',
    body,
    buttons: [
      { label: '关闭', cls: 'btn-ghost' },
      r.trashTs ? {
        label: '去隔离区还原', cls: 'btn-outline',
        onClick: () => { closeModal(); goto('trash'); },
      } : null,
      {
        label: '重新扫描', cls: 'btn-primary',
        onClick: () => { closeModal(); scan(); },
      },
    ].filter(Boolean),
  });
}

/* ---------------------------------------------------------- 执行系统动作 */

async function runAction(action, label) {
  if (S.busy) return;
  S.busy = true;
  drawer.clear();
  drawer.open(label);
  logLine('info', `${label} 开始…`);
  try {
    const { job } = await api('/api/action', { method: 'POST', body: JSON.stringify({ action }) });
    const result = await streamJob(job, (ev) => {
      if (ev.type === 'log') logLine(ev.level, ev.text);
    });
    if (result) {
      logLine('ok', result.detail);
      if (result.env) S.env = result.env;
      await loadEnv();
      toast(result.detail, 'ok');
    }
    renderAll();
  } catch (err) {
    logLine('error', err.message);
    toast(`${label} 失败：${err.message}`, 'err');
  } finally {
    S.busy = false;
  }
}

/* ---------------------------------------------------------- 视图渲染 */

function renderAll() {
  renderSidebar();
  renderTitlebar();
  renderActionbar();
  const c = $('content');
  // 分组视图统一由 GROUP_VIEWS 驱动：新增软件分组只要改这一处，
  // 不会再出现「加了视图却忘了在某个 switch 里补分支」的漏项。
  if (GROUP_VIEWS.includes(S.view)) {
    c.innerHTML = viewGroup(S.view);
    bindGroup();
  } else if (S.view === 'winsxs') {
    c.innerHTML = viewWinsxs();
    bindWinsxs();
  } else if (S.view === 'trash') {
    c.innerHTML = viewTrash();
    bindTrash();
  } else if (S.view === 'protected') {
    c.innerHTML = viewProtected();
  } else {
    c.innerHTML = viewOverview();
    bindOverview();
  }
  if (location.hash.slice(1) !== S.view) {
    history.replaceState(null, '', `#${S.view}`);
  }
}

// 分组视图清单：软件分组（workbuddy / codex / deepseek）与系统分组共用 viewGroup
const GROUP_VIEWS = ['workbuddy', 'codex', 'deepseek', 'system'];
const VIEWS = ['overview', ...GROUP_VIEWS, 'winsxs', 'trash', 'protected'];

function goto(view) {
  if (!VIEWS.includes(view)) view = 'overview';
  S.view = view;
  if (view === 'trash') return loadTrash().then(renderAll);
  if (view === 'protected' && !S.protectedList) {
    return Promise.all([api('/api/protected'), api('/api/rules')]).then(([p, r]) => {
      S.protectedList = p.protected;
      S.rules = r.rules;
      renderAll();
    });
  }
  renderAll();
}

function statCards(group) {
  return `
    <div class="cards">
      <div class="stat"><div class="k">可回收合计</div>
        <div class="v" style="color:var(--accent)">${group ? group.totalHuman : grandTotal()}</div></div>
      <div class="stat safe clickable" data-chip="safe"><div class="k">安全项</div>
        <div class="v">${group ? group.safeHuman : sumField('safe')}</div>
        <div class="s">缓存 / 日志，删了自动重建</div></div>
      <div class="stat caution clickable" data-chip="caution"><div class="k">需注意</div>
        <div class="v">${group ? group.cautionHuman : sumField('caution')}</div>
        <div class="s">可重建但要联网重下</div></div>
      <div class="stat danger clickable" data-chip="danger"><div class="k">高风险</div>
        <div class="v">${group ? group.dangerHuman : sumField('danger')}</div>
        <div class="s">会影响历史 / 功能</div></div>
      <div class="stat keep clickable" data-chip="keep"><div class="k">保护项</div>
        <div class="v">${group ? groupKeep(group) : sumField('keep')}</div>
        <div class="s">永不清理，仅统计</div></div>
    </div>`;
}

function grandTotal() {
  return human(Object.values(S.groups).reduce((a, g) => a + g.total, 0));
}

function sumField(level) {
  const key = { safe: 'safe', caution: 'caution', danger: 'danger' }[level];
  if (key) return human(Object.values(S.groups).reduce((a, g) => a + g[key], 0));
  // keep：非可清理项的体积
  let b = 0;
  allItems().forEach((it) => { if (it.protected) b += it.size; });
  return human(b);
}

function groupKeep(group) {
  return human(group.items.filter((i) => i.protected).reduce((a, i) => a + i.size, 0));
}

function viewOverview() {
  if (!Object.keys(S.groups).length) return emptyState();
  const rows = GROUP_VIEWS.map((k) => {
    const g = S.groups[k];
    if (!g) return '';
    const picked = g.items.filter((i) => S.sel.has(i.rid) && i.actionable);
    const manual = g.items.filter((i) => i.actionable && !i.defaultOn && !i.protected);
    return `
      <tr>
        <td><b>${esc(g.title.replace(/^\d+\.\s*/, ''))}</b></td>
        <td class="num">${esc(g.totalHuman)}</td>
        <td>${g.items.filter((i) => i.actionable).length} 项可清理${
          manual.length ? ` · <span style="color:var(--caution)">${manual.length} 项需手动勾选</span>` : ''}</td>
        <td class="num">${picked.length} 项 / ${human(picked.reduce((a, i) => a + i.size, 0))}</td>
        <td class="row-actions">
          <button class="btn btn-outline btn-sm" data-goto="${k}">查看</button>
          <button class="btn btn-primary btn-sm" data-run-group="${k}">清理本组安全项</button>
        </td>
      </tr>`;
  }).join('');

  const dism = S.env && S.env.dism;
  return `
    <div class="head">
      <div>
        <h2>概览</h2>
        <p>扫描结果基于${S.scannedAt ? ` ${esc(S.scannedAt)} 的扫描` : '最近一次扫描'}；勾选后点右下角「执行清理」。
           默认把目标移入隔离区，可随时还原。</p>
      </div>
    </div>
    ${statCards(null)}
    ${!S.env || !S.env.admin ? `
      <div class="notice warn"><span class="ico">⚠</span>
        <div>当前是<b>普通用户</b>权限，WinSxS、Windows 更新缓存、休眠文件等系统级项目无法执行。
        点顶栏的「普通用户 · 点此提权」会用管理员身份另开一个窗口。</div></div>` : ''}
    <div class="section-title">三大清理功能</div>
    <table class="table">
      <thead><tr><th>功能</th><th>可回收</th><th>覆盖</th><th>当前已选</th><th>操作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>

    <div class="section-title">WinSxS 组件存储</div>
    ${dism ? `
      <table class="table">
        <thead><tr><th>指标</th><th>数值</th></tr></thead>
        <tbody>
          <tr><td>组件存储实际大小</td><td class="num">${human(dism.actual)}</td></tr>
          <tr><td>已与 Windows 共享</td><td class="num">${human(dism.shared)}</td></tr>
          <tr><td><b>备份和已禁用的功能（可回收）</b></td>
              <td class="num" style="color:var(--safe)">${human(dism.reclaimable)}</td></tr>
          <tr><td>可回收的程序包</td><td class="num">${dism.reclaimable_packages || 0} 个</td></tr>
          <tr><td>官方建议清理</td><td class="num">${dism.recommended ? '是' : '否'}</td></tr>
          <tr><td>分析时间</td><td class="num">${esc(dism.time_human || '')}</td></tr>
        </tbody>
      </table>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn btn-outline" data-goto="winsxs">打开 WinSxS 面板</button>
      </div>`
      : `<div class="notice"><span class="ico">ℹ</span>
         <div>还没有 WinSxS 分析数据。到「WinSxS 组件」页面点一次「分析」即可（只读，约 20 秒）。</div></div>`}
  `;
}

function emptyState() {
  return `
    <div class="empty">
      <div class="big">▦</div>
      <div>还没有扫描数据</div>
      <div class="hint" style="margin-top:6px">扫描是只读操作，不会修改任何文件</div>
      <button class="btn btn-primary" onclick="scan()">开始扫描</button>
    </div>`;
}

function viewGroup(key) {
  const g = S.groups[key];
  if (!g) return emptyState();
  const tips = {
    workbuddy: 'WorkBuddy 的日志、性能 trace、Electron 缓存与会话改动备份。运行时、凭证、记忆都在保护名单里，永远不会被清理。',
    codex: 'Codex 的临时目录、插件与市场缓存、日志数据库。codex.exe 等宿主程序在保护名单里。',
    deepseek: 'DeepSeek Harness 的更新器残留、桌面端渲染缓存、会话回收站与市场缓存。'
            + '内置运行时（Node/Python）与凭证在保护名单里，插件 node_modules 需手动勾选。',
    system: 'C 盘系统级垃圾。WinSxS 必须走 DISM，本工具已内置；休眠文件与「永久删除」一样需要二次确认。',
  }[key];

  return `
    <div class="head">
      <div><h2>${esc(g.title.replace(/^\d+\.\s*/, ''))}</h2><p>${esc(tips)}</p></div>
      <div class="head-actions">
        <button class="btn btn-ghost" data-select-safe>只选安全项</button>
      </div>
    </div>
    ${statCards(g)}
    <div class="toolbar">
      <div class="chips">
        ${chip('all', '全部')}${chip('safe', '安全')}${chip('caution', '需注意')}
        ${chip('danger', '高风险')}${chip('keep', '保护')}
      </div>
      <div class="spacer"></div>
      <span class="hint">${filteredItems(g).length} 项显示</span>
    </div>
    <div class="list">${filteredItems(g).map(itemRow).join('') || '<div class="empty">该分类下没有项目</div>'}</div>
  `;
}

function chip(v, label) {
  const on = S.filter === v;
  return `<button class="chip ${on ? 'active s-' + v : ''}" data-filter="${v}">${label}</button>`;
}

function filteredItems(g) {
  if (S.filter === 'all') return g.items;
  if (S.filter === 'keep') return g.items.filter((i) => i.protected);
  return g.items.filter((i) => i.level === S.filter);
}

function itemRow(it) {
  const on = S.sel.has(it.rid);
  const selectable = it.actionable || it.kind === 'action';
  const dis = !selectable || it.protected;
  const open = S.expanded.has(it.rid);
  // 默认不勾选、需要用户自己决定的项目：直接在行上标出来，不靠展开才发现
  const manual = selectable && !it.defaultOn && !it.protected;
  const risky = manual && (it.level === 'caution' || it.level === 'danger');
  const title = `${esc(it.title)}${it.minAgeDays ? `<span class="hint"> · 仅 ${it.minAgeDays} 天前</span>` : ''}`;
  const sizeCls = it.size ? '' : 'zero';
  const sizeTxt = it.size ? esc(it.sizeHuman) : (it.note ? esc(it.note) : '—');
  const sub = it.size && it.files ? `<small>${fmt(it.files)} 个文件</small>` : '';

  return `
    <div class="li ${on ? 'on' : ''} ${dis && !it.protected ? 'dim' : ''}" data-row="${esc(it.rid)}">
      <span class="cb ${on ? 'on' : ''} ${dis ? 'dis' : ''}"></span>
      <div class="li-main">
        <div class="li-title"><span class="t">${title}</span>
          ${manual ? '<span class="tag-manual">需手动勾选</span>' : ''}
          ${it.requiresAdmin ? '<span class="hint">· 需管理员</span>' : ''}</div>
        <div class="li-desc">${esc(it.kind === 'action' && it.note ? '' : it.desc)}</div>
        ${risky && it.impact ? `<div class="li-impact">⚠ ${esc(it.impact)}</div>` : ''}
      </div>
      <span class="badge ${it.level}">${esc(it.levelLabel)}</span>
      <div class="li-size ${sizeCls}">${sizeTxt}${sub}</div>
      <button class="exp-btn" data-expand="${esc(it.rid)}">${open ? '▴' : '▾'}</button>
      ${open ? `<div style="grid-column:1/-1">${expandBody(it)}</div>` : ''}
    </div>`;
}

function expandBody(it) {
  return `
    <div class="li-expand">
      <div class="row"><span class="k">规则 id</span><span class="v mono">${esc(it.rid)}</span></div>
      <div class="row"><span class="k">这是什么</span><span class="v">${esc(it.desc || '—')}</span></div>
      <div class="row"><span class="k">影响</span><span class="v impact">${esc(it.impact || '—')}</span></div>
      ${it.note ? `<div class="row"><span class="k">当前状态</span><span class="v">${esc(it.note)}</span></div>` : ''}
      ${it.count ? `<div class="row"><span class="k">目标</span><span class="v">共 ${it.count} 处${
        it.files ? `，${fmt(it.files)} 个文件` : ''}</span></div>` : ''}
      ${it.targets && it.targets.length ? `
        <div class="row"><span class="k">路径</span><span class="v"></span></div>
        <div class="paths">${it.targets.map((t) => `<div>${esc(t)}</div>`).join('')}${
          it.targetsMore ? `<div>… 另有 ${it.targetsMore} 处</div>` : ''}</div>` : ''}
    </div>`;
}

function viewWinsxs() {
  const d = S.env && S.env.dism;
  const admin = S.env && S.env.admin;
  return `
    <div class="head">
      <div><h2>WinSxS 组件存储</h2>
      <p>WinSxS 里的文件和 System32 通过硬链接共享，<b>手工删除会让系统更新、SFC 修复彻底失效</b>，
        只能用 DISM 清理。本工具走的正是官方命令。</p></div>
    </div>
    ${!admin ? `<div class="notice warn"><span class="ico">⚠</span>
      <div>DISM 需要管理员权限。点顶栏「普通用户 · 点此提权」重启一个管理员窗口后再操作。</div></div>` : ''}
    ${d ? `
      <div class="cards">
        <div class="stat"><div class="k">组件存储实际大小</div><div class="v">${human(d.actual)}</div></div>
        <div class="stat"><div class="k">已与 Windows 共享</div><div class="v" style="color:var(--muted)">${human(d.shared)}</div></div>
        <div class="stat safe"><div class="k">可回收</div><div class="v">${human(d.reclaimable)}</div>
          <div class="s">备份和已禁用的功能</div></div>
        <div class="stat caution"><div class="k">可回收程序包</div><div class="v">${d.reclaimable_packages || 0}</div>
          <div class="s">官方建议：${d.recommended ? '清理' : '暂不需要'}</div></div>
      </div>
      <div class="hint" style="margin-bottom:14px">上次分析：${esc(d.time_human || '')}</div>`
      : `<div class="notice"><span class="ico">ℹ</span>
        <div>还没有分析数据。点下面的「分析（只读）」先看看能回收多少。</div></div>`}

    <div class="section-title">可用操作</div>
    <div class="list">
      ${actionRow('dism_analyze', '分析组件存储（只读）', 'safe',
        '执行 DISM /Online /Cleanup-Image /AnalyzeComponentStore，只读不修改，约 20~60 秒。')}
      ${actionRow('dism_cleanup', '标准清理', 'caution',
        '执行 /StartComponentCleanup，清理被取代的组件版本。已安装的更新将无法卸载回滚，系统功能不受影响。')}
      ${actionRow('dism_resetbase', '深度清理 /ResetBase', 'danger',
        '额外回收所有被取代组件的备份，通常再多释放 1~3 GB。⚠ 不可逆：之后所有已安装更新都无法卸载。')}
      ${actionRow('recyclebin', '清空回收站', 'caution',
        '清空所有盘的回收站，回收站里的文件将无法还原。')}
      ${actionRow('wu_cache', '清理 Windows 更新下载缓存', 'caution',
        '停止 wuauserv/bits 后清空 SoftwareDistribution\\Download，正在下载的更新会作废重下。')}
      ${actionRow('hibernate_off', '关闭休眠并释放 hiberfil.sys', 'danger',
        '执行 powercfg /h off，释放约等于内存容量的空间。⚠ 之后不能用「休眠」，快速启动也会失效，可用 powercfg /h on 恢复。')}
    </div>
  `;
}

function actionRow(action, title, level, desc) {
  return `
    <div class="li" style="grid-template-columns:1fr auto auto">
      <div class="li-main">
        <div class="li-title"><span class="t">${esc(title)}</span></div>
        <div class="li-desc" style="white-space:normal">${esc(desc)}</div>
      </div>
      <span class="badge ${level}">${level === 'safe' ? '只读' : level === 'caution' ? '需注意' : '不可逆'}</span>
      <button class="btn ${action === 'dism_analyze' ? 'btn-outline' : level === 'danger' ? 'btn-danger' : 'btn-primary'} btn-sm"
        data-action="${action}" data-label="${esc(title)}" style="margin-left:12px">执行</button>
    </div>`;
}

function viewTrash() {
  const e = S.env;
  const list = (e && e.trash) || [];
  if (!list.length) {
    return `
      <div class="head"><div><h2>隔离区</h2>
      <p>清理时被移出的文件都会放在这里，可以随时还原到原位置。</p></div></div>
      <div class="empty"><div class="big">↺</div><div>隔离区是空的</div>
        <div class="hint" style="margin-top:6px">执行一次「隔离区模式」的清理后，内容会出现在这里</div></div>`;
  }
  const rows = list.map((t) => `
    <tr>
      <td class="mono">${esc(t.ts)}</td>
      <td class="num">${human(t.size)}</td>
      <td class="num">${t.entries}</td>
      <td class="num">${fmt(t.files)}</td>
      <td class="mono" style="font-size:11px">${esc(t.time || '')}</td>
      <td class="row-actions">
        <button class="btn btn-outline btn-sm" data-restore="${esc(t.ts)}">还原</button>
        <button class="btn btn-ghost btn-sm" data-purge="${esc(t.ts)}">永久删除</button>
      </td>
    </tr>`).join('');

  return `
    <div class="head">
      <div><h2>隔离区</h2>
      <p>共 ${list.length} 个批次、${esc(e.trashTotalHuman)}。还原会把文件搬回原位置；永久删除不可恢复。</p></div>
      <div class="head-actions">
        <button class="btn btn-danger" data-purge-all>清空全部隔离区</button>
      </div>
    </div>
    <table class="table">
      <thead><tr><th>时间戳</th><th>体积</th><th>条目</th><th>文件数</th><th>时间</th><th>操作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="notice" style="margin-top:14px"><span class="ico">ℹ</span>
      <div>隔离区位置：<code>%LOCALAPPDATA%\\wbcleaner\\trash</code>（非 C 盘目标会放在对应盘的
      <code>\\_wbcleaner-trash</code>）。每个批次里都有 manifest.json 记录原始路径。</div></div>
  `;
}

function viewProtected() {
  const pl = S.protectedList || [];
  const rules = (S.rules || []).filter((r) => r.protected);
  return `
    <div class="head">
      <div><h2>保护名单</h2>
      <p>下面这些位置<b>任何模式下都不会被清理</b>。这份名单硬编码在 <code>wbc/rules.py</code> 里，
        连永久删除模式也会被安全守卫拦下。</p></div>
    </div>
    <div class="section-title">受保护路径（${pl.length} 条）</div>
    <table class="table">
      <thead><tr><th>说明</th><th>路径</th></tr></thead>
      <tbody>${pl.map((p) => `<tr><td>${esc(p.label)}</td><td class="mono">${esc(p.path)}</td></tr>`).join('')}</tbody>
    </table>
    ${rules.length ? `
      <div class="section-title">仅统计不清理的项目</div>
      <table class="table">
        <thead><tr><th>项目</th><th>分组</th><th>体积</th><th>说明</th></tr></thead>
        <tbody>${rules.map((r) => {
          const it = allItems().find((i) => i.rid === r.rid);
          return `<tr><td><b>${esc(r.title)}</b></td>
            <td>${esc({ workbuddy: 'WorkBuddy', codex: 'Codex', system: 'C盘系统' }[r.group] || r.group)}</td>
            <td class="num">${it && it.size ? esc(it.sizeHuman) : '—'}</td>
            <td>${esc(r.impact || r.desc)}</td></tr>`;
        }).join('')}</tbody>
      </table>` : ''}
  `;
}

/* ---------------------------------------------------------- 事件绑定 */

function bindOverview() {
  $('content').querySelectorAll('[data-goto]').forEach((b) => {
    b.onclick = () => goto(b.dataset.goto);
  });
  $('content').querySelectorAll('[data-run-group]').forEach((b) => {
    b.onclick = () => {
      const g = S.groups[b.dataset.runGroup];
      S.sel = new Set(g.items.filter((i) => i.actionable && i.level === 'safe' && !i.protected)
        .map((i) => i.rid));
      S.view = b.dataset.runGroup;
      renderAll();
      toast(`已选中 ${g.title} 的安全项，确认后点「执行清理」`, 'ok');
    };
  });
  $('content').querySelectorAll('[data-chip]').forEach((c) => {
    c.onclick = () => { S.filter = c.dataset.chip; S.view = 'workbuddy'; renderAll(); };
  });
}

function bindGroup() {
  const c = $('content');
  c.querySelectorAll('[data-filter]').forEach((b) => {
    b.onclick = () => { S.filter = b.dataset.filter; renderAll(); };
  });
  c.querySelectorAll('.li[data-row]').forEach((row) => {
    const rid = row.dataset.row;
    const it = allItems().find((x) => x.rid === rid);
    const box = row.querySelector('.cb');
    const selectable = it && !it.protected && (it.actionable || it.kind === 'action');
    if (!selectable) {
      if (box) box.style.cursor = 'not-allowed';
      return;
    }
    // 整行可点，更接近桌面软件的操作手感
    row.style.cursor = 'pointer';
    row.onclick = () => { toggle(rid); renderAll(); };
  });
  c.querySelectorAll('[data-expand]').forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const rid = b.dataset.expand;
      S.expanded.has(rid) ? S.expanded.delete(rid) : S.expanded.add(rid);
      renderAll();
    };
  });
  c.querySelectorAll('[data-select-safe]').forEach((b) => {
    b.onclick = () => {
      const g = S.groups[S.view];
      if (!g) return;
      S.sel = new Set(g.items.filter((i) => i.actionable && i.level === 'safe' && !i.protected)
        .map((i) => i.rid));
      renderAll();
    };
  });
  c.querySelectorAll('[data-chip]').forEach((s) => {
    s.onclick = () => { S.filter = s.dataset.chip; renderAll(); };
  });
}

function bindWinsxs() {
  $('content').querySelectorAll('[data-action]').forEach((b) => {
    b.onclick = () => {
      const action = b.dataset.action;
      const label = b.dataset.label;
      const danger = b.classList.contains('btn-danger');
      const needType = action === 'dism_resetbase' ? 'DANGER'
        : action === 'hibernate_off' ? 'CLOSE-HIBERNATE' : null;
      if (!danger && !needType) return runAction(action, label);
      modal({
        title: `确认：${label}`,
        body: `<div class="warn-box danger">${action === 'dism_resetbase'
          ? '⚠ /ResetBase 不可逆：之后所有已安装的 Windows 更新都无法卸载回滚。'
          : '⚠ 关闭休眠后无法使用「休眠」，Windows 快速启动也会失效（可用 powercfg /h on 恢复）。'}</div>
          <div style="font-size:12.5px;color:var(--text-2)">请输入 <b>${needType}</b> 确认：
          <input class="confirm-input" id="confirmWord" autocomplete="off"></div>`,
        buttons: [
          { label: '取消', cls: 'btn-ghost' },
          {
            label: '确认执行', cls: 'btn-danger',
            onClick: () => {
              const v = ($('confirmWord').value || '').trim().toUpperCase();
              if (v !== needType) return toast(`请输入 ${needType}`, 'warn');
              closeModal();
              runAction(action, label);
            },
          },
        ],
        onOpen: () => $('confirmWord').focus(),
      });
    };
  });
}

function bindTrash() {
  const c = $('content');
  c.querySelectorAll('[data-restore]').forEach((b) => {
    b.onclick = () => {
      const ts = b.dataset.restore;
      modal({
        title: '还原隔离区批次',
        body: `<p>将批次 <code>${esc(ts)}</code> 里的文件搬回原来的位置。</p>
               <div class="warn-box ok">目标位置已存在同名文件时会自动改名，不会覆盖现有数据。</div>`,
        buttons: [
          { label: '取消', cls: 'btn-ghost' },
          {
            label: '还原', cls: 'btn-primary',
            onClick: async (btn) => {
              btn.disabled = true; btn.textContent = '还原中…';
              try {
                await api('/api/trash/restore', { method: 'POST', body: JSON.stringify({ ts }) });
                closeModal();
                await loadEnv(); await loadTrash();
                renderAll();
                toast('还原完成', 'ok');
              } catch (err) { toast(`还原失败：${err.message}`, 'err'); btn.disabled = false; btn.textContent = '还原'; }
            },
          },
        ],
      });
    };
  });
  c.querySelectorAll('[data-purge]').forEach((b) => {
    b.onclick = () => confirmPurge(b.dataset.purge);
  });
  const all = c.querySelector('[data-purge-all]');
  if (all) all.onclick = () => confirmPurge(null);
}

function confirmPurge(ts) {
  modal({
    title: '永久删除隔离区内容',
    body: `<div class="warn-box danger">⚠ 永久删除后<b>无法恢复</b>，
      这些文件会从磁盘上彻底移除${ts ? `（批次 ${esc(ts)}）` : '（全部批次）'}。</div>
      <div style="font-size:12.5px;color:var(--text-2)">请输入 <b>PURGE</b> 确认：
      <input class="confirm-input" id="confirmWord" autocomplete="off"></div>`,
    buttons: [
      { label: '取消', cls: 'btn-ghost' },
      {
        label: '永久删除', cls: 'btn-danger',
        onClick: async () => {
          const v = ($('confirmWord').value || '').trim().toUpperCase();
          if (v !== 'PURGE') return toast('请输入 PURGE', 'warn');
          await api('/api/trash/purge', { method: 'POST', body: JSON.stringify({ ts }) });
          closeModal();
          await loadEnv(); await loadTrash();
          renderAll();
          toast('隔离区已清空', 'ok');
        },
      },
    ],
    onOpen: () => $('confirmWord').focus(),
  });
}

/* ---------------------------------------------------------- 加载 */

async function loadTrash() {
  const data = await api('/api/trash');
  if (S.env) { S.env.trash = data.entries; S.env.trashTotal = data.total; S.env.trashTotalHuman = data.totalHuman; }
}

async function elevate() {
  try {
    const data = await api('/api/elevate', {
      method: 'POST',
      body: JSON.stringify({ port: Number(location.port) || 8791 }),
    });
    toast(data.detail, data.ok ? 'ok' : 'err');
  } catch (err) { toast(`提权失败：${err.message}`, 'err'); }
}

async function doctor() {
  const e = S.env || {};
  let body = `
    <div class="kv">
      <span class="k">WBCleaner</span><span class="v">v${esc(e.version || '?')}</span>
      <span class="k">Python</span><span class="v">${esc(e.python || '?')}</span>
      <span class="k">用户</span><span class="v">${esc(e.user || '?')}</span>
      <span class="k">权限</span><span class="v">${e.admin ? '管理员' : '普通用户'}</span>
      <span class="k">C 盘</span><span class="v">已用 ${esc(e.disk ? e.disk.usedHuman : '?')} / ${esc(e.disk ? e.disk.totalHuman : '?')}，剩余 ${esc(e.disk ? e.disk.freeHuman : '?')}</span>
      <span class="k">隔离区</span><span class="v">${esc(e.trashTotalHuman || '0 B')}</span>
    </div>`;
  try {
    const r = await api('/api/rules');
    const groups = { workbuddy: 'WorkBuddy', codex: 'Codex', system: 'C盘系统' };
    const counts = { workbuddy: 0, codex: 0, system: 0 };
    r.rules.forEach((x) => { if (!x.protected && x.kind !== 'report') counts[x.group] += 1; });
    body += `        <div class="section-title">规则表</div>
      <div class="kv">
        ${Object.keys(counts).map((k) => `<span class="k">${groups[k]}</span>
          <span class="v">${counts[k]} 条可清理规则</span>`).join('')}
        <span class="k">保护名单</span>
        <span class="v">${r.rules.filter((x) => x.protected).length} 条永不清理${
          S.protectedList ? `，${S.protectedList.length} 个受保护路径` : ''}</span>
      </div>`;
  } catch { /* ignore */ }
  body += `<div class="warn-box ok" style="margin-top:14px">
    日志文件：<code>logs\\wbcleaner-YYYYMMDD.log</code>，每次清理的每个目标都有记录。</div>`;
  modal({ title: '环境概览', body, buttons: [{ label: '关闭', cls: 'btn-outline' }] });
}

function bindGlobal() {
  $('nav').querySelectorAll('.nav-item').forEach((b) => {
    b.onclick = () => goto(b.dataset.view);
  });
  $('btnScan').onclick = () => scan();
  $('btnReport').onclick = async () => {
    try {
      const { job } = await api('/api/report', { method: 'POST', body: '{}' });
      const res = await streamJob(job, (ev) => {
        if (ev.type === 'log') logLine(ev.level, ev.text);
      });
      if (res) {
        const name = res.path.split(/[\\/]/).pop();
        toast('报告已生成，正在打开…', 'ok');
        window.open(`/reports/${encodeURIComponent(name)}?t=${encodeURIComponent(TOKEN)}`, '_blank');
      }
    } catch (err) { toast(`导出失败：${err.message}`, 'err'); }
  };
  $('btnDoctor').onclick = doctor;

  $('daysSelect').onchange = (e) => {
    S.days = e.target.value;
    localStorage.setItem('wbc.days', S.days);
    toast(S.days ? `只清理 ${S.days} 天前的数据，重新扫描中…` : '不限时间，重新扫描中…');
    scan(true);
  };
  $('permSwitch').onchange = (e) => {
    S.permanent = e.target.checked;
    localStorage.setItem('wbc.permanent', S.permanent ? '1' : '');
    renderActionbar();
    if (S.permanent) toast('已切换到永久删除模式：不进隔离区，无法恢复', 'warn');
  };

  $('btnPreview').onclick = () => openRunDialog(true);
  $('btnRun').onclick = () => openRunDialog(false);
  $('btnDefault').onclick = () => { applyRecommendation(); renderAll(); };
  $('btnSelectSafe').onclick = () => {
    S.sel = new Set(allItems().filter((i) => i.actionable && i.level === 'safe' && !i.protected)
      .map((i) => i.rid));
    renderAll();
  };
  $('btnSelectAll').onclick = () => {
    S.sel = new Set(allItems().filter((i) => i.actionable && !i.protected).map((i) => i.rid));
    renderAll();
  };
  $('btnClear').onclick = () => { S.sel = new Set(); renderAll(); };
  $('modalX').onclick = closeModal;
  $('modalMask').onclick = (e) => { if (e.target === $('modalMask')) closeModal(); };
  $('btnDrawerClose').onclick = () => drawer.close();
  $('btnDrawerClear').onclick = () => drawer.clear();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeModal(); drawer.close(); }
    if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) { e.preventDefault(); scan(); }
  });
}

/* ---------------------------------------------------------- 启动 */

(async function main() {
  S.days = localStorage.getItem('wbc.days') || '';
  S.permanent = localStorage.getItem('wbc.permanent') === '1';
  $('daysSelect').value = S.days;
  $('permSwitch').checked = S.permanent;
  S.view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';

  bindGlobal();
  renderAll();
  await loadEnv();
  if (S.view === 'trash') await loadTrash();
  if (S.view === 'protected') {
    try {
      const [p, r] = await Promise.all([api('/api/protected'), api('/api/rules')]);
      S.protectedList = p.protected;
      S.rules = r.rules;
    } catch { /* ignore */ }
  }

  // 有缓存结果就直接用，否则自动扫描一次
  try {
    const cached = await api('/api/scan/cached');
    if (cached.groups && Object.keys(cached.groups).length) {
      S.groups = cached.groups;
      S.scannedAt = cached.scannedAt
        ? new Date(cached.scannedAt * 1000).toLocaleString('zh-CN', { hour12: false }) : null;
      applyRecommendation();
      renderAll();
    } else {
      scan(true);
    }
  } catch {
    scan(true);
  }
})();
