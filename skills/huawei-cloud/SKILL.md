# huawei-cloud

Query Huawei Cloud resources and monitoring data via SDK.

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

## Tools

### ECS Management

#### huawei_list_ecs
List all ECS instances in a specified region.

Parameters:
- region (required): Huawei Cloud region (e.g., cn-north-4, cn-east-3)
- project_id (optional): Project ID
- ak (optional): Access Key ID, defaults to HUAWEI_AK env
- sk (optional): Secret Access Key, defaults to HUAWEI_SK env
- limit (optional): Limit number of results
- offset (optional): Pagination offset

Returns: List of ECS instances with ID, name, status, IP addresses, flavor info.

#### huawei_get_ecs_metrics
Get monitoring metrics for a specific ECS instance.

Parameters:
- region (required): Huawei Cloud region
- instance_id (required): ECS instance ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Monitoring metrics including:
- cpu_util (CPU usage %)
- mem_util (Memory usage %)
- disk_util (Disk usage %)
- network_incoming_bytes_rate (Network inbound)
- network_outgoing_bytes_rate (Network outbound)
- disk_read_bytes_rate (Disk read)
- disk_write_bytes_rate (Disk write)

Data covers past 1 hour with 5-minute granularity.

### VPC & Network

#### huawei_list_vpc
List all VPC networks in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- limit (optional): Limit number of results

Returns: List of VPCs with ID, name, CIDR, status.

#### huawei_list_security_groups
List all security groups in a specified region.

Parameters:
- region (required): Huawei Cloud region
- vpc_id (optional): Filter by VPC ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of security groups with ID, name, description, etc.

#### huawei_list_vpc_acls
List all VPC network ACLs in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of VPC ACLs with ID, name, status.

### ECS Flavors

#### huawei_list_flavors
List available ECS instance types (flavors) in a region.

Parameters:
- region (required): Huawei Cloud region
- az (optional): Availability zone
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of available instance types with vCPUs, RAM, disk info.

### EVS (Cloud Disk)

#### huawei_list_evs
List all EVS volumes in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of EVS volumes with ID, name, status, size, volume_type.

#### huawei_get_evs_metrics
Get monitoring metrics for a specific EVS volume.

Parameters:
- region (required): Huawei Cloud region
- volume_id (required): EVS volume ID
- instance_id (optional): ECS instance ID (for attached volumes)
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: EVS volume metrics including:
- read_bytes_rate (Disk read bandwidth)
- write_bytes_rate (Disk write bandwidth)
- read_requests_rate (Read IOPS)
- write_requests_rate (Write IOPS)
- read_latency (Read latency)
- write_latency (Write latency)

Data covers past 1 hour with 5-minute granularity.

### ELB (Load Balancer)

#### huawei_list_elb
List all ELB load balancers in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of ELB instances with ID, name, type, status, VIP.

#### huawei_list_elb_listeners
List all ELB listeners for a specific load balancer.

Parameters:
- region (required): Huawei Cloud region
- loadbalancer_id (required): ELB instance ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of ELB listeners with port, protocol, backend_group.

#### huawei_get_elb_metrics
Get monitoring metrics for a specific ELB instance.

Parameters:
- region (required): Huawei Cloud region
- loadbalancer_id (required): ELB instance ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: ELB metrics including connections, throughput, etc.

### EIP (Elastic IP)

#### huawei_list_eip
List all EIP resources in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of EIPs with ID, public IP, status, bandwidth.

#### huawei_get_eip_metrics
Get monitoring metrics for a specific EIP.

Parameters:
- region (required): Huawei Cloud region
- eip_id (required): EIP ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: EIP metrics including bandwidth, traffic.

### CCE (Cloud Container Engine)

#### huawei_list_cce_clusters
List all CCE clusters in a specified region.

Parameters:
- region (required): Huawei Cloud region
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of CCE clusters with ID, name, status, version.

#### huawei_get_cce_nodes
Get detailed node information for a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Detailed node information including conditions, capacity.

