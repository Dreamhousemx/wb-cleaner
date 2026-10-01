# -*- coding: utf-8 -*-
"""基础工具层：路径展开、体积统计、权限检测、控制台着色、日志、安全守卫。"""

import ctypes
import datetime
import os
import re
import shutil
import stat
import sys
import time

# ---------------------------------------------------------------- 控制台


_ANSI_OK = None


def enable_ansi():
    """在 Windows 控制台打开 ANSI 转义支持（Win10+ 才有 VT 处理）。"""
    global _ANSI_OK
    if _ANSI_OK is not None:
        return _ANSI_OK
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            _ANSI_OK = False
            return False
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        _ANSI_OK = True
    except Exception:
        _ANSI_OK = False
    return _ANSI_OK


class C:
    """颜色常量。不支持 ANSI 时全部退化为空串。"""

    def __init__(self):
        ok = enable_ansi()
        self.RESET = "\033[0m" if ok else ""
        self.BOLD = "\033[1m" if ok else ""
        self.DIM = "\033[2m" if ok else ""
        self.RED = "\033[31m" if ok else ""
        self.GREEN = "\033[32m" if ok else ""
        self.YELLOW = "\033[33m" if ok else ""
        self.BLUE = "\033[34m" if ok else ""
        self.MAGENTA = "\033[35m" if ok else ""
        self.CYAN = "\033[36m" if ok else ""
        self.GRAY = "\033[90m" if ok else ""


C_ = C()


def supports_unicode_console():
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


# ---------------------------------------------------------------- 路径


def expand(path):
    """展开环境变量与 ~，统一成绝对 Windows 路径（正斜杠保留与否无所谓）。"""
    if not path:
        return ""
    p = os.path.expandvars(os.path.expanduser(path))
    return os.path.abspath(p)


def norm_key(path):
    """路径比较用的归一化 key（大小写不敏感 + 去掉末尾分隔符）。"""
    if not path:
        return ""
    p = os.path.normpath(expand(path))
    return os.path.normcase(p)


def short_path(path, limit=58):
    """把长路径缩短成 ...\\a\\b\\c 形式，便于表格显示。"""
    p = path
    home = expand("~")
    if norm_key(p).startswith(norm_key(home) + os.sep):
        p = "~" + p[len(home):]
    if len(p) <= limit:
        return p
    parts = p.replace("/", "\\").split("\\")
    out = parts[-1]
    for seg in reversed(parts[:-1]):
        cand = seg + "\\" + out
        if len(cand) + 4 > limit:
            break
        out = cand
    return "...\\" + out


def is_subpath(child, parent):
    """child 是否等于或位于 parent 之下。"""
    c, p = norm_key(child), norm_key(parent)
    if not c or not p:
        return False
    return c == p or c.startswith(p + os.sep)


# ---------------------------------------------------------------- 体积


