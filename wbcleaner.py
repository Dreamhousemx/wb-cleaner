#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WBCleaner —— WorkBuddy / Codex / C 盘 无用文件清理工具（主程序）

用法
  python wbcleaner.py                     进入交互菜单
  python wbcleaner.py scan                只扫描并打印报告（不做任何修改）
  python wbcleaner.py scan --html r.html  额外生成 HTML 报告
  python wbcleaner.py clean --only safe   按等级清理（默认进隔离区，可还原）
  python wbcleaner.py clean --rids wb-logs-sandbox,cx-tmp --yes
  python wbcleaner.py clean --group system --only all --yes
  python wbcleaner.py trash list          查看隔离区
  python wbcleaner.py trash restore <ts>  还原某个时间戳
  python wbcleaner.py trash purge [<ts>]  永久删除隔离区内容
  python wbcleaner.py dism analyze        分析 WinSxS 可回收空间（只读）
  python wbcleaner.py dism cleanup        清理 WinSxS（DISM 官方方式）
  python wbcleaner.py dism resetbase      深度清理（不可逆）
  python wbcleaner.py doctor              环境自检
  python wbcleaner.py selftest            规则与引擎单元自检

安全约定
  * 不带 --execute 一律 dry-run；交互菜单里必须手工输入 CLEAN 才动手。
  * 默认「隔离区」模式，随时可还原；--permanent 才真正删除。
  * 保护名单（凭证、记忆、运行时、WinSxS 本体等）在 wbc/rules.py 里硬编码。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wbc import __version__, executor, report, rules as R, scanner, syswin, util
from wbc.util import C_, human

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(APP_DIR, "logs")


# ==================================================================== 显示辅助


def cjk_width(s):
    """近似字符显示宽度（中文按 2 格算）。"""
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x1100 and not (0x2000 <= ord(ch) <= 0x2BFF) else 1
    return w


def pad(s, width, align="left"):
    gap = max(0, width - cjk_width(s))
    if align == "right":
        return " " * gap + s
    return s + " " * gap


def level_color(level):
    return {"safe": C_.GREEN, "caution": C_.YELLOW, "danger": C_.RED,
            "keep": C_.GRAY}.get(level, "")


def bar(fraction, width=22):
    n = int(max(0.0, min(1.0, fraction)) * width)
    return "█" * n + "░" * (width - n)


def make_logger(verbose=False, echo=True):
    os.makedirs(LOG_DIR, exist_ok=True)
    name = "wbcleaner-%s.log" % time.strftime("%Y%m%d")
    return util.Logger(os.path.join(LOG_DIR, name), verbose=verbose, echo=echo)


def header_block():
    free, total = util.free_space(r"C:\\")
    used = total - free
    lines = [
        "%s%s 扫尘 (WBCleaner) %s%s —— WorkBuddy / Codex / C盘 无用文件清理" % (
            C_.BOLD, C_.CYAN, __version__, C_.RESET),
        "%s用户 %s ｜ 管理员 %s ｜ C盘 %s / %s 已用%s" % (
            C_.GRAY, os.environ.get("USERNAME", "?"),
            (C_.GREEN + "是" + C_.GRAY) if util.is_admin() else (C_.RED + "否" + C_.GRAY),
            human(used), human(total), C_.RESET),
        "%sC盘占用 %s%s" % (C_.GRAY, bar(used / total if total else 0), C_.RESET),
    ]
    return lines


def print_header(title=None):
    print()
    for line in header_block():
        print("  " + line)
    if title:
        print("\n  " + C_.BOLD + title + C_.RESET)
    print("  " + C_.GRAY + "─" * 78 + C_.RESET)


def cell(text, width=0, color="", align="left"):
    """先按纯文本算宽度，再套颜色，避免 ANSI 转义把列宽算歪。"""
    return (color or "") + pad(text, width, align) + (C_.RESET if color else "")