#### huawei_list_cce_nodes
List all nodes in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- limit (optional): Limit
- offset (optional): Offset

Returns: List of nodes with ID, name, status, flavor.

#### huawei_list_cce_nodepools
List all node pools in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of node pools with ID, name, flavor, node count.

#### huawei_list_cce_addons
List all addons (plugins) in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of addons with name, version, status, description.

#### huawei_get_cce_namespaces
List all namespaces in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of namespaces.

#### huawei_get_cce_pods
List all pods in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- namespace (optional): Kubernetes namespace
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of pods with name, status, IP, node.

#### huawei_get_cce_deployments
List all deployments in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- namespace (optional): Kubernetes namespace
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of deployments with name, replicas, available.

#### huawei_get_cce_events
List events in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- namespace (optional): Kubernetes namespace
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of events with type, reason, message.

#### huawei_get_cce_pvcs
List PersistentVolumeClaims in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- namespace (optional): Kubernetes namespace
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of PVCs with name, status, capacity.

#### huawei_get_cce_pvs
List PersistentVolumes in a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: List of PVs with name, capacity, status.

#### huawei_get_cce_services
获取 CCE 集群内的 Service 列表。

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- namespace (optional): Kubernetes 命名空间 (默认所有命名空间)
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns:
```json
{
  "success": true,
  "count": 10,
  "services": [
    {
      "name": "nginx-service",
      "namespace": "default",
      "type": "LoadBalancer",
      "cluster_ip": "10.247.0.1",
      "load_balancer_ip": "1.2.3.4",
      "load_balancer_ingress": [{"ip": "1.2.3.4", "hostname": ""}],
      "ports": [
        {"name": "http", "protocol": "TCP", "port": 80, "target_port": 8080, "node_port": 30080}
      ],
      "selector": {"app": "nginx"},
      "labels": {},
      "annotations": {}
    }
  ]
}
```

Service 类型说明:
- ClusterIP: 仅集群内部访问
- NodePort: 通过节点端口暴露服务
- LoadBalancer: 通过负载均衡器暴露服务
- ExternalName: 映射到外部 DNS 名称

#### huawei_get_cce_ingresses
获取 CCE 集群内的 Ingress 列表。

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- namespace (optional): Kubernetes 命名空间 (默认所有命名空间)
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns:
```json
{
  "success": true,
  "count": 5,
  "ingresses": [
    {
      "name": "nginx-ingress",
      "namespace": "default",
      "ingress_class_name": "nginx",
      "rules": [
        {
          "host": "example.com",
          "paths": [
            {
              "path": "/",
              "path_type": "Prefix",
              "backend": {
                "service_name": "nginx-service",
                "service_port": 80
              }
            }
          ]
        }
      ],
      "tls": [
        {
          "hosts": ["example.com"],
          "secret_name": "example-tls"
        }
      ],
      "load_balancer_ingress": [
        {"ip": "1.2.3.4", "hostname": ""}
      ],
      "labels": {},
      "annotations": {}
    }
  ]
}
```

#### huawei_get_cce_pod_metrics
获取 CCE 集群 Pod 监控数据（CPU/内存使用率 Top N）。

自动获取 AOM 实例并执行 Pod CPU/内存监控查询，返回 Top N 数据。

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- namespace (optional): 命名空间过滤 (默认所有命名空间)
- label_selector (optional): Pod 标签选择器 (格式: "app=nginx,version=v1")
- top_n (optional): 返回 Top N 数据 (默认 10)
- hours (optional): 查询时间范围（小时）(默认 1)
- cpu_query (optional): 自定义 CPU PromQL
- memory_query (optional): 自定义内存 PromQL
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

**label_selector 使用说明**:
- 格式: `key1=value1,key2=value2` (多个条件用逗号分隔，需全部匹配)
- 示例: `app=nginx` 或 `app=nginx,tier=frontend`
- 使用 label_selector 时会先通过 Kubernetes API 获取匹配的 Pod 列表，再查询监控数据

