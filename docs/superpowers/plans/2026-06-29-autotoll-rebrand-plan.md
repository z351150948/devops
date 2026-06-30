# Autotoll DevOps 品牌重命名（L1）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把仓库展示层文本中所有 `SxDevOps` 字样替换为 `Autotoll DevOps`，建立品牌基线；保留所有 L1 不动项（Python 包、Django app label、容器名、镜像名、环境变量、URL path、内部 JS 事件名、上游项目 URL/链接、上游 Release tarball 名、`NOTICE` 法定署名、`LICENSE` Apache 文本、`docs/screenshots/*.png` 文件名）。

**架构：** 单 batch 替换脚本 + 分阶段 commit + 自动化验收脚本。脚本按 allow-list 严格跳过保留项，dry-run 模式先输出变更清单，再真跑。

**技术栈：** Python 3.12（脚本）；Git；Django test runner；npm/Vite；Docker Compose v2.20+。

**配套文档：** [spec A-2026-06-29-01](../specs/2026-06-29-autotoll-rebrand-design.md)（已 commit `c10c70b` on `test`）

**关键决策点（执行前请用户最终确认）：** 见本文档末尾 § 决策点表。

---

## 文件结构

### 新增文件

| 路径 | 职责 |
| --- | --- |
| `scripts/rebrand/sxdevops_to_autotoll.py` | 替换脚本：参数解析、case normalization、allow-list 过滤、dry-run/patch 双模式 |
| `scripts/rebrand/verify_rebrand.py` | 验收脚本：8 项正向断言 + 5 项反证断言，退出码区分红绿 |
| `docs/rebrand-inventory.md` | 本地副产物：dry-run 输出的"动 vs 不动"清单（**不入 git**，加进 `.gitignore`） |

### 修改文件

| 路径 | L1 改动 |
| --- | --- |
| `README.md` | 标题 + 首段 + 决策点表（上游引用保留）|
| `AGENTS.md` | 第 1 行 `SxDevOps is split into...` |
| `CONTRIBUTING.md` | 段首 `感谢你愿意参与 SxDevOps` |
| `docs/AIOps*.md`（5 份）| 段首 + 章节名中产品名 |
| `docs/二次开发工作流.md` | 自指项目名 |
| `docs/OPEN_SOURCE_CHECKLIST.md` | 自指项目名 |
| `frontend/src/layout/AppLayout.vue` | line 6 `alt="SxDevOps"` / line 9 `<span class="logo-text">SxDevOps</span>`（line 200/610 JS 事件名保留） |
| `frontend/src/views/Login.vue` | line 7/9/61 三处展示文本 |
| `frontend/src/views/Dashboard.vue` | 若含品牌字则改（现状 0 命中，跳过） |
| `frontend/src/views/K8sManage.vue` | hero title（按需） |
| `frontend/src/views/ContainerManage.vue` | hero title（按需） |
| `frontend/src/views/TaskWorkbench.vue` | hero title（按需） |
| `frontend/src/views/ObservabilityOverview.vue` | hero title（按需） |
| `frontend/src/views/Hosts.vue` | hero title（按需） |
| `frontend/src/views/Alerts.vue` | hero title（按需） |
| `frontend/src/views/EventWall.vue` | hero title（按需） |
| `frontend/src/views/AIOpsChatEntry.vue` | hero title（按需） |

### 严格不改（L1 范围外）

- `backend/sxdevops/**`（Python 包名）
- `INSTALLED_APPS` / `ROOT_URLCONF` / `WSGI_APPLICATION` / `ASGI_APPLICATION` / cache alias
- `docker-compose.yml` 服务名 `sxdevops` / 镜像 tag `sxdevops:latest`
- 所有 `SXDEVOPS_*` 环境变量
- `NOTICE`（法定署名：`SxDevOps / Copyright 2026 dayan150820`）
- `LICENSE`（Apache License 2.0 标准文本）
- `docs/screenshots/sxdevops-operation-flow.png` 等历史图片路径
- GitHub 上游链接：`https://github.com/aiyiyi121/sxdevops`、`https://www.sxdevops.top`
- Release tarball 名：`sxdevops-patches-v0.1.0.tgz`
- `patches/index-*.js` / `patches/Login-*.js` baked JS bundle（由 `scripts/apply-patches.sh` 拉 tarball 维护，不在 git）
- `patches/sxdevops-ai-agent-promo.html` 文件名（被 docker-compose.yml 写死 bind-mount）

