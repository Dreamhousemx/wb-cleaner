# -*- coding: utf-8 -*-
"""本地 Web 服务：给可视化界面提供 API。

只监听 127.0.0.1，并要求每次请求带上随机 token（防止同机其它程序乱调接口）。
耗时操作（扫描 / 清理 / DISM）跑在后台线程里，通过 SSE 把进度推给界面。
"""

import ctypes
import json
import mimetypes
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, executor, report, rules as R, scanner, syswin, util

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

TOKEN = os.environ.get("WBC_UI_TOKEN") or secrets.token_urlsafe(18)
_STATE = {
    "last_scan": None,      # 最近一次扫描的 payload，切换标签页时直接复用
    "last_scan_at": 0,
}
_LOCK = threading.Lock()


# ==================================================================== 任务队列


class Job:
    """一次后台任务的事件流。"""

    def __init__(self, kind, title=""):
        self.id = secrets.token_hex(8)
        self.kind = kind
        self.title = title
        self.q = queue.Queue()
        self.result = None
        self.error = None
        self.finished = False
        self.created = time.time()

    # ---- 发事件
    def emit(self, kind, **payload):
        payload["type"] = kind
        payload["ts"] = time.time()
        self.q.put(payload)

    def log(self, level, text):
        self.emit("log", level=level, text=text)

    def finish(self, result=None, error=None):
        self.result = result
        self.error = error
        if error:
            self.emit("error", message=error)
        else:
            self.emit("done", result=result)
        self.finished = True

    def drain(self, timeout=0.5, limit=200):
        out = []
        deadline = time.time() + timeout
        while len(out) < limit:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                out.append(self.q.get(timeout=remaining))
            except queue.Empty:
                break
        return out


JOBS = {}


def new_job(kind, title=""):
    job = Job(kind, title)
    with _LOCK:
        JOBS[job.id] = job
        # 只保留最近 20 个任务
        for old in sorted(JOBS.values(), key=lambda j: j.created)[:-20]:
            JOBS.pop(old.id, None)
    return job


def get_job(job_id):
    return JOBS.get(job_id)


class JobLogger(util.Logger):
    """把日志同时推给界面。"""

    def __init__(self, job, path=None, verbose=True):
        super().__init__(path, verbose=verbose, echo=False)
        self.job = job

    def _write(self, level, msg):
        self.job.log(level.lower(), msg)
        line = "[%s] %-5s %s" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), level, msg)
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass


def log_path():
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"),
                exist_ok=True)
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs",
        "wbcleaner-%s.log" % time.strftime("%Y%m%d"))


# ==================================================================== 载荷


def item_dict(it):
    return {
        "rid": it.rid,
        "group": it.rule.group,
        "title": it.rule.title,
        "level": it.rule.level,
        "levelLabel": it.rule.level_label,
        "kind": it.rule.kind,
        "action": it.rule.action,
        "size": it.size,
        "sizeHuman": util.human(it.size) if it.size else "-",
        "files": it.files,
        "count": len(it.targets),
        "targets": [util.short_path(t, 110) for t in it.targets[:60]],
        "targetsMore": max(0, len(it.targets) - 60),
        "desc": it.rule.desc,
        "impact": it.rule.impact,
        "minAgeDays": it.rule.min_age_days,
        "defaultOn": it.rule.default_on,
        "actionable": it.actionable,
        "note": it.note,
        "requiresAdmin": it.rule.requires_admin,
        "freesSpace": it.rule.frees_space,
        "protected": it.rule.protected or it.rule.kind == "report",
    }


def scan_payload(scan, days):
    groups = {}
    for group, items in scan.items():
        tot, safe, caution, danger = scanner.totals(items)
        groups[group] = {
            "key": group,
            "title": R.GROUP_TITLES.get(group, group),
            "total": tot,
            "totalHuman": util.human(tot),
            "safe": safe, "caution": caution, "danger": danger,
            "safeHuman": util.human(safe),
            "cautionHuman": util.human(caution),
            "dangerHuman": util.human(danger),
            "items": [item_dict(i) for i in items],
            "defaultRids": sorted(scanner.default_selection(items)),
        }
    return groups


