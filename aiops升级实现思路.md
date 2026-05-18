# AIOps 升级实现思路

## 1. 升级目标

本次 AIOps 升级的核心不是扩展更多问答入口，而是把智能体改造成“环境驱动、图谱约束、告警与系统态势优先、证据可追溯、动作受控”的平台内智能分析能力。

升级后的主链路为：

```text
用户问题
-> 环境识别与确认
-> 读取该环境的知识图谱视图
-> 获取系统/服务/数据源/容器/事件关联范围
-> 优先查询告警中心和系统态势
-> 按需补充日志、链路、监控看板、事件中心、容器环境证据
-> 输出结论、证据、推断、建议动作
-> 如需执行，仅生成待确认任务草稿
```

事件中心不作为分析主入口。线上问题可能来自容量、性能、依赖、错误率、SLA 波动、容器状态、发布后退化等，并不一定先产生平台事件。因此主入口应是告警中心和系统态势；事件中心作为辅助定位、复盘和变更/操作证据来源。

## 2. 信息源边界

平台内分析信息源收敛为以下几类：

- 告警中心：作为默认分析入口之一，用于发现当前异常、未恢复告警、告警级别、影响对象和时间窗口。
- 系统态势：如果所选环境配置了系统态势，则作为默认分析入口之一，读取系统健康度、SLA、可用性、错误率、延迟、组件状态、影响事件和风险等级等信息。
- 可观测性：用于补充日志、链路追踪、Grafana 看板、数据源关联配置和系统/服务字段映射。
- 事件中心：用于辅助定位变更、操作、任务、工单、发布、失败记录和复盘证据，不作为第一查询入口。
- 容器环境：只允许通过平台内接口读取 K8s / Docker 快照、集群摘要、namespace、工作负载、Pod 状态等信息，不允许 AIOps 直接连接集群、Docker daemon 或主机执行操作。
- 任务中心：只作为生成待执行任务的出口，不作为分析事实来源。
- 外部 MCP：继续保留 HTTP / STDIO MCP 接入能力，但必须受工具白名单、只读策略、超时、权限和审计约束。

不再作为默认分析信息源的能力：

- 工单系统：工单相关事件已经进入事件中心，分析时通过事件中心读取。
- 任务中心查询：任务执行、结果、失败等已经进入事件中心，分析时通过事件中心读取。
- CMDB MCP：保留配置能力但默认不启用，不作为默认信息源。
- 中间件 MCP：从平台内置 MCP 中删除；中间件/DB 依赖关系优先来自知识图谱、链路、容器标签、系统态势依赖和可观测性关联配置。

## 3. 环境前置规则

所有分析类问题必须先指定环境。

如果用户没有指定环境，后端不进入工具调用和模型分析，直接返回：

```text
必须先指定环境后才能分析。
可选环境：生产、测试、预发、交易生产 ...
```

环境识别规则：

- 精确匹配：优先匹配 `AIOpsKnowledgeEnvironment.name`。
- 别名匹配：支持 `prod`、`生产`、`生产环境`、`线上` 等别名归一。
- 模糊匹配：用户说法不需要逐字一致，能唯一匹配时直接使用。
- 多候选匹配：如果命中多个环境，返回候选环境让用户选择。
- 会话继承：同一会话中已确认过环境，后续追问默认继承该环境，除非用户显式切换。

建议对 `AIOpsKnowledgeEnvironment` 增加 `aliases` 字段，用于维护环境别名，避免把环境识别写死在提示词或硬编码字典里。

## 4. 知识图谱作为分析约束

拿到环境后，必须先读取该环境的知识图谱视图，形成统一的 `analysis_scope`。后续工具调用必须在该 scope 内进行，避免模型按关键词全局乱查。

`analysis_scope` 建议包含：

- 环境：环境名、别名、事件环境、告警环境。
- 系统：业务系统、系统态势系统、系统所属业务线。
- 服务：服务名、部署名、运行时标签、命名空间、关联系统。
- 可观测性：日志数据源、链路数据源、Grafana 目录/看板、告警环境、关联配置。
- 系统态势：SLA、可用性、错误率、延迟、健康度、组件状态、风险等级、影响时间段。
- 容器环境：K8s 集群、namespace、工作负载、Pod、Docker 主机。
- 事件范围：事件中心环境、事件源、事件类型、资源关联字段。
- 依赖关系：服务依赖、系统依赖、中间件/DB 依赖、上下游关联。

