# 规格说明：品牌重命名 SxDevOps → Autotoll DevOps（L1 仅展示层）

| 项 | 值 |
| --- | --- |
| 编号 | A-2026-06-29-01 |
| 日期 | 2026-06-29 |
| 作者 | 二次开发规划（用户主导，自动化辅助） |
| 状态 | 已评审，待规格审查 |
| 范围 | **L1：仅展示层文本**，不改 Python 包名、不改 Django app label、不改容器名、不改镜像名、不改环境变量、不改 URL path、不改内部接口命名 |
| 受众 | 二次开发协作者、维护者 |

## 1. 目标与背景

仓库 fork 后已经历一次 fork 侧的品牌定制（提交 `d39e652 feat(autotoll): brand rebadge`），但当前 front-end 页面、文档、品牌资源里仍然残留 `SxDevOps` 作为展示文本。本轮 spec 把**展示层**所有 `SxDevOps` 字样替换为 `Autotoll DevOps`，建立品牌基线；后续的观测性扩展（spec B）与知识库（spec C）在新品牌基线之上进行，避免再过一轮替换。

## 2. 范围

### 2.1 必须替换（展示层）

| 类别 | 路径 / 文件 | 备注 |
| --- | --- | --- |
| README | [README.md](../../../README.md) | 项目标题、副标题、入门段、模块说明中的品牌词 |
| 项目规约 | [AGENTS.md](../../../AGENTS.md) | 第 1 行 `SxDevOps is split into...` 改为 `Autotoll DevOps is split into...` |
| 贡献指南 | [CONTRIBUTING.md](../../../CONTRIBUTING.md) | 标题 + 段首问候 |
| 架构与产品文档 | [docs/AIOps智能体实现说明.md](../../AIOps智能体实现说明.md)<br>[docs/AIOps-MCP-Skill-双阶段应答设计.md](../../AIOps-MCP-Skill-双阶段应答设计.md)<br>[docs/AIOps2.0升级优化方案.md](../../AIOps2.0升级优化方案.md)<br>[docs/AIOps2.1指标证据包设计.md](../../AIOps2.1指标证据包设计.md)<br>[docs/AIOps2.1.2-Action-Handler与上下文Copilot设计.md](../../AIOps2.1.2-Action-Handler与上下文Copilot设计.md)<br>[docs/二次开发工作流.md](../../二次开发工作流.md)<br>[docs/OPEN_SOURCE_CHECKLIST.md](../../OPEN_SOURCE_CHECKLIST.md) | 每份段落标题、入门介绍中产品名 |
| 品牌资源 | [patches/sxdevops-ai-agent-promo.html](../../../patches/sxdevops-ai-agent-promo.html) | HTML title + H1 + 段落内品牌词；**文件名保留**（被 `docker-compose.yml` 写死 bind-mount） |
| 前端布局 | [frontend/src/layout/AppLayout.vue](../../../frontend/src/layout/AppLayout.vue) | Logo 旁 alt / 顶栏品牌区 |
| 登录页 | [frontend/src/views/Login.vue](../../../frontend/src/views/Login.vue) | 卡片标题、副标题、footer 文本 |
| 工作台入口 | [frontend/src/views/Dashboard.vue](../../../frontend/src/views/Dashboard.vue) | 欢迎语、模块标题 |
| 工作台页 hero | [frontend/src/views/K8sManage.vue](../../../frontend/src/views/K8sManage.vue)<br>[frontend/src/views/ContainerManage.vue](../../../frontend/src/views/ContainerManage.vue)<br>[frontend/src/views/TaskWorkbench.vue](../../../frontend/src/views/TaskWorkbench.vue)<br>[frontend/src/views/ObservabilityOverview.vue](../../../frontend/src/views/ObservabilityOverview.vue)<br>[frontend/src/views/Hosts.vue](../../../frontend/src/views/Hosts.vue)<br>[frontend/src/views/Alerts.vue](../../../frontend/src/views/Alerts.vue)<br>[frontend/src/views/EventWall.vue](../../../frontend/src/views/EventWall.vue)<br>[frontend/src/views/AIOpsChatEntry.vue](../../../frontend/src/views/AIOpsChatEntry.vue) | hero title 旁文案、stats card 标题 |
| Login 静态资源 | [patches/index.html](../../../patches/index.html) | 静态 HTML title |
| 后端 display 文本 | [backend/sxdevops/settings.py](../../../backend/sxdevops/settings.py) | `SITE_NAME` / `SITE_DISPLAY_NAME` / 站点头显示文本（如该变量存在） |
| 后端 fallback view | [backend/sxdevops/frontend_views.py](../../../backend/sxdevops/frontend_views.py) | fallback HTML 内 `<title>` 字样 |
| LICENSE / NOTICE | [LICENSE](../../../LICENSE)<br>[NOTICE](../../../NOTICE) | 若提及品牌字样 |