def print_scan_table(items, selection=None, days=None):
    print("  " + C_.BOLD + cell("#", 3) + cell("项目", 34) + cell("等级", 6)
          + cell("体积", 10, align="right") + cell(" 勾选", 7) + "状态" + C_.RESET)
    print("  " + C_.GRAY + "─" * 80 + C_.RESET)
    for idx, it in enumerate(items, 1):
        lv = it.rule.level
        color = level_color(lv)
        mark = "●" if (selection and it.rid in selection) else "○"
        has_size = bool(it.size)
        title = it.rule.title
        if it.rule.min_age_days:
            title += " (>%dd)" % it.rule.min_age_days

        if it.rule.kind in ("action", "report"):
            status, scolor = it.note or "—", C_.GRAY
        elif it.actionable:
            status, scolor = "可清理", color
        else:
            status, scolor = it.note or "无内容", C_.GRAY

        # 默认勾选策略：只有 safe 级才默认勾选，其余一律"手动"
        if it.rule.protected or it.rule.kind == "report":
            dflt, dcolor = "—", C_.GRAY
        elif it.rule.default_on:
            dflt, dcolor = "✓", C_.GREEN
        elif it.actionable or it.rule.kind == "action":
            dflt, dcolor = "手动", C_.YELLOW
        else:
            dflt, dcolor = "—", C_.GRAY

        print("  " + cell(str(idx), 3)
              + cell(mark + " " + title, 34, color)
              + cell(it.rule.level_label, 6, color)
              + cell(human(it.size) if has_size else "-", 10, "" if has_size else C_.GRAY,
                     align="right")
              + cell(" " + dflt, 7, dcolor)
              + cell(status, 0, scolor))
    print("  " + C_.GRAY + "─" * 80 + C_.RESET)


def print_manual_hints(items, width=76):
    """列出「默认不勾选、需要用户手动决定」的项目及其影响——这是安全边界的一部分。"""
    manual = [i for i in items
              if not i.rule.default_on and i.actionable
              and not i.rule.protected and i.rule.kind != "report"]
    if not manual:
        return
    print("\n  %s以下 %d 项默认不勾选，需要你确认影响后手动选择：%s" % (
        C_.YELLOW, len(manual), C_.RESET))
    for it in manual:
        color = level_color(it.rule.level)
        print("  %s· [%s] %s%s%s  %s%s%s" % (
            color, it.rule.level_label, C_.BOLD, it.rule.title, C_.RESET,
            C_.GRAY, human(it.size), C_.RESET))
        if it.rule.impact:
            print("    %s影响：%s%s" % (color, it.rule.impact, C_.RESET))


def print_totals(items, selection):
    tot, safe, caution, danger = scanner.totals(
        [i for i in items if not selection or i.rid in selection])
    print("  已选 %s%d%s 项 ｜ %s安全 %s%s ｜ %s注意 %s%s ｜ %s危险 %s%s" % (
        C_.BOLD, len(selection) if selection is not None else len(items), C_.RESET,
        C_.GREEN, human(safe), C_.RESET, C_.YELLOW, human(caution), C_.RESET,
        C_.RED, human(danger), C_.RESET))
    print("  %s预计可回收：%s%s%s（部分需管理员权限）" % (
        C_.BOLD, C_.GREEN, human(tot), C_.RESET))


# ==================================================================== 交互确认


def confirm_cb(text, level):
    color = C_.RED if level == "danger" else C_.YELLOW
    print("\n  %s⚠ %s%s" % (color, text, C_.RESET))
    word = "DANGER" if level == "danger" else "yes"
    ans = input("  输入 %s 继续，其它任意键取消 > " % word).strip()
    return ans == word


def interactive_confirm(items, selection, permanent, days):
    todo = [i for i in items if i.rid in selection and i.actionable]
    if not todo:
        print("  " + C_.YELLOW + "没有选中任何有内容的项目。" + C_.RESET)
        return False
    print()
    for it in todo:
        color = level_color(it.rule.level)
        print("  %s•%s %s%-32s%s %s%10s%s" % (
            color, C_.RESET, C_.BOLD, it.rule.title, C_.RESET,
            color, human(it.size), C_.RESET))
        # 非安全项必须把影响摆在眼前，别让人凭感觉点确认
        if it.rule.level in ("caution", "danger") and it.rule.impact:
            print("    %s⚠ %s%s" % (color, it.rule.impact, C_.RESET))
    tot, safe, caution, danger = scanner.totals(todo)
    mode = C_.RED + "永久删除（不可恢复）" + C_.RESET if permanent else \
        C_.GREEN + "移入隔离区（可还原）" + C_.RESET
    print("\n  共 %d 项，合计 %s%s%s ｜ 模式：%s" % (len(todo), C_.BOLD, human(tot), C_.RESET, mode))
    if days:
        print("  %s只清理 %d 天前的数据%s" % (C_.GRAY, days, C_.RESET))
    print("\n  " + C_.YELLOW + "⚠ 此操作会移动/删除文件，请确认已选中正确项目。" + C_.RESET)
    ans = input("  输入 " + C_.BOLD + "CLEAN" + C_.RESET + " 开始执行，其它任意键取消 > ").strip()
    return ans == "CLEAN"