知识图谱的职责不是替代所有查询，而是限定“查哪里、查什么、怎么关联”。真正的证据仍由告警、系统态势、日志、链路、看板、事件中心和容器平台接口返回。

## 5. 分析优先级

默认分析顺序调整为：

1. 告警中心：先判断当前是否存在未恢复、未确认、高等级或持续波动告警。
2. 系统态势：如果环境配置了系统态势，则读取 SLA、健康度、可用性、错误率、延迟、组件状态和影响范围。
3. 可观测性补证：根据知识图谱和关联配置查询日志、链路、看板指标、数据源证据。
4. 容器环境补证：通过平台内接口查看集群、namespace、工作负载、Pod、容器重启、调度、资源状态。
5. 事件中心辅助定位：查询发布、变更、任务、工单、操作、失败记录等事件，用于判断异常是否和近期动作相关。
6. 任务草稿生成：如果用户要求巡检、修复、执行命令或生成动作，只生成待确认任务草稿。

事件中心的角色是“辅助定位与复盘证据”，不是“主分析入口”。只有当告警、系统态势或用户问题指向变更/操作/执行结果时，才重点查询事件中心。

## 6. MCP 调整

### 6.1 平台内置 MCP

建议保留和调整如下：

- 可观测性 MCP：保留并增强，覆盖 `query_alerts`、`query_observability`、`query_logs`、`query_traces`、`query_dashboard_metadata`、`query_system_posture`、`query_observability_links`。
- 事件中心 MCP：保留，定位为辅助证据工具，例如 `query_event_wall`。
- 容器环境 MCP：保留，但只能通过平台内接口读取容器信息，例如 `query_container_assets`、`query_k8s_cluster_summary`，禁止直连真实环境操作。
- 任务中心 MCP：保留，但只保留生成任务能力，例如 `generate_host_task`。移除或禁用 `query_task_center`、`query_host_tasks` 等查询能力。
- CMDB MCP：保留配置但默认停用，不进入默认启用列表。
- 中间件 MCP：从平台内置 MCP 删除。
- 工单系统 MCP：不再作为分析工具；工单相关信息统一通过事件中心查询。

### 6.2 外部 MCP

外部 MCP 能力继续保留，包括 Grafana MCP、N9E MCP、SkyWalking MCP 等。

外部 MCP 需要满足以下约束：

- 默认只读。
- 工具必须进入白名单后才允许调用。
- 每次调用记录 `AIOpsToolInvocation` 审计。
- 设置超时、失败兜底和错误可视化。
- 不允许外部 MCP 绕过平台 RBAC 读取用户无权访问的数据。
- 涉及写操作的外部工具默认禁用，除非后续明确设计审批链路。

## 7. Skill 优化

Skill 不只用于回答格式，也应该承载平台内置的 AIOps 固化流程。建议把固化逻辑拆成可见、可启停、可审计的内置 Skill。

内置 Skill 可以禁止编辑和删除，但应允许在配置页查看内容，让管理员直观看到智能体的分析流程和约束。

建议新增或重构以下 Skill：

- 环境前置检查 Skill：所有分析必须先有环境；无环境时返回候选环境，不继续分析。
- 知识图谱取证 Skill：有环境后必须先读取环境图谱，形成 `analysis_scope`。
- 告警优先分析 Skill：默认先查告警中心，识别未恢复、高等级、持续波动和影响对象。
- 系统态势/SLA 分析 Skill：环境配置了系统态势时，必须纳入 SLA、健康度、错误率、延迟、可用性和组件状态。
- 可观测性关联 Skill：根据平台关联配置决定日志、Trace、告警、看板、事件字段如何关联。
- 看板分析 Skill：优先通过平台可观测性接口读取看板元数据和系统映射；需要实时指标值时再调用 Grafana MCP 或平台 Grafana API。
- 容器只读取证 Skill：容器环境只能通过平台接口读取，不允许直连环境或执行操作。
- 事件辅助定位 Skill：事件中心用于辅助判断近期变更、任务、工单、发布和操作是否与问题相关。
- 任务生成 Skill：涉及巡检、修复、执行命令时，只生成任务草稿，确认后进入任务中心。
- 证据化回答 Skill：回答必须区分结论、证据、推断、建议动作和下一步。

Skill 的执行方式建议是“后端规则 + Skill 可视化说明”结合。关键安全和流程约束必须在后端硬控制，Skill 用于让模型理解流程并让管理员可见，不应只靠提示词保证。

## 8. 会话上下文记忆

同一个对话框里的问答需要有上下文记忆。建议在会话元数据中维护结构化上下文，而不是只依赖历史消息文本。

