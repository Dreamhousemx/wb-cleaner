# 扫尘 (WBCleaner)

> 把缓存与垃圾当灰尘扫掉，清理前一律先收进「匣子」——可还原。

清理 **WorkBuddy**、**Codex** 产生的无用缓存，以及 **C 盘**系统级垃圾的 Windows 工具。
自带可视化界面，清理默认进隔离区、可一键还原。

本机实测（2026-10-01）：WorkBuddy 目录 5.8 GB、Codex 目录 564 MB、WinSxS 12.37 GB。

**名字备选**：净匣（CleanVault）· 腾地方（MakeRoom）· 拾掇（Tidy）。
想换名字只需改 `web/index.html` 的标题与 `wbcleaner_ui.py` 的 `APP_NAME`。

---

## 应用图标

`icon/` 下有做好的图标，可直接设给桌面快捷方式：

| 文件 | 用途 |
|---|---|
| `icon/app-icon.ico` | **桌面快捷方式用这个**（9 个尺寸：16/20/24/32/40/48/64/128/256） |
| `icon/app-icon.png` | 1024×1024 母版，圆角透明 |
| `icon/preview.html` | 各尺寸真机观感预览（含深色任务栏效果） |

设置方法：**右键快捷方式 → 属性 → 更改图标 → 浏览到 `icon\app-icon.ico`**。

界面本身的窗口/任务栏图标取自同一张图的 favicon，不需要额外配置。
想重新生成或调整字形大小：改 `icon/make_icon.py` 里的 `GLYPH_BOX` / `CORNER_RADIUS`，
再跑 `python icon/make_icon.py`。

懒得手工设图标的话，`make-shortcut.bat` 可以一步在桌面建好带图标的快捷方式
（执行 `tools/make_shortcut.py`，只在桌面新增一个 .lnk，需要时自己运行）。

---

## 三大功能

| 功能 | 覆盖内容 | 本次实测可回收 |
|---|---|---|
| **1. 清理 WorkBuddy 文件** | 沙箱日志、按日期归档日志、trace 性能文件、文件树清单、Electron 缓存、剪贴板图片、插件/市场缓存、会话改动备份、blob 存储 | 约 2 GB（安全项约 1.4 GB） |
| **2. 清理 Codex 文件** | `.tmp` 临时目录、远程插件目录缓存、插件包缓存、日志数据库、会话回滚文件、状态备份 | 约 141 MB |
| **3. 清理 C 盘无用文件** | **WinSxS（DISM 官方方式）**、Windows 更新缓存、`%TEMP%`、系统临时文件、崩溃转储、WER、pip/npm/uv 包缓存、浏览器与系统缓存、回收站、休眠文件 | 约 8 GB（不含休眠文件）/ 24.9 GB（含休眠） |

### 关于 WinSxS（重点）

WinSxS **绝对不能手工删**——里面大量文件是通过硬链接与 `System32` 共享的，
手工删除会让 Windows 更新、SFC、组件修复彻底失效，且无法撤销。

本工具走官方唯一正确路径：

```
DISM /Online /Cleanup-Image /AnalyzeComponentStore        # 先只读分析
DISM /Online /Cleanup-Image /StartComponentCleanup        # 标准清理（可回滚更新）
DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase   # 深度清理（不可逆）
```

本机分析结果：组件存储实际 **12.37 GB**，其中「备份和已禁用功能」**3.86 GB** 可回收，
可回收程序包 2 个，官方建议清理 = 是。

---

## 安全设计（这是本工具的核心）

清理工具最怕误删。本工具做了五层防护：

1. **默认只扫描**：`scan` 与交互式预览不发任何删除调用；执行前必须手工输入 `CLEAN` 确认。
2. **保护名单硬编码**（`wbc/rules.py` 的 `PROTECTED`）：
   工作区 `.workbuddy/memory`、个人档案（SOUL/IDENTITY/USER/MEMORY）、凭证、登录态、
   托管运行时 `binaries/`、Codex `auth.json` / `config.toml` / `cx.exe`、
   WinSxS 本体、`Windows\Installer`、分页文件——**任何模式都不会被清理**。
3. **安全守卫**（`util.guard`）：删除前逐条校验，拒绝盘根、拒绝浅层路径、
   拒绝命中保护名单的路径；命中即跳过并记录，绝不静默继续。
