"""WBCleaner —— WorkBuddy / Codex / Windows C 盘 无用文件清理工具。

设计原则：
  1. 只扫描不删除是默认行为（dry-run）。
  2. 任何删除都必须先经过「保护名单」与「安全守卫」校验。
  3. 默认删到隔离区（可一键还原），只有显式 --permanent 才真删。
  4. 系统级动作（DISM / 服务 / 回收站）单独成组，默认不勾选，且需要管理员。
"""

__version__ = "1.0.0"
__all__ = ["util", "rules", "scanner", "executor", "syswin", "report"]