建议保存：

- `current_environment`：当前确认环境。
- `environment_candidates`：最近一次候选环境。
- `analysis_scope`：最近一次环境图谱范围摘要。
- `last_systems`：最近涉及的系统。
- `last_services`：最近涉及的服务。
- `last_time_window`：最近分析时间窗口。
- `last_evidence_summary`：最近证据摘要。
- `last_pending_action`：最近生成的待确认动作。

后续追问如“继续查这个服务”“那昨天呢”“生成巡检任务”时，可以继承当前环境、系统、服务和时间窗口。

如果用户显式切换环境，必须清理或重建 `analysis_scope`，避免跨环境串证据。

## 9. 监控看板分析策略

监控看板可以分析，但要分层处理。

平台可以直接分析的内容：

- 看板属于哪个环境、系统、服务。
- 看板有哪些 Panel。
- Panel 使用哪些数据源和查询语句。
- 看板和日志、链路、告警、系统态势之间的关联。
- 看板是否覆盖关键 SLI / SLA 指标。
- 看板元数据是否能支撑当前问题排查。

需要平台 Grafana API 或 Grafana MCP 的内容：

- 当前时间窗口里的真实指标值。
- PromQL / Loki 查询结果。
- Panel 实时曲线、异常点、峰值、P95/P99、错误率等计算结果。
- 需要跨数据源实时查询的看板证据。

建议策略：

- 默认先通过平台可观测性接口读取看板元数据、关联配置和系统映射。
- 如果问题需要实时指标值，默认调用平台后端 Grafana API，而不是把 Grafana MCP 作为主路径。
- Grafana MCP 作为外部扩展能力保留，适合临时接入第三方 Grafana、已有独立 Grafana MCP 或平台后端暂未适配的数据源。
- Grafana MCP 不应绕过平台环境、权限、白名单和审计。

### 9.1 Grafana / PromQL 取数推荐方案

推荐把 Grafana 实时指标分析做成平台后端能力，AIOps 只调用平台工具，不直接把 Grafana 凭据或 Grafana API 暴露给模型。

平台后端取数分两层：

1. PromQL 查询层：类似 Grafana Explore 执行 PromQL。
2. Dashboard Panel 查询层：通过 Grafana Dashboard API 拉取 dashboard JSON，解析指定 panel 的 PromQL target，再执行查询。

PromQL 查询层建议提供：

```text
POST /api/observability/grafana/promql/query/
```

能力边界：

- 支持 instant query：调用 `/api/v1/query`。
- 支持 range query：调用 `/api/v1/query_range`。
- 优先使用 `PROMETHEUS_QUERY_URL` 直连 Prometheus。
- 如果没有直连 Prometheus，则通过 Grafana datasource proxy：

```text
GET /api/datasources/uid/{datasource_uid}
GET /api/datasources/proxy/{datasource_id}/api/v1/query
GET /api/datasources/proxy/{datasource_id}/api/v1/query_range
```

Dashboard Panel 查询层建议提供：

```text
POST /api/observability/grafana/panel/query/
```

能力边界：

- 根据 dashboard UID 或平台看板 key 获取 Grafana dashboard JSON。
- 根据 `panel_id` 或 `panel_title` 定位 panel。
- 解析 panel `targets[].expr` 中的 PromQL。
- 支持用平台传入的变量替换 `$namespace`、`${workload}` 等 Grafana 变量。
- 如果 target 声明了 Prometheus datasource uid，优先使用该 uid。
- 查询结果返回序列数量、样例点、最新值和时间窗口，供 AIOps 做证据化分析。

相关配置建议沿用平台后端配置：

- `PROMETHEUS_QUERY_URL`：直连 Prometheus 时使用。
- `PROMETHEUS_GRAFANA_URL` 或平台 Grafana 配置 `url`：走 Grafana proxy 时使用。
- `PROMETHEUS_GRAFANA_DATASOURCE_UID`：默认 Prometheus 数据源 UID。
- `PROMETHEUS_GRAFANA_DATASOURCE_ID`：已知 datasource id 时可跳过 uid 查询。
- `PROMETHEUS_GRAFANA_API_TOKEN`：Grafana service account token。
- `PROMETHEUS_QUERY_TIMEOUT`：查询超时。

AIOps 工具建议新增：

- `query_grafana_promql`：执行明确的 PromQL，适合用户问 QPS、错误率、P95、资源使用率、趋势等。
- `query_dashboard_panel_data`：分析指定看板或面板，适合用户说“直接分析这个监控看板/面板”。