4. **隔离区而非直接删除**：默认把目标移动到
   `%LOCALAPPDATA%\wbcleaner\trash\<时间戳>\` 并写 `manifest.json`，
   用 `trash restore <时间戳>` 可原样还原。只有 `--permanent` 才真正删除。
5. **年龄阈值**：日志 / trace / 会话备份默认只清理 3~14 天前的数据，
   正在运行的文件会被自动跳过并写进日志。

另外：所有删除都记日志到 `logs/wbcleaner-YYYYMMDD.log`，随时可核对做了什么。

---

## 快速开始

### 方式一：可视化界面（推荐）

双击 **`ui.bat`** —— 会起一个本地服务，并用 Edge/Chrome 的**应用窗口模式**打开，
看起来就是一个桌面软件（无地址栏、无标签页）。

```
┌──────────────┬───────────────────────────────────────────────┐
│ ▦ 概览        │  C 盘 84.30 GB / 230 GB 已用  ● 管理员        │
│ ◆ WorkBuddy  │                                               │
│ ◇ Codex      │  [可回收合计] [安全项] [需注意] [高风险]        │
│ ▣ C 盘系统    │                                               │
│ ⚙ WinSxS     │  ○ 沙箱运行日志        安全   407 MB   ✓       │
│ ↺ 隔离区      │  ● 性能追踪（trace）   安全   417 MB   ✓       │
│ ⛨ 保护名单    │  ○ 插件市场仓库克隆     注意   145 MB          │
│              │  ○ 会话改动备份        危险   1.3 GB           │
│ 只清理N天前的 │                                               │
│ 永久删除 [?]  │  已选 5 项  1.02 GB        [预览][执行清理]     │
└──────────────┴───────────────────────────────────────────────┘
```

界面能力：

- **点选式清理**：整行可点勾选，风险等级用颜色区分，展开可看目标路径与影响
- **实时进度**：扫描与清理进度通过 SSE 推送，日志抽屉里逐条可见
- **预览 + 二次确认**：执行前弹出清单，隔离区模式要输 `CLEAN`，永久删除要输 `DELETE`
- **隔离区管理**：列出每个批次，一键还原或永久删除
- **WinSxS 面板**：DISM 分析 / 标准清理 / 深度清理，危险操作要输 `DANGER`
- **一键提权**：顶栏显示权限状态，普通用户点一下就能以管理员身份另开窗口
- **深链**：地址栏 `#workbuddy` / `#trash` / `#winsxs` 可直接进入对应页面

想一步到位就用 **`ui-admin.bat`**（自动弹 UAC）。
不想用应用窗口（比如想放浏览器标签页里）就 `python wbcleaner_ui.py --browser`。

> 界面只监听 `127.0.0.1`，并且每次启动生成随机令牌，链接里带着令牌才能访问接口；
> 静态前端资源不含任何数据，无需令牌。API 一律校验令牌。

### 方式二：终端菜单

双击 **`run.bat`**（会自动弹 UAC 提权）→ 进入交互菜单。

```
  [1] 清理 WorkBuddy 文件
  [2] 清理 Codex 文件
  [3] 清理 C 盘无用文件
  [4] 一次扫描全部并生成 HTML 报告
  [5] 隔离区管理（还原 / 永久删除）
  [6] WinSxS 组件存储（DISM 分析 / 清理）
  [7] 环境自检
  [0] 退出
```

只想看看能清多少（不需要管理员、绝对只读）：双击 **`run-scan.bat`**，
会在浏览器打开 `reports/scan.html`。

### 命令行

```bash
python wbcleaner.py                                   # 交互菜单
python wbcleaner_ui.py                                # 可视化界面（应用窗口）
python wbcleaner_ui.py --port 8800 --no-browser        # 指定端口、不自动开窗
python wbcleaner.py scan --html reports/scan.html     # 只读扫描 + HTML 报告
python wbcleaner.py doctor                            # 环境自检

# 清理（默认进隔离区，可还原）
python wbcleaner.py clean --only safe --yes           # 清理全部安全项
python wbcleaner.py clean --group workbuddy --only default --yes
python wbcleaner.py clean --rids wb-logs-sandbox,cx-tmp --yes
python wbcleaner.py clean --group system --only all --yes --no-confirm

python wbcleaner.py trash list                        # 查看隔离区
python wbcleaner.py trash restore 20261001-150000      # 还原
python wbcleaner.py trash purge 20261001-150000        # 永久删除该批次
python wbcleaner.py trash purge                       # 清空全部隔离区

python wbcleaner.py dism analyze                      # 分析 WinSxS（只读）
python wbcleaner.py dism cleanup                      # 标准清理
python wbcleaner.py dism resetbase                    # 深度清理（不可逆）

python tests/selftest.py                              # 43 项自检
python tests/uitest.py                                # 49 项界面服务集成测试（只读 + 演练）
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--only safe\|all\|default` | 按等级选择清理项；`default` = 规则表里预勾选的安全项 |
| `--rids a,b,c` | 精确指定规则 id（`scan` 输出里有） |
| `--days N` | 只清理 N 天前的数据，覆盖规则默认阈值 |
| `--permanent` | 直接永久删除，**不进隔离区** |
| `--dry-run` | 演练：只列出要做什么，不做任何修改 |
| `--yes` | 跳过最终确认（脚本化时用） |

---

## 目录结构