默认 PromQL:
- CPU 使用率: `topk(N, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!=""}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu"}) * 100)`
- 内存使用率: `topk(N, sum by (pod, namespace) (container_memory_working_set_bytes{image!=""}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory"}) * 100)`

调用示例:
```bash
# 获取所有 Pod 监控 Top 10
python3 huawei-cloud.py huawei_get_cce_pod_metrics region=cn-north-4 cluster_id=xxx top_n=10 ak=xxx sk=xxx

# 按 namespace 过滤
python3 huawei-cloud.py huawei_get_cce_pod_metrics region=cn-north-4 cluster_id=xxx namespace=default ak=xxx sk=xxx

# 按 label 过滤
python3 huawei-cloud.py huawei_get_cce_pod_metrics region=cn-north-4 cluster_id=xxx label_selector="app=online-users" ak=xxx sk=xxx

# 组合过滤
python3 huawei-cloud.py huawei_get_cce_pod_metrics region=cn-north-4 cluster_id=xxx namespace=default label_selector="app=nginx,tier=frontend" top_n=5 ak=xxx sk=xxx
```

Returns:
```json
{
  "success": true,
  "cluster_name": "test-cce-ai-diagnose",
  "aom_instance_id": "xxx",
  "inspection_time": "2026-03-24 10:53:00",
  "query_params": {
    "top_n": 10,
    "hours": 1,
    "namespace": null,
    "label_selector": "app=nginx"
  },
  "label_filter": {
    "selector": "app=nginx",
    "matched_count": 3,
    "matched_pods": [
      {"name": "nginx-xxx", "namespace": "default", "labels": {"app": "nginx"}, "status": "Running", "node": "192.168.1.1"}
    ]
  },
  "promql": {
    "cpu": "...",
    "memory": "..."
  },
  "metrics": {
    "cpu_top_n": [
      {"pod": "nginx-xxx", "namespace": "default", "cpu_usage_percent": 95.2, "status": "critical"}
    ],
    "memory_top_n": [
      {"pod": "nginx-xxx", "namespace": "default", "memory_usage_percent": 22.5, "status": "normal"}
    ],
    "all_pods": [...]
  },
  "summary": {
    "total_pods": 3,
    "critical_cpu": 1,
    "critical_memory": 0,
    "warning_cpu": 0,
    "warning_memory": 0
  }
}
```

状态判定:
- critical: 使用率 > 80%
- warning: 使用率 > 50%
- normal: 使用率 <= 50%

#### huawei_get_cce_node_metrics
获取 CCE 集群节点监控数据（CPU/内存/磁盘使用率 Top N）。

自动获取 AOM 实例并执行节点 CPU/内存/磁盘监控查询，返回 Top N 数据。

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- top_n (optional): 返回 Top N 数据 (默认 10)
- hours (optional): 查询时间范围（小时）(默认 1)
- cpu_query (optional): 自定义 CPU PromQL
- memory_query (optional): 自定义内存 PromQL
- disk_query (optional): 自定义磁盘 PromQL
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

默认 PromQL:
- CPU 使用率: `topk(N, 100 - (avg by (instance) (irate(node_cpu_seconds_total{mode='idle'}[5m])) * 100))`
- 内存使用率: `topk(N, avg by (instance) ((1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100)`
- 磁盘使用率: `topk(N, avg by (instance) ((1 - node_filesystem_avail_bytes{mountpoint='/'} / node_filesystem_size_bytes)) * 100)`

调用示例:
```bash
# 获取节点监控 Top 10
python3 huawei-cloud.py huawei_get_cce_node_metrics region=cn-north-4 cluster_id=xxx top_n=10 ak=xxx sk=xxx

# 自定义时间范围
python3 huawei-cloud.py huawei_get_cce_node_metrics region=cn-north-4 cluster_id=xxx hours=6 top_n=5 ak=xxx sk=xxx
```

