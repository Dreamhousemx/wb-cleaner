#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""可视化界面（本地服务）集成测试。

自己起一个临时端口的服务，然后用 HTTP 把界面用到的每个接口都跑一遍：
  token 校验 / 静态资源 / env / 扫描(SSE) / 扫描缓存 / dry-run 清理(SSE) / 报告 / 隔离区 / 规则表 / 保护名单
只做只读与演练，不会执行任何真实清理。

运行： python tests/uitest.py
"""

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["WBC_UI_TOKEN"] = "selftest-token"      # 必须在导入 webui 之前设置
from wbc import webui                              # noqa: E402

TOKEN = os.environ["WBC_UI_TOKEN"]
PASS, FAIL = [], []
PORT = 8799


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s  %s" % ("\033[32mPASS\033[0m" if cond else "\033[31mFAIL\033[0m",
                           name, detail if not cond else ""))


def url(path, token=TOKEN):
    sep = "&" if "?" in path else "?"
    return "http://127.0.0.1:%d%s%s%s" % (PORT, path, sep, "t=%s" % token if token else "")


def get(path, token=TOKEN, timeout=30):
    with urllib.request.urlopen(url(path, token), timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def get_bytes(path, token=TOKEN, timeout=30):
    with urllib.request.urlopen(url(path, token), timeout=timeout) as r:
        return r.status, r.read()


def post(path, payload=None, timeout=30):
    req = urllib.request.Request(
        url(path), data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def sse(job_id, timeout=180):
    """消费任务事件流，直到收到 event: end。"""
    events = []
    req = urllib.request.Request(url("/api/events?job=%s" % job_id))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
            elif line.startswith("event: end"):
                break
    return events


def main():
    print("=" * 64)
    print(" WBCleaner 界面服务集成测试（只读 + 演练，不做真实清理）")
    print("=" * 64)

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), webui.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    try:
        # ---------------- 1 静态资源与鉴权
        print("\n[1] 静态资源与鉴权")
        status, html = get("/")
        check("首页返回 200", status == 200 and len(html) > 2000, "len=%d" % len(html))
        check("首页引用了 css/js",
              "/static/app.css" in html and "/static/app.js" in html)
        for name, must in (("app.css", "--accent"), ("app.js", "openRunDialog")):
            st, body = get("/static/%s" % name)
            check("静态文件 %s 可访问" % name, st == 200 and must in body,
                  "status=%s len=%d" % (st, len(body)))

        st, icon = get_bytes("/static/app-icon.png")
        check("应用图标可访问", st == 200 and icon[:4] == b"\x89PNG" and len(icon) > 5000,
              "status=%s len=%d magic=%r" % (st, len(icon), icon[:4]))
        check("首页引用了图标（favicon + 顶栏 logo）",
              html.count("/static/app-icon.png") >= 2,
              "出现 %d 次" % html.count("/static/app-icon.png"))
        check("界面标题带应用名", "<title>扫尘" in html, html[:120])

        ico = os.path.join(ROOT, "icon", "app-icon.ico")
        check("桌面快捷方式用的 ico 存在", os.path.isfile(ico),
              "请在 icon/ 下找到 app-icon.ico")
        try:
            get("/api/env", token="")
            check("无 token 被拒绝", False, "竟然放行了")
        except urllib.error.HTTPError as exc:
            check("无 token 被拒绝", exc.code == 403, "code=%s" % exc.code)
        try:
            get("/api/env", token="wrong")
            check("错误 token 被拒绝", False)
        except urllib.error.HTTPError as exc:
            check("错误 token 被拒绝", exc.code == 403, "code=%s" % exc.code)
        try:
            get("/static/../wbcleaner.py")
            check("路径穿越被拦截", False)
        except urllib.error.HTTPError as exc:
            check("路径穿越被拦截", exc.code in (403, 404), "code=%s" % exc.code)

        # ---------------- 2 环境
        print("\n[2] 环境接口")
        _, body = get("/api/env")
        env = json.loads(body)
        check("env 含必要字段",
              all(k in env for k in ("version", "admin", "disk", "trash", "dism")),
              str(list(env.keys())))
        check("磁盘信息可读", env["disk"]["total"] > 0, str(env["disk"]))
        check("隔离区字段存在", isinstance(env["trash"], list))

        # ---------------- 3 扫描
        print("\n[3] 扫描（SSE 进度）")
        t0 = time.time()
        _, j = post("/api/scan", {"days": 3})
        job = j.get("job")
        check("扫描任务已创建", bool(job), str(j))
        events = sse(job)
        kinds = {}
        for e in events:
            kinds[e["type"]] = kinds.get(e["type"], 0) + 1
        check("收到进度事件", kinds.get("progress", 0) >= 40, str(kinds))
        check("收到 done 事件", kinds.get("done", 0) == 1, str(kinds))
        done = [e for e in events if e["type"] == "done"][0]["result"]
        groups = done["groups"]
        check("返回三组结果",
              set(groups) == {"workbuddy", "codex", "system"}, str(set(groups)))
        check("每组都有 items",
              all(len(g["items"]) > 0 for g in groups.values()))
        wb = groups["workbuddy"]
        check("WorkBuddy 有可回收体积", wb["total"] > 0, wb["totalHuman"])
        check("天数过滤已生效", done["days"] == 3, str(done["days"]))
        check("含环境快照", "env" in done and done["env"]["disk"]["total"] > 0)
        print("     扫描耗时 %.1fs，可回收 %s / %s / %s" % (
            time.time() - t0, wb["totalHuman"],
            groups["codex"]["totalHuman"], groups["system"]["totalHuman"]))

        item = wb["items"][0]
        check("条目字段完整",
              all(k in item for k in ("rid", "title", "level", "sizeHuman", "desc",
                                      "impact", "actionable", "protected", "defaultOn")),
              str(sorted(item.keys())))

        # ---------------- 4 扫描缓存
        print("\n[4] 扫描结果缓存")
        _, body = get("/api/scan/cached")
        cached = json.loads(body)
        check("缓存里有数据", bool(cached.get("groups")) and len(cached["groups"]) == 3)
        check("缓存带有时间戳", bool(cached.get("scannedAt")))

        # ---------------- 5 规则 / 保护名单
        print("\n[5] 规则表与保护名单")
        _, body = get("/api/rules")
        rules = json.loads(body)["rules"]
        check("规则表非空", len(rules) >= 40, "%d 条" % len(rules))
        check("规则含保护标记", any(r["protected"] for r in rules))
        _, body = get("/api/protected")
        prot = json.loads(body)["protected"]
        check("保护名单非空", len(prot) >= 10, "%d 条" % len(prot))
        check("保护名单含 WinSxS",
              any("WinSxS" in p["path"] for p in prot), str(prot[:3]))

        # ---------------- 6 dry-run 清理
        print("\n[6] 演练清理（dry-run，不修改任何文件）")
        safe_rids = [i["rid"] for i in groups["codex"]["items"]
                     if i["actionable"] and i["level"] == "safe" and not i["protected"]]
        check("能选出安全项", bool(safe_rids), str(safe_rids))
        _, j = post("/api/clean", {"rids": safe_rids[:2], "dryRun": True,
                                   "permanent": False, "allowSystem": False})
        events = sse(j.get("job"))
        done = [e for e in events if e["type"] == "done"]
        check("dry-run 正常返回", len(done) == 1,
              str([e for e in events if e["type"] == "error"]))
        res = done[0]["result"]
        check("dry-run 标记正确", res["dryRun"] is True)
        check("dry-run 未移动文件", res["moved"] == 0 and res["deleted"] == 0,
              "moved=%s deleted=%s" % (res["moved"], res["deleted"]))
        check("dry-run 仍给出回收量", res["freed"] > 0, res["freedHuman"])
        check("未产生隔离批次", not res["trashDir"], str(res["trashDir"]))
        check("返回磁盘剩余", bool(res["diskFreeHuman"]), res["diskFreeHuman"])
        check("日志事件已推送", any(e["type"] == "log" for e in events))

        # ---------------- 7 绑定保护项应被拒绝
        print("\n[7] 保护项不可被清理")
        protected_rids = [i["rid"] for i in groups["workbuddy"]["items"] if i["protected"]]
        if protected_rids:
            _, j = post("/api/clean", {"rids": protected_rids, "dryRun": False,
                                       "permanent": True, "allowSystem": True})
            events = sse(j.get("job"))
            errs = [e for e in events if e["type"] == "error"]
            check("保护项被拒绝（没有可清理内容）", len(errs) == 1,
                  str([e.get("message") for e in errs]))
            check("错误信息可读", errs and "没有可清理内容" in errs[0]["message"],
                  str(errs))
        # 未知 id
        _, j = post("/api/clean", {"rids": ["不存在的规则"], "dryRun": True})
        events = sse(j.get("job"))
        errs = [e for e in events if e["type"] == "error"]
        check("未知规则 id 被拒绝", len(errs) == 1 and "未知清理项" in errs[0]["message"],
              str(errs))

        # ---------------- 8 报告导出
        print("\n[8] 报告导出")
        _, j = post("/api/report", {})
        events = sse(j.get("job"))
        done = [e for e in events if e["type"] == "done"]
        check("报告任务成功", len(done) == 1, str(events[-1]))
        rpath = done[0]["result"]["path"]
        check("报告文件已生成", os.path.isfile(rpath), rpath)
        name = os.path.basename(rpath)
        # 静态服务能不能取到报告
        req = urllib.request.Request(
            "http://127.0.0.1:%d/reports/%s?t=%s" % (PORT, name, TOKEN))
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8")
        check("报告可经 /reports/ 访问", "扫尘 · 扫描报告" in html)
        try:
            get("/reports/../wbcleaner.py")
            check("报告路径穿越被拦截", False)
        except urllib.error.HTTPError as exc:
            check("报告路径穿越被拦截", exc.code in (403, 404), "code=%s" % exc.code)

        # ---------------- 9 隔离区接口
        print("\n[9] 隔离区")
        _, body = get("/api/trash")
        tr = json.loads(body)
        check("隔离区列表可读", isinstance(tr["entries"], list) and "totalHuman" in tr)
        try:
            post("/api/trash/restore", {})
            check("还原缺参数被拒绝", False)
        except urllib.error.HTTPError as exc:
            check("还原缺参数被拒绝", exc.code == 400, "code=%s" % exc.code)

        # ---------------- 10 系统动作的确认链路
        print("\n[10] 系统动作（不让它真的执行）")
        _, j = post("/api/action", {"action": "不存在的动作"})
        events = sse(j.get("job"))
        errs = [e for e in events if e["type"] == "error"]
        check("未知动作被拒绝", len(errs) == 1 and "未知动作" in errs[0]["message"],
              str(errs))
        # dism_analyze 是只读的，可以真跑一次，验证链路与解析
        if os.environ.get("WBC_TEST_DISM") == "1":
            _, j = post("/api/action", {"action": "dism_analyze"})
            events = sse(j.get("job"), timeout=600)
            done = [e for e in events if e["type"] == "done"]
            check("DISM 只读分析链路可用", len(done) == 1,
                  str([e.get("message") for e in events if e["type"] == "error"]))
        else:
            print("     （跳过 DISM 实跑；需要时用 WBC_TEST_DISM=1 运行）")

        # ---------------- 11 前端静态一致性
        print("\n[11] 前端静态一致性")
        web = os.path.join(ROOT, "web")
        html_src = open(os.path.join(web, "index.html"), encoding="utf-8").read()
        js_src = open(os.path.join(web, "app.js"), encoding="utf-8").read()
        css_src = open(os.path.join(web, "app.css"), encoding="utf-8").read()

        html_ids = set(re.findall(r'\bid="([^"]+)"', html_src))
        js_ids = set(re.findall(r"\$\('([^']+)'\)", js_src))
        # 弹窗内容是运行时拼出来的，这两个 id 只存在于 JS 模板里
        runtime_ids = {"confirmWord", "allowSys"}
        missing = sorted(i for i in js_ids if i not in html_ids and i not in runtime_ids)
        check("JS 引用的 DOM id 都存在", not missing, str(missing))

        css_classes = set(re.findall(r"\.([a-zA-Z_][\w-]*)", css_src))
        used = set(re.findall(r'class="([^"]*)"', html_src)) | \
            set(re.findall(r'class="([^"]*)"', js_src))
        tokens = set()
        for u in used:
            for t in re.sub(r"\$\{[^}]*\}", " ", u).split():
                tokens.add(t)
        # 状态词是 JS 里按数据拼上去的，CSS 里以 .safe/.on 之类的组合形式存在
        dynamic_words = {"safe", "caution", "danger", "keep", "info", "warn", "error",
                         "debug", "ok", "zero", "on", "off", "dim", "bad", "perm",
                         "active", "open", "hide", "clickable", "mono", "hidden"}
        undef = sorted(t for t in tokens
                       if t not in css_classes and t not in dynamic_words)
        check("模板用到的 class 都有样式定义", not undef, str(undef))

        check("CSS 花括号配对", css_src.count("{") == css_src.count("}"),
              "%d vs %d" % (css_src.count("{"), css_src.count("}")))
        check("index.html 无外部依赖（离线可用）",
              "http://" not in html_src and "https://" not in html_src,
              "含外部链接")
        check("界面未使用内联事件属性",
              "onclick=" not in html_src.lower(),
              "index.html 里出现了 onclick")

        # ---------------- 12 未知路径
        print("\n[12] 其它")
        try:
            get("/api/nope")
            check("未知 API 返回 404", False)
        except urllib.error.HTTPError as exc:
            check("未知 API 返回 404", exc.code == 404, "code=%s" % exc.code)

    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n" + "=" * 64)
    print(" 通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("   失败：%s" % f)
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