```
wb-cleaner/
├── wbcleaner.py          # 终端主程序：菜单 + 子命令
├── wbcleaner_ui.py       # 可视化界面入口（起本地服务 + 打开应用窗口）
├── wbc/
│   ├── util.py           # 路径/体积/权限/日志/安全守卫
│   ├── rules.py          # ★ 全部清理规则 + 保护名单（要改行为改这里）
│   ├── scanner.py        # 扫描引擎（只读）
│   ├── executor.py       # 执行引擎（隔离区 / 还原 / 永久删除）
│   ├── syswin.py         # DISM、Windows 更新缓存、回收站、休眠文件
│   ├── webui.py          # 本地 HTTP 服务 + JSON API + SSE（界面后端）
│   └── report.py         # HTML / JSON 报告
├── web/                  # ★ 界面前端（纯静态，无框架、无外部依赖）
│   ├── index.html
│   ├── app.css
│   ├── app.js
│   └── app-icon.png      # 界面用图标（favicon + 顶栏 logo，由 make_icon.py 生成）
├── icon/                 # ★ 应用图标
│   ├── app-icon.ico      # 快捷方式图标（9 尺寸：16~256）
│   ├── app-icon.png      # 1024 母版
│   ├── preview.html      # 各尺寸真机观感预览
│   ├── make_icon.py      # 从 AI 原图重建图标并打包 ico
│   └── raw/              # AI 生成的原始图
├── tools/
│   └── make_shortcut.py  # 可选：在桌面建带图标的快捷方式
├── tests/
│   ├── selftest.py       # 43 项：规则 / 守卫 / 隔离还原闭环 / 格式串
│   └── uitest.py         # 53 项：token 校验 / 各 API / SSE / dry-run / 前端静态一致性
├── reports/              # 生成的扫描报告
├── logs/                 # 操作日志
├── ui.bat                # 可视化界面（推荐）
├── ui-admin.bat          # 可视化界面（自动提权）
├── run.bat               # 终端菜单（自动提权）
├── run-scan.bat          # 只扫描（无需管理员）
└── make-shortcut.bat     # 建桌面快捷方式（可选）
```

## 自定义规则

编辑 `wbc/rules.py`：

```python
_r("my-rule", "workbuddy", "我的清理项", "contents",
   [r"~/.workbuddy/some-cache"],
   level="safe",            # keep / safe / caution / danger
   min_age_days=7,          # 只清 7 天前的
   default_on=True,
   desc="这是什么", impact="删了会怎样")
```

`kind` 支持 `contents`（清空目录内容）、`subdirs`（按子目录清理）、
`dir`（整个目录）、`glob`（按模式匹配文件）、`action`（系统动作）、`report`（仅统计）。

改完跑 `python tests/selftest.py`（43 项，含「可删路径与保护名单无重叠」等护栏），
再跑 `python tests/uitest.py`（49 项，含界面服务与前端静态一致性检查）。
新增动作记得在 `wbc/syswin.py` 的 `ACTIONS` 里注册，两个测试都会检查完整性。

## 界面 API（想自己接别的前端可以用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/env` | 权限、磁盘、隔离区、DISM 分析结果 |
| GET | `/api/scan/cached` | 最近一次扫描结果（内存缓存） |
| POST | `/api/scan` | 起扫描任务，返回 `{job}` |
| GET | `/api/events?job=<id>` | SSE 事件流：`progress` / `log` / `done` / `error`，结束发 `end` |
| POST | `/api/clean` | `{rids, permanent, dryRun, days, allowSystem}` |
| POST | `/api/action` | `{action}`：`dism_analyze` / `dism_cleanup` / `dism_resetbase` / `recyclebin` / `wu_cache` / `hibernate_off` |
| GET | `/api/trash` | 隔离区批次列表 |
| POST | `/api/trash/restore` \| `/api/trash/purge` | `{ts}` |
| GET | `/api/rules` \| `/api/protected` | 规则表 / 保护名单 |
| POST | `/api/report` | 用最近一次扫描生成 HTML 报告 |
| POST | `/api/elevate` | 以管理员身份另起一个实例 |
| POST | `/api/shutdown` | 关闭服务 |

除静态资源与报告文件外，所有接口都要带 `?t=<令牌>`（启动时打印在控制台）。

---

## 注意事项

- **`--permanent` 不可恢复**。不确定时不要加，隔离区用着更放心。
- **`dism resetbase` 不可逆**：之后所有已安装的 Windows 更新都无法卸载。
  建议系统稳定运行 1~2 周、确认不打算回退更新后再做。
- **休眠文件 12.73 GB**：关闭后不能用「休眠」，Windows「快速启动」也失效
  （`powercfg /h on` 可恢复）。收益巨大但属于功能取舍，请自行判断。
- **`~/.workbuddy/workspace/sessions`（1.3 GB）** 是会话的改动备份，
  删掉会失去「回滚这次 AI 改动」的能力，标记为「危险」且默认不勾选。
- 被程序占用的文件会自动跳过（不是报错），需要先关掉对应程序再清理。

## 环境要求

Windows 10/11，Python 3.8+（脚本用到 `dataclasses`）。**只用标准库，无需 pip 安装任何依赖。**
`run.bat` 会自动优先使用 `~/.workbuddy/binaries/python/versions/` 下的托管 Python。