# ==================================================================== 命令实现


def do_scan(args):
    logger = make_logger(verbose=getattr(args, "verbose", False))
    groups = [args.group] if getattr(args, "group", None) else ["workbuddy", "codex", "deepseek", "system"]
    days = getattr(args, "days", None)
    print_header("扫描中，请稍候（只读操作，不会修改任何文件）...")

    def progress(rule):
        if sys.stdout.isatty():          # 重定向到文件时不要刷屏
            print("  %s·%s %s          " % (C_.GRAY, C_.RESET, rule.title),
                  end="\r", flush=True)

    scan = scanner.scan_all(groups, days_override=days, progress=progress)
    if sys.stdout.isatty():
        print(" " * 80, end="\r")

    free, total = util.free_space(r"C:\\")
    extra = {"disk": {"free": free, "total": total}}
    dism = scanner.load_dism_cache()
    if dism:
        extra["dism"] = dism

    payload = report.build_payload(scan, days, extra)

    for group, items in scan.items():
        print_header(R.GROUP_TITLES.get(group, group))
        print_scan_table(items, selection=None, days=days)
        tot, safe, caution, danger = scanner.totals(items)
        print("  可回收 %s%s%s ｜ 安全 %s ｜ 注意 %s ｜ 危险 %s" % (
            C_.BOLD, human(tot), C_.RESET, human(safe), human(caution), human(danger)))
        print_manual_hints(items)
        protected = [i for i in items if not i.actionable and i.rule.kind == "report"]
        if protected:
            keep = sum(i.size for i in protected)
            print("\n  %s另有保护项 %d 项、合计 %s（运行时/凭证/数据库，永不清理）%s" % (
                C_.GRAY, len(protected), human(keep), C_.RESET))

    grand, safe, _, _ = scanner.totals([i for items in scan.values() for i in items])
    print_header("汇总")
    print("  本次可回收合计：%s%s%s" % (C_.BOLD, C_.GREEN, human(grand) + C_.RESET))
    print("  %s下一步建议：%s执行 python wbcleaner.py clean --only safe --yes "
          "清理安全项（默认进隔离区，可还原）%s" % (C_.GRAY, C_.CYAN, C_.RESET))

    if getattr(args, "json", None):
        path = report.write_json(payload, args.json)
        print("  JSON 报告：%s" % path)
    html_path = getattr(args, "html", None)
    if html_path:
        path = report.write_html(payload, html_path)
        print("  HTML 报告：%s" % path)
    return 0


def select_by_spec(items, spec):
    """spec: safe | all | default | rid1,rid2,..."""
    spec = (spec or "default").lower()
    actionable = {i.rid: i for i in items if i.actionable}
    if spec == "all":
        return set(actionable)
    if spec == "safe":
        return {rid for rid, i in actionable.items() if i.rule.level == "safe"}
    if spec == "default":
        return {rid for rid, i in actionable.items() if i.rule.default_on}
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [w for w in wanted if w not in {i.rid for i in items}]
    if unknown:
        raise SystemExit("未知的清理项 id：%s\n可用 id：%s" % (
            ", ".join(unknown), ", ".join(sorted(R.RULES_BY_ID))))
    return set(wanted)


