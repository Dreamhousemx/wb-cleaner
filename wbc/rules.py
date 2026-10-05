# -*- coding: utf-8 -*-
"""清理规则表。

每条规则描述「一个可清理目标」以及它的风险等级、年龄门槛与清理方式。
所有路径都基于真实扫描结果（2026-10-01 本机实测），不是凭空猜的。

等级含义
  keep    —— 只统计展示，永不删除（运行时/凭证/内存）
  safe    —— 纯缓存、日志、临时文件，删了软件会自动重建
  caution —— 可重建但需要联网重下或会丢失历史记录，删前请确认
  danger  —— 影响较大（会话备份、休眠文件等），需要单独二次确认
"""

import os
from dataclasses import dataclass, field

from . import util

HOME = os.path.expanduser("~")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))
APPDATA = os.environ.get("APPDATA", os.path.join(HOME, "AppData", "Roaming"))
WINDIR = os.environ.get("SystemRoot", r"C:\Windows")
PROGRAMDATA = os.environ.get("ProgramData", r"C:\ProgramData")

WB = os.path.join(HOME, ".workbuddy")
CX = os.path.join(HOME, ".codex")

# DeepSeek Harness（桌面端叫 "DeepSeek Harness"，内部代号 dsh）
# 安装目录本身（如 D:\Dev Tools\DeepSeek Harness）属于程序文件，不在清理范围；
# 这里只针对用户配置目录下确实由它产生的缓存与残留。
DSH = os.path.join(HOME, ".dsh")                                   # 主目录：运行时/档案/会话
DS_KEEP = os.path.join(HOME, ".dws")                               # 身份与日志
DS_DESKTOP = os.path.join(APPDATA, "@deepseek-ai", "dsh-desktop")  # Electron 桌面端数据
DS_UPDATER = os.path.join(LOCALAPPDATA, "@deepseek-aidsh-desktop-updater")  # 更新器缓存

# 项目自身位置（用于保护所在工作区的 .workbuddy 记忆目录，不写死绝对路径）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(PROJECT_ROOT)

GROUP_TITLES = {
    "workbuddy": "1. WorkBuddy 文件清理",
    "codex": "2. Codex 文件清理",
    "deepseek": "3. DeepSeek Harness 文件清理",
    "system": "4. C 盘无用文件清理（系统级）",
}

LEVEL_ORDER = {"danger": 0, "caution": 1, "safe": 2, "keep": 3}
LEVEL_LABEL = {
    "keep": "保护",
    "safe": "安全",
    "caution": "注意",
    "danger": "危险",
}


@dataclass
class Rule:
    rid: str
    group: str
    title: str
    kind: str                      # contents | subdirs | dir | glob | action | report
    paths: list = field(default_factory=list)
    level: str = "safe"
    desc: str = ""                 # 这是什么
    impact: str = ""               # 删了会怎样
    min_age_days: int = 0          # 只清理「N 天前」的数据，0=不限
    default_on: bool = False       # 默认是否勾选
    requires_admin: bool = False
    action: str = ""               # 系统动作标识
    name_glob: str = ""            # subdirs/glob 的名称过滤
    skip_names: tuple = ()         # subdirs 里要跳过的名字
    protected: bool = False        # 保护项（只展示）
    frees_space: bool = True       # 是否计入「可回收空间」（只读分析类为 False）
    exclusive_group: str = ""      # 互斥组：同组内只按最大的一个计入总量

    @property
    def level_label(self):
        return LEVEL_LABEL.get(self.level, self.level)


def _r(*args, **kwargs):
    return Rule(*args, **kwargs)


# ==================================================================== 保护名单（补充项）
# 这里只放「没有对应规则、但同样必须保护」的路径。
# 其余保护路径由规则表里 protected=True 的规则自动汇总（见文件末尾 _build_protected）。
def _user_archives():
    """个人档案目录名带会话 UUID，这里按实际情况枚举，避免写死某一个 UUID。"""
    import glob as _glob
    return sorted(_glob.glob(os.path.join(WB, "user-*")))


PROTECTED_EXTRA = [
    ("工作区记忆目录（.workbuddy/memory）", os.path.join(WORKSPACE, ".workbuddy")),
    ("项目内 .workbuddy", os.path.join(PROJECT_ROOT, ".workbuddy")),
] + [
    ("个人档案（SOUL/IDENTITY/USER/MEMORY）", p) for p in _user_archives()
] + [
    ("系统组件存储本体（须走 DISM）", os.path.join(WINDIR, "WinSxS")),
]


