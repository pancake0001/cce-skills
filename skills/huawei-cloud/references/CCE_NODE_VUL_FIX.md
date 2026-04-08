# CCE 节点漏洞修复指南

> 📅 **更新：2026-04-08** — 基于 test-cce-ai-diagnose 集群真实修复事故经验更新

---

## 1. 核心教训（必读）

### ⚠️ `immediate_repair` 是异步 API — 这一点至关重要

调用 `change_vul_status(operate_type=immediate_repair)` 后：

1. API **立即返回 200**（请求被接受）
2. 漏洞状态从 `unfix` → `fixing`（修复进行中）
3. HSS Agent 在节点上**异步下载并安装补丁**
4. **对于需要重启的漏洞**，补丁安装完成后状态仍为 `fixing`，**必须重启节点**才能使修复生效，状态才变为 `fixed`

**如果跳过 reboot_ecs：**
- 漏洞状态卡在 `fixing`（看起来"正在修复"）
- 用户以为"已在修复中" → 实际系统根本没修好
- **这是最危险的情况：虚假安全感**

### ⚠️ reboot_ecs 绝对不能跳过

kernel/bpftool/kernel-tools 类漏洞（HCE2-SA-2025-0327 等）：
- 修复方式：`yum update kernel && reboot`
- 补丁安装完成后必须**重启节点**才能使新内核生效
- 重启是漏洞修复的**必要步骤**，不是可选步骤

### ⚠️ 幂等调用行为

`change_vul_status` 是幂等接口：
- 首次调用：返回 200，状态 → `fixing`
- 再次调用（状态仍为 `fixing`）：返回 **HSS.1105**（Unknown error）
- 再次调用（状态已 `fixed`）：返回 200
- **遇到 HSS.1105 ≠ 失败**，说明首次调用已成功触发

---

## 2. 漏洞状态（官方定义）

| 状态值 | 含义 | 说明 |
|--------|------|------|
| `vul_status_unfix` | 未处理 | 漏洞存在，尚未修复 |
| `vul_status_ignored` | 已忽略 | 人工忽略 |
| `vul_status_verified` | 验证中 | 正在验证漏洞 |
| `vul_status_fixing` | 修复中 | ⚠️ **补丁安装中，需重启生效** |
| `vul_status_fixed` | 已修复 | ✅ **已修复（内核漏洞必须重启后才可能变为此状态）** |
| `vul_status_reboot` | 修复待重启 | 补丁已安装，需重启生效 |
| `vul_status_failed` | 修复失败 | 修复执行失败 |
| `vul_status_fix_after_reboot` | 请重启后修复 | 需重启后再次执行修复 |

> **`vul_status_unhandled` 不是官方漏洞状态**，它是"所有漏洞"的别名，实际行为等同于不传 status 参数。过滤未处理漏洞应使用 `vul_status_unfix`。

---

## 3. 完整修复工作流（正确版本）

```
阶段一：信息收集
├── 集群节点列表 → huawei_list_cce_nodes（含 server_id）
├── 节点漏洞概览 → huawei_hss_list_hosts（匹配 server_id）
└── 单节点漏洞详情 → huawei_hss_list_host_vuls_all

阶段二：制定修复计划
├── 确认每个漏洞的修复方式（yum update / reboot）
├── 确认 reboot 类漏洞存在 → reboot_ecs 必须执行
└── 与用户协商确认后再执行

阶段三：逐节点执行（每个节点必须按顺序完成全部步骤）
│
├── 步骤① cordon（标记不可调度）
│   confirm=true
│
├── 步骤② drain（驱逐 Pod）
│   confirm=true
│
├── 步骤③ HSS 触发修复 ← 必须执行
│   huawei_hss_change_vul_status(operate_type=immediate_repair, confirm=true)
│   ⚠️ API 返回 200 ≠ 修复完成
│
├── 步骤④ reboot_ecs ← 绝对不能跳过
│   confirm=true
│   ⚠️ reboot 是 kernel 类漏洞修复的必要步骤
│   ⚠️ 重启期间节点为 NotReady，K8s 会自动感知
│
├── 步骤⑤ 等待节点 Ready
│   huawei_cce_node_status 确认节点状态恢复
│   ⚠️ 必须等待节点 Ready 后才能进入下一步
│
├── 步骤⑥ uncordon（恢复调度）
│   confirm=true
│
└── 步骤⑦ 验证漏洞状态
    huawei_hss_list_host_vuls_all
    ⚠️ 必须在 reboot 后验证，不能在 API 调用后立即验证
    ⚠️ kernel 类漏洞：reboot 后状态应为 fixed
    ⚠️ 如仍为 fixing：可能是 HSS Agent 安装失败，需检查节点日志

阶段四：业务恢复确认
├── 确认业务 Pod 已重建并 Running
└── 如有异常 → 进入"非预期影响应对"流程
```