def do_clean(args):
    dry_run = getattr(args, "dry_run", False)
    logger = make_logger(verbose=getattr(args, "verbose", False) or dry_run)
    groups = [args.group] if getattr(args, "group", None) else ["workbuddy", "codex", "deepseek", "system"]
    days = getattr(args, "days", None)
    permanent = getattr(args, "permanent", False)

    print_header("扫描目标...")
    scan = scanner.scan_all(groups, days_override=days)
    items = [i for g in scan.values() for i in g]

    selection = select_by_spec(items, getattr(args, "only", "default") or
                               getattr(args, "rids", None))
    if getattr(args, "rids", None) and not getattr(args, "only", None):
        selection = select_by_spec(items, args.rids)

    todo = [i for i in items if i.rid in selection and i.actionable]
    if not todo:
        print("  " + C_.YELLOW + "没有匹配到有内容的清理项。" + C_.RESET)
        for i in items:
            if i.rid in selection:
                print("  %s· %s：%s%s" % (C_.GRAY, i.rule.title, i.note or "空", C_.RESET))
        return 0

    tot, _, _, _ = scanner.totals(todo)
    print("  选中 %d 项，可回收 %s%s%s ｜ 模式：%s" % (
        len(todo), C_.BOLD, human(tot), C_.RESET,
        (C_.RED + "永久删除" + C_.RESET) if permanent else
        (C_.GREEN + "隔离区（可还原）" + C_.RESET)))

    if dry_run:
        print("  " + C_.YELLOW + "（--dry-run：仅列出将执行的动作，不做任何修改）" + C_.RESET)
    elif not getattr(args, "yes", False):
        if not interactive_confirm(items, selection, permanent,
                                  days if days else None):
            print("  " + C_.YELLOW + "已取消（未做任何修改）。" + C_.RESET)
            return 0

    print_header("执行清理")
    result = executor.execute(
        items, selection, permanent=permanent, dry_run=dry_run,
        logger=logger, confirm=confirm_cb if not args.no_confirm else (lambda t, l: True),
    )

    print_header("结果")
    if dry_run:
        print("  " + C_.YELLOW + "演练模式（--dry-run）：上面列出了将要处理的目标，"
              "实际未做任何修改。" + C_.RESET)
    print("  释放 %s%s（%d 个文件）%s" % (
        C_.BOLD + C_.GREEN, human(result.freed), result.files, C_.RESET))
    if permanent:
        print("  " + C_.RED + "⚠ 永久删除模式：本次不做隔离备份，无法还原。" + C_.RESET)
    print("  移动 %d 个目标到隔离区%s" % (
        result.moved, "" if permanent else "（可随时还原）"))
    if result.deleted:
        print("  永久删除 %d 个目标" % result.deleted)
    if result.skipped:
        print("  " + C_.YELLOW + "跳过 %d 个（被占用/权限不足）" % len(result.skipped) + C_.RESET)
        for p, why in result.skipped[:5]:
            print("    %s· %s：%s%s" % (C_.GRAY, util.short_path(p), why, C_.RESET))
    for action, ok, detail in result.actions:
        print("  %s%s %s%s -> %s" % (
            C_.GREEN if ok else C_.RED, "✓" if ok else "✗", action, C_.RESET, detail))
    if result.trash_dir:
        print("\n  隔离区：%s%s%s" % (C_.CYAN, result.trash_dir, C_.RESET))
        print("  还原：%s python wbcleaner.py trash restore %s%s" % (
            C_.BOLD, os.path.basename(result.trash_dir), C_.RESET))
    free, total = util.free_space(r"C:\\")
    print("  C 盘可用：%s%s%s" % (C_.BOLD, human(free), C_.RESET))
    print("  日志：%s%s%s" % (C_.GRAY, logger.path, C_.RESET))
    return 0


def do_trash(args):
    logger = make_logger(echo=True)
    action = args.trash_action
    if action == "list" or action is None:
        entries = executor.list_trash()
        if not entries:
            print("  隔离区为空（还没有执行过隔离清理，或已全部清除）")
            return 0
        print_header("隔离区")
        print("  %-18s %10s %8s %s" % ("时间戳", "体积", "条目", "位置"))
        print("  " + C_.GRAY + "─" * 78 + C_.RESET)
        for e in entries:
            print("  %-18s %10s %8d %s" % (e["ts"], human(e["size"]), e["entries"],
                                           util.short_path(e["path"], 40)))
        print("\n  还原：python wbcleaner.py trash restore <时间戳>")
        print("  清空：python wbcleaner.py trash purge <时间戳>")
        return 0
    if action == "restore":
        if not args.ts:
            raise SystemExit("请给出时间戳：trash restore <YYYYmmdd-HHMMSS>")
        return executor.restore_trash(args.ts, logger=logger, dry_run=args.dry_run)
    if action == "purge":
        return executor.purge_trash(args.ts, logger=logger)
    raise SystemExit("未知子命令：%s" % action)