Returns:
```json
{
  "success": true,
  "cluster_name": "test-cce-ai-diagnose",
  "aom_instance_id": "xxx",
  "inspection_time": "2026-03-24 11:10:00",
  "query_params": {
    "top_n": 10,
    "hours": 1
  },
  "promql": {
    "cpu": "...",
    "memory": "...",
    "disk": "..."
  },
  "metrics": {
    "cpu_top_n": [
      {"instance": "192.168.32.1:9100", "node_ip": "192.168.32.1", "node_name": "node-xxx", "cpu_usage_percent": 85.5, "status": "critical"}
    ],
    "memory_top_n": [
      {"instance": "192.168.32.2:9100", "node_ip": "192.168.32.2", "node_name": "node-yyy", "memory_usage_percent": 72.3, "status": "warning"}
    ],
    "disk_top_n": [
      {"instance": "192.168.32.1:9100", "node_ip": "192.168.32.1", "node_name": "node-xxx", "disk_usage_percent": 45.2, "status": "normal"}
    ],
    "all_nodes": [...]
  },
  "summary": {
    "total_nodes": 4,
    "critical_cpu": 1,
    "critical_memory": 0,
    "critical_disk": 0,
    "warning_cpu": 0,
    "warning_memory": 1,
    "warning_disk": 0
  }
}
```

状态判定:
- critical: 使用率 > 80%
- warning: 使用率 > 50%
- normal: 使用率 <= 50%

#### huawei_cce_cluster_inspection
CCE 集群巡检工具，执行 **7 大检查项**并返回巡检结果。

检查项:
1. **Pod状态巡检** - 检查Pod运行状态、重启次数、异常状态
2. **Node状态巡检** - 检查节点状态、Ready/NotReady数量
3. **集群Pod监控巡检** - 检查CPU/内存使用率>80%的Pod数量及Top 10
4. **节点资源监控巡检** - 检查CPU/内存/磁盘使用率>80%的节点数量及Top 10
5. **Event巡检** - 检查关键事件和Warning事件
6. **AOM告警巡检** - 检查活跃告警和严重级别
7. **ELB负载均衡监控巡检** - 检查LoadBalancer类型Service的ELB监控数据（连接数、带宽）

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns:
```json
{
  "success": true,
  "cluster_id": "xxx",
  "inspection_time": "2026-03-24 14:32:00",
  "result": {
    "status": "CRITICAL",
    "total_issues": 20,
    "critical_issues": 2,
    "warning_issues": 18
  },
  "checks": {
    "pods": {...},
    "nodes": {...},
    "pod_monitoring": {...},
    "node_monitoring": {...},
    "events": {...},
    "alarms": {...},
    "elb_monitoring": {
      "name": "ELB负载均衡监控巡检",
      "status": "PASS",
      "checked": true,
      "total_loadbalancers": 2,
      "loadbalancer_services": [
        {
          "service_name": "nginx-service",
          "namespace": "default",
          "elb_id": "xxx-xxx-xxx",
          "elb_ip": "1.2.3.4",
          "ports": [...]
        }
      ],
      "elb_metrics": [
        {
          "service_name": "nginx-service",
          "namespace": "default",
          "elb_id": "xxx",
          "connection_num": 1000,
          "in_bandwidth_bps": 10000000,
          "qps": 100
        }
      ],
      "high_connection_elbs": [],
      "high_bandwidth_elbs": []
    }
  },
  "issues": [...],
  "report": "文本格式报告",
  "html_report": "HTML格式网页报告"
}
```

#### huawei_export_inspection_report
生成并导出 HTML 格式的集群巡检报告。

自动执行集群巡检并生成网页版报告文件，包含详细的巡检结果和问题解决建议。

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE 集群 ID
- output_file (optional): HTML报告输出路径 (默认: /tmp/cce_inspection_report_{cluster_id}.html)
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns:
```json
{
  "success": true,
  "message": "HTML巡检报告已生成",
  "file": "/tmp/cce_inspection_report.html",
  "cluster_id": "034b98c7-1c4d-11f1-842d-0255ac100249",
  "inspection_time": "2026-03-24 14:15:59",
  "status": "CRITICAL"
}
```

