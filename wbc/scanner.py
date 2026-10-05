# -*- coding: utf-8 -*-
"""扫描引擎：把规则表翻译成「具体能删什么、能回收多少」。只读，不做任何修改。"""

import glob as globmod
import json
import os
import time
from dataclasses import dataclass, field

from . import rules as R
from . import util

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
DISM_CACHE = os.path.join(CACHE_DIR, "dism_analyze.json")


@dataclass
class ScanItem:
    rule: R.Rule
    size: int = 0
    files: int = 0
    targets: list = field(default_factory=list)
    mode: str = "paths"        # paths | contents | action
    cutoff: float = 0.0
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def rid(self):
        return self.rule.rid

    @property
    def actionable(self):
        """有实际可回收内容（或可执行的系统动作）。"""
        if self.rule.kind == "action":
            return True
        return bool(self.targets) and self.size > 0

    def summary(self):
        if self.rule.kind == "action":
            return self.note or "系统动作"
        if not self.targets:
            return "无内容"
        return "%s / %d 个文件" % (util.human(self.size), self.files)


# ------------------------------------------------------------------ 单条规则扫描


def scan_rule(rule, days_override=None, master_cutoff=None):
    """扫描单条规则。

    days_override 是「全局年龄下限」，语义是**只收紧、不放松**：
    取 规则自身阈值 与 全局值 的较大者。规则里的 min_age_days 表达的是
    「这份数据要放这么久才敢删」（比如日志要等 2 天避开正在跑的会话），
    全局设置不应该把它调小——否则用户一个参数就把安全边界抹掉了。
    全局值填 0/None 表示按各规则自己的阈值。
    """
    if days_override:
        days = max(rule.min_age_days, days_override)
    else:
        days = rule.min_age_days
    cutoff = (master_cutoff - days * 86400) if master_cutoff else (time.time() - days * 86400)
    item = ScanItem(rule=rule)

    # ---- 系统动作类：体积由专门逻辑给出
    if rule.kind == "action":
        item.mode = "action"
        _measure_action(item, rule, cutoff)
        return item

    existing = [p for p in rule.paths if os.path.lexists(p)]

    if not existing:
        item.note = "不存在"
        return item

    if rule.kind == "contents":
        item.mode = "contents"
        item.cutoff = cutoff if days > 0 else 0.0
        for p in existing:
            if util.is_link(p):
                # 极少数情况：规则目标本身就是链接。只算 1 个链接条目、
                # 0 字节，绝不统计（更不删除）它背后的目标内容。
                item.targets.append(p)
                item.files += 1
            elif os.path.isfile(p):
                sz, cnt = util.walk_stats(p, cutoff=cutoff)
                if sz:
                    item.targets.append(p)
                    item.size += sz
                    item.files += cnt
            else:
                sz, cnt = util.walk_stats(p, cutoff=cutoff)
                item.size += sz
                item.files += cnt
                if sz:
                    item.targets.append(p)
        if not item.targets:
            item.note = ("无 %d 天前的文件" % days) if days else "空"

    elif rule.kind == "subdirs":
        item.mode = "paths"
        for p in existing:
            if not os.path.isdir(p):
                continue
            try:
                children = sorted(os.listdir(p))
            except OSError:
                continue
            for name in children:
                if name in rule.skip_names:
                    continue
                if rule.name_glob and not _fnmatch(name, rule.name_glob):
                    continue
                cp = os.path.join(p, name)
                if util.is_link(cp):
                    # 链接 / junction 视为一个条目：算 0 字节、1 个文件，
                    # 且不跟随目标（目标可能是别处的真实数据，不是这里的缓存）。
                    sz, cnt = 0, 1
                elif os.path.isdir(cp):
                    newest = util.newest_mtime(cp)
                    if days > 0 and newest and newest > cutoff:
                        continue  # 太新，保留
                    sz, cnt = util.walk_stats(cp, cutoff=0)
                else:
                    try:
                        if days > 0 and os.path.getmtime(cp) > cutoff:
                            continue
                        sz = os.path.getsize(cp)
                    except OSError:
                        continue
                    cnt = 1
                if sz or cnt:
                    item.targets.append(cp)
                    item.size += sz
                    item.files += cnt
        if not item.targets:
            item.note = ("无 %d 天前的条目" % days) if days else "空"

    elif rule.kind == "dir":
        item.mode = "paths"
        for p in existing:
            if days > 0 and util.newest_mtime(p) > cutoff:
                continue
            sz, cnt = util.walk_stats(p, cutoff=0)
            item.targets.append(p)
            item.size += sz
            item.files += cnt
        if not item.targets:
            item.note = "不存在或过新"

    elif rule.kind == "glob":
        item.mode = "paths"
        for pat in rule.paths:
            for p in globmod.glob(os.path.expandvars(os.path.expanduser(pat))):
                try:
                    if days > 0 and os.path.getmtime(p) > cutoff:
                        continue
                    sz = os.path.getsize(p) if os.path.isfile(p) else 0
                except OSError:
                    continue
                item.targets.append(p)
                item.size += sz
                item.files += 1
        if not item.targets:
            item.note = "无匹配文件"

    elif rule.kind == "report":
        for p in existing:
            sz, cnt = util.walk_stats(p, cutoff=0)
            item.size += sz
            item.files += cnt
        item.note = "保护项，仅统计"

    return item