def do_dism(args):
    logger = make_logger(echo=True)
    what = args.dism_action or "analyze"
    if what == "analyze":
        ok, detail = syswin.dism_analyze(logger)
    elif what == "cleanup":
        ok, detail = syswin.dism_cleanup(logger, reset_base=False)
    elif what == "resetbase":
        print("  " + C_.RED + "⚠ /ResetBase 不可逆：之后所有已安装更新都无法卸载。" + C_.RESET)
        ans = input("  输入 DANGER 继续 > ").strip()
        if ans != "DANGER":
            print("  已取消。")
            return 0
        ok, detail = syswin.dism_cleanup(logger, reset_base=True)
    else:
        raise SystemExit("未知子命令：%s（可选 analyze / cleanup / resetbase）" % what)
    print(("  " + (C_.GREEN if ok else C_.RED) + "%s" + C_.RESET) % detail)
    print("  日志：%s" % logger.path)
    return 0 if ok else 1


def do_doctor(args):
    print_header("环境自检")
    checks = [
        ("Windows 系统", True, sys.platform),
        ("管理员权限", util.is_admin(),
         "已提权" if util.is_admin() else "未提权，系统级清理项不可用（用 run.bat 启动）"),
        ("DISM 可用", os.path.exists(syswin._dism_exe()), syswin._dism_exe()),
        ("powercfg 可用", True, "用于休眠文件管理"),
        ("规则数", len(R.ALL_RULES), "%d 条规则 / %d 条保护名单" % (
            len([r for r in R.ALL_RULES if not r.protected]), len(R.PROTECTED))),
    ]
    for name, ok, detail in checks:
        print("  %s%s%s %-16s %s" % (C_.GREEN if ok else C_.RED, "✓" if ok else "✗",
                                     C_.RESET, name, detail))

    viol = R.default_on_violations()
    print("\n  默认勾选策略：%s" % (
        C_.GREEN + "仅 safe 级默认勾选 ✓" + C_.RESET if not viol
        else C_.RED + "有 %d 条非安全项被默认勾选 ✗" % len(viol) + C_.RESET))

    print("\n  清理目标可用性：")
    for group in ("workbuddy", "codex", "deepseek", "system"):
        items = scanner.scan_group(group)
        avail = sum(1 for i in items if i.actionable)
        tot = sum(i.size for i in items if i.actionable)
        manual = [i for i in items if i.actionable and not i.rule.default_on]
        print("    %-22s %2d/%2d 项有内容，可回收 %s%s" % (
            R.GROUP_TITLES[group], avail, len(items), human(tot),
            C_.GRAY + "（其中 %d 项需手动勾选）%s" % (len(manual), C_.RESET) if manual else ""))
    free, total = util.free_space(r"C:\\")
    print("\n  C 盘：可用 %s / 总计 %s" % (human(free), human(total)))
    tr = executor.list_trash()
    if tr:
        print("  隔离区：%d 个批次，合计 %s（trash list 查看）" % (
            len(tr), human(sum(t["size"] for t in tr))))
    return 0


# ==================================================================== 交互菜单


MENU = """
  {b}[1]{r} 清理 WorkBuddy 文件            {g}(日志 / trace / 缓存 / 会话备份)
  {b}[2]{r} 清理 Codex 文件                {g}(临时目录 / 插件与市场缓存 / 日志库)
  {b}[3]{r} 清理 DeepSeek Harness 文件     {g}(更新器残留 / 桌面缓存 / 会话回收站)
  {b}[4]{r} 清理 C 盘无用文件              {g}(WinSxS / 更新缓存 / 临时文件 / 包缓存)
  {b}[5]{r} 一次扫描全部并生成 HTML 报告
  {b}[6]{r} 隔离区管理（还原 / 永久删除）
  {b}[7]{r} WinSxS 组件存储（DISM 分析 / 清理）
  {b}[8]{r} 环境自检
  {b}[0]{r} 退出

  {g}默认只勾选「安全」级项目（删了不影响软件使用）；「注意 / 高风险」默认不勾，
  展开对应条目可看具体影响说明，需要时手动勾选。{r}
"""