# ==================================================================== WorkBuddy
WORKBUDDY_RULES = [
    _r("wb-logs-sandbox", "workbuddy", "沙箱运行日志", "contents",
       [os.path.join(WB, "logs", "sandbox")],
       level="safe", min_age_days=2, default_on=True,
       desc="沙箱进程的 .log / .mmap3 运行日志，本机占 773 MB。",
       impact="无。日志仅用于排障，删后软件继续正常写新日志。"),

    _r("wb-logs-dated", "workbuddy", "按日期归档的日志", "subdirs",
       [os.path.join(WB, "logs")],
       name_glob="????-??-??*", skip_names=("sandbox", "update"),
       level="safe", min_age_days=3, default_on=True,
       desc="logs/ 下按日期切分的日志目录（含 *.expired-* 过期日志）。",
       impact="无。旧的排障信息会丢失。"),

    _r("wb-logs-app", "workbuddy", "桌面端日志", "contents",
       [os.path.join(LOCALAPPDATA, "WorkBuddy", "logs")],
       level="safe", min_age_days=3, default_on=True,
       desc="Electron 桌面端自身写的日志。",
       impact="无。"),

    _r("wb-traces", "workbuddy", "性能追踪文件（trace）", "contents",
       [os.path.join(WB, "traces")],
       level="safe", min_age_days=1, default_on=True,
       desc="Chrome DevTools 格式的性能 trace，本机 498 MB / 66 个。",
       impact="无。仅在需要分析卡顿时才会用到，可随时重新抓取。"),

    _r("wb-file-manifests", "workbuddy", "文件树清单缓存", "contents",
       [os.path.join(WB, "file-tree-manifests")],
       level="safe", min_age_days=1, default_on=True,
       desc="编辑器文件树快照，本机 82 MB。",
       impact="无。打开工作区时会重新生成，首次打开稍慢一点。"),

    _r("wb-app-cache", "workbuddy", "Electron 渲染缓存", "contents",
       [os.path.join(WB, "app", "cache"),
        os.path.join(WB, "app", "session", "Cache"),
        os.path.join(WB, "app", "session", "GPUCache"),
        os.path.join(WB, "app", "session", "Code Cache"),
        os.path.join(WB, "app", "session", "DawnWebGPUCache"),
        os.path.join(WB, "app", "session", "DawnGraphiteCache"),
        os.path.join(WB, "app", "Crashpad")],
       level="safe", default_on=True,
       desc="Chromium 的磁盘/GPU 着色器缓存，本机 74 MB。",
       impact="无。首次启动界面渲染稍慢。"),

    _r("wb-clipboard", "workbuddy", "剪贴板图片缓存", "contents",
       [os.path.join(WB, "clipboard-images")],
       level="safe", default_on=True,
       desc="粘贴进对话的图片临时副本。",
       impact="无。已发出的对话内容不受影响。"),

    _r("wb-shell-snapshots", "workbuddy", "Shell 环境快照", "contents",
       [os.path.join(WB, "shell-snapshots")],
       level="safe", default_on=True,
       desc="终端环境快照缓存。",
       impact="无。"),

    _r("wb-telemetry", "workbuddy", "待上报遥测数据", "contents",
       [os.path.join(WB, "pending-telemetry")],
       level="safe", default_on=True,
       desc="尚未发送的埋点数据。",
       impact="无。"),

    _r("wb-update-cache", "workbuddy", "更新下载缓存", "contents",
       [os.path.join(WB, "logs", "update")],
       level="safe", min_age_days=3, default_on=True,
       desc="安装包下载与更新日志。",
       impact="无。"),

    _r("wb-plugin-cache", "workbuddy", "插件包解压缓存", "contents",
       [os.path.join(WB, "plugins", "cache")],
       level="caution", default_on=False,
       desc="已安装插件的解压副本，本机 88 MB。",
       impact="下次启动对应插件时需要重新解压（可能联网重下）。"),

    _r("wb-connectors-marketplace", "workbuddy", "连接器市场索引", "contents",
       [os.path.join(WB, "connectors-marketplace")],
       level="caution", default_on=False,
       desc="连接器市场元数据缓存，本机 63 MB。",
       impact="打开连接器市场时会重新拉取。"),

    _r("wb-plugins-marketplaces", "workbuddy", "插件市场仓库克隆", "contents",
       [os.path.join(WB, "plugins", "marketplaces")],
       level="caution", default_on=False,
       desc="各市场仓库的本地克隆，本机 173 MB。",
       impact="再次浏览市场需要重新克隆（耗时 + 耗流量）。"),

    _r("wb-changes-history", "workbuddy", "文件变更历史索引", "contents",
       [os.path.join(WB, "changes-detail"), os.path.join(WB, "changes-index")],
       level="caution", min_age_days=14, default_on=False,
       desc="AI 改动文件的前后快照索引，本机 23 MB。",
       impact="「查看改动」面板只能看到最近 14 天的记录。"),

    _r("wb-file-history", "workbuddy", "文件历史快照", "contents",
       [os.path.join(WB, "file-history")],
       level="caution", min_age_days=14, default_on=False,
       desc="文件历史版本数据，本机 17 MB。",
       impact="失去 14 天前的文件历史回溯能力。"),

    _r("wb-projects-index", "workbuddy", "项目索引数据", "contents",
       [os.path.join(WB, "projects")],
       level="caution", min_age_days=14, default_on=False,
       desc="每个工作区的会话索引与元数据，本机 124 MB。",
       impact="旧项目的会话列表/索引可能需要重建。"),

    _r("wb-session-backups", "workbuddy", "会话改动备份", "subdirs",
       [os.path.join(WB, "workspace", "sessions")],
       level="danger", min_age_days=7, default_on=False,
       desc="每个会话的 modify_backup + snapfile 快照，本机 1.3 GB（最大单会话 693 MB）。",
       impact="无法再回滚这些会话做过的文件修改（撤销/差异对比失效）。"),

    _r("wb-blobs", "workbuddy", "内容 blob 存储", "contents",
       [os.path.join(WB, "blobs")],
       level="danger", min_age_days=14, default_on=False,
       desc="按内容寻址的附件/图片存储，本机 190 MB。",
       impact="历史对话里的附件、图片可能无法再打开。"),

    _r("wb-audit-log", "workbuddy", "审计日志", "contents",
       [os.path.join(WB, "audit-log")],
       level="caution", min_age_days=14, default_on=False,
       desc="工具调用审计记录。",
       impact="失去旧的操作审计追溯能力。"),

    # ---- 只展示的保护项 ----
    _r("wb-keep-runtime", "workbuddy", "托管运行时 binaries/", "report",
       [os.path.join(WB, "binaries")],
       level="keep", protected=True,
       desc="Python 3.13.12 / Node 22.22.2 / PortableGit，本机 2.0 GB。",
       impact="删除后需要重新下载安装，且当前所有脚本会立刻失效。"),

    _r("wb-keep-db", "workbuddy", "活动数据库与状态文件", "report",
       [os.path.join(WB, "local_storage"), os.path.join(WB, "connectors"),
        os.path.join(WB, "credentials"), os.path.join(WB, "security")],
       level="keep", protected=True,
       desc="SQLite 库、登录态、凭证、威胁库。",
       impact="删除会丢失登录态与授权，需要重新登录。"),
]


