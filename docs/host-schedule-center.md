# 主机中心 - 定时任务中心

## 功能概览

定时任务中心是主机中心下的新二级页签，用来把批量主机任务从“手工触发”扩展为“按规则自动触发”。

当前支持：

- `Cron 表达式`：适合夜间巡检、日报采集、固定时间窗口任务
- `固定间隔`：适合周期性指标刷新、轻量巡检、基线采集
- `单次执行`：适合维护窗口、灰度切换前检查、一次性 Playbook

执行模型复用现有主机任务体系：

- `SSH 直连`
- `Ansible 分发`
- `Ansible Playbook 执行`

## 实现思路

定时任务**不会直接在主机上执行命令**，而是在到点时自动生成一条真实的 `HostTask`，再复用当前任务中心已有的执行链路。

这有几个好处：

- 任务历史、终止、重跑、执行明细完全复用
- SSH / Ansible 两条执行链路只维护一套
- 后续做审计、告警、通知时只需要围绕 `HostTask` 扩展

## 后端组成

新增模型：

- `HostTaskSchedule`：定时编排定义
- `HostTaskScheduleExecution`：编排触发记录

新增接口：

- `/api/host-task-schedules/`
- `/api/host-task-schedules/stats/`
- `/api/host-task-schedules/preview_next_runs/`
- `/api/host-task-schedules/{id}/toggle_enabled/`
- `/api/host-task-schedules/{id}/run_now/`
- `/api/host-task-schedule-executions/`

新增调度命令：

```bash
cd backend
python manage.py run_host_task_scheduler
```

支持单次扫描：

```bash
cd backend
python manage.py run_host_task_scheduler --once
```

常用参数：

- `--interval`：轮询间隔秒数
- `--limit`：单轮最多触发多少条编排
- `--actor`：执行记录中的触发人标识

## 权限设计

新增 RBAC 权限：

- `ops.host.schedule.view`
- `ops.host.schedule.manage`
- `ops.host.schedule.execute`

内置角色继承策略：

- `platform-admin`：全部权限
- `ops-admin`：查看 / 管理 / 立即执行
- `developer`：查看
- `read-only`：查看

## 前端设计

主机中心新增页签：

- `任务中心`
- `定时任务`

页签内部分为三块：

- `任务编排`：创建 / 编辑定时编排
- `编排列表`：启停、立即执行、删除
- `执行记录`：查看自动触发与手动触发历史

左侧菜单与主机中心页签顺序统一为：

- `主机资产`
- `任务中心`
- `定时任务`
- `主机申请`

## Demo 数据

`python manage.py seed_data` 已补充示例：

- 生产主机夜间健康巡检
- 核心主机资源指标刷新
- 窗口期 Nginx Playbook 检查

同时会生成对应的触发记录、关联真实任务与执行明细，便于页面直接演示：

- `编排列表` 可直接看到启停状态、下次执行时间、累计执行次数
- `执行记录` 可看到自动调度 / 手动触发两类样例
- `任务中心 -> 任务历史` 可继续查看由定时编排生成的真实任务详情

## 使用建议

- 高频轻量巡检优先用 `固定间隔`
- 批量命令和标准化巡检优先用 `Ansible`
- 高风险变更建议使用 `单次执行 + Playbook`
- 关键任务建议开启 `跳过重叠执行`
