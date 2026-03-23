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

---

## CCE 安全组配置参考

### 安全组类型
| 类型 | 名称格式 | 说明 |
|------|---------|------|
| Master安全组 | {集群名}-cce-control-{随机ID} | 控制面节点 |
| Node安全组 | {集群名}-cce-node-{随机ID} | 工作节点 |
| ENI安全组 | {集群名}-cce-eni-{随机ID} | CCE Turbo集群容器网络 |

### 三种网络模型
1. **VPC网络模型** - 传统模式，使用VPC自带网络能力
2. **容器隧道网络模型** - 隧道模式，通过VXLAN隧道
3. **云原生网络2.0 (CCE Turbo)** - 新一代ENI直连模式

### 关键端口要求

#### Node节点必须开放
| 端口 | 协议 | 用途 | 建议 |
|------|------|------|------|
| 22 | TCP | SSH远程管理 | 可修改为指定IP |
| 10250 | TCP | kubelet (执行kubectl exec) | 不建议修改 |
| 30000-32767 | TCP/UDP | NodePort服务端口 | 可修改 |
| 4789 | UDP | 容器网络 (隧道模式) | 不建议修改 |

#### Master节点必须开放
| 端口 | 协议 | 用途 | 建议 |
|------|------|------|------|
| 5443 | TCP | kube-apiserver HAProxy | 建议限制IP |
| 5444 | TCP | kube-apiserver | 不建议修改 |
| 8445 | TCP | 存储插件访问 | 不建议修改 |
| 9443 | TCP | 网络插件访问 | 不建议修改 |

#### 出方向规则（所有模型）
| 端口 | 放通地址段 | 用途 |
|------|-----------|------|
| 53 | 子网DNS | 域名解析 |
| 5353 | 容器网段 | CoreDNS |
| 4789 | 所有IP | 容器间互访 |
| 5443/5444 | Master/VPC网段 | kube-apiserver |
| 8445/9443 | VPC网段 | 插件访问 |
| 123 | 100.125.0.0/16 | NTP时间同步 |
| 443 | 100.125.0.0/16 | OBS拉取安装包 |

### 注意事项
- 修改安全组属于高危操作，建议在测试环境验证
- 不建议修改的端口：UDP全部、TCP全部(VPC网段)、ICMP全部
- 新增规则需与原规则不冲突，否则可能导致原有规则失效
- 建议业务低峰期操作，观察组件可用性和业务连通性

### 官方文档
- 安全组配置指南: https://support.huaweicloud.com/cce_faq/cce_faq_00265.html