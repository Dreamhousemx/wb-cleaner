#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自检：验证规则表、安全守卫、隔离区/还原闭环。

整个自检只在临时目录里造自己的测试数据，绝不触碰真实清理目标。
运行： python tests/selftest.py
"""

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wbc import executor, rules as R, scanner, util  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  \033[32mPASS\033[0m %s" % name)
    else:
        FAIL.append(name)
        print("  \033[31mFAIL\033[0m %s  %s" % (name, detail))


def touch(path, content=b"x" * 1024, age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)
    if age_days:
        ts = time.time() - age_days * 86400
        os.utime(path, (ts, ts))
    return path


# ------------------------------------------------------------------ 1. 规则表


def test_rules():
    print("\n[1] 规则表结构")
    valid_groups = set(R.RULES_BY_GROUP)
    valid_kinds = {"contents", "subdirs", "dir", "glob", "action", "report"}
    valid_levels = {"safe", "caution", "danger", "keep"}
    ids = [r.rid for r in R.ALL_RULES]
    check("规则 id 唯一", len(ids) == len(set(ids)), "重复：%s" % ids)
    bad = [r.rid for r in R.ALL_RULES
           if r.group not in valid_groups or r.kind not in valid_kinds
           or r.level not in valid_levels]
    check("分组/类型/等级合法", not bad, str(bad))
    bad2 = [r.rid for r in R.ALL_RULES if r.kind != "action" and not r.paths]
    check("非动作规则都有路径", not bad2, str(bad2))
    bad3 = [r.rid for r in R.ALL_RULES if r.requires_admin and r.group != "system"]
    check("仅系统组要求管理员", not bad3, str(bad3))
    three = {r.group for r in R.ALL_RULES}
    check("三大功能分组齐全", three == {"workbuddy", "codex", "system"}, str(three))
    n_req = len([r for r in R.ALL_RULES if not r.protected and r.kind != "report"])
    check("可清理项数量合理", n_req >= 20, "共 %d 条" % n_req)


def test_paths():
    print("\n[2] 路径展开")
    bad = []
    for r in R.ALL_RULES:
        for p in r.paths:
            e = util.expand(p)
            if not os.path.isabs(e) or "$" in e or "%" in e or "~" in e:
                bad.append((r.rid, p, e))
    check("所有路径都能展开成绝对路径", not bad, str(bad[:3]))


# ------------------------------------------------------------------ 3. 安全守卫


def test_guard():
    print("\n[3] 安全守卫")
    prot = [(lbl, p) for lbl, p in R.PROTECTED]
    home = os.path.expanduser("~")
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    cases = [
        (os.path.join(sysroot, "WinSxS"), True, "WinSxS 本体"),
        (os.path.join(sysroot, "System32"), True, "System32"),
        (home, True, "用户主目录"),
        (os.path.join(home, "AppData"), True, "AppData 根"),
        (os.path.join(home, ".workbuddy", "binaries"), True, "托管运行时"),
        (os.path.join(home, ".workbuddy", "user-abc123-personal"), True, "个人档案（任意 UUID）"),
        (os.path.join(home, ".codex", "auth.json"), True, "Codex 授权文件"),
        (os.path.join(R.PROJECT_ROOT, ".git"), True, "Git 版本库"),
        (os.path.join(R.WORKSPACE, ".workbuddy"), True, "工作区记忆"),
        (os.path.join(home, ".workbuddy", "logs", "sandbox"), False, "沙箱日志（应放行）"),
        (os.path.join(home, ".codex", "tmp"), False, "Codex 临时目录（应放行）"),
    ]
    for target, should_block, label in cases:
        try:
            util.guard(target, prot, must_exist=False)
            blocked = False
        except util.UnsafeTarget:
            blocked = True
        check("守卫%s %s" % ("拦截" if should_block else "放行", label),
              blocked == should_block, "target=%s blocked=%s" % (target, blocked))

    try:
        util.guard(os.path.join(sysroot, "System32"), prot, must_exist=False)
        check("盘内浅层路径被拒", False)
    except util.UnsafeTarget:
        check("盘内浅层路径被拒", True)

    # 禁止集合必须是「按当前机器推导」出来的，而不是抄了一份别的机器的
    drive_root = os.path.splitdrive(home)[0] + os.sep
    check("禁止集合含当前用户主目录",
          util.norm_key(home) in util.FORBIDDEN_ROOTS, str(sorted(util.FORBIDDEN_ROOTS)[:4]))
    check("禁止集合含当前系统盘根",
          util.norm_key(drive_root) in util.FORBIDDEN_ROOTS, drive_root)
    check("禁止集合含当前 SystemRoot",
          util.norm_key(os.environ.get("SystemRoot", r"C:\Windows")) in util.FORBIDDEN_ROOTS,
          os.environ.get("SystemRoot", ""))


def test_no_hardcoded_paths():
    """回归：源码里不允许出现本机专属的绝对路径 / 用户名。

    这个工具要能直接分享给别人用，写死 C:\\Users\\<某人> 会同时造成
    「安全守卫在别人机器上失效」和「仓库泄露本机信息」两个问题。
    """
    print("\n[10] 无本机专属硬编码（回归）")
    import re as _re
    bad_patterns = [
        (_re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.-]+"), "写死的用户目录"),
        (_re.compile(r"[A-Za-z]:[\\/]Workspace[\\/]"), "写死的工作区路径"),
    ]
    self_path = os.path.abspath(__file__)
    hits = []
    scanned = 0
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs
                   if d not in (".git", ".cache", "reports", "logs", "__pycache__", "raw")]
        for name in files:
            if not name.endswith((".py", ".js", ".html", ".css", ".bat")):
                continue
            path = os.path.join(root, name)
            if os.path.abspath(path) == self_path:
                continue          # 本文件里的规则串本身就是在描述这些模式
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            scanned += 1
            for pattern, label in bad_patterns:
                for m in pattern.finditer(text):
                    hits.append("%s：%s（%s）" % (
                        os.path.relpath(path, ROOT), m.group(0), label))
    check("源码无本机专属路径（扫描 %d 个文件）" % scanned, not hits,
          "；".join(hits[:4]))


def test_relkey():
    print("\n[4] 隔离区路径映射")
    home = os.path.expanduser("~")
    sys_root = os.path.join(os.path.splitdrive(os.environ.get("SystemRoot", r"C:\Windows"))[0]
                            + os.sep, "Users", os.environ.get("USERNAME", "user"))
    sample = os.path.join(sys_root, ".workbuddy", "logs", "sandbox")
    a = executor._rel_key(sample)
    b = executor._rel_key(os.path.join(home, "somewhere", "else"))
    check("映射不丢盘符", a.startswith(os.path.splitdrive(sample)[0][:1].upper())
          and "sandbox" in a, a)
    check("映射结果不含冒号", ":" not in a and ":" not in b, "%s | %s" % (a, b))
    check("映射保留目录层级", a.count(os.sep) >= 3, a)

    # 隔离区必须落在同盘的 LOCALAPPDATA 下（保证移动是瞬时 rename，而不是跨盘拷贝）
    root_c = executor.trash_root_for(sample)
    local = os.environ.get("LOCALAPPDATA", "")
    check("系统盘目标的隔离区在 LOCALAPPDATA 下",
          bool(local) and util.norm_key(root_c).startswith(util.norm_key(local)),
          root_c)
    other = executor.trash_root_for(os.path.join(home, "x"))
    check("隔离区始终和目标同盘",
          os.path.splitdrive(other)[0] == os.path.splitdrive(home)[0], other)


# ------------------------------------------------------------------ 5. 隔离/还原闭环


def test_quarantine_roundtrip():
    print("\n[5] 隔离区 -> 还原 闭环")
    base = tempfile.mkdtemp(prefix="wbcleaner-selftest-")
    sandbox = os.path.join(base, "fake", "logs", "sandbox")
    old = touch(os.path.join(sandbox, "old.log"), b"a" * 4096, age_days=10)
    new = touch(os.path.join(sandbox, "new.log"), b"b" * 1024, age_days=0)
    sub = os.path.join(sandbox, "sub")
    old_sub = touch(os.path.join(sub, "deep.log"), b"c" * 2048, age_days=30)

    rule = R.Rule("test-contents", "workbuddy", "测试", "contents", [sandbox],
                  level="safe", min_age_days=3)
    item = scanner.scan_rule(rule)
    check("扫描到 3 个文件中的 2 个（不含今天）", item.files == 2,
          "实际 %d，体积 %s" % (item.files, util.human(item.size)))
    check("体积统计正确", item.size == 4096 + 2048, str(item.size))

    # --- dry-run 必须什么都不做
    res = executor.execute([item], {item.rid}, dry_run=True,
                           logger=util.Logger(echo=False))
    check("dry-run 不移动任何文件",
          os.path.exists(old) and os.path.exists(new) and os.path.exists(old_sub))
    check("dry-run 报告了回收量", res.freed >= 6144, str(res.freed))

    # --- 真实执行（隔离模式）
    res = executor.execute([item], {item.rid}, permanent=False,
                           logger=util.Logger(echo=False))
    check("新文件被保留", os.path.exists(new))
    check("旧文件已移出原位置", not os.path.exists(old) and not os.path.exists(old_sub))
    check("产生了隔离批次", bool(res.trash_dir) and os.path.isdir(res.trash_dir or ""),
          str(res.trash_dir))
    man = os.path.join(res.trash_dir or base, "manifest.json")
    check("写入了还原清单", os.path.exists(man))
    check("释放量统计非零", res.freed >= 6144, str(res.freed))
    check("占用跳过列表为空", len(res.skipped) == 0, str(res.skipped))

    # --- 还原
    rc = executor.restore_trash(os.path.basename(res.trash_dir), logger=util.Logger(echo=False))
    check("还原返回成功", rc == 0, "rc=%d" % rc)
    check("旧文件回到原位", os.path.exists(old) and os.path.exists(old_sub))

    # --- 清理隔离区
    executor.purge_trash(os.path.basename(res.trash_dir), logger=util.Logger(echo=False))
    shutil.rmtree(base, ignore_errors=True)
    print("  \033[90m（测试数据已清理：%s）\033[0m" % base)


def test_protected_not_selected():
    print("\n[6] 保护项不会被默认选中")
    losers = []
    for group in ("workbuddy", "codex"):
        items = scanner.scan_group(group)
        sel = scanner.default_selection(items)
        for it in items:
            if (it.rule.protected or it.rule.kind == "report") and it.rid in sel:
                losers.append(it.rid)
    check("默认勾选里没有保护项", not losers, str(losers))

    # 保护名单路径不得出现在任何规则的可删目标里
    over = []
    for r in R.ALL_RULES:
        if r.protected or r.kind == "report":
            continue
        for p in r.paths:
            for lbl, pp in R.PROTECTED:
                if util.is_subpath(p, pp):
                    over.append((r.rid, lbl))
    check("可删路径与保护名单无重叠", not over, str(over))


def test_format():
    print("\n[7] 格式化与动作表")
    check("KB/GB 格式化", util.human(1536) == "1.50 KB" and util.human(1024 ** 3).endswith("GB"),
          "%s | %s" % (util.human(1536), util.human(1024 ** 3)))
    from wbc import syswin
    need = {"dism_analyze", "dism_cleanup", "dism_resetbase", "recyclebin",
            "hibernate_off", "wu_cache"}
    check("DISM 等动作都已注册", need <= set(syswin.ACTIONS),
          str(need - set(syswin.ACTIONS)))
    acts = {r.action for r in R.ALL_RULES if r.kind == "action"}
    check("规则里的动作都有实现", acts <= set(syswin.ACTIONS), str(acts - set(syswin.ACTIONS)))


def test_walk_stats_semantics():
    """回归：cutoff=0 必须表示「不过滤年龄」，而不是「只看 0 秒前的文件」。"""
    print("\n[8] walk_stats 年龄语义（回归）")
    base = tempfile.mkdtemp(prefix="wbcleaner-walk-")
    try:
        new = touch(os.path.join(base, "a", "new.bin"), b"n" * 3000, age_days=0)
        old = touch(os.path.join(base, "a", "b", "old.bin"), b"o" * 5000, age_days=40)
        sz_all, n_all = util.walk_stats(base, cutoff=0)
        check("cutoff=0 统计全部文件", (sz_all, n_all) == (8000, 2),
              "got (%d, %d)" % (sz_all, n_all))
        sz_new, n_new = util.walk_stats(base, min_age_days=10)
        check("min_age_days 只统计旧文件", (sz_new, n_new) == (5000, 1),
              "got (%d, %d)" % (sz_new, n_new))
        sz_none, n_none = util.walk_stats(base)
        check("不传参数统计全部", (sz_none, n_none) == (8000, 2),
              "got (%d, %d)" % (sz_none, n_none))
        check("单文件统计正确", util.walk_stats(old, cutoff=0)[0] == 5000)
        check("不存在的路径返回 0", util.walk_stats(os.path.join(base, "nope")) == (0, 0))
        check("新旧文件都还在（只读）", os.path.exists(new) and os.path.exists(old))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_format_strings():
    r"""静态检查：'%s %s' % (...) 里的占位符个数必须和参数个数一致。

    这类 bug 只有真正跑到那一行才会炸，所以用 AST 提前全量扫描一遍。
    """
    print("\n[9] 格式串与参数个数一致性（静态扫描）")
    import ast
    import re

    SPEC = re.compile(r"%(?!%)[-+ #0]*(\d+|\*)?(\.\d+|\*)?[hlL]?([diouxXeEfFgGcrsa])")

    def spec_count(fmt):
        return len(SPEC.findall(fmt))

    problems = []
    scanned = 0
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".cache", "reports", "logs", "__pycache__")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read(), path)
            except SyntaxError as exc:
                problems.append("%s 语法错误：%s" % (name, exc))
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)):
                    continue
                left, right = node.left, node.right
                if not isinstance(left, ast.Constant) or not isinstance(left.value, str):
                    continue
                if not isinstance(right, ast.Tuple):
                    continue          # 单参数 % 不用比
                scanned += 1
                n_spec = spec_count(left.value)
                n_arg = len(right.elts)
                if n_spec != n_arg:
                    problems.append("%s:%d 占位符 %d 个但参数 %d 个 -> %s" % (
                        os.path.relpath(path, ROOT), node.lineno, n_spec, n_arg,
                        left.value.strip()[:60]))
    check("格式串全部匹配（共扫描 %d 处）" % scanned, not problems,
          "\n      ".join(problems[:6]))


def main():
    print("=" * 62)
    print(" WBCleaner 自检（只在自己的临时目录里操作，不碰任何真实数据）")
    print("=" * 62)
    test_rules()
    test_paths()
    test_guard()
    test_relkey()
    test_quarantine_roundtrip()
    test_protected_not_selected()
    test_format()
    test_walk_stats_semantics()
    test_format_strings()
    test_no_hardcoded_paths()
    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("   失败：%s" % f)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
