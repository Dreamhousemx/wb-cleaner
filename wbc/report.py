# -*- coding: utf-8 -*-
"""扫描报告：JSON（给机器）+ HTML（给人看）。纯静态、单文件、无外部依赖。"""

import datetime
import html
import json
import os

from . import __version__
from . import scanner
from . import util
from .rules import GROUP_TITLES, LEVEL_LABEL

LEVEL_STYLE = {
    "safe": ("#0f7b3f", "#e7f7ed", "#b7e6c8"),
    "caution": ("#8a5a00", "#fff6e5", "#ffe0a3"),
    "danger": ("#b3261e", "#fdecea", "#f6bdb8"),
    "keep": ("#4a5568", "#eef1f5", "#d5dbe3"),
}


def build_payload(scan, days, extra=None):
    payload = {
        "tool": "WBCleaner",
        "version": __version__,
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "age_filter_days": days,
        "user": os.environ.get("USERNAME", ""),
        "admin": util.is_admin(),
        "groups": {},
    }
    for group, items in scan.items():
        rows = []
        for it in items:
            rows.append({
                "rid": it.rid,
                "title": it.rule.title,
                "level": it.rule.level,
                "kind": it.rule.kind,
                "action": it.rule.action,
                "size": it.size,
                "size_human": util.human(it.size),
                "files": it.files,
                "targets": [util.short_path(t, 200) for t in it.targets],
                "count": len(it.targets),
                "desc": it.rule.desc,
                "impact": it.rule.impact,
                "min_age_days": it.rule.min_age_days,
                "default_on": it.rule.default_on,
                "actionable": it.actionable,
                "note": it.note,
                "requires_admin": it.rule.requires_admin,
            })
        tot, safe, caution, danger = scanner.totals(items)
        payload["groups"][group] = {
            "title": GROUP_TITLES.get(group, group),
            "total": tot,
            "total_human": util.human(tot),
            "safe": safe, "caution": caution, "danger": danger,
            "rows": rows,
        }
    if extra:
        payload["extra"] = extra
    return payload


def write_json(payload, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def render_html(payload):
    groups = payload["groups"]
    grand = sum(g["total"] for g in groups.values())
    safe_total = sum(g["safe"] for g in groups.values())
    caution_total = sum(g["caution"] for g in groups.values())
    danger_total = sum(g["danger"] for g in groups.values())

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WBCleaner 扫描报告</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1a202c;
 font:14px/1.6 "Microsoft YaHei","PingFang SC",-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:24px;margin:0 0 6px}
