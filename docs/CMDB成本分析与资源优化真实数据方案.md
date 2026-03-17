# CMDB 成本分析与资源优化真实数据方案

## 1. 目的

当前 CMDB 的“成本分析”和“资源优化”页面已经具备完整展示能力，演示环境里的数据主要来自 Demo Seed。

在真实环境中，这两块数据不应该靠手工维护，而应由以下三类真实数据自动汇总生成：

1. 云账单/计费数据：回答“这台资源这个月实际花了多少钱”
2. 监控与使用率数据：回答“这台资源是否真的用满了”
3. CMDB 归属数据：回答“这笔钱属于谁、是否能优化、该谁处理”

---

## 2. 页面上的数据分别来自哪里

### 2.1 成本分析页

成本分析页核心依赖 `CostRecord` 和 `ConfigItem` 两类数据：

- `ConfigItem`
  - 资源主数据
  - 包含资源名称、类型、业务线、环境、负责人、云厂商等归属信息
- `CostRecord`
  - 月度成本事实表
  - 每条记录至少包含：
    - `ci`
    - `month`
    - `amount`
    - `provider`

页面中的指标来源：

- 月度总成本：`sum(CostRecord.amount)`
- 业务线成本分布：按 `ConfigItem.business_line` 聚合 `CostRecord.amount`
- 环境成本分布：按 `ConfigItem.environment` 聚合
- 资源类型成本分布：按 `ConfigItem.ci_type` 聚合
- 供应商成本分布：按 `CostRecord.provider` 聚合
- Top 成本资源：按资源维度汇总后取成本最高的前 N 条
- 近 6 月趋势：按 `month` 汇总 `CostRecord.amount`

### 2.2 资源优化页

资源优化页是在“真实成本”基础上，再叠加“资源利用率”和“治理规则”计算出来的。

当前后端规则主要参考这些字段：

- 成本相关
  - `monthly_cost`
- 计算资源规格
  - `cpu`
  - `memory_gb`
- 利用率
  - `avg_cpu_usage`
  - `avg_memory_usage`
- 存储
  - `storage_gb` / `disk_gb`
  - `storage_utilization`
- 生命周期/运行策略
  - `status`
  - `always_on`
  - `schedule_exempt`
  - `offline_days`
- 治理归属
  - `business_line`
  - `admin_user`

后端基于这些字段输出：

- 可回收资源
- 非生产定时启停建议
- 高成本低利用率缩容建议
- 存储分层建议
- 归属治理建议

---

## 3. 真实环境的数据采集方式

## 3.1 成本数据

推荐按“日采集、月聚合”的方式接入。

可选来源：

- 阿里云：费用中心/账单明细 API、成本中心导出
- 腾讯云：账单明细 API、费用分账数据
- 华为云 / AWS / Azure：各自账单明细 API
- 私有云 / IDC：内部财务分摊表、采购/折旧/月摊销表

建议采集粒度：

- 最细可到实例/磁盘/公网 IP/负载均衡/数据库实例
- 采集字段建议至少包括：
  - 账期
  - 云厂商
  - 资源实例 ID
  - 资源名称
  - 产品类型
  - 原始金额
  - 折扣后金额
  - 计费模式
  - 标签/项目/账号信息

落库建议：

- 原始表：保留完整账单明细，便于审计和对账
- 汇总表：按“资源 + 月份”汇总后写入 `CostRecord`

推荐映射：

- `CostRecord.month` <- 账期，例如 `2026-03`
- `CostRecord.amount` <- 该资源该月汇总成本
- `CostRecord.provider` <- 云厂商或计费来源
- `CostRecord.ci` <- 通过实例 ID / 标签 / 主机名映射到 `ConfigItem`

---

## 3.2 监控与利用率数据

资源优化是否准确，关键不在账单，而在利用率数据是否可信。

推荐来源：

- 主机监控
  - Prometheus + Node Exporter
  - Zabbix
  - 云监控（阿里云云监控、腾讯云监控等）
- 数据库监控
  - RDS 监控 API
  - 自建 MySQL/Redis Exporter
- 存储监控
  - 云盘使用率
  - OSS / 对象存储容量与访问频度

建议按“近 7 天 / 14 天 / 30 天”计算下列指标回写到 `ConfigItem.attributes`：

- `avg_cpu_usage`
- `avg_memory_usage`
- `storage_utilization`
- `offline_days`
- `always_on`
- `schedule_exempt`

建议不要只取瞬时值，至少要保留：

- 平均值
- 峰值
- P95 / P99
- 工作时段与非工作时段分布

这样优化建议会更稳，不容易误判。

---

## 3.3 CMDB 主数据和归属信息

成本分析能否“看出问题”，很大程度取决于归属是否准确。

`ConfigItem` 至少要维护好这些字段：

- `name`
- `ci_type`
- `business_line`
- `environment`
- `admin_user`
- `status`

`attributes` 建议补充：

- `instance_id`
- `cloud_provider`
- `region`
- `billing_provider`
- `cpu`
- `memory_gb`
- `disk_gb`
- `storage_gb`
- `project`
- `owner_team`
- `charge_mode`
- `tags`

