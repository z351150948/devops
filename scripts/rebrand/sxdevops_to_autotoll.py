#!/usr/bin/env python3
"""SxDevOps → Autotoll DevOps 替换脚本（L1 范围）。

默认 dry-run 模式只输出 diff，真跑需显式 --apply。
--scope 控制批次范围（docs / patches-static / frontend-display / backend-display / all）。

allow-list 保护严格跳过 L1 不动项：
- backend/sxdevops/** 整目录
- 任何含 SXDEVOPS_ / sxdevops- / /sxdevops/ / image: sxdevops / container_name: sxdevops 的行
- patches/index-*.js、patches/Login-*.js baked JS
- .git/、node_modules/、frontend/dist/、backend/__pycache__/
- 所有 *.lock / *.min.js / *.svg / *.png 文件

替换映射见 §3 of ../specs/2026-06-29-autotoll-rebrand-design.md
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

# 主映射 + case normalization 映射
REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bSxDevOps\s+AI\s+Agent\b"), "Autotoll DevOps 智能体"),
    (re.compile(r"\bSxDevOps\s+智能体\b"), "Autotoll DevOps 智能体"),
    (re.compile(r"\bSxDevOps\s+Platform\b"), "Autotoll DevOps Platform"),
    (re.compile(r"\bthe\s+SxDevOps\s+project\b"), "the Autotoll DevOps project"),
    (re.compile(r"\b本项目（SxDevOps）"), "本项目（Autotoll DevOps）"),
    (re.compile(r"\bSxDevOps\b"), "Autotoll DevOps"),
]

# 文件级跳过：基于 basename 的 glob 命中整文件跳过（目录类已迁移到 SKIP_DIRS）
SKIP_FILE_GLOBS = (
    "*.lock",
    "*.min.js",
    "*.svg",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.webp",
    "*.ico",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "patches/index-*.js",
    "patches/Login-*.js",
)

# 行级跳过：跳过整行
SKIP_LINE_PATTERNS = (
    re.compile(r"SXDEVOPS_[A-Z_]+"),       # 环境变量
    re.compile(r"X-SxDevOps[\w-]*"),       # HTTP header (X-SxDevOps-Token 等)
    re.compile(r"/sxdevops/"),             # URL path
    re.compile(r"image:\s*sxdevops"),      # docker image
    re.compile(r"container_name:\s*sxdevops"),
    re.compile(r"(?:^|\s)(?:from|import)\s+sxdevops[\w.]*"),  # Python import path (avoid markdown ref false-positive)
    re.compile(r"(?:上游[\s\S]*?|基于\s+|是\s+|在\s+|相对\s+)SxDevOps"),  # 上游项目署名/合规引用（L1 必保留）
)

# 整目录跳过（任一祖先目录命中即跳过整子树）
# - 以 "/" 结尾的 glob 仍兼容（理论兼容，目前未使用）
# - 不含 "/" 的目录名（.git / node_modules / .venv 等）走 parts 匹配
# - 含 "/" 的多级路径（backend/sxdevops 等）走前缀匹配
SKIP_DIRS = {
    "backend/sxdevops",
    "docs/superpowers",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "frontend/dist",
    "backend/__pycache__",
}


def path_allowed(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    parts = Path(rel).parts
    # 目录跳过：单级目录走 parts 匹配，多级路径走前缀匹配
    for d in SKIP_DIRS:
        if "/" in d:
            if rel == d or rel.startswith(d + "/"):
                return False
        else:
            if d in parts:
                return False
    # 文件级 glob 匹配（基于 basename，用 fnmatch 严格匹配）
    base = parts[-1] if parts else ""
    if base and any(fnmatch.fnmatch(base, glob) for glob in SKIP_FILE_GLOBS):
        return False
    return True


def line_allowed(line: str) -> bool:
    return not any(p.search(line) for p in SKIP_LINE_PATTERNS)


def transform_text(text: str) -> tuple[str, int]:
    hits = 0
    out = text
    for pat, target in REPLACEMENTS:
        new = pat.sub(target, out)
        if new != out:
            hits += out.count("SxDevOps")  # 近似计数
            out = new
    return out, hits


def iter_files(scope: str, repo_root: Path):
    if scope in ("docs", "all"):
        yield from repo_root.glob("**/*.md")
        yield from (repo_root / "docs").rglob("*.md")
    if scope in ("patches-static", "all"):
        yield from (repo_root / "patches").rglob("*.html")
    if scope in ("frontend-display", "all"):
        for ext in ("*.vue", "*.js", "*.ts"):
            for p in (repo_root / "frontend").rglob(ext):
                if "node_modules" in p.parts or "dist" in p.parts:
                    continue
                yield p
    if scope in ("backend-display", "all"):
        for ext in ("*.py",):
            for p in (repo_root / "backend").rglob(ext):
                if "__pycache__" in p.parts:
                    continue
                if "sxdevops" in p.relative_to(repo_root).parts:
                    continue
                yield p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真跑修改文件（默认 dry-run）")
    parser.add_argument("--scope", default="all",
                        choices=["all", "docs", "patches-static", "frontend-display", "backend-display"])
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    if not (repo_root / ".git").exists():
        print(f"error: {repo_root} does not contain .git; pass --repo <path>",
              file=sys.stderr)
        return 2
    total_files = 0
    total_hits = 0

    for path in iter_files(args.scope, repo_root):
        if not path_allowed(path, repo_root):
            continue
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"[WARN] skip non-utf8: {rel}", file=sys.stderr)
            continue
        except OSError as e:
            print(f"[WARN] skip unreadable {rel}: {e}", file=sys.stderr)
            continue

        new_lines = []
        file_hits = 0
        for line in text.splitlines(keepends=True):
            if not line_allowed(line):
                new_lines.append(line)
                continue
            new, n = transform_text(line)
            if n:
                file_hits += n
            new_lines.append(new)
        if not file_hits:
            continue
        new_text = "".join(new_lines)
        total_files += 1
        total_hits += file_hits
        if args.apply:
            path.write_text(new_text, encoding="utf-8")
            print(f"[PATCH] {rel}  hits={file_hits}")
        else:
            print(f"[DRY ] {rel}  hits={file_hits}")

    print(f"---\ntotal files={total_files}  total hits={total_hits}  mode={'APPLY' if args.apply else 'DRY'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())