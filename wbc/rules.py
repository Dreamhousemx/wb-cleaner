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

# 项目自身位置（用于保护所在工作区的 .workbuddy 记忆目录，不写死绝对路径）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(PROJECT_ROOT)

GROUP_TITLES = {
    "workbuddy": "1. WorkBuddy 文件清理",
    "codex": "2. Codex 文件清理",
    "system": "3. C 盘无用文件清理（系统级）",
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


# ==================================================================== 保护名单
# 任何情况下都不允许清理的位置（既是文档也是运行时判据）
def _user_archives():
    """个人档案目录名带会话 UUID，这里按实际情况枚举，避免写死某一个 UUID。"""
    import glob as _glob
    return sorted(_glob.glob(os.path.join(WB, "user-*")))


PROTECTED = [
    ("工作区记忆目录（.workbuddy/memory）", os.path.join(WORKSPACE, ".workbuddy")),
    ("项目内 .workbuddy", os.path.join(PROJECT_ROOT, ".workbuddy")),
] + [
    ("个人档案（SOUL/IDENTITY/USER/MEMORY）", p) for p in _user_archives()
] + [
    ("凭证目录", os.path.join(WB, "credentials")),
    ("本机连接器配置", os.path.join(WB, "connectors")),
    ("本地登录态存储", os.path.join(WB, "local_storage")),
    ("托管运行时（Python/Node/Git）", os.path.join(WB, "binaries")),
    ("安全威胁库", os.path.join(WB, "security")),
    ("Codex 授权文件", os.path.join(CX, "auth.json")),
    ("Codex 配置文件", os.path.join(CX, "config.toml")),
    ("Codex 宿主程序", os.path.join(CX, "plugins", ".plugin-appserver")),
    ("Codex 技能目录", os.path.join(CX, "skills")),
    ("Codex 记忆库", os.path.join(CX, "memories_1.sqlite")),
    ("系统组件存储本体（须走 DISM）", os.path.join(WINDIR, "WinSxS")),
    ("系统安装缓存（删了卸载/修复会失败）", os.path.join(WINDIR, "Installer")),
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


ALL_RULES = WORKBUDDY_RULES + CODEX_RULES + SYSTEM_RULES

RULES_BY_GROUP = {
    "workbuddy": WORKBUDDY_RULES,
    "codex": CODEX_RULES,
    "system": SYSTEM_RULES,
}

RULES_BY_ID = {r.rid: r for r in ALL_RULES}


def group_rules(group, include_protected=False):
    rules = RULES_BY_GROUP.get(group, [])
    if include_protected:
        return list(rules)
    return [r for r in rules if not r.protected and r.kind != "report"]


def protected_rules(group=None):
    return [r for r in ALL_RULES if r.protected or r.kind == "report"
            if group is None or r.group == group]
