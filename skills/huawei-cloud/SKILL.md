# huawei-cloud

Query Huawei Cloud resources and monitoring data via SDK.

## 安全约束 (Security Constraints)

✅ **本技能严格遵守以下安全规则：**

1. **禁止持久化存储认证信息** - 从不将AK/SK、Token、证书等敏感认证信息保存到磁盘文件
2. **禁止长期内存缓存** - AK/SK仅在当前API请求调用过程中存在于内存，调用结束后自动释放
3. **仅项目ID内存缓存** - 仅将非敏感的项目ID缓存在进程内存中（不写入磁盘）
4. **禁止日志泄露** - 不在任何日志、响应输出或错误信息中包含AK/SK等敏感信息
5. **临时文件安全清理** - 如果因API需求创建临时证书文件，使用后立即删除
6. **⚠️ 变动类操作二次确认机制** - 所有删除、扩缩容等危险操作必须携带 `confirm=true` 参数才会真正执行，否则仅返回操作预览和确认提示

AK/SK仅支持以下两种方式使用：
- 通过环境变量 `HUAWEI_AK` / `HUAWEI_SK` 传入（进程级，不保存）
- 通过每次调用参数传入（仅本次调用有效）

---

## 变动类操作二次确认机制

### 需二次确认的操作列表

所有以下变动类操作都强制执行二次确认机制：

| 工具 | 操作类型 | 说明 |
|------|---------|------|
| `huawei_resize_cce_nodepool` | 扩缩容 | 调整节点池节点数量 |
| `huawei_delete_cce_node` | 删除 | 删除集群节点 |
| `huawei_delete_cce_cluster` | 删除 | 删除整个CCE集群 |
| `huawei_scale_cce_workload` | 扩缩容 | 调整Deployment/StatefulSet副本数 |
| `huawei_delete_cce_workload` | 删除 | 删除工作负载（Deployment/StatefulSet） |

### 工作流程

⚠️ **所有操作默认不会执行，需要两步确认：**

**第一步：预览操作** - 不带 `confirm` 参数调用
```bash
# 示例：预览删除工作负载
python3 huawei-cloud.py huawei_delete_cce_workload \
  region=cn-north-4 \
  cluster_id=xxx \
  workload_type=deployment \
  name=my-app \
  namespace=default
```

返回：操作预览、警告提示、确认示例

**第二步：确认执行** - 携带 `confirm=true` 参数再次调用
```bash
# 示例：确认并执行删除
python3 huawei-cloud.py huawei_delete_cce_workload \
  region=cn-north-4 \
  cluster_id=xxx \
  workload_type=deployment \
  name=my-app \
  namespace=default \
  confirm=true
```

### 安全特性

- ❌ **未带 confirm 参数时**：操作不执行，仅返回预览和警告
- ✅ **携带 confirm=true 时**：操作才真正执行
- 📝 **返回清晰的提示**：包含警告信息、操作说明和确认示例
- ⏱️ **代码级验证**：函数内部强制校验 confirm 参数

## When to use
- User wants to query Huawei Cloud ECS instances
- User needs to get monitoring metrics (CPU, memory, network, etc.)
- User wants to list VPC networks or available ECS flavors
- User wants to query CCE cluster information (nodes, pods, deployments, etc.)

## Setup

### Option 1: Environment Variables (Recommended)
Set your Huawei Cloud credentials as environment variables:
```bash
export HUAWEI_AK="your-access-key-id"
export HUAWEI_SK="your-secret-access-key"
```

### Option 2: Pass as Parameters
Pass AK/SK directly in each API call (less secure, not recommended for production).

### Dependencies
The following Python packages are required:
```bash
pip install huaweicloudsdkcore huaweicloudsdkecs huaweicloudsdkvpc huaweicloudsdkces huaweicloudsdkcce huaweicloudsdkiam huaweicloudsdkevs huaweicloudsdkelb
```

## 工具分类

工具按云服务分类组织如下：

---

### 🖥️ ECS 弹性云服务器

| 工具 | 功能 |
|------|------|
| `huawei_list_ecs` | 查询区域内所有ECS实例列表 |
| `huawei_get_ecs_metrics` | 获取指定ECS实例的监控数据（CPU/内存/磁盘/网络） |
| `huawei_list_flavors` | 查询区域内可用的ECS实例规格 |

**参数说明：**
- `region` (required): 华为云区域 (e.g., cn-north-4, cn-east-3)
- `instance_id` (required for metrics): ECS实例ID
- `project_id` (optional): 项目ID
- `ak`/`sk` (optional): 认证信息，默认从环境变量读取

**返回监控数据粒度：** 过去1小时，5分钟间隔

---

### 💿 EVS 弹性云硬盘

