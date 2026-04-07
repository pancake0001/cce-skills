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

> **`vul_status_unhandled` 不是官方漏洞状态**。它是 HSS 查询 API 中用于筛选"待处理漏洞"的操作类型别名，实际返回 `vul_status_unfix` 状态的漏洞集合。

## 2. 工具列表

### HSS 漏洞查询

| 工具 | 功能 |
|------|------|
| `huawei_hss_list_vul_host_hosts` | 查询所有主机的漏洞概览 |
| `huawei_hss_list_host_vuls` | 查询指定主机漏洞详情（分页）|
| `huawei_hss_list_host_vuls_all` | 查询指定主机漏洞（全量自动翻页）|

### HSS 漏洞操作

| 工具 | 功能 |
|------|------|
| `huawei_hss_change_vul_status` | 修改漏洞状态（忽略/修复/验证）|

### CCE 节点操作

| 工具 | 功能 |
|------|------|
| `huawei_cce_node_cordon` | 标记节点不可调度 |
| `huawei_cce_node_uncordon` | 恢复节点可调度 |
| `huawei_cce_node_drain` | 驱逐节点 Pod |
| `huawei_cce_node_status` | 查询节点调度状态 |

### ECS 操作

| 工具 | 功能 |
|------|------|
| `huawei_reboot_ecs` | 重启 ECS 实例 |

## 3. 漏洞修复工作流

```
查询漏洞概览
    ↓
list_vul_host_hosts → 确认有漏洞的主机
    ↓
list_host_vuls (status=unfix) → 获取漏洞列表
    ↓
节点排水：cordon → drain
    ↓
change_vul_status (operate_type=immediate_repair, host_data_list 模式)
    ↓
 reboot 类漏洞？ → reboot_ecs → 等待重启
    ↓
验证：list_host_vuls (status=reboot) == 0
    ↓
恢复调度：uncordon
```

### 关键约束：data_list 与 host_data_list 互斥

`change_vul_status` 请求体中 `data_list`（漏洞视角）和 `host_data_list`（主机视角）**不能同时传递**，同时传递会触发 HSS.0004 错误。

| 场景 | 调用方式 |
|------|---------|
| 主机所有漏洞 | `host_data_list=[HostVulOperateInfo(host_id=..., vul_id_list=[all])]` |
| 指定漏洞跨主机 | `data_list=[VulOperateInfo(vul_id=...) for ...]` |
| 同时传 | ❌ HSS.0004 |
| `data_list=None, host_data_list=None` | ❌ 缺参数 |

## 4. 两套严重度体系

| 来源 | 字段 | 分类依据 |
|------|------|---------|
| `list_vul_host_hosts` → `vul_num_with_repair_priority_list` | `repair_priority` | 修复优先级（High/Medium/Low）— **匹配 Console** |
| `list_host_vuls` | `severity_level` | CVE NVD 官方 CVSS 评分 |

**注意**：两套体系独立，不要混淆。同一漏洞在两套体系中严重度可能不同。

## 5. 错误码速查

| 错误码 | 含义 | 处理建议 |
|--------|------|---------|
| HSS.0002 | 请求参数格式错误 | 检查 operate_type、type 参数 |
| HSS.0004 | 数据库操作失败 | 确认 data_list/host_data_list 未同时传 |
| HSS.0191 | 主机未开启防护 | 先开启 HSS 防护 |
| HSS.1059 | 漏洞状态不允许操作 | 确认漏洞状态是否为 unfix |
| HSS.1060 | 修复失败 | 检查 HSS Agent 状态 |
| HSS.1061 | 漏洞正在修复中 | 等待完成后重试 |

## 6. 其他参考文档

- [节点故障检测策略配置](./CCE_Node_Fault_Detection_Configuration.md)
- [CCE 安全组配置说明](./CCE_Security_Group_Configuration.md)
