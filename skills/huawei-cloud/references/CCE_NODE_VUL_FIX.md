# CCE 节点漏洞修复指南

## 1. 漏洞状态（官方定义）

来源：[ShowVulReportData —华为云 HSS API](https://support.huaweicloud.com/api-hss2.0/ShowVulReportData.html)

| 状态值 | 含义 | 说明 |
|--------|------|------|
| `vul_status_unfix` | 未处理 | 漏洞存在，尚未修复 |
| `vul_status_ignored` | 已忽略 | 人工忽略 |
| `vul_status_verified` | 验证中 | 正在验证漏洞 |
| `vul_status_fixing` | 修复中 | 修复进行中 |
| `vul_status_fixed` | 已修复 | 已修复 |
| `vul_status_reboot` | 修复待重启 | 补丁已下载，需重启生效 |
| `vul_status_failed` | 修复失败 | 修复执行失败 |
| `vul_status_fix_after_reboot` | 请重启后修复 | 需重启后再次执行修复 |

> **`vul_status_unhandled` 不是官方漏洞状态**，它是"所有漏洞"的别名，实际行为等同于不传 status 参数。过滤未处理漏洞应使用 `vul_status_unfix`。

## 2. 工具列表

### HSS 漏洞查询

| 工具 | 功能 |
|------|------|
| `huawei_hss_list_vul_host_hosts` | 查询所有主机的漏洞概览 |
| `huawei_hss_list_host_vuls` | 查询指定主机漏洞详情（分页）|
| `huawei_hss_list_host_vuls_all` | 查询指定主机漏洞（全量自动翻页）|

### HSS 漏洞操作（均需 confirm）

| 工具 | 功能 |
|------|------|
| `huawei_hss_change_vul_status` | 修改漏洞状态（忽略/修复/验证），confirm=true 执行 |

### CCE 节点操作（均需 confirm）

| 工具 | 功能 |
|------|------|
| `huawei_cce_node_cordon` | 标记节点不可调度（confirm=true） |
| `huawei_cce_node_uncordon` | 恢复节点可调度（confirm=true） |
| `huawei_cce_node_drain` | 驱逐节点 Pod（confirm=true） |
| `huawei_cce_node_status` | 查询节点调度状态（仅查询） |

### ECS 操作（均需 confirm）

| 工具 | 功能 |
|------|------|
| `huawei_reboot_ecs` | 重启 ECS 实例（confirm=true） |

## 3. 漏洞修复完整工作流

```
阶段一：信息收集
├── 集群节点列表 → list_cce_cluster_nodes
├── 节点漏洞概览 → huawei_hss_list_vul_host_hosts（匹配 server_id）
└── 单节点漏洞详情 → huawei_hss_list_host_vuls_all

阶段二：制定修复计划 ← 【执行前必须输出完整计划】
├── 评估是否涉及重启（reboot 类漏洞）
├── 评估漏洞修复优先级（High/Medium/Low）
├── 确定并发度（单节点还是批量）
├── 制定分批策略（节点排序、分批顺序）
└── 与用户协商确认后再执行

阶段三：执行修复（按批次顺序执行）
├── 前置检查：节点状态、Pod 分布、业务影响评估
├── 节点排水：cordon → drain（confirm=true）
├── 漏洞修复：change_vul_status（confirm=true）
├── 重启（如有 reboot 类漏洞）：reboot_ecs（confirm=true）
└── 恢复调度：uncordon（confirm=true）

阶段四：验证与巡检
├── 漏洞状态验证：list_host_vuls（reboot 类漏洞应为 0）
├── 节点健康检查：node_status_inspection
├── 业务 Pod 可用性检查：pod_status_inspection
└── 如发现非预期影响 → 扩容新节点 + 隔离异常节点
```

## 4. 修复计划模板

执行前必须提供以下格式的计划并获用户确认：

```markdown
# 漏洞修复执行计划

## 基本信息
- 集群：<cluster_id>
- 节点数：<N> 台
- 漏洞总数：<X>（High: <H> / Medium: <M> / Low: <L>）

## 修复范围
| 节点 | IP | 漏洞数 | 高危 | 重启类 | 修复优先级 |
|------|-----|--------|------|--------|----------|
| node-1 | x.x.x.1 | 10 | 2 | 是 | P0 |
| node-2 | x.x.x.2 | 5 | 0 | 否 | P1 |

## 是否涉及重启
- 是/否
- 原因：<具体漏洞名，如 USN-8096-1 需要重启生效>

## 分批策略
- 批次1：node-1（高危，2台高危漏洞）
- 批次2：node-2、node-3（可并行）
- ...

## 并发度
- 本次修复并发度：1（逐节点执行，避免影响业务）

## 业务影响评估
- cordon 后节点不可调度，存量 Pod 不受影响
- drain 会驱逐非系统 Pod，请确认业务副本数 > 1

## 回退预案
- 如修复后节点异常，优先扩容新节点承载流量
- 隔离异常节点：cordon + drain + 从集群移除

## 确认执行
请回复「确认执行」开始漏洞修复。
```

## 5. 关键约束

### data_list 与 host_data_list 互斥

`change_vul_status` 请求体中两者**不能同时传递**，同时传递触发 HSS.0004：

| 场景 | 调用方式 |
|------|---------|
| 主机所有漏洞 | `host_data_list=[HostVulOperateInfo(host_id=..., vul_id_list=None)]` |
| 指定漏洞列表 | `data_list=[VulOperateInfo(vul_id=...) for ...]` |
| 同时传 | ❌ HSS.0004 |

> `host_ids` 参数传入时自动使用 `host_data_list`，`vul_ids` 参数传入时自动使用 `data_list`。

### confirm 机制

所有变动类操作（cordon/drain/uncordon/reboot/change_vul_status）均需要 `confirm=true` 才真正执行，否则仅返回预览。

## 6. 两套严重度体系

| 来源 | 字段 | 分类依据 | 说明 |
|------|------|---------|------|
| `list_vul_host_hosts` → `vul_num_with_repair_priority_list` | `repair_priority` | 修复优先级 | **匹配 Console 显示**，用于判断是否紧急 |
| `list_host_vuls` | `severity_level` | CVE NVD CVSS | 官方严重度，用于分批排序 |

**High/Priority 排序参考**：优先处理 High + reboot 类漏洞的节点。

## 7. 错误码速查

| 错误码 | 含义 | 处理建议 |
|--------|------|---------|
| HSS.0004 | 数据库操作失败 | 确认 data_list/host_data_list 未同时传 |
| HSS.0191 | 主机未开启防护 | 先开启 HSS 防护 |
| HSS.1059 | 漏洞状态不允许操作 | 使用 list_host_vuls 确认状态为 unfix |
| HSS.1060 | 修复失败 | 检查 HSS Agent 状态 |
| HSS.1061 | 漏洞正在修复中 | 等待完成后重试 |

## 8. 非预期影响应对

修复过程中如发现业务受影响，按以下顺序处理：

1. **立即 cordon 异常节点**（阻止新 Pod 调度）
2. **检查节点 Pod 状态**：`huawei_pod_status_inspection`
3. **扩容新节点**承担当前业务（cce_node_add）
4. **驱逐异常节点**上的 Pod（drain）
5. **分析根因**：检查 HSS 修复日志、节点系统状态
6. **决策**：继续修复其他节点或暂停本次修复计划

## 9. 其他参考

- [节点故障检测策略配置](./CCE_Node_Fault_Detection_Configuration.md)
- [CCE 安全组配置说明](./CCE_Security_Group_Configuration.md)
