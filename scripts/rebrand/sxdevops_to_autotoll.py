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

替换映射见 spec § 3 ../specs/2026-06-29-autotoll-rebrand-design.md
"""
from __future__ import annotations

import argparse
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

# 文件级跳过：绝对路径或 glob 命中整文件跳过
SKIP_FILE_GLOBS = (
    ".git/",
    "node_modules/",
    "frontend/dist/",
    "backend/__pycache__/",
    ".venv/",
    "venv/",
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
    re.compile(r"/sxdevops/"),             # URL path
    re.compile(r"image:\s*sxdevops"),      # docker image
    re.compile(r"container_name:\s*sxdevops"),
    re.compile(r"`?sxdevops`?(?:[._-]|$)"),  # import path / 文件名
)

# 整目录跳过
SKIP_DIRS = {"backend/sxdevops"}


def path_allowed(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    if any(rel.startswith(glob.rstrip("*")) for glob in SKIP_FILE_GLOBS):
        return False
    if any(glob.rstrip("*") in rel for glob in SKIP_FILE_GLOBS if "*" in glob):
        return False
    for d in SKIP_DIRS:
        if rel == d or rel.startswith(d + "/"):
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
    total_files = 0
    total_hits = 0

    for path in iter_files(args.scope, repo_root):
        if not path_allowed(path, repo_root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
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
        rel = path.relative_to(repo_root).as_posix()
        if args.apply:
            path.write_text(new_text, encoding="utf-8")
            print(f"[PATCH] {rel}  hits={file_hits}")
        else:
            print(f"[DRY ] {rel}  hits={file_hits}")

    print(f"---\ntotal files={total_files}  total hits={total_hits}  mode={'APPLY' if args.apply else 'DRY'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