| 工具 | 功能 |
|------|------|
| `huawei_list_evs` | 查询区域内所有EVS云硬盘列表 |
| `huawei_get_evs_metrics` | 获取指定EVS硬盘的监控数据 |

**监控指标：** 读/写带宽、读/写IOPS、读写延迟

---

### 🌐 VPC 虚拟私有云

| 工具 | 功能 |
|------|------|
| `huawei_list_vpc` | 查询区域内所有VPC网络列表 |
| `huawei_list_vpc_subnets` | 查询VPC子网列表 |
| `huawei_list_security_groups` | 查询安全组列表（可按VPC过滤） |
| `huawei_list_vpc_acls` | 查询VPC网络ACL列表 |
| `huawei_list_nat` | 查询NAT网关列表 |

---

### 📁 SFS 文件存储

| 工具 | 功能 |
|------|------|
| `huawei_list_sfs` | 查询弹性文件存储SFS列表 |
| `huawei_list_sfs_turbo` | 查询弹性文件存储SFS Turbo列表 |

---

### ⚖️ ELB 弹性负载均衡

| 工具 | 功能 |
|------|------|
| `huawei_list_elb` | 查询区域内所有ELB负载均衡器列表 |
| `huawei_list_elb_listeners` | 查询指定负载均衡器的监听器列表 |
| `huawei_get_elb_metrics` | 获取指定ELB的监控数据（连接数、吞吐量） |

---

### 📶 EIP 弹性公网IP

| 工具 | 功能 |
|------|------|
| `huawei_list_eip` | 查询区域内所有EIP弹性公网IP列表 |
| `huawei_get_eip_metrics` | 获取指定EIP的带宽流量监控 |

---

### ☸️ CCE 云容器引擎

#### 集群基础信息查询

| 工具 | 功能 |
|------|------|
| `huawei_list_cce_clusters` | 查询区域内所有CCE集群列表 |
| `huawei_list_cce_addons` | 查询集群内所有插件（addons）列表 |
| `huawei_get_cce_namespaces` | 查询集群内所有命名空间 |
| `huawei_list_cce_configmaps` | 查询集群内ConfigMap列表 |
| `huawei_list_cce_secrets` | 查询集群内Secret列表 |
| `huawei_get_cce_kubeconfig` | 获取集群kubeconfig配置 |
| `huawei_get_kubernetes_nodes` | 获取Kubernetes节点信息 |

#### 节点管理

| 工具 | 功能 |
|------|------|
| `huawei_list_cce_nodes` | 查询集群内所有节点列表 |
| `huawei_get_cce_nodes` | 获取指定节点详细信息 |
| `huawei_list_cce_nodepools` | 查询集群内所有节点池列表 |
| `huawei_resize_cce_nodepool` | 调整节点池节点数量（扩缩容） |
| `huawei_delete_cce_node` | 从集群删除指定节点 |
| `huawei_delete_cce_cluster` | 删除整个CCE集群 |

#### 工作负载与资源

| 工具 | 功能 |
|------|------|
| `huawei_get_cce_pods` | 查询集群内Pod列表 |
| `huawei_get_cce_deployments` | 查询集群内Deployment列表 |
| `huawei_scale_cce_workload` | 扩缩容Deployment/StatefulSet工作负载副本数 |
| `huawei_get_cce_services` | 查询集群内Service列表 |
| `huawei_get_cce_ingresses` | 查询集群内Ingress列表 |
| `huawei_get_cce_events` | 查询集群事件列表 |
| `huawei_get_cce_pvcs` | 查询PVC列表 |
| `huawei_get_cce_pvs` | 查询PV列表 |
| `huawei_delete_cce_workload` | 删除工作负载（Deployment/StatefulSet） |

#### 监控分析

| 工具 | 功能 |
|------|------|
| `huawei_get_cce_pod_metrics` | 获取Pod CPU/内存使用率 Top N |
| `huawei_get_cce_node_metrics` | 获取节点 CPU/内存/磁盘使用率 Top N |

#### 集群日志查询

| 工具 | 功能 |
|------|------|
| `huawei_get_cce_logconfigs` | 从CCE集群获取LogConfig自定义资源（CR），返回应用与日志流的关联关系 |
| `huawei_get_application_log_stream` | 根据namespace和应用名获取对应的日志组和日志流 |

#### 集群巡检

| 工具 | 模式 | 功能 |
|------|------|------|
| `huawei_cce_cluster_inspection` | 串行 | 执行CCE集群完整巡检（8项检查） |
| `huawei_cce_cluster_inspection_parallel` | 并行 ⚡ | 多线程并行巡检，速度提升3-5倍 |
| `huawei_cce_cluster_inspection_subagent` | Subagent 🚀 | Subagent分布式并行巡检 |
| `huawei_cce_cluster_inspection_subagent_legacy` | Subagent (legacy) | 旧版Subagent分布式并行巡检 |
| `huawei_aggregate_inspection_results` | 结果汇总 | 汇总Subagent巡检结果 |
| `huawei_export_inspection_report` | 报告生成 | 导出HTML格式完整巡检报告 |