调用示例:
```bash
# 生成HTML巡检报告
python3 huawei-cloud.py huawei_export_inspection_report \
  region=cn-north-4 \
  cluster_id=034b98c7-1c4d-11f1-842d-0255ac100249 \
  output_file=/tmp/my_report.html \
  ak=xxx sk=xxx
```

HTML报告内容包括:
- 巡检概览和状态汇总
- 6大巡检项详细结果
- 问题列表和严重程度
- 每个问题的解决建议
- 可视化进度条和状态标签

### 独立巡检工具

以下工具可单独调用，用于执行特定的巡检任务：

#### huawei_pod_status_inspection
Pod状态巡检。检查Pod运行状态、容器重启次数、异常状态识别。

检查内容：
- Pod 运行状态统计 (Running/Pending/Failed)
- 容器重启次数检查 (>=5次为CRITICAL，>=2次为WARNING)
- 异常状态识别 (CrashLoopBackOff、ImagePullBackOff、OOMKilled、Evicted等)

Parameters:
- region (required): 华为云区域 (如 cn-north-4)
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "Pod状态巡检",
    "status": "PASS/WARN/FAIL",
    "checked": true,
    "total": 50,
    "running": 48,
    "pending": 1,
    "failed": 1,
    "restart_pods": [
      {"pod": "nginx-xxx", "namespace": "default", "container": "nginx", "restart_count": 5, "node": "192.168.1.1"}
    ],
    "abnormal_pods": [
      {"pod": "app-xxx", "namespace": "default", "status": "Failed", "reason": "OOMKilled", "node": "192.168.1.2"}
    ],
    "abnormal_summary": {"OOMKilled": ["app-xxx"], "CrashLoopBackOff": ["web-yyy"]}
  },
  "issues": [...]
}
```

#### huawei_addon_pod_monitoring_inspection
插件Pod监控巡检（kube-system + monitoring命名空间）。检查系统插件的CPU/内存使用率。

检查内容：
- CPU 使用率 > 80% 的插件Pod数量及Top 10
- 内存使用率 > 80% 的插件Pod数量及Top 10

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "插件Pod监控巡检",
    "status": "PASS/WARN",
    "checked": true,
    "high_cpu_count": 2,
    "high_memory_count": 1,
    "high_cpu_pods_top10": [
      {"pod": "coredns-xxx", "namespace": "kube-system", "cpu_usage_percent": 85.5, "node": "192.168.1.1", "status": "warning"}
    ],
    "high_memory_pods_top10": [...],
    "namespaces": ["kube-system", "monitoring"]
  },
  "issues": [...]
}
```

#### huawei_biz_pod_monitoring_inspection
业务Pod监控巡检（非kube-system/monitoring命名空间）。检查业务应用的CPU/内存使用率。

检查内容：
- CPU 使用率 > 80% 的业务Pod数量及Top 10
- 内存使用率 > 80% 的业务Pod数量及Top 10

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns: 与 `huawei_addon_pod_monitoring_inspection` 类似结构。

#### huawei_node_status_inspection
Node状态巡检。检查节点运行状态和健康度。

