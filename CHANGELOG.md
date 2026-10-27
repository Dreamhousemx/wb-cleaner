# 更新日志

本文件记录扫尘 (WBCleaner) 的版本变更。版本号遵循 `主版本.次版本.修订号`：
清理规则或行为有不兼容变化时升主版本，新增功能升次版本，修 bug 只升修订号。

---

## v1.1.0 — 2026-10-27

这个版本的重点是**安全**：修掉一个会真的删到用户数据的链接处理缺陷，并补齐了配套回归测试。

### 链接 / junction：只删链接，绝不动目标数据（重要）

Windows 目录 junction 是重解析点，但 `os.path.islink()` 对它返回 `False`、
`os.path.isdir()` 返回 `True`，看上去就是个普通目录。旧实现因此踩了两个坑：

- `clean_contents` 里的 `isdir(cp) and not islink(cp)` 判断失效，`shutil.move` 跨盘失败后
  退化成 `copytree(symlinks=True)`；而 Python 对 `IO_REPARSE_TAG_MOUNT_POINT` 硬编码
  `is_symlink=False`，于是把**链接目标的内容**当普通文件拷进隔离区，`rmtree` 再顺着链接
  清空目标，最后只留一个空链接——既虚报释放空间，又真的删掉了用户数据。
- `--permanent` 更直接：链接和目标文件一起删。

现在 `util` 新增 `is_junction` / `is_symlink` / `is_link` / `remove_link` / `prune_link_dirs`，
凡涉及删除与清点的地方统一先判链接：`remove_path`、`clean_contents`、`syswin.wu_cache`、
扫描器的 `contents`/`subdirs` 分支、`walk_stats`、`newest_mtime`。链接按「0 字节、1 个条目」
计，删除只 `os.rmdir` 掉重解析点本身；`_on_rm_error` 作为兜底，即使 `rmtree` 顺着目录走，
也只移除链接。回归测试：`tests/selftest.py [15]`。

### 新增：DeepSeek Harness 清理分组

第四个界面分组，覆盖更新器残留安装包、桌面端渲染缓存、会话回收站、项目缓存、插件市场缓存。
内置运行时 `dsh-runtimes/`、凭证、桌面端登录态与 `plugins/` 全部进保护名单
（`plugins/` 下有指向用户真实数据目录的 junction，顺着删会清掉真实数据）。

### 默认勾选策略收紧到「安全」级

规则表新增强制约束：**非 `safe` 级不得 `default_on=True`**，由 `tests/selftest.py [11]` 钉死。
其余条目在界面上标 `需手动勾选` 并在行内直接说明影响；确认弹窗逐条列出所选风险项的影响。

### 修复

- **保护名单单一事实来源**：原先 `PROTECTED` 列表与 `Rule.protected` 两处各维护一份，
  DeepSeek 的保护项只进了后者——界面上显示「保护」，`guard()` 实际拦不住。
  改为由 `protected=True` 的规则自动汇总，再加 `PROTECTED_EXTRA` 补充。
- **点 DeepSeek Harness 视图无反应**：新增视图时漏了 `renderAll()` 的 `case`，掉进 default
  分支重渲染概览。根因是分组列表散写在四处，现在收敛为单一常量 `GROUP_VIEWS`。
- **不再拦截 F5 / Ctrl+R**：原来把它俩劫持成「重新扫描」，但重新扫描不会重新加载 `app.js`，
  界面有 bug 时用户按 F5 会以为没修好。刷新是用户的救命键，重新扫描请用顶栏按钮。

### 测试

- `tests/selftest.py`：86 项（新增链接安全、全局年龄下限语义、DeepSeek 规则回归等）
- `tests/uitest.py`：93 项界面服务集成测试（只读 + 演练）
- `tests/fronttest.js`：27 项，在 Node 里真跑 `web/app.js` 逐个视图验证渲染

### 文档

- README 修正自检项数（72 → 86）、保护路径数（31 → 33）与防护层数（五层 → 七层）
- 补充桌面快捷方式的创建 / 改名 / 删除用法，以及「关窗口不会结束后台服务」的提示

---

## v1.0.0 — 2026-10-01

首个版本：WorkBuddy / Codex / C 盘 三合一清理工具，纯 Python 标准库 + 零依赖前端。

- 清理 WorkBuddy：沙箱日志、按日期归档日志、trace、Electron 缓存、剪贴板图片、
  插件与市场缓存、会话改动备份、blob 存储
- 清理 Codex：`.tmp`、远程插件目录缓存、插件包缓存、日志数据库、会话回滚、状态备份
- 清理 C 盘：WinSxS（只走 DISM 官方命令）、Windows 更新缓存、`%TEMP%`、崩溃转储、WER、
  pip/npm/uv 包缓存、浏览器缓存、回收站、休眠文件
- 安全设计：默认只扫描；执行前输入 `CLEAN` 确认，永久删除输入 `DELETE`；
  隔离区 + `manifest.json` 可一键还原；保护名单 + 正则层 + 路径深度校验 + 年龄阈值
- 界面：本地 `http.server` + 原生 HTML/CSS/JS，Edge/Chrome 应用窗口模式，
  仅监听 `127.0.0.1` 且每次启动生成随机令牌；耗时任务走 Job 线程 + SSE 推进度
- 自带桌面快捷方式工具（`tools/make_shortcut.py`）与 9 尺寸应用图标