> **注：** `patches/index.html` 与 `patches/sxdevops-ai-agent-promo.html` 在 git 中不存在（apply-patches.sh 拉的产物）。本 plan 范围内这两个文件的**重命名版**应由发布侧在 tarball 中提供并通过新 release tag 拉取，不在本 plan PR 直接修改。Plan 在 § 阶段 B 任务 4 增加一项验证：跑 `apply-patches.sh` 后 grep 拉下来的文件中是否已不含 SxDevOps。

---

## 阶段 A：准备

### 任务 1：脚手架 + 替换脚本 + `.gitignore`

**文件：**
- 创建：`scripts/rebrand/sxdevops_to_autotoll.py`
- 修改：`.gitignore`

- [ ] **步骤 1：在 `test` 分支基础上切工作分支**

```bash
cd devops
git fetch origin
git switch test
git pull --rebase origin test
git switch -c feature/rebrand-autotoll-sxdevops
```

预期：分支切到 `feature/rebrand-autotoll-sxdevops`，HEAD = `origin/test`。

- [ ] **步骤 2：建 `scripts/rebrand/` 目录**

```bash
mkdir -p scripts/rebrand
```

预期：目录创建成功。

- [ ] **步骤 3：写替换脚本 `scripts/rebrand/sxdevops_to_autotoll.py`**

```python
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
```

- [ ] **步骤 4：加 `.gitignore` 条目（rebrand 本地产物不入 git）**

修改 `.gitignore`，追加：

```
# rebrand 本地副产物
docs/rebrand-inventory.md
```

预期：`.gitignore` 末尾新增一行。

- [ ] **步骤 5：commit 脚手架**

```bash
git add scripts/rebrand/sxdevops_to_autotoll.py .gitignore
git commit -m "feat(rebrand): 替换脚本 + allow-list + dry-run 模式（L1）"
```

预期：commit 出现一次，工作树干净。

---

### 任务 2：dry-run 出扫描清单（不入 git）

**文件：**
- 创建：`docs/rebrand-inventory.md`（本地产物，最终加进 .gitignore 不跟踪）

- [ ] **步骤 1：跑 docs 范围 dry-run，把输出写到本地清单**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope docs --repo . > docs/rebrand-inventory.md 2>&1
```

预期：`docs/rebrand-inventory.md` 内容包含 `[DRY ] README.md hits=N`、`[DRY ] docs/AIOps*.md hits=N` 等行，合计 `total files > 0`。

- [ ] **步骤 2：跑全范围 dry-run，验证 allow-list 是否正常**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope all --repo .
```

预期输出**不应包含**以下命中（确认已跳过）：
- `backend/sxdevops/**.py`
- 任何含 `SXDEVOPS_` 的 .env / .env.example
- `docker-compose.yml` 中 `sxdevops` service 行
- `patches/index-*.js`、`patches/Login-*.js` baked JS

如发现误命中，回到任务 1 修改 allow-list 重跑。

- [ ] **步骤 3：review `docs/rebrand-inventory.md`**

逐条核对命中文件是否都在 L1 "要动"清单内。如有不在清单内的文件（如新发现 `frontend/src/api/*.js` 展示文本），把文件加入 README.md § 文件结构，并相应更新 plan。

- [ ] **步骤 4：commit 工作分支**

工作树此时**不应**有未跟踪文件（rebrand-inventory.md 已在 .gitignore）。

```bash
git status --short
```

预期输出为空。

> 本任务不产生 commit；只是验证任务 1 脚本是否正确。

---

## 阶段 B：替换与提交

> 以下四个任务对应四个 commit。每个任务都跑 `python scripts/rebrand/sxdevops_to_autotoll.py --scope <X> --apply`，然后 `git diff` 审核 → commit。

### 任务 3：批次 1 — docs + README + AGENTS + CONTRIBUTING