检查内容：
- 节点状态检查 (Active/Error/Deleting/Installing/Abnormal)
- Ready/NotReady 统计
- 异常节点原因说明

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "Node状态巡检",
    "status": "PASS/FAIL",
    "checked": true,
    "total": 4,
    "ready": 3,
    "not_ready": 1,
    "abnormal_nodes": [
      {"name": "node-xxx", "ip": "192.168.1.3", "status": "Error", "reason": "节点处于错误状态，可能需要重启或重新加入集群"}
    ]
  },
  "issues": [...]
}
```

#### huawei_node_resource_inspection
节点资源监控巡检。检查节点CPU/内存/磁盘使用率。

检查内容：
- CPU 使用率 > 80% 的节点数量及Top 10
- 内存使用率 > 80% 的节点数量及Top 10
- 磁盘使用率 > 80% 的节点数量及Top 10

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "节点资源监控巡检",
    "status": "PASS/WARN",
    "checked": true,
    "high_cpu_count": 1,
    "high_memory_count": 0,
    "high_disk_count": 0,
    "high_cpu_nodes_top10": [
      {"node_ip": "192.168.1.1", "node_name": "node-xxx", "cpu_usage_percent": 85.2, "status": "warning"}
    ]
  },
  "issues": [...]
}
```

#### huawei_event_inspection
Event巡检。检查集群事件和异常告警。

检查内容：
- 事件类型统计 (Normal/Warning)
- 关键事件识别 (Failed/Error/CrashLoopBackOff/OOMKilled/Evicted/FailedScheduling等)
- 按原因/命名空间归一统计

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "Event巡检",
    "status": "PASS/WARN",
    "checked": true,
    "total": 120,
    "normal": 100,
    "warning": 20,
    "critical_events": [
      {"reason": "CrashLoopBackOff", "namespace": "default", "involved_object": "pod/nginx-xxx", "count": 5, "message": "..."}
    ],
    "events_by_reason": {"CrashLoopBackOff": {"count": 5, "events": [...]}, ...},
    "events_by_namespace": {"default": {"count": 50, "events": [...]}, ...}
  },
  "issues": [...]
}
```

#### huawei_aom_alarm_inspection
AOM告警巡检。获取当前活跃告警。

检查内容：
- 当前活跃告警列表
- 严重级别分类 (Critical/Major/Minor/Info)
- 过滤当前集群相关告警
- 按告警类型归一统计

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "AOM告警巡检",
    "status": "PASS/WARN/FAIL",
    "checked": true,
    "total": 10,
    "severity_breakdown": {"Critical": 1, "Major": 2, "Minor": 5, "Info": 2},
    "cluster_alarms": [
      {"name": "CPU使用率过高", "severity": "Critical", "resource_id": "...", "message": "..."}
    ],
    "alarms_by_type": {...}
  },
  "issues": [...]
}
```

#### huawei_elb_monitoring_inspection
ELB负载均衡监控巡检。检查LoadBalancer类型Service的ELB和EIP监控。

检查内容：
- LoadBalancer Service列表
- ELB监控指标（连接数、带宽、使用率）
- 公网EIP带宽监控
- 高连接/高带宽使用率ELB识别
- EIP带宽超限告警

Parameters:
- region (required): 华为云区域
- cluster_id (required): CCE集群ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- project_id (optional): Project ID

Returns:
```json
{
  "success": true,
  "check": {
    "name": "ELB负载均衡监控巡检",
    "status": "PASS/WARN",
    "checked": true,
    "total_loadbalancers": 2,
    "loadbalancer_services": [
      {"service_name": "nginx-svc", "namespace": "default", "elb_id": "xxx", "elb_ip": "1.2.3.4", "ports": [...]}
    ],
    "elb_metrics": [
      {"service_name": "nginx-svc", "elb_id": "xxx", "connection_num": 1000, "l4_connection_usage_percent": 45.2}
    ],
    "eip_metrics": [
      {"service_name": "nginx-svc", "public_ip": "1.2.3.4", "bw_usage_out_percent": 75.5}
    ],
    "high_bandwidth_usage_elbs": [],
    "high_bandwidth_eips": []
  },
  "issues": [...]
}
```

调用示例:
```bash
# Pod状态巡检
python3 huawei-cloud.py huawei_pod_status_inspection region=cn-north-4 cluster_id=xxx

# Node状态巡检
python3 huawei-cloud.py huawei_node_status_inspection region=cn-north-4 cluster_id=xxx

# Event巡检
python3 huawei-cloud.py huawei_event_inspection region=cn-north-4 cluster_id=xxx

# AOM告警巡检
python3 huawei-cloud.py huawei_aom_alarm_inspection region=cn-north-4 cluster_id=xxx

# ELB网络巡检
python3 huawei-cloud.py huawei_elb_monitoring_inspection region=cn-north-4 cluster_id=xxx
```

