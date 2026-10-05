# -*- coding: utf-8 -*-
"""执行引擎。

默认策略是「隔离区」：把要清理的东西移动到 <隔离区>/<时间戳>/ 下并写 manifest，
随时可以用 `wbcleaner.py trash restore <时间戳>` 原样搬回。
只有显式指定永久删除（--permanent）才会真正 unlink。
"""

import json
import os
import shutil
import stat
import time

from . import rules as R
from . import util
from .util import human, norm_key

TRASH_NAME = "wbcleaner-trash"


# ------------------------------------------------------------------ 隔离区


def trash_root_for(path):
    """按目标所在盘选择隔离区位置，优先同盘（同盘移动是瞬时的 rename）。"""
    drive = util.drive_of(path)
    local = os.environ.get("LOCALAPPDATA", "")
    if drive and local and norm_key(drive) == norm_key(os.path.splitdrive(local)[0] + os.sep):
        return os.path.join(local, "wbcleaner", "trash")
    return os.path.join(drive or "C:\\", "_" + TRASH_NAME)


def new_trash_dir(targets):
    ts = time.strftime("%Y%m%d-%H%M%S")
    root = trash_root_for(targets[0] if targets else os.getcwd())
    path = os.path.join(root, ts)
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(root, "%s_%d" % (ts, n))
    os.makedirs(path, exist_ok=True)
    return path


def list_trash():
    roots = set()
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.add(os.path.join(local, "wbcleaner", "trash"))
    for d in "CDEFGH":
        roots.add("%s:\\_%s" % (d, TRASH_NAME))
    out = []
    for root in sorted(roots):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root), reverse=True):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            man = os.path.join(p, "manifest.json")
            info = {"ts": name, "path": p, "size": 0, "files": 0, "entries": 0}
            if os.path.exists(man):
                try:
                    with open(man, encoding="utf-8") as fh:
                        data = json.load(fh)
                    info["size"] = data.get("size", 0)
                    info["files"] = data.get("files", 0)
                    info["entries"] = len(data.get("entries", []))
                    info["time"] = data.get("time_human", "")
                except (OSError, ValueError):
                    pass
            out.append(info)
    return out