### 每个步骤跳过的后果

| 步骤 | 跳过后果 |
|------|---------|
| ① cordon | drain 时新 Pod 被调度到该节点，重启时业务中断 |
| ② drain | 业务 Pod 在节点重启时 crash，服务中断 |
| ③ HSS 触发 | 漏洞根本没触发修复 |
| ④ reboot_ecs | **kernel 类漏洞卡在 fixing，用户以为在修，实际没修好** |
| ⑤ 等待 Ready | 节点还没启动完就 uncordon，Pod 调度失败 |
| ⑥ uncordon | 节点永久不可用 |
| ⑦ 验证 | 不知道修复到底成功没有 |

---

## 4. 工具列表

### CCE 节点操作

| 工具 | 功能 | confirm |
|------|------|--------|
| `huawei_cce_node_cordon` | 标记节点不可调度 | ✅ |
| `huawei_cce_node_uncordon` | 恢复节点可调度 | ✅ |
| `huawei_cce_node_drain` | 驱逐节点 Pod（非系统） | ✅ |
| `huawei_cce_node_status` | 查询节点调度状态 | 查询 |

### HSS 漏洞操作

| 工具 | 功能 | confirm |
|------|------|--------|
| `huawei_hss_list_host_vuls_all` | 查询主机漏洞（全量，自动翻页） | 查询 |
| `huawei_hss_list_hosts` | 查询所有主机漏洞概览 | 查询 |
| `huawei_hss_change_vul_status` | 修改漏洞状态（修复/忽略/验证） | ✅ |

### ECS 操作

| 工具 | 功能 | confirm |
|------|------|--------|
| `huawei_reboot_ecs` | 重启 ECS 实例 | ✅ |

---

## 5. 关键约束

### data_list 与 host_data_list 互斥

| 场景 | 调用方式 |
|------|---------|
| 主机所有漏洞 | `host_data_list=[HostVulOperateInfo(host_id=..., vul_id_list=None)]` |
| 指定漏洞列表 | `data_list=[VulOperateInfo(vul_id=...) for ...]` |
| 同时传 | ❌ HSS.0004 |

### confirm 机制

所有变动类操作（cordon/drain/uncordon/reboot/change_vul_status）均需要 `confirm=true` 才真正执行。

---

## 6. 错误码速查

| 错误码 | 含义 | 实际含义与处理 |
|--------|------|--------------|
| HSS.0004 | 数据库操作失败 | data_list 和 host_data_list 不能同时传 |
| HSS.0013 | Insufficient permissions | AK/SK 无 HSS 修复权限，在控制台授权 |
| HSS.0191 | 主机未开启防护 | 先开启 HSS 防护 |
| HSS.1059 | 漏洞状态不允许操作 | 确认漏洞状态为 unfix 才能触发修复 |
| HSS.1060 | 修复失败 | 检查 HSS Agent 状态和节点系统日志 |
| HSS.1061 | 漏洞正在修复中 | 等待修复完成（HSS.1105 也可能同时出现，属正常幂等） |
| **HSS.1105** | **Unknown error** | ⚠️ **不是失败！是幂等回调信号，首次调用已成功，后续调用被拦截** |

---

## 7. 验证要求

### 验证时机

- **错误做法**：API 调用返回 200 后立即验证 → 此时状态可能还是 fixing
- **正确做法**：reboot 后等待 2-3 分钟再验证 → kernel 补丁生效后才能看到 fixed

### 验证判断标准

| 漏洞类型 | 修复成功后状态 |
|---------|--------------|
| 非内核漏洞（bind/openssl/cups等） | `fixed` 或 `unfix`（取决于 HSS Agent 是否完成安装） |
| 内核漏洞（HCE2-SA-2025-0327等） | `fixed`（必须在 reboot 后才能变为 fixed） |

---

## 8. 非预期影响应对

修复过程中如发现业务受影响，按以下顺序处理：

1. **立即 cordon 异常节点**（阻止新 Pod 调度）
2. **检查节点 Pod 状态**：`huawei_get_cce_pods`
3. **扩容新节点**承担当前业务
4. **驱逐异常节点**上的 Pod（drain）
5. **分析根因**：检查 HSS 修复日志、节点系统状态
6. **决策**：继续修复其他节点或暂停本次修复计划

---

## 9. 其他参考

- [节点故障检测策略配置](./CCE_Node_Fault_Detection_Configuration.md)
- [CCE 安全组配置说明](./CCE_Security_Group_Configuration.md)