# ==================================================================== Codex
CODEX_RULES = [
    _r("cx-tmp", "codex", "Codex 临时目录", "contents",
       [os.path.join(CX, ".tmp")],
       level="safe", default_on=True,
       desc="市场/插件的临时解压目录，本机 77 MB。",
       impact="无。下次同步会重建。"),

    _r("cx-plugin-catalog", "codex", "远程插件目录缓存", "contents",
       [os.path.join(CX, "cache", "remote_plugin_catalog")],
       level="safe", default_on=True,
       desc="插件市场目录的 JSON 缓存，本机 28 MB。",
       impact="无。打开插件市场时重新拉取。"),

    _r("cx-apps-cache", "codex", "Apps 工具信息缓存", "contents",
       [os.path.join(CX, "cache", "codex_apps_tools"),
        os.path.join(CX, "cache", "codex_apps_server_info")],
       level="safe", default_on=True,
       desc="内置 Apps 的工具清单缓存。",
       impact="无。"),

    _r("cx-plugin-cache", "codex", "插件包缓存", "contents",
       [os.path.join(CX, "plugins", "cache")],
       level="caution", default_on=False,
       desc="已下载插件的本地副本，本机 37 MB。",
       impact="再次使用对应插件需要联网重新下载。"),

    _r("cx-install-staging", "codex", "插件安装暂存区", "contents",
       [os.path.join(CX, "plugins", ".remote-plugin-install-staging")],
       level="safe", default_on=True,
       desc="插件安装中断时残留的暂存目录。",
       impact="无。"),

    _r("cx-logs-db", "codex", "日志数据库", "glob",
       [os.path.join(CX, "logs_2.sqlite"), os.path.join(CX, "logs_2.sqlite-wal"),
        os.path.join(CX, "logs_2.sqlite-shm")],
       level="caution", default_on=False,
       desc="运行日志库，本机约 10 MB（且 WAL 已涨到 4.3 MB）。",
       impact="失去历史运行日志；Codex 下次启动会重建。"),

    _r("cx-sessions", "codex", "历史会话记录", "subdirs",
       [os.path.join(CX, "sessions"), os.path.join(CX, "archived_sessions")],
       level="caution", min_age_days=30, default_on=False,
       desc="rollout *.jsonl 会话回放文件，本机共 4 个（体积很小）。",
       impact="无法恢复 30 天前的对话上下文，收益也很小，通常不必删。"),

    _r("cx-global-state-bak", "codex", "全局状态备份文件", "glob",
       [os.path.join(CX, ".codex-global-state.json.bak")],
       level="safe", min_age_days=7, default_on=True,
       desc="状态文件的自动备份（68 KB）。",
       impact="无。当前状态文件仍在。"),

    _r("cx-models-cache", "codex", "模型清单缓存", "glob",
       [os.path.join(CX, "models_cache.json")],
       level="safe", min_age_days=7, default_on=False,
       desc="模型列表缓存（181 B）。",
       impact="无，但收益可忽略。"),

    # ---- 只展示的保护项 ----
    _r("cx-keep-appserver", "codex", "Codex 宿主可执行文件", "report",
       [os.path.join(CX, "plugins", ".plugin-appserver")],
       level="keep", protected=True,
       desc="codex.exe 等核心程序，本机 417 MB，是 Codex 目录体积的主要来源。",
       impact="删除后 Codex 完全无法启动，必须重装。"),

    _r("cx-keep-db", "codex", "活动状态库", "report",
       [os.path.join(CX, "auth.json"), os.path.join(CX, "config.toml"),
        os.path.join(CX, "sqlite"), os.path.join(CX, "skills"),
        os.path.join(CX, "memories_1.sqlite")],
       level="keep", protected=True,
       desc="授权、配置、记忆库、技能。",
       impact="删除会掉登录、丢配置与记忆。"),
]


