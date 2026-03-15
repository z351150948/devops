# AgDevOps 运维平台

基于 Django 5 + Vue 3 + Element Plus 的一体化运维平台，覆盖主机管理、CMDB、部署管理、容器管理、日志中心、告警中心和 SQL 审计等场景。

## 功能概览

- 仪表盘：聚合主机、部署、告警等核心指标
- CMDB：资源关系、成本分析、资产管理
- 主机与部署：主机台账、部署记录、运行状态查看
- 容器管理：K8s 集群、Docker 环境管理
- Nginx 管理：域名、路由、证书与环境配置
- 日志中心：
  - 数据源管理与日志查询分离
  - 支持 Loki、ELK / Elasticsearch、阿里云 SLS
  - 支持 Demo 数据源与 Demo 日志，便于本地演示
  - 查询页支持多标签页、历史记录、收藏条件、趋势图
  - 提供三种日志源的站内查询语法帮助
- SQL 审计：数据源、工单、只读查询

## 日志中心亮点

- 菜单拆分为 `日志中心 / 日志数据源` 与 `日志中心 / 日志查询`
- 首次进入日志查询默认选中 `SLS 演示（上海）`
- 记住用户上次使用的数据源
- 默认查询最近 1 小时，支持最近 10 分钟 / 30 分钟 / 1 小时 / 6 小时
- Loki、ELK、SLS 均内置生产风格 Spring Cloud Demo 日志
- Demo 日志包含 trace/span、线程、类名、多租户、灰度发布等字段

## 项目结构

```text
agdevops/
├─ backend/
│  ├─ agdevops/            # Django 配置
│  ├─ ops/                 # 运维、日志中心、主机、部署、告警
│  ├─ cmdb/                # CMDB 与成本分析
│  ├─ sqlaudit/            # SQL 审计
│  ├─ requirements.txt
│  └─ manage.py
├─ frontend/
│  ├─ src/api/             # 前端 API 封装
│  ├─ src/layout/          # 布局与菜单
│  ├─ src/router/          # 路由
│  ├─ src/views/           # 页面视图
│  └─ package.json
└─ README.md
```

## 快速启动

### 后端

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python -m daphne -b 0.0.0.0 -p 8000 agdevops.asgi:application
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认访问：`http://localhost:3000`

## 常用命令

```bash
# 后端测试
cd backend && python manage.py test ops

# 前端构建
cd frontend && npm run build
```

## 日志相关接口

- `GET /api/log/providers/`
- `GET /api/log/datasources/`
- `POST /api/log/datasources/`
- `POST /api/log/providers/<provider>/catalog/`
- `POST /api/log/query/`

## 配置说明

后端支持通过 `backend/agdevops/settings.py` 或环境变量配置日志源默认参数：

- `LOKI_URL`
- `ELK_URL`
- `ELK_AUTH_TYPE`
- `ALIYUN_SLS_ENDPOINT`
- `ALIYUN_SLS_PROJECT`

首次执行迁移后会自动写入 Loki、ELK、SLS 的 Demo 数据源，可直接用于演示日志查询页面。

## License

MIT