这两个工具必须受当前环境 `analysis_scope` 约束：

- 只能查询当前知识图谱环境关联的 Grafana 目录、看板或数据源。
- 所有调用记录 `AIOpsToolInvocation`。
- 用户必须具备 `ops.grafana.view` 权限。
- Grafana token 只保存在后端，前端和 LLM 都不能接触。

与 Grafana MCP 的关系：

- 平台后端 Grafana API 是默认取证路径。
- Grafana MCP 是可选外部 MCP，用于补充平台暂未覆盖的 Grafana 能力。
- 当两者都可用时，内置 AIOps 优先走平台后端 API，因为它更容易统一 RBAC、审计、环境过滤、限流、缓存和字段标准化。

## 10. 后端实现建议

后端建议新增一个显式编排层，放在聊天入口和 LLM 工具调用之间。

编排流程：

```text
normalize_user_question
-> resolve_or_require_environment
-> load_session_context
-> build_analysis_scope_from_knowledge_graph
-> choose_builtin_flow_skills
-> build_allowed_tools
-> query_alerts_and_system_posture_first
-> invoke_llm_tool_planning_if_needed
-> collect_evidence
-> format_answer
-> persist_context_and_audit
```

关键点：

- 环境缺失时直接返回，不进入 LLM。
- 环境识别、MCP 白名单、容器只读、任务只生成草稿等规则由后端硬控制。
- LLM 可以规划工具调用，但不能突破 `analysis_scope` 和工具白名单。
- 工具调用结果必须写入审计。
- 回答前进行二阶段整理，确保输出结构稳定。

## 11. 前端实现建议

聊天组件建议增加：

- 当前环境显示。
- 环境未指定提示。
- 环境候选按钮。
- 当前分析 scope 摘要，例如系统、服务、时间窗口。
- 思考过程里展示“环境识别 -> 图谱读取 -> 告警/系统态势 -> 补充证据 -> 输出结论”。
- 任务草稿卡片继续保留，确认后进入任务中心。

AIOps 配置页建议调整：

- MCP 列表展示新的内置 MCP 边界。
- 任务中心 MCP 只显示生成任务能力。
- CMDB MCP 默认停用。
- 中间件 MCP 不再作为内置项。
- 外部 MCP 保持可配置，并突出只读、白名单和审计。
- Skill 页展示内置固化流程，内置 Skill 禁止编辑/删除，但允许查看内容。

## 12. 最终用户体验

用户没有指定环境时：

```text
必须先指定环境后才能分析。
可选环境：生产、预发、测试、交易生产。
```

用户指定环境后：

```text
已使用环境：交易生产

结论：
当前 order-center 存在错误率升高，系统态势显示 SLA 已低于目标，告警中心存在 2 条未恢复告警。

证据：
1. 告警中心：order-center 5xx 错误率告警持续 18 分钟。
2. 系统态势：当前可用性 99.42%，低于 SLA 目标 99.9%。
3. 链路追踪：checkout -> order-center P95 延迟上升。
4. 事件中心：异常开始前 10 分钟有一次 order-center 发布事件。

推断：
问题更可能与 order-center 发布后接口错误率升高相关，事件中心仅作为辅助证据，主证据来自告警和系统态势。

建议动作：
建议生成 order-center 巡检任务草稿，检查 Pod 重启、最近日志错误和依赖接口延迟。
```

## 13. 实施顺序

建议按以下顺序落地：

1. 调整内置 MCP 清单和默认启用策略：删除中间件 MCP，CMDB 默认停用，任务中心只保留生成任务，外部 MCP 保持。
2. 增加环境前置编排：无环境阻断，多候选返回，支持会话继承。
3. 增加 `analysis_scope`：由知识图谱环境视图生成统一分析范围。
4. 增强系统态势取证：把 SLA、健康度、错误率、延迟、组件状态纳入工具返回。
5. 调整分析顺序：告警中心和系统态势优先，事件中心辅助定位。
6. 增强 Grafana 取证：平台后端提供 PromQL query/query_range 和 dashboard panel 数据查询，AIOps 增加 `query_grafana_promql`、`query_dashboard_panel_data`。
7. 重构 Skill：把固化流程拆成可见的内置 Skill，并禁止编辑删除。
8. 增强聊天前端：显示当前环境、候选环境、scope 摘要和新的思考过程。
9. 补充测试：覆盖环境缺失、环境模糊匹配、系统态势优先、Grafana 后端取数、任务中心只生成任务、容器只读、外部 MCP 保留等场景。