# ==================================================================== DeepSeek Harness
# 本机实测（2026-10-01）：~/.dsh 709 MB、更新器缓存 552 MB、桌面端数据 27 MB，
# 合计约 1.29 GB；安装目录（D:\Dev Tools\DeepSeek Harness，1.2 GB）属程序文件，不清理。
DEEPSEEK_RULES = [
    # ---------- 更新器残留（本机最大的一块，552 MB）----------
    _r("ds-updater-installer", "deepseek", "更新器缓存的安装包", "glob",
       [os.path.join(DS_UPDATER, "installer.exe"),
        os.path.join(DS_UPDATER, "current.blockmap")],
       level="safe", default_on=True,
       desc="更新器下载并执行过的完整安装包副本（本机 289 MB）+ 差分校验文件。",
       impact="无。已安装的程序不受影响；只有再次升级或修复安装时需要重新下载约 290 MB。"),

    _r("ds-updater-pending", "deepseek", "待安装的更新包", "contents",
       [os.path.join(DS_UPDATER, "pending")],
       level="safe", default_on=True,
       desc="更新器已下载、等待安装的更新包（本机 276 MB）。"
            "实测当前躺在里面的是 0.2.0-rc.1，而系统里已装的是 0.2.0-rc.2——"
            "是上一轮升级留下的旧包。",
       impact="无。若恰好有更新正在下载，那份会被丢弃并在下次更新时重新下载。"),

    # ---------- 桌面端缓存 ----------
    _r("ds-electron-cache", "deepseek", "桌面端渲染缓存", "contents",
       [os.path.join(DS_DESKTOP, "Cache"),
        os.path.join(DS_DESKTOP, "Code Cache"),
        os.path.join(DS_DESKTOP, "GPUCache"),
        os.path.join(DS_DESKTOP, "DawnGraphiteCache"),
        os.path.join(DS_DESKTOP, "DawnWebGPUCache")],
       level="safe", default_on=True,
       desc="Electron/Chromium 的磁盘缓存、GPU 着色器缓存，本机约 26 MB。",
       impact="无。首次启动界面渲染稍慢，之后自动重建。"),

    _r("ds-dictionaries", "deepseek", "拼写检查词典", "contents",
       [os.path.join(DS_DESKTOP, "Dictionaries")],
       level="safe", default_on=True,
       desc="输入框拼写检查用的词典文件（en-US-10-1.bdic，本机 444 KB）。",
       impact="无。下次使用拼写检查时自动重新下载。"),

    _r("ds-shared-dict", "deepseek", "共享字典缓存", "contents",
       [os.path.join(DS_DESKTOP, "Shared Dictionary")],
       level="safe", default_on=True,
       desc="Chromium 共享字典（压缩字典）缓存。",
       impact="无。"),

    # ---------- 主目录下的缓存与回收站 ----------
    _r("ds-sessions-trash", "deepseek", "已删除会话的回收站", "contents",
       [os.path.join(DSH, "sessions-trash")],
       level="safe", default_on=True,
       desc="在 Harness 里删掉的会话会被移到这里暂存，本机 612 KB。",
       impact="无。这些会话本就已经被标记删除；清掉后无法再从回收站恢复它们。"),

    _r("ds-projcache", "deepseek", "会话项目缓存", "contents",
       [os.path.join(DSH, "storages", "session_projcache")],
       level="safe", default_on=True,
       desc="会话的项目索引缓存，本机 1.4 MB。",
       impact="无。打开项目时会重新扫描建立。"),

    _r("ds-market-cache", "deepseek", "插件市场缓存", "glob",
       [os.path.join(DSH, "profiles", "desktop", ".dsh-market", "discovery-compatibility-v1.json"),
        os.path.join(DSH, "profiles", "desktop", ".dsh-market", "log.ndjson")],
       level="safe", default_on=True,
       desc="插件市场的发现清单缓存与操作日志（73 KB + 9 KB）。",
       impact="无。打开市场时会重新拉取。"),

    _r("ds-plugin-manager-logs", "deepseek", "插件管理器日志", "contents",
       [os.path.join(DSH, "profiles", "desktop", ".plugin-manager", "logs")],
       level="safe", default_on=True,
       desc="插件管理器的运行日志。",
       impact="无。"),

    _r("ds-dws-logs", "deepseek", "身份服务日志", "contents",
       [os.path.join(DS_KEEP, "logs")],
       level="safe", default_on=True,
       desc="~/.dws 下的日志目录（本机为空，日志会随使用增长）。",
       impact="无。"),

    _r("ds-usage-backup", "deepseek", "用量统计的备份副本", "glob",
       [os.path.join(DSH, ".dsh-usage-ledger.json.bak"),
        os.path.join(DSH, ".dsh-usage-stats.json.bak")],
       level="safe", min_age_days=7, default_on=True,
       desc="用量账本与统计的自动备份文件（各一份，共约 24 KB）。",
       impact="无。正式文件仍在，备份只是上一版副本。"),

    # ---------- 需要手动确认的 ----------
    _r("ds-plugin-node-modules", "deepseek", "插件依赖 node_modules", "contents",
       [os.path.join(DSH, "profiles", "desktop", "node_modules")],
       level="caution", default_on=False,
       desc="桌面端插件运行所需的 npm 依赖，本机约 393 MB"
            "（含 sharp 的 libvips、mermaid 等大体积包）。",
       impact="删除后插件会启动失败，需要重新联网执行 pnpm install 才能恢复"
              "（依赖网络与镜像速度，可能耗时较久）。默认不勾选。"),

    _r("ds-sessions", "deepseek", "历史会话记录", "subdirs",
       [os.path.join(DSH, "sessions")],
       level="caution", min_age_days=30, default_on=False,
       desc="按项目组织的会话历史（本机仅 3.8 MB）。",
       impact="失去 30 天前的对话记录与上下文回溯，收益很小，通常不必删。"),

    # ---------- 只展示的保护项 ----------
    _r("ds-keep-runtime", "deepseek", "内置运行时 dsh-runtimes/", "report",
       [os.path.join(DSH, "dsh-runtimes")],
       level="keep", protected=True,
       desc="Harness 自带的 Node 24 / pnpm / Python 3.12 与 numpy、pandas、"
            "Pillow 等依赖，本机 289 MB。",
       impact="⚠️ 删除后 Harness 完全无法运行，必须重装。"),

    _r("ds-keep-credentials", "deepseek", "凭证与身份", "report",
       [os.path.join(DSH, ".credentials.yaml"),
        os.path.join(DSH, ".anonymous-user-id"),
        os.path.join(DS_KEEP, "identity.json")],
       level="keep", protected=True,
       desc="登录凭证与匿名身份标识。",
       impact="⚠️ 删除会掉登录，需要重新授权。"),

    _r("ds-keep-plugins", "deepseek", "已装插件目录（含符号链接）", "report",
        [os.path.join(DSH, "profiles", "desktop", "plugins")],
        level="keep", protected=True,
        desc="已安装插件的挂载点。该目录（或 node_modules 里）可能含指向"
             "「会话归档目录」等真实用户数据的符号链接/junction。本机该目录为空，"
             "链接位于 profiles/desktop/node_modules 下。",
        impact="⚠️ 千万不要删：顺着链接会把你的真实数据目录一起清掉。"),

    _r("ds-keep-desktop-state", "deepseek", "桌面端登录态与配置", "report",
       [os.path.join(DS_DESKTOP, "Local Storage"),
        os.path.join(DS_DESKTOP, "Session Storage"),
        os.path.join(DS_DESKTOP, "WebStorage"),
        os.path.join(DS_DESKTOP, "Network"),
        os.path.join(DS_DESKTOP, "Preferences"),
        os.path.join(DS_DESKTOP, "Local State")],
       level="keep", protected=True,
       desc="窗口里的登录态、Cookie、本地存储与偏好设置。",
       impact="⚠️ 删除会掉登录并重置界面设置。"),

    _r("ds-keep-workspace", "deepseek", "默认工作区与会话归档", "report",
       [os.path.join(HOME, "Documents", "deepseek-harness")],
       level="keep", protected=True,
       desc="Harness 的默认工作区目录（当前为空目录，是本机用户数据位置）。",
       impact="⚠️ 这是你的数据目录，不是缓存。"),
]