def _fnmatch(name, pattern):
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


# ------------------------------------------------------------------ 系统动作测量


def _measure_action(item, rule, cutoff):
    act = rule.action
    if act in ("dism_analyze", "dism_cleanup", "dism_resetbase"):
        data = load_dism_cache()
        if data:
            item.size = data.get("reclaimable", 0)
            item.extra = data
            prefix = "只读分析 ｜ " if not rule.frees_space else ""
            item.note = "%sWinSxS 可回收 %s（%s 分析）" % (
                prefix, util.human(data.get("reclaimable", 0)),
                data.get("time_human", "?"))
        else:
            item.size = 0
            item.note = "尚未分析，请先执行「分析 WinSxS」"
        return

    if act == "recyclebin":
        size = recyclebin_size()
        item.size = size
        item.note = util.human(size) if size else "无"
        return

    if act == "hibernate_off":
        p = r"C:\hiberfil.sys"
        try:
            item.size = os.path.getsize(p) if os.path.exists(p) else 0
        except OSError:
            item.size = 0
        item.note = ("可释放 %s" % util.human(item.size)) if item.size else "休眠已关闭"
        return

    if act == "wu_cache":
        p = os.path.join(R.WINDIR, "SoftwareDistribution", "Download")
        sz, cnt = util.walk_stats(p, cutoff=0)
        item.size, item.files = sz, cnt
        item.note = "%s / %d 个文件" % (util.human(sz), cnt)
        return


def recyclebin_size():
    """用 Shell API 查询回收站占用（不依赖 PowerShell）。"""
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]

        shell32 = ctypes.windll.shell32
        total = 0
        for drive in "CDEFG":
            info = SHQUERYRBINFO()
            info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            root = "%s:\\" % drive
            if not os.path.exists(root):
                continue
            # 0x00000001 = SHQUERYRBINFO 只查大小
            rc = shell32.SHQueryRecycleBinW(ctypes.c_wchar_p(root), ctypes.byref(info))
            if rc == 0:
                total += int(info.i64Size)
        return total
    except Exception:
        return 0


# ------------------------------------------------------------------ DISM 分析缓存


def save_dism_cache(payload):
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload["time"] = time.time()
    payload["time_human"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(payload["time"]))
    try:
        with open(DISM_CACHE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_dism_cache():
    try:
        with open(DISM_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ 批量扫描


def scan_group(group, days_override=None, include_protected=True, progress=None):
    rules = R.RULES_BY_GROUP.get(group, [])
    items = []
    for rule in rules:
        if progress:
            progress(rule)
        items.append(scan_rule(rule, days_override=days_override))
    items.sort(key=lambda it: (R.LEVEL_ORDER.get(it.rule.level, 9), -it.size))
    return items


def scan_all(groups=("workbuddy", "codex", "deepseek", "system"), days_override=None,
             progress=None):
    return {g: scan_group(g, days_override=days_override, progress=progress) for g in groups}


def totals(items):
    """返回 (可回收字节, 安全项字节, 需注意字节, 危险项字节)。

    只读分析类（frees_space=False）不计入；互斥组（如 DISM 标准清理 vs 深度清理）
    只按组内最大的那个计一次，避免把同一块空间重复累加。
    """
    picked, exclusive = [], {}
    for i in items:
        if not i.actionable or not i.rule.frees_space:
            continue
        g = i.rule.exclusive_group
        if g:
            if g not in exclusive or i.size > exclusive[g].size:
                exclusive[g] = i
        else:
            picked.append(i)
    picked.extend(exclusive.values())

    def _sum(level):
        return sum(i.size for i in picked if i.rule.level == level)

    safe, caution, danger = _sum("safe"), _sum("caution"), _sum("danger")
    return safe + caution + danger, safe, caution, danger


def default_selection(items):
    return {i.rid for i in items
            if i.rule.default_on and i.actionable and i.rule.level in ("safe", "caution")}