.sub{color:#64748b;font-size:13px;margin-bottom:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:26px}
.card{background:#fff;border:1px solid #e5e9f0;border-radius:12px;padding:16px 18px}
.card .k{font-size:12px;color:#64748b;margin-bottom:6px}
.card .v{font-size:22px;font-weight:700;letter-spacing:-.02em}
.card.safe .v{color:#0f7b3f}.card.caution .v{color:#8a5a00}.card.danger .v{color:#b3261e}
h2{font-size:17px;margin:32px 0 12px;padding-left:10px;border-left:4px solid #2563eb}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e9f0;
 border-radius:12px;overflow:hidden;font-size:13px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid #eef1f5;vertical-align:top}
th{background:#f8fafc;font-weight:600;color:#475569;font-size:12px;white-space:nowrap}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;
 border:1px solid;white-space:nowrap}
.on{color:#0f7b3f;font-weight:600}
.off{color:#94a3b8}
.path{font-family:Consolas,Menlo,monospace;font-size:12px;color:#64748b}
.desc{color:#334155}
.impact{color:#7c5a00;font-size:12px;margin-top:3px}
.note{color:#94a3b8;font-size:12px}
.admin{color:#b3261e;font-size:12px;font-weight:600}
footer{margin-top:36px;color:#94a3b8;font-size:12px;border-top:1px solid #e5e9f0;padding-top:14px}
.warn{background:#fff8e6;border:1px solid #ffe0a3;border-radius:10px;padding:12px 16px;
 color:#7c5a00;font-size:13px;margin:18px 0 0}
</style>
</head>
<body><div class="wrap">""")

    parts.append("<h1>扫尘 · 扫描报告</h1>")
    parts.append('<div class="sub">%s ｜ 用户 <b>%s</b> ｜ 管理员权限：%s ｜ 年龄过滤：%s ｜ 本报告只读，未删除任何文件</div>' % (
        html.escape(payload["time"]),
        html.escape(payload["user"]),
        "是" if payload["admin"] else "否（系统项需管理员）",
        ("%d 天前" % payload["age_filter_days"]) if payload["age_filter_days"] else "不限",
    ))

    parts.append('<div class="cards">')
    parts.append('<div class="card"><div class="k">合计可回收</div><div class="v">%s</div></div>' % util.human(grand))
    parts.append('<div class="card safe"><div class="k">安全项</div><div class="v">%s</div></div>' % util.human(safe_total))
    parts.append('<div class="card caution"><div class="k">需注意</div><div class="v">%s</div></div>' % util.human(caution_total))
    parts.append('<div class="card danger"><div class="k">高风险项</div><div class="v">%s</div></div>' % util.human(danger_total))
    parts.append("</div>")

    for group, g in groups.items():
        parts.append("<h2>%s ｜ 可回收 %s</h2>" % (html.escape(g["title"]), util.human(g["total"])))
        parts.append("<table><thead><tr><th>项目</th><th>等级</th><th>体积</th><th>默认</th>"
                     "<th>说明 / 影响</th></tr></thead><tbody>")
        for row in g["rows"]:
            fg, bg, bd = LEVEL_STYLE.get(row["level"], LEVEL_STYLE["keep"])
            badge = '<span class="badge" style="color:%s;background:%s;border-color:%s">%s</span>' % (
                fg, bg, bd, LEVEL_LABEL.get(row["level"], row["level"]))
            if not row["actionable"] and row["kind"] != "action":
                vol = '<span class="note">%s</span>' % html.escape(row["note"] or "0 B")
            else:
                vol = html.escape(row["size_human"])
                if row["files"]:
                    vol += '<br><span class="note">%d 文件</span>' % row["files"]
            default = '<span class="on">✓</span>' if row["default_on"] else '<span class="off">—</span>'
            info = '<div class="desc">%s</div>' % html.escape(row["desc"])
            if row["impact"]:
                info += '<div class="impact">影响：%s</div>' % html.escape(row["impact"])
            if row["requires_admin"]:
                info += '<div class="admin">需要管理员权限</div>'
            if row["min_age_days"]:
                info += '<div class="note">仅清理 %d 天前的数据</div>' % row["min_age_days"]
            if row["targets"]:
                info += '<div class="path">%s%s</div>' % (
                    html.escape(row["targets"][0]),
                    (" 等 %d 处" % row["count"]) if row["count"] > 1 else "")
            parts.append("<tr><td><b>%s</b></td>" % html.escape(row["title"]))
            parts.append("<td>%s</td><td class=\"num\">%s</td><td>%s</td><td>%s</td></tr>" % (
                badge, vol, default, info))
        parts.append("</tbody></table>")

    extra = payload.get("extra") or {}
    if extra.get("dism"):
        d = extra["dism"]
        parts.append("<h2>WinSxS 组件存储分析（DISM）</h2>")
        parts.append("<table><thead><tr><th>指标</th><th>数值</th></tr></thead><tbody>")
        for k, label in [("actual", "组件存储实际大小"), ("shared", "已与 Windows 共享"),
                         ("reclaimable", "备份和已禁用的功能（可回收）"),
                         ("reclaimable_packages", "可回收的程序包数")]:
            v = d.get(k)
            parts.append("<tr><td>%s</td><td class=\"num\">%s</td></tr>" % (
                label, util.human(v) if isinstance(v, int) and k != "reclaimable_packages" else v))
        parts.append("<tr><td>官方建议清理</td><td class=\"num\">%s</td></tr>" % ("是" if d.get("recommended") else "否"))
        parts.append("</tbody></table>")

    parts.append("""<div class="warn"><b>安全说明：</b>本工具默认把清理对象移动到隔离区而不是直接删除，
可用 <code>wbcleaner.py trash restore &lt;时间戳&gt;</code> 原样还原；
只有显式指定永久删除才会真正 unlink。被占用的文件会自动跳过并记录在日志里。</div>""")
    parts.append("<footer>由 扫尘 (WBCleaner) %s 生成 ｜ 规则与保护名单见 wbc/rules.py ｜ "
                 "WinSxS 只能通过 DISM 清理，手工删除会导致系统更新与修复失效</footer>" % payload["version"])
    parts.append("</div></body></html>")
    return "".join(parts)


def write_html(payload, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_html(payload))
    return path
