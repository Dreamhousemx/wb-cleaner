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

## 四大功能

| 功能 | 覆盖内容 | 本次实测可回收（其中安全项） |
|---|---|---|
| **1. 清理 WorkBuddy** | 沙箱日志、按日期归档日志、trace 性能文件、文件树清单、Electron 缓存、剪贴板图片、插件/市场缓存、会话改动备份、blob 存储 | **1.24 GB**（991 MB） |
| **2. 清理 Codex** | `.tmp` 临时目录、远程插件目录缓存、插件包缓存、日志数据库、会话回滚文件、状态备份 | **141 MB**（96.8 MB） |
| **3. 清理 DeepSeek Harness** | 更新器残留安装包、桌面端渲染缓存、会话回收站、项目缓存、插件市场缓存 | **964 MB**（579 MB） |
| **4. 清理 C 盘无用文件** | **WinSxS（DISM 官方方式）**、Windows 更新缓存、`%TEMP%`、系统临时文件、崩溃转储、WER、pip/npm/uv 包缓存、浏览器与系统缓存、回收站、休眠文件 | **18.26 GB**（516 MB） |

合计约 **20.6 GB**（其中休眠文件 12.73 GB、WinSxS 3.86 GB）。

### 默认勾选策略（重要）

**只有「安全」级项目默认勾选**——也就是删掉不会影响软件正常使用的那一类
（纯缓存、日志、临时文件、更新器残留）。

「注意」和「高风险」一律**默认不勾选**，需要你在界面上看清影响说明后手动选择。
界面上这类条目会带 `需手动勾选` 标签，并在行的下方直接写明影响，例如：

```
注意  插件依赖 node_modules        385 MB   [需手动勾选]
      ⚠ 删除后插件会启动失败，需要重新联网执行 pnpm install 才能恢复
```

默认勾选的项在数据里也必须有明确的「影响」说明；规则表里任何
「非安全级却默认勾选」的写法都会让测试直接失败（`tests/selftest.py [11]`）。
系统级分组（C 盘）同样遵循这个策略：DISM 清理、休眠文件、回收站都是手动勾选。

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

### 关于 DeepSeek Harness

它的空间分三块，本工具只碰用户配置目录下的缓存与残留：

| 位置 | 本机体积 | 处理 |
|---|---|---|
| 更新器缓存 `%LOCALAPPDATA%\@deepseek-aidsh-desktop-updater` | 552 MB | 清理（含一份 289 MB 安装包 + 一份 276 MB 旧版更新包） |
| 主目录 `~/.dsh` | 709 MB | 只清缓存；运行时 272 MB 与凭证进保护名单 |
| 桌面端数据 `%APPDATA%\@deepseek-ai\dsh-desktop` | 27 MB | 只清渲染缓存；登录态与 Cookie 进保护名单 |
| 安装目录（如 `D:\Dev Tools\DeepSeek Harness`） | 1.2 GB | **不处理**——属程序文件 |

⚠️ 两个坑写在这里提醒：

- `~/.dsh/profiles/desktop/plugins` 里有**指向你自己数据的符号链接**
  （本机是 `archived-sessions` → 你的会话归档目录）。整个 `plugins` 目录在保护名单里，
  顺着链接删会把真实数据一起清掉。
- 更新器的 `pending/` 里当前躺的是 `0.2.0-rc.1`，而系统里装的是 `0.2.0-rc.2`——
  是上一轮升级留下的旧包。判据来自 `~/.dsh/dsh-runtimes/*/runtime.json` 的 `desktopVersion`。

---

## 安全设计（这是本工具的核心）

清理工具最怕误删。本工具做了五层防护：

1. **默认只扫描**：`scan` 与交互式预览不发任何删除调用；执行前必须手工输入 `CLEAN` 确认。
2. **保护名单（单一事实来源）**：给规则打上 `protected=True`，它就**自动**进入
   `guard()` 使用的保护名单；另有 `PROTECTED_EXTRA` 补充没有对应规则的路径
   （工作区 `.workbuddy/memory`、个人档案、WinSxS 本体）。
   本机共 31 条保护路径：WorkBuddy 的运行时/凭证/登录态、Codex 的 `auth.json`/宿主程序、
   DeepSeek Harness 的内置运行时（Node/Python 272 MB）与凭证、`Windows\Installer` 等。
   ⚠️ 曾经两处各维护一份名单，导致 DeepSeek 的保护项只显示在界面上、实际拦不住——
   现在改成自动汇总并加了回归测试。