### 2.2 严格不替换（保留为代号）

| 类别 | 保留形式 | 原因 |
| --- | --- | --- |
| Python 包 | `backend/sxdevops/` 整个目录 | L1 不动 import path |
| Django app | `INSTALLED_APPS` 中的 `'sxdevops'` / `'sxdevops.frontend_views'` 等 | app label 不动 |
| Docker 服务 | `docker-compose.yml` 内 `services:` 下 `sxdevops:` | service 名不动 |
| 镜像 tag | `image: sxdevops:latest`、`Dockerfile` 中构建上下文名 | image name 不动 |
| 环境变量 | `SXDEVOPS_*` 系列 30+ 变量 | env 前缀不动 |
| URL / 路径前缀 | `/api/`、`/admin/`、其他 path | URL 不动 |
| Django models table name | `Meta.db_table = 'sxdevops_*'`、迁移文件名 | table 不动 |
| 文件名（除促销 HTML 外） | 含 `sxdevops` 但被路径硬编码引用的文件名 | L1 不动文件路径 |
| 历史 commit | `git log` 中旧文本 | 不重写 git history |

### 2.3 不在本 spec 范围

- Python 类名、模块名、变量名中包含 `sxdevops` 的字符串（L1 不动代码）
- 数据库迁移（不需迁移）
- 后端 API 响应 JSON 中的 `product` 字段值变更（除非该字段为 SITE_DISPLAY_NAME 引用）

## 3. 替换映射表

| 原 | 目标 | 出现位置示例 |
| --- | --- | --- |
| `SxDevOps` | `Autotoll DevOps` | README、docs 段首、H1 |
| `SxDevOps Platform` | `Autotoll DevOps Platform` | docs 入段 |
| `the SxDevOps project` | `the Autotoll DevOps project` | AGENTS.md |
| `本项目（SxDevOps）` | `本项目（Autotoll DevOps）` | CONTRIBUTING.md 中文段 |
| `SxDevOps 智能体` | `Autotoll DevOps 智能体` | docs/AIOps*.md |

## 4. 实施步骤

### 阶段 A：准备

| 步骤 | 内容 |
| --- | --- |
| 4.A.1 | 从 `test` 切 `feature/rebrand-autotoll-sxdevops` |
| 4.A.2 | 用 ripgrep 扫描全部 `SxDevOps` 字眼，输出清单到 `docs/rebrand-inventory.md`（不入 git，加进 `.gitignore`） |
| 4.A.3 | 写替换脚本 `scripts/rebrand/sxdevops_to_autotoll.py`，按 § 2.2 allow-list 跳过：<br>- `patches/index-*.js`、`patches/Login-*.js`<br>- `backend/sxdevops/**`<br>- 含 `SXDEVOPS_*` 的环境变量行<br>- 含 `/sxdevops/` URL 行<br>- 含 `image: sxdevops` / `container_name: sxdevops` 行<br>- 路径含 `patches/sxdevops-ai-agent-promo.html` 的引用 |
| 4.A.4 | 跑 dry-run 预览 diff（`-n` / `--dry-run`） |

### 阶段 B：替换与提交

按四批 commit：