# ------------------------------------------------------------------ 链接探测
# junction / 符号链接不是普通目录：删「目录」的常规做法会顺着链接删到目标去。
# 这里在启动时探测一遍，把真实存在的链接显式写进规则说明，避免出现
# 「说明里写 A、实际链接在 B」这种会随时间失效的硬编码描述。
_LINK_SCAN = [
    (os.path.join(DSH, "profiles", "desktop", "node_modules"), "node_modules"),
    (os.path.join(DSH, "profiles", "desktop", "plugins"), "plugins"),
]


def _list_links(root, limit=3):
    """root 下第一层的链接 / junction 名字（不递归）。"""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if util.is_link(os.path.join(root, n))][:limit]


def _apply_link_notes():
    """把探测到的链接信息追加到相关规则说明里（没有链接就不改）。"""
    found = [(label, _list_links(root)) for root, label in _LINK_SCAN]
    note = "".join("、".join("%s/%s" % (label, n) for n in names) + "；"
                   for label, names in found if names)
    if not note:
        return
    suffix = (" ⚠ 本机检测到链接/junction：%s它们只是链接，指向的真实数据在别处；"
              "本工具只移除链接本身，不会跟随。" % note)
    for rule in DEEPSEEK_RULES:
        if rule.rid in ("ds-plugin-node-modules", "ds-keep-plugins"):
            rule.desc += suffix