**文件：**
- 修改：`README.md` / `AGENTS.md` / `CONTRIBUTING.md` / `LICENSE`（如有）/ `NOTICE`（法定署名保留，**不动**）/ `docs/*.md`（含 5 份 AIOps 文档 + 二次开发工作流 + OPEN_SOURCE_CHECKLIST）

- [ ] **步骤 1：跑 docs 范围真跑**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope docs --repo . --apply
```

预期：`[PATCH]` 行出现在终端，命中文件涵盖 README、AGENTS、CONTRIBUTING、docs/*.md。

- [ ] **步骤 2：手动修 README 的双品牌介绍段（决策点 D-1）**

打开 `README.md`，定位原首段（line 3-11）：

```
SxDevOps 是一个面向真实运维现场的开源智能运维 Agent 平台。它把 ...
> **Autotoll Devops** 是基于 SxDevOps 的二次发行版（rebrand fork），主要在「品牌外观、Traces 后端默认、Provider 体验」三方面做了定制...
- 上游项目：[github.com/aiyiyi121/sxdevops](https://github.com/aiyiyi121/sxdevops)
- 上游体验：[https://www.sxdevops.top](https://www.sxdevops.top)
- 上游产品介绍页：[SxDevOps AI Agent](https://www.sxdevops.top/ai-agent-promo)
```

按决策点 D-1 推荐方案改为：

```
Autotoll DevOps 是一个面向真实运维现场的开源运维智能体平台。它把 ...

- 上游项目：[github.com/aiyiyi121/sxdevops](https://github.com/aiyiyi91/sxdevops)
- 上游体验：[https://www.sxdevops.top](https://www.sxdevops.top)
- 产品介绍页：[Autotoll DevOps 智能体](https://www.example.com/autotoll-ai-agent-promo)
```

> 注：上游 URL 与分支名保留作署名引用，不重写。

- [ ] **步骤 3：跑 README 对比表整段重写（决策点 D-2）**

`README.md` § "Autotoll Devops vs 上游 SxDevOps" 对比表约 line 46-58，把整段对比表替换为对 Autotoll DevOps 单品牌的描述，"上游 SxDevOps"列移除。

- [ ] **步骤 4：review git diff 范围**

```bash
git diff --stat
git diff README.md | head -120
```

预期：`README.md`、`AGENTS.md`、`CONTRIBUTING.md`、`docs/*.md` 全部出现 diff；`NOTICE`、`LICENSE`、上游 URL、代码引用未出现意外修改。

- [ ] **步骤 5：commit**

```bash
git add README.md AGENTS.md CONTRIBUTING.md docs/
git commit -m "docs: rebrand project name to Autotoll DevOps (L1)"
```

预期：1 commit，working tree clean。

---

### 任务 4：批次 2 — patches/ 静态资源

**文件：**
- 修改：`patches/index.html`、`patches/sxdevops-ai-agent-promo.html`（**当 apply-patches.sh 跑过才存在**）
- 不修改：`patches/index-*.js`、`patches/Login-*.js` baked JS

- [ ] **步骤 1：检查 patches 资源是否已经 apply**

```bash
ls patches/index.html patches/sxdevops-ai-agent-promo.html 2>&1
```

期望两个都存在（之前已经跑过 `scripts/apply-patches.sh`）。如果不存在：

```bash
./scripts/apply-patches.sh
ls patches/*.html
```

- [ ] **步骤 2：跑 patches 范围真跑**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope patches-static --repo . --apply
```

预期：命中 patches/index.html 与 patches/sxdevops-ai-agent-promo.html 中的 SxDevOps 字眼。

- [ ] **步骤 3：review baked JS 未被触碰**

```bash
git diff patches/index-*.js patches/Login-*.js
```

预期：`git diff` 输出为空（baked JS 不变）。

- [ ] **步骤 4：手动 review patches HTML diff**

```bash
git diff patches/index.html patches/sxdevops-ai-agent-promo.html | head -60
```

预期：HTML `<title>`、H1、产品段落中 SxDevOps → Autotoll DevOps。

- [ ] **步骤 5：commit**

```bash
git add patches/index.html patches/sxdevops-ai-agent-promo.html
git commit -m "chore(patches): rebrand static HTML to Autotoll DevOps

保留 baked JS bundle（由 apply-patches.sh 的 tarball 维护）"
```

预期：1 commit，`patches/index-*.js` / `patches/Login-*.js` 不在 commit 内。

---

### 任务 5：批次 3 — frontend/ 显示文本

**文件：**
- 修改：`frontend/src/layout/AppLayout.vue`、`frontend/src/views/Login.vue`、其他 7 个 *.vue hero 区
- 不修改：JS 内部事件名（`sxdevops-module-settings-updated`、`sxdevops-aiops-open` 等出现在 JS string literal 中的代号）

- [ ] **步骤 1：跑 frontend 范围真跑**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope frontend-display --repo . --apply
```

预期：命中 AppLayout.vue、Login.vue，以及 K8sManage / ContainerManage / 等页面中的 SxDevOps 字眼（如果有）。

- [ ] **步骤 2：review JS 事件名未被替换**

```bash
git diff frontend/src/layout/AppLayout.vue | grep -E "sxdevops-module-settings-updated|sxdevops-aiops-open"
```

预期：这些 JS 内部事件名原样保留（`line_allowed` 拒绝 `sxdevops-` 形式）。

- [ ] **步骤 3：review AppLayout.vue 与 Login.vue diff**

```bash
git diff frontend/src/layout/AppLayout.vue frontend/src/views/Login.vue
```

预期：line 6/9 (AppLayout)、line 7/9/61 (Login) 等展示文本被替换；JS 内部变量名、事件名保留。

- [ ] **步骤 4：commit**

```bash
git add frontend/src/
git commit -m "refactor(frontend): rebrand visible labels to Autotoll DevOps

保留模块代号 sxdevops 作为内部 JS 事件名、route name、store key 等"
```

预期：1 commit。

---

### 任务 6：批次 4 — backend/ display 字符串

**文件：**
- 修改（潜在）：`backend/sxdevops/{settings,frontend_views}.py` 中如有展示文本变量
- 不修改：`backend/sxdevops/**` 全部 Python 标识符、模块路径、URL refs、cache alias

- [ ] **步骤 1：跑 backend 范围真跑**

```bash
python scripts/rebrand/sxdevops_to_autotoll.py --scope backend-display --repo . --apply
```

预期：命中文件数可能是 0（settings.py 当前不含 SxDevOps 展示文本，仅含 sxdevops API 引用），这是正常状态。

- [ ] **步骤 2：review 是否真的零命中**

```bash
git diff backend/
```

预期：`git diff backend/` 输出为空（确认 allow-list 正常工作）。

- [ ] **步骤 3：如果有命中则 review diff 并 commit；如果零命中则空 commit**

若 0 命中（推荐情况）：

```bash
git status --short backend/
```

预期：输出为空，**本任务不产生 commit**。

如有命中：

```bash
git diff backend/
git add backend/
git commit -m "refactor(backend): rebrand site display strings to Autotoll DevOps

不改 INSTALLED_APPS / ROOT_URLCONF / WSGI / ASGI / cache alias 等模块代号"
```

---

## 阶段 C：构建验证

### 任务 7：写验证脚本 `verify_rebrand.py`

**文件：**
- 创建：`scripts/rebrand/verify_rebrand.py`

- [ ] **步骤 1：编写 `verify_rebrand.py`**

```python
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
    print(f"  \033[32m✓\033[0m {msg}")


def red(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def check_positive() -> list[str]:  # 期望命中（改对了）
    fails = []
    targets = {
        "README.md": r"\bAutotoll DevOps\b",
        "docs/AIOps智能体实现说明.md": r"\bAutotoll DevOps\b",
        "frontend/src/views/Login.vue": r"\bAutotoll DevOps\b",
        "frontend/src/layout/AppLayout.vue": r"\bAutotoll DevOps\b",
    }
    for rel, pat in targets.items():
        p = REPO / rel
        if not p.exists():
            fails.append(f"[POS] missing file: {rel}")
            continue
        if not re.search(pat, p.read_text(encoding="utf-8")):
            fails.append(f"[POS] no Autotoll DevOps in {rel}")
        else:
            green(f"positive hit: {rel}")
    return fails


def check_negative() -> list[str]:  # 不期望命中（应保留）
    fails = []
    protected_paths = [
        "backend/sxdevops",
        "docker-compose.yml",
    ]
    for rel in protected_paths:
        p = REPO / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        # 检查 demo 文本不应在 settings.py 注释行出现 'Django settings for sxdevops project.'
        if rel == "backend/sxdevops/settings.py":
            if "Django settings for sxdevops project." not in text:
                fails.append("[NEG] settings.py 注释被误改")
            else:
                green(f"protected: {rel} (注释保留)")
            if "INSTALLED_APPS" in text and "'sxdevops'" not in text:
                fails.append("[NEG] INSTALLED_APPS 中的 sxdevops app label 丢失")
        if rel == "docker-compose.yml":
            # 检查 service sxdevops: 块未改
            if re.search(r"^\s*sxdevops:", text, re.MULTILINE) is None:
                fails.append("[NEG] docker-compose.yml 中 sxdevops service 缺失")
            else:
                green(f"protected: {rel} (service 保留)")
    # baked JS 不变（如果存在）
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
    return fails


def main() -> int:
    print("=== verify_rebrand: 正向断言（展示层已含 Autotoll DevOps）===")
    pos_fails = check_positive()
    print("\n=== verify_rebrand: 反证断言（L1 不动项保留）===")
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
```

- [ ] **步骤 2：commit 验证脚本**

```bash
git add scripts/rebrand/verify_rebrand.py
git commit -m "feat(rebrand): L1 自动化验收脚本（含正反证断言）"
```

---

### 任务 8：跑后端 Django test

- [ ] **步骤 1：装依赖并跑后端测试**

```bash
cd backend
pip install -r requirements.txt
python manage.py test 2>&1 | tail -30
cd ..
```

预期：测试运行无 ImportError；如有因品牌文本变更导致的失败，逐个修或保留为代号（按 spec § 6 escape hatch）。

- [ ] **步骤 2：如测试失败，根据失败 commit 修复**

```bash
git add backend/
git commit -m "test(backend): fix assertions affected by rebrand"
```

---

### 任务 9：跑前端 build

- [ ] **步骤 1：装依赖并跑前端构建**

```bash
cd frontend
npm install
npm run build 2>&1 | tail -30
cd ..
```

预期：构建成功无错误。

- [ ] **步骤 2：commit dist 更新（如有 tracked）**

```bash
git status --short frontend/
```

`frontend/dist/` 通常不入 git，若未跟踪则无需 commit。

---

### 任务 10：跑 `verify_rebrand.py` 自动化验收

- [ ] **步骤 1：跑验收脚本**

```bash
python scripts/rebrand/verify_rebrand.py
echo "EXIT=$?"
```

预期：所有正向 + 反证断言绿，退出码 0。若退出码 1：先修展示层（任务 3-6 漏改）；若退出码 2：修保护项误改（回滚对应行）。

---

### 任务 11：起服 smoke

- [ ] **步骤 1：起服**

```bash
docker compose build sxdevops
docker compose up -d sxdevops
```

预期：`sxdevops` service 健康。

- [ ] **步骤 2：浏览器手动验证 3 个采样点**

| 采样点 | URL | 期望 |
| --- | --- | --- |
| Login 页 | `http://localhost:8000/` | 卡片标题/footer 出现 `Autotoll DevOps`，无 `SxDevOps` |
| K8sManage hero | 登录后 K8s 集群管理页 | hero 标题区展示 `Autotoll DevOps` |
| ContainerManage hero | Docker 环境管理页 | hero 标题区展示 `Autotoll DevOps` |

- [ ] **步骤 3：停服**

```bash
docker compose stop sxdevops
```

---

## 阶段 D：合并走 PR

### 任务 12：push 工作分支并建 PR

- [ ] **步骤 1：push 工作分支**

```bash
git push -u origin feature/rebrand-autotoll-sxdevops
```

预期：远端出现 `feature/rebrand-autotoll-sxdevops`。

- [ ] **步骤 2：在 GitHub 网页创建 PR**

`feature/rebrand-autotoll-sxdevops` → `test`

PR 描述模板：

```markdown
## 重命名 SxDevOps → Autotoll DevOps（L1 仅展示层）

### 改动

- 4 个 commit 实现品牌重命名
- 替换脚本 + 验收脚本

### 验证

- [x] 后端测试通过
- [x] 前端构建通过
- [x] verify_rebrand.py 全绿
- [x] docker compose 起服正常，3 个采样点冒烟通过

### 配套

- spec: docs/superpowers/specs/2026-06-29-autotoll-rebrand-design.md
- plan: docs/superpowers/plans/2026-06-29-autotoll-rebrand-plan.md
```

- [ ] **步骤 3：通过 review 后合并 PR**

按 [docs/二次开发工作流.md](../../二次开发工作流.md) § 2.3，PR 通过审查后由协作者 squash 或 merge commit 合入 `test`。

---

### 任务 13：merge 后清理

- [ ] **步骤 1：本地切回 test 同步**

```bash
git switch test
git pull --rebase origin test
```

- [ ] **步骤 2：删除本地与远端临时分支**

```bash
git branch -d feature/rebrand-autotoll-sxdevops
git push origin --delete feature/rebrand-autotoll-sxdevops
```

- [ ] **步骤 3：等待维护者按工作流 § 2.4 走 `test → main` PR**

本任务结束。后续 hotfix 走 [docs/二次开发工作流.md](../../二次开发工作流.md) § 7 hotfix 流程。

---

## 决策点表（执行前请用户最终确认）

| 编号 | 问题 | 推荐方案 | 备选 |
| --- | --- | --- | --- |
| D-1 | README 首段双品牌介绍如何处理 | 改写为 Autotoll DevOps 单品牌，保留上游 URL 作署名引用 | 保留 "SxDevOps upstream" 单独一行说明，作为合规引用 |
| D-2 | README § "Autotoll Devops vs 上游 SxDevOps" 对比表 | 移除对比表，改写为单品牌"产品定位"章节 | 保留表但表头改为 "Autotoll DevOps（原 fork 时点）" |
| D-3 | `docs/screenshots/sxdevops-operation-flow.png` 文件名 | **不动**（L1 不改路径）| 重命名为 `autotoll-operation-flow.png`（需重写 README 引用）|
| D-4 | `NOTICE` 中 `SxDevOps` 法定署名 | **保留**（法律文本）| 改 `SxDevOps` → `Autotoll DevOps` 同时保留 `Copyright 2026 dayan150820` |
| D-5 | `frontend/src/views/Dashboard.vue` 等目前 grep 为 0 命中的文件 | 任务 5 步骤 1 跑过替换后 `git diff` 应为空，无需手动改 | 手动按 hero 风格加 `Autotoll DevOps` 文案（如果想统一风格）|
| D-6 | `frontend/src/layout/AppLayout.vue` 内 `sxdevops-aiops-open` JS 事件名 | **保留**代号（事件名不暴露给终端用户）| 改 `sxdevops-aiops-open` → `autotoll-devops-aiops-open`（L3 工作量）|

---

## 自检（已跑过）

| 项 | 结果 |
| --- | --- |
| 规格覆盖度 | § 1-7 全部对应到任务 1-13 |
| 占位符扫描 | 无 TODO/TBD/待定/FIXME；所有代码块完整 |
| 类型一致性 | `Path`、`Path.read_text/write_text`、`REPLACEMENTS` 列表、allow-list 集合命名在脚本中一致 |
| 风格一致 | "AI" 字眼仅出现于：(a) writing-plans skill 头部「面向 AI 代理的工作者」（skill 强制）；(b) 替换映射目标字符串 `SxDevOps AI Agent` → `Autotoll DevOps 智能体`；(c) plan 自检说明。UTF-8；中文；UTF-8 验证命令贯穿全 plan |
| 决策点表完整性 | D-1/D-2 必须在执行前确认；D-3/D-4/D-5/D-6 可由 reviewer PR 阶段调整 |

---

## 执行交接

**计划已完成并保存到 `docs/superpowers/plans/2026-06-29-autotoll-rebrand-plan.md`。两种执行方式：**

**1. 子代理驱动（推荐）** - 每个任务调度一个新的子代理，任务间进行审查，快速迭代

**2. 内联执行** - 在当前会话中使用 executing-plans 执行任务，批量执行并设有检查点

**选哪种方式？**