| 批次 | 范围 | commit type | commit message |
| --- | --- | --- | --- |
| 1 | docs/* + README + AGENTS.md + CONTRIBUTING.md + LICENSE + NOTICE | `docs` | `docs: rebrand project name to Autotoll DevOps (L1)` |
| 2 | patches/* 静态 HTML（含 sxdevops-ai-agent-promo.html 与 index.html）；保留 baked JS | `chore(patches)` | `chore(patches): rebrand static HTML to Autotoll DevOps` |
| 3 | frontend/src/* 全部显示文本 | `refactor(frontend)` | `refactor(frontend): rebrand visible labels to Autotoll DevOps` |
| 4 | backend/sxdevops/{settings,frontend_views}.py 内 display 字符串与 admin site header | `refactor(backend)` | `refactor(backend): rebrand site display strings to Autotoll DevOps` |

### 阶段 C：构建验证

| 步骤 | 内容 |
| --- | --- |
| 4.C.1 | `cd backend && python manage.py test` — 必须全过 |
| 4.C.2 | `cd frontend && npm run build` — 必须成功 |
| 4.C.3 | `docker compose build sxdevops && docker compose up -d sxdevops` — 起服 smoke |
| 4.C.4 | 浏览器手动验证：Login 页、K8sManage 页 hero、ContainerManage 页 hero 三个采样点 |

### 阶段 D：合并走 PR

| 步骤 | 内容 |
| --- | --- |
| 4.D.1 | `feature/rebrand-autotoll-sxdevops` → GitHub PR → `test` |
| 4.D.2 | PR 通过审查（至少 1 名维护者） |
| 4.D.3 | 合入 `test`，删除远端临时分支 |
| 4.D.4 | 由维护者按 docs/二次开发工作流 § 2.4 走 `test → main` |

## 5. 验收标准

| 项 | 标准 | 验证方式 |
| --- | --- | --- |
| 5.1 README | 标题与首段出现 `Autotoll DevOps`，不再出现 `SxDevOps` | `rg 'SxDevOps' README.md` 返回 0 命中（除历史 commit 链） |
| 5.2 文档全集 | docs/*.md 中 `SxDevOps` 不再作为展示词出现 | `rg -l 'SxDevOps' docs/` 返回 0 行展示文本命中（如 AGENTS.md 保留 `SxDevOps is split into` 句式作为代号说明，验证跳过该保留点） |
| 5.3 登录页 | 浏览器 Login 页：`Autotoll DevOps` 出现 | 手动 + 自动爬 |
| 5.4 工作台 hero | K8sManage / ContainerManage hero 区出现 `Autotoll DevOps` | 手动 + 自动爬 |
| 5.5 后端 settings | `python manage.py shell -c "from django.conf import settings; print(getattr(settings, 'SITE_NAME', getattr(settings, 'SITE_DISPLAY_NAME', 'N/A')))"` 输出 `Autotoll DevOps`（如存在） | shell 自检 |
| 5.6 baked JS 不变 | `patches/index-*.js`、`patches/Login-*.js` 内容未被替换 | `git diff patches/index-*.js patches/Login-*.js` 为空 |
| 5.7 代码结构不变 | `backend/sxdevops/**`、`SXDEVOPS_*` env、`image: sxdevops` 等保留 | `rg 'sxdevops' backend/ docker-compose.yml` 仅命中保留位置 |
| 5.8 构建通过 | 后端测试 + 前端构建 + docker build 全通过 | 见 § 4.C |

## 6. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 替换脚本误改 baked JS bundle | allow-list 锁定 `patches/index-*.js`、`patches/Login-*.js`；脚本支持 `--include-baked` 显式 opt-in |
| 误改 Python 包名 / 容器名 / URL | allow-list 锁定 `backend/sxdevops/**`、含 `SXDEVOPS_*` 行、含 `/sxdevops/` 路径、含 `image:`/`container_name:` 行 |
| 文档中 `SxDevOps` 在某些上下文中应保留为代号 | § 3 替换映射表只针对展示语；如发现需要保留的代号场景，由维护者 PR review 阶段调整 |
| 字符串 case 不一致（`sx devops`、`sxDevOps` 等） | 脚本先做 case normalization；映射表覆盖主 case，其他 case 报告后人工处理 |
| 测试用例断言中含 `SxDevOps` | 在 § 4.C.1 跑测试时如断言失败，由维护者决定是断言 update 还是保留为代号 |
| README 截图历史有旧品牌 | 不重写截图；后续截图更新任务不由本 spec 承担 |

## 7. 后续 spec 引用

完成本 spec 后，spec B（观测性扩展：主机 + 数据库监控）与 spec C（知识库）皆建立在新的 `Autotoll DevOps` 品牌基线之上：

- spec B 不会再做品牌替换
- spec C 不会再做品牌替换
- spec A 中如发现遗漏的展示文本，提交 hotfix；hotfix 走 docs/二次开发工作流 § 7 hotfix 流程，**不重开本 spec**