def restore_trash(ts, logger=None, dry_run=False):
    """把某个时间戳的隔离区内容搬回原位。"""
    logger = logger or util.Logger()
    cands = [t for t in list_trash() if t["ts"] == ts]
    if not cands:
        logger.error("找不到隔离记录：%s" % ts)
        return 1
    base = cands[0]["path"]
    man_path = os.path.join(base, "manifest.json")
    if not os.path.exists(man_path):
        logger.error("隔离区缺少 manifest.json，无法自动还原：%s" % base)
        return 1
    with open(man_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    ok = fail = 0
    for ent in manifest.get("entries", []):
        src, dst = ent.get("quarantine"), ent.get("original")
        if not src or not os.path.lexists(src):
            continue
        if dry_run:
            logger.info("[演练] 还原 %s -> %s" % (util.short_path(src), util.short_path(dst)))
            ok += 1
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                dst = _unique(dst)
            shutil.move(src, dst)
            ok += 1
        except OSError as exc:
            fail += 1
            logger.error("还原失败 %s：%s" % (util.short_path(dst), exc))
    logger.info("还原完成：成功 %d，失败 %d" % (ok, fail))
    return 0 if fail == 0 else 2


def purge_trash(ts=None, logger=None):
    """永久删除隔离区内容。ts 为空则清空全部。"""
    logger = logger or util.Logger()
    entries = list_trash()
    if ts:
        entries = [e for e in entries if e["ts"] == ts]
    if not entries:
        logger.warn("没有可清除的隔离记录")
        return 0
    freed = 0
    for ent in entries:
        size = ent["size"]
        try:
            shutil.rmtree(ent["path"], onerror=_on_rm_error)
            freed += size
            logger.info("已永久删除隔离区 %s（%s）" % (ent["ts"], human(size)))
        except OSError as exc:
            logger.error("删除隔离区失败 %s：%s" % (ent["ts"], exc))
    logger.info("隔离区共释放 %s" % human(freed))
    return 0


# ------------------------------------------------------------------ 结果对象


class ExecResult:
    def __init__(self):
        self.freed = 0
        self.moved = 0
        self.deleted = 0
        self.files = 0
        self.skipped = []       # (path, reason)
        self.actions = []       # (action, ok, detail)
        self.errors = []
        self.trash_dir = None

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {
            "freed": self.freed,
            "freed_human": human(self.freed),
            "moved": self.moved,
            "deleted": self.deleted,
            "files": self.files,
            "skipped": len(self.skipped),
            "actions": self.actions,
            "errors": self.errors,
            "trash_dir": self.trash_dir,
        }


# ------------------------------------------------------------------ 删除原语


def _on_rm_error(func, path, exc_info):
    """只读文件先改权限再删；链接 / junction 只移除重解析点本身。

    junction 必须在这里兜住：它看起来是普通目录，一旦 rmtree 的实现退化成
    「顺着目录走」的写法，就会把链接背后的真实数据一起删掉。只读标志也常常
    挂在重解析点上，所以先 chmod 再 os.rmdir。
    """
    if util.is_link(path):
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass
        try:
            os.rmdir(path)
        except OSError:
            pass
        return
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _unique(path):
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(path):
        i += 1
        path = "%s_%d%s" % (base, i, ext)
    return path


def remove_path(path, quarantine=None, permanent=False, result=None, logger=None,
                dry_run=False):
    """删一个文件或目录。返回释放的字节数。"""
    result = result or ExecResult()
    logger = logger or util.Logger(echo=False)
    try:
        size, files = util.walk_stats(path, cutoff=0)
        if os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            files = 1
    except OSError:
        size, files = 0, 0

    if dry_run:
        logger.debug("[演练] 将清理 %s（%s）" % (util.short_path(path), human(size)))
        result.freed += size
        result.files += files
        return size

    try:
        if util.is_link(path):
            size, files = 0, 1
            if dry_run:
                logger.debug("[演练] 将移除链接 %s（不跟随目标）" % util.short_path(path))
                result.freed += size
                result.files += files
                return size
            if util.remove_link(path):
                if permanent:
                    result.deleted += 1
                else:
                    result.moved += 1
                result.files += files
                logger.debug("已移除链接 %s（未跟随目标）" % util.short_path(path))
                return size
            raise OSError("无法移除链接（可能被占用）")
        if permanent:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, onerror=_on_rm_error)
            else:
                try:
                    os.remove(path)
                except OSError:
                    os.chmod(path, stat.S_IWRITE)
                    os.remove(path)
            result.deleted += 1
        else:
            dst = os.path.join(quarantine, _rel_key(path))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                dst = _unique(dst)
            shutil.move(path, dst)
            _record(quarantine, path, dst, size, files)
            result.moved += 1
        result.freed += size
        result.files += files
        logger.debug("已清理 %s（%s）" % (util.short_path(path), human(size)))
        return size
    except OSError as exc:
        result.skipped.append((path, str(exc)))
        logger.debug("跳过 %s：%s" % (util.short_path(path), exc))
        return 0


def _rel_key(path):
    """把绝对路径映射成隔离区里的相对路径（C:\\a\\b -> C/a/b）。"""
    p = os.path.abspath(path)
    drive, tail = os.path.splitdrive(p)
    drive = drive.rstrip(":").upper() or "X"
    tail = tail.strip("\\/").replace(":", "_")
    return os.path.join(drive, tail) if tail else drive


_manifests = {}


def _record(quarantine, original, dst, size, files):
    _manifests.setdefault(quarantine, []).append(
        {"original": original, "quarantine": dst, "size": size, "files": files})