_apply_link_notes()


# ==================================================================== 系统（C 盘）
SYSTEM_RULES = [
    # ---------- WinSxS / DISM ----------
    _r("sys-dism-analyze", "system", "分析 WinSxS 组件存储（只读）", "action",
       [], action="dism_analyze", level="safe", requires_admin=True,
       frees_space=False, exclusive_group="winsxs",
       desc="执行 DISM /Online /Cleanup-Image /AnalyzeComponentStore，"
            "本机测得：实际 12.37 GB，其中「备份和已禁用功能」3.86 GB 可回收。",
       impact="只读分析，不做任何修改、不释放空间。"),

    _r("sys-dism-cleanup", "system", "清理 WinSxS 组件存储（DISM）", "action",
       [], action="dism_cleanup", level="caution", requires_admin=True,
       exclusive_group="winsxs",
       desc="执行 DISM /Online /Cleanup-Image /StartComponentCleanup，"
            "清理被取代的组件版本。这是清理 WinSxS 的官方唯一正确方式——"
            "手工删除 WinSxS 里的文件会让系统更新和修复彻底失效。",
       impact="已安装的更新无法再卸载回滚，但系统功能不受影响。"),

    _r("sys-dism-resetbase", "system", "WinSxS 深度清理（/ResetBase）", "action",
       [], action="dism_resetbase", level="danger", requires_admin=True,
       exclusive_group="winsxs",
       desc="在 StartComponentCleanup 基础上追加 /ResetBase，"
            "额外回收所有被取代组件的备份，通常能再多释放 1~3 GB。"
            "与「标准清理」互斥，可回收量按最大者计。",
       impact="⚠️ 不可逆：之后所有已安装的 Windows 更新都无法卸载。"
              "确认系统稳定运行 1~2 周后再做。"),

    # ---------- Windows 更新缓存 ----------
    _r("sys-wu-download", "system", "Windows 更新下载缓存", "action",
       [], action="wu_cache", level="caution", requires_admin=True,
       desc="停止 wuauserv/bits 后清空 SoftwareDistribution\\Download，"
            "本机约 13 MB（下载中的更新会被丢弃，之后重新下载）。",
       impact="正在进行的更新下载作废，需重新下载。"),

    _r("sys-wu-datastore", "system", "Windows 更新数据库", "contents",
       [os.path.join(WINDIR, "SoftwareDistribution", "DataStore")],
       level="danger", requires_admin=True, default_on=False,
       desc="更新历史与扫描结果数据库，本机 44 MB。",
       impact="丢失更新历史记录，下次扫描会变慢。收益低，不建议删。"),

    # ---------- 临时文件 ----------
    _r("sys-temp-user", "system", "用户临时文件 %TEMP%", "contents",
       [os.path.join(LOCALAPPDATA, "Temp")],
       level="safe", min_age_days=1, default_on=True,
       desc="用户级临时文件，本机 114 MB。被占用的文件会自动跳过。",
       impact="无。正在运行的程序占用的文件不会被删除。"),

    _r("sys-temp-win", "system", "系统临时文件 Windows\\Temp", "contents",
       [os.path.join(WINDIR, "Temp")],
       level="safe", min_age_days=1, default_on=True, requires_admin=True,
       desc="系统级临时文件（本机仅 12 KB）。",
       impact="无。"),

    _r("sys-crashdumps", "system", "崩溃转储文件", "contents",
       [os.path.join(LOCALAPPDATA, "CrashDumps")],
       level="safe", default_on=True,
       desc="程序崩溃时的内存转储，本机 13 MB。",
       impact="无。除非正在排查崩溃原因。"),

    _r("sys-wer", "system", "Windows 错误报告", "contents",
       [os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "WER"),
        os.path.join(PROGRAMDATA, "Microsoft", "Windows", "WER")],
       level="safe", min_age_days=7, default_on=True,
       desc="应用错误上报的缓存与报告。",
       impact="无。"),

    # ---------- 包管理缓存 ----------
    _r("sys-pip-cache", "system", "pip 下载缓存", "contents",
       [os.path.join(LOCALAPPDATA, "pip", "Cache")],
       level="safe", default_on=True,
       desc="Python 包 wheel 缓存，本机 226 MB。",
       impact="以后再装同样的包需要重新下载。已安装的包不受影响。"),

    _r("sys-npm-cache", "system", "npm 下载缓存", "contents",
       [os.path.join(LOCALAPPDATA, "npm-cache"), os.path.join(APPDATA, "npm-cache")],
       level="safe", default_on=True,
       desc="Node 包 tarball 缓存，本机 253 MB。",
       impact="以后 npm install 需要重新下载。已安装的 node_modules 不受影响。"),

    _r("sys-uv-cache", "system", "uv 下载缓存", "contents",
       [os.path.join(LOCALAPPDATA, "uv", "cache")],
       level="safe", default_on=True,
       desc="uv 的包缓存，本机 31 MB。",
       impact="下次 uv 安装包需重新下载。"),

    # ---------- 浏览器 / 系统 UI 缓存 ----------
    _r("sys-inetcache", "system", "IE/系统网络缓存", "contents",
       [os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "INetCache")],
       level="safe", default_on=True,
       desc="WinINet 网络缓存。",
       impact="无。"),

    _r("sys-webcache", "system", "WebCache 数据库", "contents",
       [os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "WebCache")],
       level="caution", default_on=False, requires_admin=True,
       desc="系统 Web 缓存数据库，本机 36 MB。",
       impact="需要先停止 explorer 相关占用，可能影响正在运行的资源管理器。"),

    _r("sys-thumbnails", "system", "缩略图 / 图标缓存", "glob",
       [os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "Explorer", "thumbcache_*.db"),
        os.path.join(LOCALAPPDATA, "Microsoft", "Windows", "Explorer", "iconcache_*.db")],
       level="caution", default_on=False,
       desc="资源管理器缩略图与图标缓存，本机 13 MB。",
       impact="需要重启资源管理器才能完全释放，之后缩略图会重新生成。"),

    _r("sys-prefetch", "system", "预读取文件 Prefetch", "contents",
       [os.path.join(WINDIR, "Prefetch")],
       level="caution", default_on=False, requires_admin=True,
       desc="程序启动预读数据，本机 18 MB。",
       impact="刚清理后开机会略慢，几天后自动恢复。收益小。"),

    _r("sys-win-logs", "system", "Windows 日志", "contents",
       [os.path.join(WINDIR, "Logs")],
       level="caution", min_age_days=14, default_on=False, requires_admin=True,
       desc="CBS/DISM 等系统日志，本机 19 MB。",
       impact="丢失系统排障日志。"),

    _r("sys-delivery-optimization", "system", "传递优化缓存", "contents",
       [os.path.join(WINDIR, "SoftwareDistribution", "DeliveryOptimization"),
        os.path.join(PROGRAMDATA, "Microsoft", "Windows", "DeliveryOptimization")],
       level="caution", default_on=False, requires_admin=True,
       desc="更新分发的 P2P 缓存（本机几乎为空）。",
       impact="无，但通常也没什么可回收的。"),

    # ---------- 系统级动作 ----------
    _r("sys-recyclebin", "system", "清空回收站", "action",
       [], action="recyclebin", level="caution",
       desc="清空所有盘的回收站（本机 318 KB，几乎为空）。",
       impact="回收站里的文件将无法还原。"),

    _r("sys-windows-old", "system", "旧版 Windows 备份 Windows.old", "dir",
       [os.path.join(WINDIR, "..", "Windows.old")],
       level="danger", requires_admin=True, default_on=False,
       desc="系统大版本升级后残留的旧系统目录（本机不存在）。",
       impact="⚠️ 删除后无法回退到升级前的 Windows 版本。"),

    _r("sys-hibernate", "system", "休眠文件 hiberfil.sys", "action",
       [], action="hibernate_off", level="danger", requires_admin=True,
       desc="本机 hiberfil.sys 占 13 GB（等于内存容量左右）。"
            "执行 powercfg /h off 可立即释放。",
       impact="⚠️ 关闭休眠后不能用「休眠」，Windows 的「快速启动」也会失效。"
              "随时可用 powercfg /h on 恢复。"),

    # ---------- 只展示 ----------
    _r("sys-keep-installer", "system", "系统安装缓存 Windows\\Installer", "report",
       [os.path.join(WINDIR, "Installer")],
       level="keep", protected=True,
       desc="MSI 安装包缓存，本机 170 MB。",
       impact="⚠️ 不要删除！删了会导致软件无法卸载/修复/升级。"),

    _r("sys-keep-paging", "system", "页面文件与交换文件", "report",
       [r"C:\pagefile.sys", r"C:\swapfile.sys"],
       level="keep", protected=True,
       desc="虚拟内存文件，本机 pagefile 5 GB + swapfile 16 MB。",
       impact="⚠️ 不要删除，改由系统「虚拟内存」设置管理。"),
]


