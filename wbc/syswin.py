# -*- coding: utf-8 -*-
"""Windows 系统级清理动作：DISM 组件存储、Windows 更新缓存、回收站、休眠文件等。

这里所有有风险的操作都遵循同一套流程：
  1. 检查管理员权限（不足则明确报错，不静默失败）
  2. 记录清理前后的盘空间，回报「实际释放」
  3. 输出原样保留在日志里，便于事后核对
"""

import ctypes
import os
import re
import shutil
import subprocess
import sys
import time

from . import util
from . import scanner

CREATE_NO_WINDOW = 0x08000000
SIZE_RE = re.compile(r"([\d.]+)\s*(GB|MB|KB|TB|字节|bytes?)", re.IGNORECASE)


# ------------------------------------------------------------------ 进程


def run_capture(cmd, timeout=1800):
    """执行命令并返回 (returncode, stdout, stderr)，自动处理 GBK/UTF-8。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时（%ds）" % timeout
    except OSError as exc:
        return 127, "", str(exc)
    return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)


def run_stream(cmd, logger, timeout=3600):
    """流式执行并实时输出进度（DISM 的进度条用 \\r 刷新）。"""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        return 127, str(exc)

    buf = b""
    lines = []
    last_print = 0.0
    start = time.time()
    try:
        while True:
            chunk = proc.stdout.read(512)
            if not chunk:
                break
            if time.time() - start > timeout:
                proc.kill()
                return 124, "命令超时"
            buf += chunk
            while True:
                idx = min([i for i in (buf.find(b"\r"), buf.find(b"\n")) if i >= 0] or [-1])
                if idx < 0:
                    break
                raw, buf = buf[:idx], buf[idx + 1:]
                text = _decode(raw).strip()
                if not text:
                    continue
                lines.append(text)
                # 进度行频繁且内容重复，限频输出
                if time.time() - last_print > 0.7 or not text.endswith("%]"):
                    logger.debug(text)
                    last_print = time.time()
        if buf.strip():
            lines.append(_decode(buf).strip())
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
    code = proc.wait()
    return code, "\n".join(lines)


def _decode(data):
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def require_admin(logger):
    if util.is_admin():
        return True
    logger.error("该操作需要管理员权限，请用 run.bat（会弹出 UAC 提权）重新启动。")
    return False


# ------------------------------------------------------------------ 服务控制


def _service(action, name, logger):
    code, out, err = run_capture(["sc.exe", action, name], timeout=120)
    ok = code == 0 or b"1056" in (err or "").encode("utf-8", "ignore")
    if not ok:
        logger.debug("sc %s %s -> %s %s" % (action, name, code, (err or out).strip()))
    return ok


def with_services_stopped(services, logger):
    """上下文管理器式的服务暂停/恢复（这里用简单函数对，便于流程显式）。"""
    stopped = []
    for svc in services:
        if _service("stop", svc, logger):
            stopped.append(svc)
    # 给服务一点时间真正停下来，否则文件仍被占用
    time.sleep(2)
    return stopped


def start_services(services, logger):
    for svc in services:
        _service("start", svc, logger)


# ------------------------------------------------------------------ DISM


def _dism_exe():
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "Dism.exe")


def _parse_sizes(text):
    """按出现顺序抽取体积数值（字节）。"""
    vals = []
    for m in SIZE_RE.finditer(text):
        num, unit = float(m.group(1)), m.group(2).upper()
        mult = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4,
                "字节": 1, "BYTE": 1, "BYTES": 1}.get(unit, 1)
        vals.append(int(num * mult))
    return vals


def dism_analyze(logger):
    if not require_admin(logger):
        return False, "需要管理员权限"
    logger.info("正在分析 WinSxS 组件存储（只读，通常 20~60 秒）...")
    code, out = run_stream([_dism_exe(), "/Online", "/Cleanup-Image",
                            "/AnalyzeComponentStore"], logger, timeout=1800)
    if code != 0:
        return False, "DISM 返回码 %s：%s" % (code, _tail(out))
    sizes = _parse_sizes(out)
    payload = {
        "reported": sizes[0] if len(sizes) > 0 else 0,
        "actual": sizes[1] if len(sizes) > 1 else 0,
        "shared": sizes[2] if len(sizes) > 2 else 0,
        "reclaimable": sizes[3] if len(sizes) > 3 else 0,
        "cache_temp": sizes[4] if len(sizes) > 4 else 0,
        "raw": out[-4000:],
    }
    m = re.search(r"可回收的程序包数\s*[:：]\s*(\d+)", out) or \
        re.search(r"Number of Reclaimable Packages\s*[:：]\s*(\d+)", out)
    payload["reclaimable_packages"] = int(m.group(1)) if m else 0
    recommended = bool(re.search(r"推荐使用组件存储清理\s*[:：]\s*(是|Yes|True)", out)) or \
        bool(re.search(r"Component Store Cleanup Recommended\s*[:：]\s*(Yes|True)", out))
    payload["recommended"] = recommended
    scanner.save_dism_cache(payload)
    detail = ("组件存储实际 %s，其中备份/已禁用功能 %s 可回收，可回收程序包 %d 个%s" % (
        util.human(payload["actual"]), util.human(payload["reclaimable"]),
        payload["reclaimable_packages"], "，官方建议清理" if recommended else ""))
    logger.info(detail)
    return True, detail


def dism_cleanup(logger, reset_base=False):
    if not require_admin(logger):
        return False, "需要管理员权限"
    free_before, _ = util.free_space(r"C:\\")
    cmd = [_dism_exe(), "/Online", "/Cleanup-Image", "/StartComponentCleanup"]
    if reset_base:
        cmd.append("/ResetBase")
    label = "深度清理（/ResetBase）" if reset_base else "标准清理"
    logger.info("正在执行 WinSxS %s，视组件数量可能耗时 5~30 分钟，请勿关机..." % label)
    code, out = run_stream(cmd, logger, timeout=5400)
    free_after, _ = util.free_space(r"C:\\")
    gained = max(0, free_after - free_before)
    if code != 0:
        # 0x800f0806 之类的可重试错误也如实报出
        return False, "DISM 返回码 %s：%s" % (code, _tail(out))
    detail = "完成，本次实际释放约 %s（C 盘可用 %s → %s）" % (
        util.human(gained), util.human(free_before), util.human(free_after))
    logger.info(detail)
    try:
        dism_analyze(logger)
    except Exception:
        pass
    return True, detail


def _tail(text, n=400):
    text = (text or "").strip().replace("\n", " | ")
    return text[-n:]


# ------------------------------------------------------------------ 其它动作


def clear_recyclebin(logger):
    try:
        shell32 = ctypes.windll.shell32
        shell32.SHEmptyRecycleBinW.restype = ctypes.c_long
        shell32.SHEmptyRecycleBinW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                               ctypes.c_uint]
        before = scanner.recyclebin_size()
        rc = shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
        # S_OK=0；没有回收站时返回 E_UNEXPECTED(0x8000FFFF)
        if rc not in (0, -2147418113):
            return False, "清空回收站失败，HRESULT=0x%08X" % (rc & 0xFFFFFFFF)
        return True, "已清空回收站，释放 %s" % util.human(before)
    except Exception as exc:
        return False, "调用 Shell API 失败：%s" % exc


def hibernate_off(logger):
    if not require_admin(logger):
        return False, "需要管理员权限"
    code, out, err = run_capture(["powercfg.exe", "/h", "off"], timeout=120)
    if code != 0:
        return False, "powercfg 失败：%s" % _tail(err or out)
    time.sleep(1)
    return True, "已关闭休眠（恢复命令：powercfg /h on）"


def wu_cache(logger):
    """清空 Windows 更新下载缓存。"""
    if not require_admin(logger):
        return False, "需要管理员权限"
    download = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "SoftwareDistribution", "Download")
    free_before, _ = util.free_space(r"C:\\")
    svcs = ["wuauserv", "bits", "dosvc"]
    stopped = with_services_stopped(svcs, logger)
    freed = 0
    try:
        for root in [download,
                     os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                  "Microsoft", "Windows", "DeliveryOptimization")]:
            if not os.path.isdir(root):
                continue
            for name in os.listdir(root):
                p = os.path.join(root, name)
                sz, _ = util.walk_stats(p, cutoff=0)
                try:
                    if util.is_link(p):
                        # 只移除链接，不顺着它删目标（更新缓存里也可能有重解析点）
                        if not util.remove_link(p):
                            raise OSError("无法移除链接")
                    elif os.path.isdir(p):
                        shutil.rmtree(p, onerror=lambda f, x, e: None)
                    else:
                        os.remove(p)
                    freed += sz
                except OSError as exc:
                    logger.debug("跳过 %s：%s" % (util.short_path(p), exc))
    finally:
        start_services(stopped or svcs, logger)
    free_after, _ = util.free_space(r"C:\\")
    return True, "已清理更新下载缓存，释放约 %s（实测盘空间 +%s）" % (
        util.human(freed), util.human(max(0, free_after - free_before)))


# ------------------------------------------------------------------ 分发


ACTIONS = {
    "dism_analyze": lambda logger: dism_analyze(logger),
    "dism_cleanup": lambda logger: dism_cleanup(logger, reset_base=False),
    "dism_resetbase": lambda logger: dism_cleanup(logger, reset_base=True),
    "recyclebin": clear_recyclebin,
    "hibernate_off": hibernate_off,
    "wu_cache": wu_cache,
}


def run_action(action, logger=None):
    logger = logger or util.Logger(echo=False)
    fn = ACTIONS.get(action)
    if not fn:
        return False, "未知动作：%s" % action
    try:
        return fn(logger)
    except Exception as exc:  # 系统调用异常不外抛，转成可读错误
        return False, "执行异常：%s" % exc