def flush_manifest(quarantine, result, logger=None):
    if not quarantine or quarantine not in _manifests:
        return
    entries = _manifests.pop(quarantine)
    payload = {
        "time": time.time(),
        "time_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        "size": sum(e["size"] for e in entries),
        "files": sum(e["files"] for e in entries),
        "entries": entries,
    }
    try:
        with open(os.path.join(quarantine, "manifest.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        if logger:
            logger.warn("写入还原清单失败：%s" % exc)
    result.trash_dir = quarantine


# ------------------------------------------------------------------ 按内容清理


def clean_contents(target, cutoff, quarantine, result, logger, dry_run=False):
    """清空目录内容（保留目录本身）。

    策略：整棵子树都比 cutoff 旧就整块搬走（快），否则逐文件处理。
    被占用的文件自动跳过。
    """
    if not os.path.isdir(target):
        return
    try:
        children = os.listdir(target)
    except OSError as exc:
        result.skipped.append((target, str(exc)))
        return

    for name in children:
        cp = os.path.join(target, name)
        try:
            if util.is_link(cp):
                # 链接 / junction 只移除链接本身，绝不顺着它删目标内容。
                # （os.path.islink 认不出 Windows junction，会被当成普通目录递归进去，
                #   把链接背后的真实数据一起清掉——这里必须用 util.is_link。）
                remove_path(cp, quarantine, False, result, logger, dry_run)
            elif os.path.isdir(cp):
                newest = util.newest_mtime(cp)
                if cutoff == 0 or (newest and newest < cutoff):
                    remove_path(cp, quarantine, False, result, logger, dry_run)
                else:
                    clean_contents(cp, cutoff, quarantine, result, logger, dry_run)
                    _prune_empty(cp)
            else:
                if cutoff and os.path.getmtime(cp) > cutoff:
                    continue
                remove_path(cp, quarantine, False, result, logger, dry_run)
        except OSError as exc:
            result.skipped.append((cp, str(exc)))


def _prune_empty(path):
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


# ------------------------------------------------------------------ 主入口


def execute(items, selection, permanent=False, yes=False, logger=None,
            dry_run=False, confirm=None, progress=None):
    """执行清理。

    items     : ScanItem 列表
    selection : 选中的 rid 集合
    permanent : True 直接永久删除；False 移入隔离区
    dry_run   : True 只报告不动作
    confirm   : 可选回调 confirm(text, level) -> bool，用于危险项二次确认
    """
    logger = logger or util.Logger()
    result = ExecResult()
    todo = [i for i in items if i.rid in selection and i.actionable]
    if not todo:
        logger.warn("没有选中任何有内容的清理项")
        return result

    protected = [(label, p) for label, p in R.PROTECTED]

    # 隔离区：按目标所在盘分组建立
    quarantine = None
    if not permanent and not dry_run:
        all_targets = [t for i in todo for t in i.targets]
        quarantine = new_trash_dir(all_targets)
        logger.info("隔离区：%s" % quarantine)

    for idx, item in enumerate(todo, 1):
        rule = item.rule
        if progress:
            progress(idx, len(todo), item)
        logger.info("[%d/%d] %s（%s，%s）" % (
            idx, len(todo), rule.title, item.summary(), rule.level_label))

        # ---- 系统动作
        if rule.kind == "action":
            if dry_run:
                result.actions.append((rule.action, True, "[演练] 未执行"))
                continue
            if rule.level in ("caution", "danger") and confirm is not None:
                if not confirm("即将执行系统动作「%s」：%s" % (rule.title, rule.impact),
                               rule.level):
                    logger.warn("  ↳ 用户取消")
                    result.actions.append((rule.action, False, "用户取消"))
                    continue
            from . import syswin
            ok, detail = syswin.run_action(rule.action, logger=logger)
            result.actions.append((rule.action, ok, detail))
            if ok:
                logger.info("  ↳ %s" % detail)
            else:
                result.errors.append("%s：%s" % (rule.title, detail))
                logger.error("  ↳ %s" % detail)
            continue

        # ---- 文件/目录清理
        if rule.kind == "contents":
            for target in item.targets:
                guard_ok = _guard(target, protected, result, logger)
                if not guard_ok:
                    continue
                clean_contents(target, item.cutoff, quarantine, result, logger, dry_run)
        else:
            for target in item.targets:
                if not _guard(target, protected, result, logger):
                    continue
                remove_path(target, quarantine, permanent, result, logger, dry_run)

    if quarantine and not dry_run:
        flush_manifest(quarantine, result, logger)
        if result.moved == 0:
            try:
                if not os.listdir(quarantine):
                    os.rmdir(quarantine)
                    result.trash_dir = None
            except OSError:
                pass

    if result.skipped:
        logger.warn("有 %d 个目标被占用或权限不足而跳过" % len(result.skipped))
        for p, why in result.skipped[:10]:
            logger.warn("  - %s：%s" % (util.short_path(p), why))
        if len(result.skipped) > 10:
            logger.warn("  ... 其余 %d 条见日志" % (len(result.skipped) - 10))

    return result


def _guard(target, protected, result, logger):
    try:
        util.guard(target, protected, must_exist=True)
        return True
    except util.UnsafeTarget as exc:
        result.skipped.append((target, "安全守卫拦截：%s" % exc))
        logger.warn("安全守卫拦截：%s" % exc)
        return False