3. **正则保护层**（`util.GUARD_PATTERNS`）：不依赖具体用户名/盘符，负责挡住
   「以后才出现的目录」，例如新会话生成的 `user-<新UUID>`；同时兜住 `.git` 版本库、
   `.codex/auth.json`、`Windows\(WinSxS|Installer)` 等固定命名位置。
4. **安全守卫**（`util.guard`）：删除前逐条校验，拒绝盘根、拒绝浅层路径、
   拒绝命中保护名单或正则层的路径；命中即跳过并记录，绝不静默继续。
5. **隔离区而非直接删除**：默认把目标移动到
   `%LOCALAPPDATA%\wbcleaner\trash\<时间戳>\` 并写 `manifest.json`，
   用 `trash restore <时间戳>` 可原样还原。只有 `--permanent` 才真正删除。
6. **年龄阈值**：日志 / trace / 会话备份默认只清理 3~14 天前的数据，
   正在运行的文件会被自动跳过并写进日志。全局年龄设置（界面上的下拉框 / `--days`）
   语义是**只收紧、不放松**：取「规则自身阈值」与「全局值」的较大者。
   规则里的 `min_age_days` 表达的是「这份数据要放这么久才敢删」（比如日志要等 2 天
   避开正在运行的会话），全局参数不应该能把它调小。
7. **保护名单自动汇总**：`protected=True` 的规则路径 + `PROTECTED_EXTRA` 补充项，
   去重后构成 `guard()` 用的名单——加保护只需给规则打一个标记。

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
│ ◈ DeepSeek   │                                               │
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
  [3] 清理 DeepSeek Harness 文件
  [4] 清理 C 盘无用文件
  [5] 一次扫描全部并生成 HTML 报告
  [6] 隔离区管理（还原 / 永久删除）
  [7] WinSxS 组件存储（DISM 分析 / 清理）
  [8] 环境自检
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

python tests/selftest.py                              # 72 项自检
python tests/uitest.py                                # 64 项界面服务集成测试（只读 + 演练）
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--only safe\|all\|default` | 按等级选择清理项；`default` = 规则表里预勾选的安全项（只有安全级） |
| `--rids a,b,c` | 精确指定规则 id（`scan` 输出里有） |
| `--days N` | 全局年龄下限：只清理 N 天前的数据。**只收紧、不放松**单条规则自身阈值 |
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
│   ├── selftest.py       # 72 项：规则 / 守卫 / 隔离还原闭环 / 格式串 / 默认勾选策略
│   └── uitest.py         # 64 项：token 校验 / 各 API / SSE / dry-run / 前端静态一致性
├── reports/              # 生成的扫描报告
├── logs/                 # 操作日志
├── ui.bat                # 可视化界面（推荐）
├── ui-admin.bat          # 可视化界面（自动提权）
├── run.bat               # 终端菜单（自动提权）
├── run-scan.bat          # 只扫描（无需管理员）
└── make-shortcut.bat     # 建桌面快捷方式（可选）
```

## 自定义规则

编辑 `wbc/rules.py`（当前 62 条可清理规则 + 11 条保护项规则 = 73 条）：

```python
_r("my-rule", "workbuddy", "我的清理项", "contents",
   [r"~/.workbuddy/some-cache"],
   level="safe",            # keep / safe / caution / danger
   min_age_days=7,          # 这份数据要放 7 天才敢删（全局年龄下限只会把它调大）
   default_on=True,         # 只有 safe 级才能写 True
   desc="这是什么",
   impact="删了会怎样，会失去什么")
```

`kind` 支持 `contents`（清空目录内容）、`subdirs`（按子目录清理）、
`dir`（整个目录）、`glob`（按模式匹配文件）、`action`（系统动作）、`report`（仅统计）。

**加新软件分组的步骤**（四步，测试会检查是否漏项）：

1. `wbc/rules.py`：加 `XXX_RULES` 列表，登记进 `ALL_RULES` / `RULES_BY_GROUP` /
   `GROUP_TITLES`，如果是软件类分组还要加进 `SOFTWARE_GROUPS`
2. `wbc/scanner.py`：`scan_all()` 的默认分组元组里加上
3. `wbcleaner.py`：菜单项与 `--group` 的 `choices`
4. `web/index.html` + `web/app.js`：侧栏导航项、`VIEWS`、分组说明

改完跑 `python tests/selftest.py`（72 项，含「可删路径与保护名单无重叠」
「非安全级不得默认勾选」「本机专属路径不得硬编码」等护栏），
再跑 `python tests/uitest.py`（64 项，含界面服务与前端静态一致性检查）。
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