def menu_loop(args):
    permanent = bool(getattr(args, "permanent", False))
    days = getattr(args, "days", None)
    verbose = bool(getattr(args, "verbose", False))
    logger = make_logger(verbose=verbose)

    while True:
        print_header("主菜单")
        print(MENU.format(b=C_.BOLD + C_.CYAN, r=C_.RESET, g=C_.GRAY))
        print("  当前模式：%s ｜ 年龄阈值：%s" % (
            C_.RED + "永久删除" if permanent else C_.GREEN + "隔离区（可还原）" + C_.RESET,
            ("%d 天前" % days) if days else "不限" + C_.RESET))
        try:
            choice = input("  请选择 > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        try:
            if choice in ("0", "q", "quit", "exit"):
                return 0
            elif choice == "1":
                group_flow("workbuddy", days, permanent, logger)
            elif choice == "2":
                group_flow("codex", days, permanent, logger)
            elif choice == "3":
                group_flow("deepseek", days, permanent, logger)
            elif choice == "4":
                group_flow("system", days, permanent, logger)
            elif choice == "5":
                out = os.path.join(APP_DIR, "reports",
                                   "scan-%s.html" % time.strftime("%Y%m%d-%H%M%S"))
                do_scan(argparse.Namespace(group=None, days=days, json=out.replace(".html", ".json"),
                                           html=out, verbose=verbose))
                print("\n  报告已生成：%s%s%s" % (C_.CYAN, out, C_.RESET))
                input("  回车返回主菜单 > ")
            elif choice == "6":
                do_trash(argparse.Namespace(trash_action="list", ts=None, dry_run=False))
                ans = input("\n  r=还原  p=永久删除 其它=返回 > ").strip().lower()
                entries = executor.list_trash()
                if ans == "r" and entries:
                    ts = input("  输入要还原的时间戳（默认 %s）> " % entries[0]["ts"]).strip() or entries[0]["ts"]
                    executor.restore_trash(ts, logger=logger, dry_run=False)
                    input("  回车继续 > ")
                elif ans == "p" and entries:
                    ts = input("  输入要永久删除的时间戳（%s=全部）> " % entries[0]["ts"]).strip()
                    if input("  永久删除不可恢复，输入 PURGE 确认 > ").strip() == "PURGE":
                        executor.purge_trash(ts or None, logger=logger)
                    input("  回车继续 > ")
            elif choice == "7":
                dism_menu(logger)
            elif choice == "8":
                do_doctor(args)
                input("  回车返回主菜单 > ")
            else:
                print("  " + C_.YELLOW + "无效选择" + C_.RESET)
        except KeyboardInterrupt:
            print("\n  " + C_.YELLOW + "已中断当前操作" + C_.RESET)
        except Exception as exc:
            print("  " + C_.RED + "出错：%s" % exc + C_.RESET)
            logger.error("菜单操作异常：%s" % exc)


def group_flow(group, days, permanent, logger):
    title = R.GROUP_TITLES[group]
    force_rescan = True
    items, selection = [], set()
    while True:
        if force_rescan:
            print_header("%s —— 扫描中..." % title)
            items = scanner.scan_group(group, days_override=days)
            selection = scanner.default_selection(items)
            force_rescan = False

        print_header(title)
        print_scan_table(items, selection)
        selected_items = [i for i in items if i.rid in selection]
        print_totals(items, selection)
        print_manual_hints(items)

        print("\n  {b}编号{r}=切换选中  {b}a{r}=全选  {b}s{r}=仅安全项  {b}d{r}=默认  {b}n{r}=全不选  "
              "{b}t{r}=改年龄阈值  {b}m{r}=切换删除模式  {b}p{r}=预览".format(
                  b=C_.BOLD, r=C_.RESET))
        print("  {b}x{r}=执行清理  {b}r{r}=重新扫描  {b}q{r}=返回主菜单".format(b=C_.BOLD, r=C_.RESET))
        print("  " + C_.GRAY + "（执行前还会再确认一次；默认移入隔离区，可随时还原）" + C_.RESET)

        cmd = input("\n  > ").strip().lower()
        if cmd in ("q", "b", ""):
            return
        if cmd == "a":
            selection = {i.rid for i in items if i.actionable}
        elif cmd == "s":
            selection = {i.rid for i in items if i.actionable and i.rule.level == "safe"}
        elif cmd == "d":
            selection = scanner.default_selection(items)
        elif cmd == "n":
            selection = set()
        elif cmd == "r":
            force_rescan = True
        elif cmd == "t":
            raw = input("  全局年龄下限：只清理 N 天前的数据（当前 %s，回车不改）\n    （只会收紧，不会放松单条规则自己的阈值）> " % (days if days else "按规则默认")).strip()
            if raw.isdigit():
                days = int(raw)
                force_rescan = True
            elif raw == "0":
                days = None
                force_rescan = True
        elif cmd == "m":
            permanent = not permanent
            print("  已切换到：%s" % ("永久删除（不可恢复）" if permanent else "隔离区（可还原）"))
        elif cmd == "p":
            preview_group(items, selection, days, permanent)
            input("  回车继续 > ")
        elif cmd == "x":
            if not selection:
                print("  " + C_.YELLOW + "请先选择要清理的项目" + C_.RESET)
                continue
            if not interactive_confirm(items, selection, permanent, days):
                print("  " + C_.YELLOW + "已取消，未做任何修改。" + C_.RESET)
                input("  回车继续 > ")
                continue
            print_header("执行中...")
            result = executor.execute(items, selection, permanent=permanent,
                                      logger=logger, confirm=confirm_cb)
            print("\n  释放 %s%s%s ｜ 移动 %d ｜ 跳过 %d" % (
                C_.BOLD, human(result.freed), C_.RESET, result.moved, len(result.skipped)))
            for action, ok, detail in result.actions:
                print("  %s%s %s%s -> %s" % (C_.GREEN if ok else C_.RED,
                                             "✓" if ok else "✗", action, C_.RESET, detail))
            if result.trash_dir:
                print("  隔离区：%s" % result.trash_dir)
                print("  还原命令：python wbcleaner.py trash restore %s" %
                      os.path.basename(result.trash_dir))
            print("  日志：%s" % logger.path)
            input("\n  回车重新扫描 > ")
            force_rescan = True
        else:
            nums = [n for n in cmd.replace(",", " ").split() if n.isdigit()]
            if nums:
                for n in nums:
                    i = int(n)
                    if 1 <= i <= len(items):
                        rid = items[i - 1].rid
                        if not items[i - 1].actionable and items[i - 1].rule.kind != "action":
                            print("  %s· 第 %d 项没有可清理内容，已忽略%s" % (
                                C_.GRAY, i, C_.RESET))
                            continue
                        selection.symmetric_difference_update({rid})
            else:
                print("  " + C_.YELLOW + "无效指令" + C_.RESET)


def preview_group(items, selection, days, permanent):
    print_header("预览：即将处理的目标")
    for it in items:
        if it.rid not in selection or not it.actionable:
            continue
        color = level_color(it.rule.level)
        print("\n  %s● %s%s  %s%s%s" % (color, C_.BOLD, it.rule.title, human(it.size),
                                        C_.RESET, ("（%d 天前）" % it.rule.min_age_days)
                                        if it.rule.min_age_days else ""))
        print("    %s%s%s" % (C_.GRAY, it.rule.desc, C_.RESET))
        if it.rule.impact:
            print("    %s影响：%s%s" % (C_.YELLOW, it.rule.impact, C_.RESET))
        for t in it.targets[:6]:
            print("    %s%s%s" % (C_.GRAY, util.short_path(t, 78), C_.RESET))
        if len(it.targets) > 6:
            print("    %s... 共 %d 个目标%s" % (C_.GRAY, len(it.targets), C_.RESET))
    tot, _, _, _ = scanner.totals([i for i in items if i.rid in selection])
    print("\n  合计 %s%s%s ｜ 模式：%s" % (
        C_.BOLD, human(tot), C_.RESET,
        "永久删除" if permanent else "隔离区（可还原）"))


def dism_menu(logger):
    while True:
        print_header("WinSxS 组件存储（必须通过 DISM 清理）")
        data = scanner.load_dism_cache()
        if data:
            print("  上次分析：%s" % data.get("time_human", "?"))
            print("    组件存储实际大小：%s" % human(data.get("actual", 0)))
            print("    已与 Windows 共享：%s" % human(data.get("shared", 0)))
            print("    %s备份和已禁用功能：%s%s（这部分可回收）" % (
                C_.GREEN, human(data.get("reclaimable", 0)), C_.RESET))
            print("    可回收程序包：%d 个 ｜ 官方建议清理：%s" % (
                data.get("reclaimable_packages", 0),
                "是" if data.get("recommended") else "否"))
        else:
            print("  " + C_.GRAY + "还没有分析数据，建议先执行 [1] 分析。" + C_.RESET)
        print("\n  {b}[1]{r} 分析（只读，20~60 秒）".format(b=C_.BOLD, r=C_.RESET))
        print("  {b}[2]{r} 标准清理 StartComponentCleanup（保留更新回滚能力）".format(b=C_.BOLD, r=C_.RESET))
        print("  {b}[3]{r} 深度清理 追加 /ResetBase {r}（不可逆，多释放 1~3 GB）".format(
            b=C_.BOLD, r=C_.RED))
        print("  {b}[0]{r} 返回".format(b=C_.BOLD, r=C_.RESET))
        print("  " + C_.GRAY + "说明：手工删除 WinSxS 里的文件会让系统更新与修复彻底失效，"
                               "只能用 DISM。" + C_.RESET)
        c = input("\n  > ").strip()
        if c in ("0", "q", ""):
            return
        if c == "1":
            ok, detail = syswin.dism_analyze(logger)
            print(("  " + (C_.GREEN if ok else C_.RED) + "%s" + C_.RESET) % detail)
        elif c == "2":
            if input("  确认执行标准清理？输入 yes > ").strip() == "yes":
                ok, detail = syswin.dism_cleanup(logger, reset_base=False)
                print(("  " + (C_.GREEN if ok else C_.RED) + "%s" + C_.RESET) % detail)
        elif c == "3":
            print("  " + C_.RED + "⚠ 不可逆：清理后所有已安装更新都无法卸载。" + C_.RESET)
            if input("  确认？输入 DANGER > ").strip() == "DANGER":
                ok, detail = syswin.dism_cleanup(logger, reset_base=True)
                print(("  " + (C_.GREEN if ok else C_.RED) + "%s" + C_.RESET) % detail)
        input("  回车继续 > ")


# ==================================================================== 入口


def build_parser():
    p = argparse.ArgumentParser(
        prog="wbcleaner",
        description="WBCleaner —— WorkBuddy / Codex / C盘 无用文件清理工具（默认只扫描，不删除）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="不带子命令时进入交互菜单。任何删除默认进隔离区，可 trash restore 还原。",
    )
    p.add_argument("-v", "--version", action="version", version="WBCleaner %s" % __version__)
    p.add_argument("--verbose", action="store_true", help="输出调试日志")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="只扫描并报告（只读）")
    s.add_argument("--group", choices=["workbuddy", "codex", "deepseek", "system"])
    s.add_argument("--days", type=int,
                   help="全局年龄下限：只统计 N 天前的数据（只收紧，不放松单条规则阈值）")
    s.add_argument("--json", help="导出 JSON 报告路径")
    s.add_argument("--html", help="导出 HTML 报告路径")
    s.set_defaults(func=do_scan)

    c = sub.add_parser("clean", help="执行清理（默认隔离区模式）")
    c.add_argument("--group", choices=["workbuddy", "codex", "deepseek", "system"])
    c.add_argument("--only", help="safe | all | default，默认 default")
    c.add_argument("--rids", help="指定规则 id，逗号分隔")
    c.add_argument("--days", type=int,
                   help="全局年龄下限：只清理 N 天前的数据（只收紧，不放松单条规则阈值）")
    c.add_argument("--permanent", action="store_true", help="直接永久删除（不进隔离区）")
    c.add_argument("--dry-run", action="store_true", help="演练，不做任何修改")
    c.add_argument("--yes", action="store_true", help="跳过交互确认")
    c.add_argument("--no-confirm", action="store_true", help="跳过系统动作的二次确认")
    c.set_defaults(func=do_clean)

    t = sub.add_parser("trash", help="隔离区管理")
    t.add_argument("trash_action", nargs="?", choices=["list", "restore", "purge"], default="list")
    t.add_argument("ts", nargs="?", help="时间戳，如 20261001-143012")
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(func=do_trash)

    d = sub.add_parser("dism", help="WinSxS 组件存储")
    d.add_argument("dism_action", nargs="?", choices=["analyze", "cleanup", "resetbase"],
                   default="analyze")
    d.set_defaults(func=do_dism)

    sub.add_parser("doctor", help="环境自检").set_defaults(func=do_doctor)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        args.permanent = False
        args.days = None
        return menu_loop(args)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  已中断。")
        return 130
    except SystemExit as exc:
        if exc.code:
            print("  %s%s%s" % (C_.RED, exc.code, C_.RESET))
        return exc.code or 0


if __name__ == "__main__":
    sys.exit(main())