如果账单系统拿到的是云实例 ID，而 CMDB 里没有实例 ID，后续就很难自动对账。

---

## 4. 一条真实数据链路应该怎么跑

推荐链路如下：

1. 资源同步
   - 从云平台或资产源同步 ECS/RDS/Redis/SLB/OSS 等资源到 `ConfigItem`
2. 账单同步
   - 每天拉取账单明细
   - 通过实例 ID / 标签 / 主机名映射到 `ConfigItem`
   - 按月聚合写入 `CostRecord`
3. 监控同步
   - 从监控系统定时计算近 7/14/30 天的平均使用率
   - 回写到 `ConfigItem.attributes`
4. 优化计算
   - 调用 CMDB 后端接口时，根据 `CostRecord + ConfigItem.attributes` 输出建议
5. 人工闭环
   - 负责人确认是否执行
   - 执行后更新资源状态、标签或策略
   - 下月账单验证是否真的降本

---

## 5. 当前代码里的真实环境落点

结合当前项目，真实环境建议这样落：

### 5.1 成本入库

- 入口模型：`backend/cmdb/models.py` 中的 `CostRecord`
- 报表接口：`backend/cmdb/views.py` 中的
  - `cmdb_cost_report`
  - `cmdb_optimization`

建议新增一个定时任务或管理命令，例如：

- `python manage.py sync_cmdb_costs`
- `python manage.py sync_cmdb_metrics`

职责分别是：

- `sync_cmdb_costs`
  - 拉取云账单
  - 建立账单资源与 `ConfigItem` 的映射
  - 写入/更新 `CostRecord`
- `sync_cmdb_metrics`
  - 拉取监控数据
  - 计算平均 CPU、平均内存、存储利用率、离线天数等
  - 回写 `ConfigItem.attributes`

### 5.2 当前月为什么还能显示

当前实现为了避免 SQLite 在 GET 请求中写库导致锁表，已经改成：

- 当前月优先读取 `CostRecord`
- 如果当前月某资源还没有成本记录，则回退读取 `ConfigItem.attributes.monthly_cost`

这适合 Demo 和过渡阶段。

真实生产环境建议仍然以“定时同步入 `CostRecord`”为主，不要长期依赖 `monthly_cost` 手工字段。

---

## 6. 资源优化建议在真实环境中的计算思路

下面是比较推荐的真实规则口径。

### 6.1 可回收

判断条件示例：

- 资源状态为下线/停用
- 连续 7~30 天 CPU 接近 0
- 最近 30 天无连接、无请求、无变更
- 已被替代但账单仍在产生

数据来源：

- CMDB 状态
- 监控无流量/无负载
- 发布平台或应用下线记录
- 云账单仍持续扣费

### 6.2 定时启停

判断条件示例：

- `environment in (dev, test)`
- 夜间和周末负载长期较低
- 不是豁免资源

数据来源：

- CMDB 环境字段
- 时段监控
- 业务日历/值班策略

### 6.3 规格缩容

判断条件示例：

- 月成本高
- CPU/内存长期利用率偏低
- 峰值也未接近现有规格上限

数据来源：

- 账单成本
- CPU / 内存平均值与峰值
- 当前实例规格

### 6.4 存储分层

判断条件示例：

- 存储容量大
- 使用率不高
- 访问频度低

数据来源：

- 存储账单
- 容量使用率
- 最近访问热度

### 6.5 治理项

判断条件示例：

- 无业务线
- 无负责人
- 无标签
- 无预算归属

数据来源：

- CMDB 主数据完整性校验

---

## 7. 建议的实施顺序

如果要从 Demo 走向真实环境，建议按下面顺序推进：

1. 先补齐 `ConfigItem` 的实例 ID、云厂商、业务线、负责人
2. 接入云账单，把月成本先真实化
3. 接入监控，把 CPU/内存/存储利用率真实化
4. 再逐步提高优化规则精度
5. 最后加“建议执行状态”和“降本结果复盘”

这样收益最大，也最容易落地。

---

## 8. 上线后的校验方法

真实环境接入后，建议每月做三类校验：

### 8.1 对账校验

- CMDB 月度总成本
- 云厂商账单月度总成本
- 差异率是否在可接受范围内

### 8.2 映射校验

- 有多少账单资源找不到对应 `ConfigItem`
- 有多少 `ConfigItem` 没有关联成本

### 8.3 优化效果校验

- 上月执行了多少条优化建议
- 本月对应资源成本是否下降
- 是否出现误杀、误回收、误缩容

---

## 9. 总结

真实环境里，这两个模块本质上分别回答两个问题：

- 成本分析：钱花到哪里去了
- 资源优化：哪些钱其实可以不花，或者少花

要让结果可靠，必须同时打通三条链路：

- 账单链路
- 监控链路
- CMDB 归属链路

只有“成本真实 + 利用率真实 + 归属真实”，页面上的优化建议才真正有业务价值。