def row_for_report(d):
    """把界面用的 camelCase 行转换成 report.build_payload 的 snake_case 结构。"""
    return {
        "rid": d["rid"], "title": d["title"], "level": d["level"], "kind": d["kind"],
        "action": d["action"], "size": d["size"], "size_human": d["sizeHuman"],
        "files": d["files"], "targets": d["targets"], "count": d["count"],
        "desc": d["desc"], "impact": d["impact"], "min_age_days": d["minAgeDays"],
        "default_on": d["defaultOn"], "actionable": d["actionable"],
        "note": d["note"], "requires_admin": d["requiresAdmin"],
    }


def env_payload():
    free, total = util.free_space("C:\\")
    dism = scanner.load_dism_cache()
    tr = executor.list_trash()
    return {
        "version": __version__,
        "user": os.environ.get("USERNAME", ""),
        "admin": util.is_admin(),
        "python": sys.version.split()[0],
        "disk": {"free": free, "total": total, "used": total - free,
                 "freeHuman": util.human(free), "totalHuman": util.human(total),
                 "usedPct": round((total - free) / total * 100, 1) if total else 0},
        "dism": dism,
        "trash": tr,
        "trashTotal": sum(t["size"] for t in tr),
        "trashTotalHuman": util.human(sum(t["size"] for t in tr)),
    }


# ==================================================================== 任务实现


def job_scan(job, groups, days):
    total_rules = sum(len(R.RULES_BY_GROUP.get(g, [])) for g in groups)
    counter = {"n": 0}

    def progress(rule):
        counter["n"] += 1
        job.emit("progress", text=rule.title, index=counter["n"], total=total_rules)

    job.log("info", "开始扫描（只读操作，不会修改任何文件）")
    scan = scanner.scan_all(groups, days_override=days, progress=progress)
    payload = scan_payload(scan, days)
    with _LOCK:
        _STATE["last_scan"] = payload
        _STATE["last_scan_at"] = time.time()

    total = sum(g["total"] for g in payload.values())
    job.log("info", "扫描完成，合计可回收 %s" % util.human(total))
    return {"groups": payload, "days": days, "env": env_payload(),
            "scannedAt": time.strftime("%Y-%m-%d %H:%M:%S")}


def job_clean(job, rids, permanent, dry_run, days, allow_system):
    logger = JobLogger(job, log_path())
    job.log("info", "模式：%s%s" % ("永久删除" if permanent else "隔离区（可还原）",
                                  "，演练" if dry_run else ""))
    scan = scanner.scan_all(("workbuddy", "codex", "system"), days_override=days)
    items = [i for g in scan.values() for i in g]
    known = {i.rid for i in items}
    unknown = [r for r in rids if r not in known and r not in R.RULES_BY_ID]
    if unknown:
        raise ValueError("未知清理项：%s" % ", ".join(unknown))

    selected = set(rids)
    todo = [i for i in items if i.rid in selected and i.actionable]
    if not todo:
        raise ValueError("选中的项目当前没有可清理内容")

    def confirm(text, level):
        if allow_system:
            job.log("warn", text)
            return True
        job.log("warn", "已跳过需要确认的系统动作：%s" % text)
        return False

    def progress(idx, total, item):
        job.emit("progress", text=item.rule.title, index=idx, total=total)

    result = executor.execute(items, selected, permanent=permanent, dry_run=dry_run,
                              logger=logger, confirm=confirm, progress=progress)
    free, total = util.free_space("C:\\")
    return {
        "freed": result.freed,
        "freedHuman": util.human(result.freed),
        "files": result.files,
        "moved": result.moved,
        "deleted": result.deleted,
        "dryRun": dry_run,
        "permanent": permanent,
        "skipped": [{"path": util.short_path(p), "why": w} for p, w in result.skipped[:50]],
        "skippedCount": len(result.skipped),
        "actions": [{"action": a, "ok": ok, "detail": d} for a, ok, d in result.actions],
        "errors": result.errors,
        "trashDir": result.trash_dir,
        "trashTs": os.path.basename(result.trash_dir) if result.trash_dir else None,
        "diskFreeHuman": util.human(free),
    }


def job_action(job, action):
    logger = JobLogger(job, log_path())
    if action not in syswin.ACTIONS:
        raise ValueError("未知动作：%s" % action)
    ok, detail = syswin.run_action(action, logger=logger)
    if not ok:
        raise RuntimeError(detail)
    return {"ok": True, "detail": detail, "env": env_payload()}


