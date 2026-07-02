#!/usr/bin/env python3
"""L1 重命名自动化验收脚本。退出码：
  0 — 全绿
  1 — 正向断言失败（展示层漏改）
  2 — 反证断言失败（L1 不动项被误改）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def green(msg: str) -> None:
    print(f"  \033[32m[OK]\033[0m {msg}")


def red(msg: str) -> None:
    print(f"  \033[31m[FAIL]\033[0m {msg}")


def check_positive() -> list[str]:
    """展示层已被替换为 Autotoll DevOps（任务 3/5/6 范围）。"""
    fails: list[str] = []
    # plan 原版 4 个
    base_targets = {
        "README.md": r"\bAutotoll DevOps\b",
        "docs/AIOps智能体实现说明.md": r"\bAutotoll DevOps\b",
        "frontend/src/views/Login.vue": r"\bAutotoll DevOps\b",
        "frontend/src/layout/AppLayout.vue": r"\bAutotoll DevOps\b",
    }
    # 任务 5/6 增补 7 个
    extra_targets = {
        "frontend/src/views/AIAgentPromo.vue": r"\bAutotoll DevOps\b",
        "frontend/src/main.js": r"\bAutotoll DevOps\b",
        "frontend/src/views/WebShell.vue": r"\bAutotoll DevOps\b",
        "backend/aiops/services.py": r"\bAutotoll DevOps\b",
        "backend/iac/terraform.py": r"\bAutotoll DevOps\b",
        "backend/ops/views.py": r"\bAutotoll DevOps\b",
        "frontend/src/assets/main.css": r"Autotoll DevOps 运维平台",
    }
    for rel, pat in {**base_targets, **extra_targets}.items():
        p = REPO / rel
        if not p.exists():
            fails.append(f"[POS] missing file: {rel}")
            continue
        if not re.search(pat, p.read_text(encoding="utf-8")):
            fails.append(f"[POS] no Autotoll DevOps in {rel}")
        else:
            green(f"positive hit: {rel}")
    return fails


def check_negative() -> list[str]:
    """L1 不动项未被误改（Python 标识符、HTTP header、JS 事件名、法定署名、上游 URL、spec/plan 自身）。"""
    fails: list[str] = []

    # ---- plan 原版反向断言 ----
    # settings.py 注释 + INSTALLED_APPS
    settings = REPO / "backend/sxdevops/settings.py"
    if settings.exists():
        text = settings.read_text(encoding="utf-8")
        if "Django settings for sxdevops project." not in text:
            fails.append("[NEG] settings.py 注释被误改")
        else:
            green("protected: backend/sxdevops/settings.py (注释保留)")
        if "INSTALLED_APPS" in text and "'sxdevops'" not in text:
            fails.append("[NEG] INSTALLED_APPS 中的 sxdevops app label 丢失")
        else:
            green("protected: backend/sxdevops/settings.py (INSTALLED_APPS 保留)")

    # docker-compose.yml service 名
    compose = REPO / "docker-compose.yml"
    if compose.exists():
        text = compose.read_text(encoding="utf-8")
        if re.search(r"^\s*sxdevops:", text, re.MULTILINE) is None:
            fails.append("[NEG] docker-compose.yml 中 sxdevops service 缺失")
        else:
            green("protected: docker-compose.yml (service 保留)")

    # baked JS 不变（如果存在；任务 4 结论是 no-op，文件不存在时 graceful skip）
    for js in (REPO / "patches").glob("index-*.js"):
        if js.read_text(encoding="utf-8", errors="ignore").count("SxDevOps") > 0:
            fails.append(f"[NEG] baked JS 被改动: {js.name}")
        else:
            green(f"protected baked JS: {js.name}")
    for js in (REPO / "patches").glob("Login-*.js"):
        if js.read_text(encoding="utf-8", errors="ignore").count("SxDevOps") > 0:
            fails.append(f"[NEG] baked JS 被改动: {js.name}")

    # NOTICE 法定署名保留
    notice = REPO / "NOTICE"
    if notice.exists():
        text = notice.read_text(encoding="utf-8")
        if "SxDevOps" not in text or "Copyright 2026 dayan150820" not in text:
            fails.append("[NEG] NOTICE 法定署名不应被改")
        else:
            green("protected: NOTICE (法定署名)")

    # 上游 URL 保留
    readme = REPO / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if "github.com/aiyiyi121/sxdevops" not in text:
            fails.append("[NEG] 上游项目 URL 应保留作引用")
        else:
            green("protected: README 上游 URL")

    # ---- 任务 5/6 增补反向断言 ----
    # JS 内部事件名（任务 5 决策点 D-6：协议层不动）
    app_layout = REPO / "frontend/src/layout/AppLayout.vue"
    if app_layout.exists():
        text = app_layout.read_text(encoding="utf-8")
        for needle in ("sxdevops-module-settings-updated", "sxdevops-aiops-open"):
            if needle not in text:
                fails.append(f"[NEG] AppLayout.vue 事件名 {needle} 被误改")
            else:
                green(f"protected: AppLayout.vue 事件名 {needle}")

    # 实际监听者在 components/aiops/AIOpsChatWidget.vue
    chat_widget = REPO / "frontend/src/components/aiops/AIOpsChatWidget.vue"
    if chat_widget.exists():
        text = chat_widget.read_text(encoding="utf-8")
        if "sxdevops-aiops-open" not in text:
            fails.append("[NEG] AIOpsChatWidget.vue 事件名 sxdevops-aiops-open 被误改")
        else:
            green("protected: AIOpsChatWidget.vue 事件名 sxdevops-aiops-open")

    # HTTP header 协议层（已在 sxdevops_to_autotoll.py allow-list 跳过）
    ops_views = REPO / "backend/ops/views.py"
    if ops_views.exists():
        text = ops_views.read_text(encoding="utf-8")
        if "X-SxDevOps-Token" not in text:
            fails.append("[NEG] ops/views.py HTTP header X-SxDevOps-Token 应保留")
        else:
            green("protected: backend/ops/views.py HTTP header X-SxDevOps-Token")

    # settings.py Python 标识符（URL/WSGI/ASGI 配置）
    if settings.exists():
        text = settings.read_text(encoding="utf-8")
        for needle in (
            "ROOT_URLCONF = 'sxdevops.urls'",
            "WSGI_APPLICATION = 'sxdevops.wsgi.application'",
            "ASGI_APPLICATION = 'sxdevops.asgi.application'",
        ):
            if needle not in text:
                fails.append(f"[NEG] settings.py 标识符被改: {needle}")
            else:
                green(f"protected: settings.py {needle}")

    # docker-compose.yml image/container_name
    if compose.exists():
        text = compose.read_text(encoding="utf-8")
        for needle in ("image: sxdevops", "container_name: sxdevops-app"):
            if needle not in text:
                fails.append(f"[NEG] docker-compose.yml 应保留: {needle}")
            else:
                green(f"protected: docker-compose.yml {needle}")

    # 元文档（spec/plan 自身不应被替换）
    spec = REPO / "docs/superpowers/specs/2026-06-29-autotoll-rebrand-design.md"
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        if "SxDevOps" not in text:
            fails.append("[NEG] spec 自身保留讨论这个字眼")
        else:
            green("protected: docs/superpowers/specs/...-design.md 保留 SxDevOps")

    plan_doc = REPO / "docs/superpowers/plans/2026-06-29-autotoll-rebrand-plan.md"
    if plan_doc.exists():
        text = plan_doc.read_text(encoding="utf-8")
        if "SxDevOps" not in text:
            fails.append("[NEG] plan 自身保留讨论这个字眼")
        else:
            green("protected: docs/superpowers/plans/...-plan.md 保留 SxDevOps")

    return fails


def main() -> int:
    print("=== verify_rebrand: 正向断言 ===")
    pos_fails = check_positive()
    print("\n=== verify_rebrand: 反证断言 ===")
    neg_fails = check_negative()
    if pos_fails:
        for f in pos_fails:
            red(f)
    if neg_fails:
        for f in neg_fails:
            red(f)
    if pos_fails:
        print(f"\nFAIL: {len(pos_fails)} 正向断言错误")
        return 1
    if neg_fails:
        print(f"\nFAIL: {len(neg_fails)} 反证断言错误")
        return 2
    print("\nPASS: 所有断言通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