#### huawei_resize_cce_nodepool
Resize (scale up or down) a CCE node pool.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- nodepool_id (required): Node pool ID
- node_count (required): Target node count
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Operation result.

#### huawei_delete_cce_node
Delete a node from a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- node_id (required): Node ID to delete
- confirm (optional): Confirm deletion
- scale_down (optional): Scale down node pool
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Operation result.

#### huawei_delete_cce_cluster
Delete a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- confirm (optional): Confirm deletion
- delete_evs (optional): Delete associated EVS
- delete_net (optional): Delete associated network
- delete_obs (optional): Delete associated OBS
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Operation result.

#### huawei_delete_cce_workload
Delete a workload (deployment/statefulset) from a CCE cluster.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- workload_type (required): "Deployment" or "StatefulSet"
- name (required): Workload name
- namespace (required): Kubernetes namespace
- confirm (optional): Confirm deletion
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key

Returns: Operation result.

### AOM (Application Operations Management)

#### huawei_get_aom_metrics
Get monitoring metrics from AOM for CCE cluster resources using PromQL.

Parameters:
- region (required): Huawei Cloud region
- cluster_id (required): CCE cluster ID
- metric_type (optional): Metric type - cpu_util, memory_util, etc.
- node_ip (optional): Node IP address
- project_id (optional): Project ID
- ak (optional): Access Key ID
- sk (optional): Secret Access Key
- hours (optional): Time range in hours (default: 1)
- period (optional): Data period in seconds (default: 60)

Returns: AOM metrics via PromQL query.

Note: Requires AOM plugin installed on CCE cluster and Prometheus remote-write configured.

### Projects

#### huawei_list_projects
List all projects for the account.

Parameters:
- ak (required): Access Key ID
- sk (required): Secret Access Key

Returns: List of projects with ID, name, region.

#### huawei_get_project_by_region
Get project ID for a specific region.

Parameters:
- region (required): Huawei Cloud region
- ak (required): Access Key ID
- sk (required): Secret Access Key

Returns: Project ID for the specified region.

## Supported Regions
- cn-north-4 (华北-北京四)
- cn-east-3 (华东-上海一)
- cn-south-1 (华南-广州)
- cn-south-2 (华南-广州友好)
- cn-west-3 (西北-西安)
- ap-southeast-1 (亚太-香港)
- ap-southeast-2 (亚太-曼谷)
- ap-southeast-3 (亚太-新加坡)
- eu-west-0 (欧洲-巴黎)

## Examples

```bash
# List ECS instances
huawei_list_ecs region="cn-north-4"

# Get ECS metrics
huawei_get_ecs_metrics region="cn-north-4" instance_id="ecs-xxxxx"

# List VPC networks
huawei_list_vpc region="cn-north-4"

# List CCE clusters
huawei_list_cce_clusters region="cn-north-4"

# List CCE addons
huawei_list_cce_addons region="cn-north-4" cluster_id="cluster-xxxxx"

# List CCE nodes
huawei_list_cce_nodes region="cn-north-4" cluster_id="cluster-xxxxx"

# List CCE pods
huawei_get_cce_pods region="cn-north-4" cluster_id="cluster-xxxxx" namespace="default"

# Get project ID
huawei_get_project_by_region region="cn-north-4"
```

## Notes
- Ensure your AK/SK has proper IAM permissions for the requested resources
- Different regions may have different resource availability
- Monitoring data may have a few minutes delay
- Some metrics may not be available for all instance types
- CCE cluster operations require appropriate Kubernetes RBAC permissions

## References
- [CCE安全组配置说明](./references/CCE_Security_Group_Configuration.md)