def job_report(job, out_html):
    with _LOCK:
        payload = _STATE.get("last_scan")
        at = _STATE.get("last_scan_at")
    if not payload:
        raise ValueError("还没有扫描结果，请先执行一次扫描")
    report_payload = {
        "tool": "WBCleaner", "version": __version__,
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at or time.time())),
        "age_filter_days": 0, "user": os.environ.get("USERNAME", ""),
        "admin": util.is_admin(),
        "groups": {k: {"title": v["title"], "total": v["total"],
                       "total_human": v["totalHuman"], "safe": v["safe"],
                       "caution": v["caution"], "danger": v["danger"],
                       "rows": [row_for_report(r) for r in v["items"]]}
                   for k, v in payload.items()},
        "extra": {"dism": scanner.load_dism_cache() or {}},
    }
    path = report.write_html(report_payload, out_html)
    return {"path": path}


# ==================================================================== HTTP


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "WBCleanerUI/%s" % __version__

    # ---- 工具
    def log_message(self, fmt, *args):
        if os.environ.get("WBC_UI_DEBUG"):
            sys.stderr.write("[webui] %s\n" % (fmt % args))

    def _check_token(self, query):
        tok = query.get("t", [None])[0] or self.headers.get("X-WBC-Token")
        return tok == TOKEN

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, OSError):
            return {}

    # ---- GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        # 静态前端资源不含任何数据，允许不带令牌（否则 <link>/<script> 无法加载）
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path.startswith("/reports/"):
            return self._report_file(path[len("/reports/"):])

        if not self._check_token(query):
            return self._json({"error": "invalid token"}, 403)

        if path == "/api/env":
            return self._json(env_payload())
        if path == "/api/scan/cached":
            with _LOCK:
                payload = _STATE.get("last_scan")
                at = _STATE.get("last_scan_at")
            return self._json({"groups": payload or {}, "scannedAt": at})
        if path == "/api/trash":
            entries = executor.list_trash()
            return self._json({"entries": entries,
                               "total": sum(e["size"] for e in entries),
                               "totalHuman": util.human(sum(e["size"] for e in entries))})
        if path == "/api/rules":
            return self._json({"rules": [
                {"rid": r.rid, "group": r.group, "title": r.title, "kind": r.kind,
                 "level": r.level, "minAgeDays": r.min_age_days,
                 "defaultOn": r.default_on, "requiresAdmin": r.requires_admin,
                 "protected": r.protected, "action": r.action,
                 "paths": [util.short_path(p, 90) for p in r.paths],
                 "desc": r.desc, "impact": r.impact}
                for r in R.ALL_RULES]})
        if path == "/api/protected":
            return self._json({"protected": [
                {"label": lbl, "path": util.short_path(p, 90)} for lbl, p in R.PROTECTED]})

        # SSE：任务事件流
        if path == "/api/events":
            job_id = (query.get("job") or [""])[0]
            job = get_job(job_id)
            if not job:
                return self._json({"error": "job not found"}, 404)
            return self._sse(job)

        return self._json({"error": "not found", "path": path}, 404)

    # ---- POST
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self._check_token(query):
            return self._json({"error": "invalid token"}, 403)
        body = self._body_json()
        path = parsed.path

        try:
            if path == "/api/scan":
                groups = body.get("groups") or ["workbuddy", "codex", "system"]
                days = body.get("days")
                days = int(days) if days not in (None, "", 0) else None
                job = new_job("scan", "扫描")
                threading.Thread(target=self._run, args=(job, job_scan, (job, groups, days)),
                                 daemon=True).start()
                return self._json({"job": job.id})

            if path == "/api/clean":
                rids = body.get("rids") or []
                if not rids:
                    return self._json({"error": "未选择任何清理项"}, 400)
                job = new_job("clean", "清理")
                job_args = (job, rids, bool(body.get("permanent")),
                            bool(body.get("dryRun")),
                            int(body["days"]) if body.get("days") else None,
                            bool(body.get("allowSystem")))
                threading.Thread(target=self._run, args=(job, job_clean, job_args),
                                 daemon=True).start()
                return self._json({"job": job.id})

            if path == "/api/action":
                action = body.get("action") or ""
                job = new_job("action", action)
                threading.Thread(target=self._run, args=(job, job_action, (job, action)),
                                 daemon=True).start()
                return self._json({"job": job.id})

            if path == "/api/report":
                out = os.path.join(os.path.dirname(WEB_DIR), "reports",
                                   "scan-%s.html" % time.strftime("%Y%m%d-%H%M%S"))
                job = new_job("report", "生成报告")
                threading.Thread(target=self._run, args=(job, job_report, (job, out)),
                                 daemon=True).start()
                return self._json({"job": job.id})

            if path == "/api/trash/restore":
                ts = body.get("ts")
                if not ts:
                    return self._json({"error": "缺少时间戳"}, 400)
                logger = util.Logger(echo=False)
                rc = executor.restore_trash(ts, logger=logger)
                return self._json({"ok": rc == 0, "env": env_payload()})

            if path == "/api/trash/purge":
                ts = body.get("ts") or None
                logger = util.Logger(echo=False)
                executor.purge_trash(ts, logger=logger)
                return self._json({"ok": True, "env": env_payload()})

            if path == "/api/elevate":
                ok, detail = self._elevate(body.get("port"))
                return self._json({"ok": ok, "detail": detail})

            if path == "/api/open":
                target = body.get("path") or ""
                if not target or not os.path.exists(target):
                    return self._json({"error": "路径不存在"}, 400)
                subprocess.Popen(["explorer.exe", "/select,", target])
                return self._json({"ok": True})

            if path == "/api/shutdown":
                self._json({"ok": True})
                threading.Timer(0.4, self.server.shutdown).start()
                return
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": str(exc)}, 500)

        return self._json({"error": "not found", "path": path}, 404)

    # ---- 内部
    def _run(self, job, fn, args):
        try:
            result = fn(*args)
            job.finish(result=result)
        except Exception as exc:                                  # noqa: BLE001
            job.finish(error=str(exc))

    def _static(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        path = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not util.norm_key(path).startswith(util.norm_key(WEB_DIR)):
            return self._json({"error": "forbidden"}, 403)
        if not os.path.isfile(path):
            return self._json({"error": "not found", "file": rel}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _report_file(self, name):
        """只允许 reports 目录下的单层文件名，防止路径穿越。"""
        name = urllib.parse.unquote(name)
        if "/" in name or "\\" in name or ".." in name or not name:
            return self._json({"error": "forbidden"}, 403)
        reports = os.path.join(os.path.dirname(WEB_DIR), "reports")
        path = os.path.join(reports, name)
        if not os.path.isfile(path):
            return self._json({"error": "not found", "file": name}, 404)
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, job):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            last_ping = time.time()
            while True:
                events = job.drain(timeout=0.5)
                for ev in events:
                    payload = json.dumps(ev, ensure_ascii=False)
                    self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                if events:
                    self.wfile.flush()
                    last_ping = time.time()
                if job.finished and job.q.empty():
                    # 终态必须主动结束流，否则浏览器里的连接会一直挂着
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                    break
                if time.time() - last_ping > 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                self.close_connection = True
            except Exception:
                pass

    # ---- 提权
    def _elevate(self, port):
        if util.is_admin():
            return False, "当前已经是管理员权限"
        exe = sys.executable
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "wbcleaner_ui.py")
        new_port = int(port) + 1 if port else 8792
        params = '"%s" --port %d' % (script, new_port)
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, os.path.dirname(script), 1)
            if rc <= 32:
                return False, "提权请求被拒绝（返回码 %d）" % rc
            return True, "已启动管理员实例，端口 %d，请在弹出的新窗口里操作" % new_port
        except Exception as exc:                                  # noqa: BLE001
            return False, "提权失败：%s" % exc


def serve(port=8791, open_browser=True, app_window=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = "http://127.0.0.1:%d/?t=%s" % (port, TOKEN)
    print("WBCleaner 界面已启动")
    print("  地址：%s" % url)
    print("  权限：%s" % ("管理员" if util.is_admin() else "普通用户（系统级清理需提权）"))
    print("  停止：在此窗口按 Ctrl+C")
    if open_browser:
        threading.Thread(target=_open_browser, args=(url, app_window), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


def _open_browser(url, app_window=True):
    time.sleep(0.6)
    if app_window:
        for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, "--app=%s" % url,
                                      "--window-size=1280,880",
                                      "--disable-features=Translate",
                                      "--user-data-dir=%s" % _app_profile()])
                    return
                except OSError:
                    continue
    try:
        os.startfile(url)                                        # noqa: S606
    except Exception:
        pass


def _app_profile():
    base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "wbcleaner", "appwindow")
    os.makedirs(base, exist_ok=True)
    return base