**8大检查项（可独立调用）：**
| 工具 | 功能 |
|------|------|
| `huawei_pod_status_inspection` | Pod状态巡检（异常状态、容器重启次数） |
| `huawei_addon_pod_monitoring_inspection` | 系统插件Pod监控（kube-system/monitoring） |
| `huawei_biz_pod_monitoring_inspection` | 业务Pod监控 |
| `huawei_node_status_inspection` | Node状态巡检（节点健康度） |
| `huawei_node_resource_inspection` | 节点资源使用率巡检 |
| `huawei_event_inspection` | 集群关键事件巡检 |
| `huawei_aom_alarm_inspection` | AOM活跃告警巡检 |
| `huawei_elb_monitoring_inspection` | ELB负载均衡监控巡检 |

---

### 📊 AOM 应用运维管理

| 工具 | 功能 |
|------|------|
| `huawei_list_aom_instances` | 查询AOM实例列表 |
| `huawei_get_aom_metrics` | 使用PromQL查询AOM监控指标 |
| `huawei_list_aom_alerts` | 查询AOM告警列表 |
| `huawei_list_aom_current_alarms` | 查询当前活跃告警 |
| `huawei_list_aom_alarm_rules` | 查询AOM告警规则列表 |
| `huawei_list_aom_action_rules` | 查询AOM动作规则列表 |
| `huawei_list_aom_mute_rules` | 查询AOM静默规则列表 |
| `huawei_query_aom_logs` | 按命名空间/Pod过滤查询AOM应用日志 |
| `huawei_aom_alarm_inspection` | AOM活跃告警巡检 |

---

### 📝 LTS 日志服务 (Log Tank Service)

| 工具 | 功能 |
|------|------|
| `huawei_list_log_groups` | 查询日志组列表 |
| `huawei_list_log_streams` | 查询日志流列表（可按日志组过滤） |
| `huawei_query_logs` | 按时间范围/关键词查询日志内容 |
| `huawei_get_recent_logs` | 查询最近N小时的日志 |

**查询示例：**
```bash
# 查询日志组列表（北京四）
python3 huawei-cloud.py huawei_list_log_groups region=cn-north-4

# 查询指定日志组的日志流
python3 huawei-cloud.py huawei_list_log_streams region=cn-north-4 log_group_id=xxx

# 按关键词查询最近1小时日志
python3 huawei-cloud.py huawei_query_logs \
  region=cn-north-4 \
  log_group_id=xxx \
  log_stream_id=xxx \
  keywords=ERROR
```

---

### 🏢 IAM 项目管理

| 工具 | 功能 |
|------|------|
| `huawei_list_projects` | 列出账号下所有项目 |
| `huawei_get_project_by_region` | 根据区域获取项目ID |
| `huawei_list_supported_regions` | 列出所有支持的区域 |

---

## 支持区域

| 区域代码 | 区域名称 |
|----------|----------|
| cn-north-4 | 华北-北京四 |
| cn-north-1 | 华北-北京一 |
| cn-north-2 | 华北-北京二 |
| cn-east-3 | 华东-上海一 |
| cn-south-1 | 华南-广州 |
| cn-south-2 | 华南-广州友好 |
| cn-east-4 | 华东-华东二 |
| cn-southwest-2 | 贵阳一 |
| ap-southeast-1 | 亚太-香港 |
| ap-southeast-2 | 亚太-曼谷 |
| ap-southeast-3 | 亚太-新加坡 |

## 使用示例

```bash
# 查询北京四所有ECS实例
python3 huawei-cloud.py huawei_list_ecs region=cn-north-4

# 查询北京四所有CCE集群
python3 huawei-cloud.py huawei_list_cce_clusters region=cn-north-4

# 扩缩容工作负载
python3 huawei-cloud.py huawei_scale_cce_workload region=cn-north-4 cluster_id=xxx workload_type=Deployment name=nginx namespace=default replicas=3

# CCE集群并行巡检
python3 huawei-cloud.py huawei_cce_cluster_inspection_parallel region=cn-north-4 cluster_id=xxx

# 查询LTS日志组列表
python3 huawei-cloud.py huawei_list_log_groups region=cn-north-4

# 获取项目ID
python3 huawei-cloud.py huawei_get_project_by_region region=cn-north-4
```

## Notes
- Ensure your AK/SK has proper IAM permissions for the requested resources
- Different regions may have different resource availability
- Monitoring data may have a few minutes delay
- Some metrics may not be available for all instance types
- CCE cluster operations require appropriate Kubernetes RBAC permissions

## References
- [CCE安全组配置说明](./references/CCE_Security_Group_Configuration.md)