def human(n):
    """字节 -> 人类可读。"""
    if n is None:
        return "-"
    n = float(n)
    neg = n < 0
    n = abs(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        s = "%d %s" % (int(n), units[i])
    elif n >= 100:
        s = "%.0f %s" % (n, units[i])
    else:
        s = "%.2f %s" % (n, units[i])
    return ("-" if neg else "") + s


def walk_stats(path, min_age_days=0, cutoff=None):
    """统计目录/文件的 (字节数, 文件数)。

    min_age_days > 0 时只统计「最后修改时间早于 N 天前」的文件。
    cutoff 可直接传入 time.time() 基准，方便测试。
    注意 cutoff=0 / None 都表示「不过滤年龄」——不要把它理解成"只统计 epoch 之前的文件"。
    """
    if not cutoff:
        cutoff = (time.time() - min_age_days * 86400) if min_age_days else None
    total, count = 0, 0
    if not os.path.exists(path):
        return 0, 0
    if os.path.isfile(path):
        try:
            if cutoff is None or os.path.getmtime(path) < cutoff:
                return os.path.getsize(path), 1
        except OSError:
            pass
        return 0, 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.lstat(fp)
                if not stat.S_ISREG(st.st_mode):
                    continue
                if cutoff is None or st.st_mtime < cutoff:
                    total += st.st_size
                    count += 1
            except OSError:
                continue
    return total, count


def newest_mtime(path):
    """目录树里最新的修改时间（用于判断整个目录有多"旧"）。"""
    newest = 0.0
    if os.path.isfile(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files + dirs:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                continue
    return newest


def age_days(ts):
    if not ts:
        return -1
    return (time.time() - ts) / 86400.0


def free_space(path):
    """返回 (可用字节, 总字节)。"""
    try:
        usage = shutil.disk_usage(os.path.splitdrive(expand(path))[0] + os.sep)
        return usage.free, usage.total
    except Exception:
        try:
            usage = shutil.disk_usage(expand(path))
            return usage.free, usage.total
        except Exception:
            return 0, 0


def drive_of(path):
    d = os.path.splitdrive(expand(path))[0]
    return (d + os.sep) if d else ""


# ---------------------------------------------------------------- 权限


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def quote(s):
    """给 subprocess/cmd 用的引号包裹。"""
    s = str(s)
    if not s:
        return '""'
    if " " in s or "\t" in s:
        return '"' + s.replace('"', r"\"") + '"'
    return s


# ---------------------------------------------------------------- 日志


class Logger:
    """写文件日志（避免中文编码问题，统一 UTF-8）并同时回显到控制台。"""

    def __init__(self, path=None, verbose=False, echo=True):
        self.path = path
        self.verbose = verbose
        self.echo = echo
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    def _write(self, level, msg):
        line = "[%s] %-5s %s" % (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            level,
            msg,
        )
        if self.echo:
            print(line)
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def info(self, msg):
        self._write("INFO", msg)

    def warn(self, msg):
        self._write("WARN", msg)

    def error(self, msg):
        self._write("ERROR", msg)

    def debug(self, msg):
        if self.verbose:
            self._write("DEBUG", msg)


# ---------------------------------------------------------------- 安全守卫


def _build_forbidden_roots():
    """按当前系统实际路径生成「精确禁止」集合。

    刻意不写死用户名或盘符——换台机器、换用户名、Windows 装在 D 盘都要成立。
    这里只管「路径本身就是它」，更深的子路径由深度检查 + 保护名单 + 正则层负责。
    """
    home = os.path.expanduser("~")
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidates = [
        os.path.splitdrive(home)[0] + os.sep,        # 系统盘根，如 C:\
        sysroot,
        os.path.join(sysroot, "System32"),
        os.path.join(sysroot, "SysWOW64"),
        os.path.join(sysroot, "WinSxS"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramData", r"C:\ProgramData"),
        home,
        os.path.join(home, "AppData"),
        os.path.join(home, "AppData", "Local"),
        os.path.join(home, "AppData", "Roaming"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Music"),
        os.path.join(home, "OneDrive"),
    ]
    return {norm_key(p) for p in candidates if p}


FORBIDDEN_ROOTS = _build_forbidden_roots()


# 正则层保护：不依赖具体用户名/盘符，任何机器上都拦得住。
# 精确路径列表保护不了「以后才出现的目录」（例如新会话生成的 user-<新UUID>），所以再加一层。
GUARD_PATTERNS = [
    (re.compile(r"[\\/]\.workbuddy[\\/]user-[^\\/]+", re.I), "个人档案（SOUL/IDENTITY/USER/MEMORY）"),
    (re.compile(r"[\\/]\.workbuddy[\\/](credentials|connectors|local_storage|security|binaries)"
                r"([\\/]|$)", re.I), "WorkBuddy 凭证 / 运行时"),
    (re.compile(r"[\\/]\.codex[\\/](auth\.json|config\.toml|installation_id|memories_1\.sqlite)"
                r"([\\/]|$)", re.I), "Codex 授权与配置"),
    (re.compile(r"[\\/]\.codex[\\/](skills|\.plugin-appserver|sqlite)([\\/]|$)", re.I),
     "Codex 技能 / 宿主程序"),
    (re.compile(r"[\\/]Windows[\\/](WinSxS|Installer)([\\/]|$)", re.I),
     "系统组件存储与安装缓存（须走 DISM）"),
    (re.compile(r"[\\/]\.git([\\/]|$)", re.I), "Git 版本库"),
]


class UnsafeTarget(Exception):
    pass


def guard(target, protected=None, must_exist=False):
    """在删除前做最后一道校验。不通过直接抛 UnsafeTarget。

    protected: [(label, path), ...] 保护名单
    """
    t = expand(target)
    if not t:
        raise UnsafeTarget("空路径")

    if must_exist and not os.path.lexists(t):
        raise UnsafeTarget("路径不存在：%s" % t)

    key = norm_key(t)
    if key in FORBIDDEN_ROOTS:
        raise UnsafeTarget("拒绝操作根目录/用户主目录：%s" % t)

    for pattern, label in GUARD_PATTERNS:
        if pattern.search(t):
            raise UnsafeTarget("命中不可清理位置「%s」：%s" % (label, t))

    # 至少要 3 层深度（C:\a\b\c 这种），避免误删盘符或一级目录
    parts = [p for p in norm_key(t).split(os.sep) if p]
    if len(parts) < 3:
        raise UnsafeTarget("路径层级过浅，拒绝操作：%s" % t)

    if os.path.lexists(t) and os.path.isdir(t) and not os.path.islink(t):
        # 目录自身不能是某个盘根的直属子目录（例如 D:\Temp 允许，D:\ 不允许）
        drv, tail = os.path.splitdrive(t)
        if tail.strip("\\/") in ("", "*"):
            raise UnsafeTarget("拒绝操作盘根目录：%s" % t)

    for label, p in (protected or []):
        if is_subpath(t, p):
            raise UnsafeTarget("命中保护名单「%s」：%s" % (label, t))
    return t