ALL_RULES = WORKBUDDY_RULES + CODEX_RULES + DEEPSEEK_RULES + SYSTEM_RULES

RULES_BY_GROUP = {
    "workbuddy": WORKBUDDY_RULES,
    "codex": CODEX_RULES,
    "deepseek": DEEPSEEK_RULES,
    "system": SYSTEM_RULES,
}

RULES_BY_ID = {r.rid: r for r in ALL_RULES}


def _build_protected():
    """保护名单 = 显式补充路径 + 所有 protected=True 规则的路径。

    单一事实来源：给规则打上 protected=True，它就自动进 guard() 用的保护名单，
    不需要在保护名单里再抄一遍。之前两处各写一份，DeepSeek 那批规则就漏了——
    界面上显示"保护"，实际删除时却拦不住，等于没有保护。
    """
    seen, out = set(), []
    candidates = list(PROTECTED_EXTRA)
    for r in ALL_RULES:
        if r.protected:
            for p in r.paths:
                candidates.append((r.title, p))
    for label, p in candidates:
        key = util.norm_key(p)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((label, p))
    return out


PROTECTED = _build_protected()

# 「软件清理」分组：这些组面向具体软件，默认勾选必须严格限制在 safe 级，
# 也就是「删掉不会影响软件正常使用」的那些。caution / danger 一律默认不勾，
# 由用户在界面上看清影响说明后手动选择（见 tests/selftest.py 的强制校验）。
SOFTWARE_GROUPS = ("workbuddy", "codex", "deepseek")


def default_on_violations():
    """返回所有「非安全级却默认勾选」的规则——这是必须为零的名单。"""
    return [r for r in ALL_RULES
            if r.default_on and r.level not in ("safe",)
            and not r.protected and r.kind != "report"]


def unchecked_but_actionable(rules):
    """需要用户手动勾选的项（默认关闭且确实有内容可清）。"""
    return [r for r in rules if not r.default_on and not r.protected
            and r.kind != "report"]


def group_rules(group, include_protected=False):
    rules = RULES_BY_GROUP.get(group, [])
    if include_protected:
        return list(rules)
    return [r for r in rules if not r.protected and r.kind != "report"]


def protected_rules(group=None):
    return [r for r in ALL_RULES if r.protected or r.kind == "report"
            if group is None or r.group == group]
