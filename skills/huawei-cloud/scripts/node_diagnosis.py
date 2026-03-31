#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集群节点问题诊断工具

功能：
1. 基于告警或用户输入的节点进行诊断
2. 批量诊断（最多10个节点，5个一批）
3. 分析节点状态、事件、监控、告警
4. 生成诊断报告

使用方式：
    # 批量诊断异常节点（不指定节点）
    python3 node_diagnosis.py huawei_node_batch_diagnose region=cn-north-4 cluster_id=xxx
    
    # 诊断指定节点
    python3 node_diagnosis.py huawei_node_diagnose region=cn-north-4 cluster_id=xxx node_ips=192.168.1.10,192.168.1.11
    
    # 获取异常节点列表
    python3 node_diagnosis.py huawei_list_abnormal_nodes region=cn-north-4 cluster_id=xxx
    
    # 验证Pod调度
    python3 node_diagnosis.py huawei_node_verify_pod_scheduling region=cn-north-4 cluster_id=xxx node_ip=192.168.1.10
"""

import os
import sys
import json
import warnings
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple

# Suppress warnings
warnings.filterwarnings('ignore')

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入主模块的工具函数
import importlib.util
spec = importlib.util.spec_from_file_location("huawei_cloud", os.path.join(os.path.dirname(__file__), "huawei-cloud.py"))
huawei_cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(huawei_cloud)

get_credentials_with_region = huawei_cloud.get_credentials_with_region
get_project_id_for_region = huawei_cloud.get_project_id_for_region
list_cce_clusters = huawei_cloud.list_cce_clusters
list_cce_cluster_nodes = huawei_cloud.list_cce_cluster_nodes
get_kubernetes_nodes = huawei_cloud.get_kubernetes_nodes
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods
get_kubernetes_events = huawei_cloud.get_kubernetes_events
get_kubernetes_nodes = huawei_cloud.get_kubernetes_nodes
list_cce_addons = huawei_cloud.list_cce_addons
list_aom_instances = huawei_cloud.list_aom_instances
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
get_cce_kubeconfig = huawei_cloud.get_cce_kubeconfig
list_nat_gateways = huawei_cloud.list_nat_gateways
list_vpc = huawei_cloud.list_vpc_networks
list_security_groups = huawei_cloud.list_security_groups


# ========== 配置 ==========

REPORT_DIR = "/root/.openclaw/workspace/report"
BATCH_SIZE = 5  # 每批分析节点数
MAX_NODES_ONCE = 10  # 单次最多分析节点数


# ========== 工具函数 ==========

def get_aom_instance(region: str, ak: str, sk: str, project_id: str = None) -> Optional[str]:
    """获取CCE类型的AOM实例ID"""
    result = list_aom_instances(region, ak, sk, project_id, prom_type="CCE")
    if result.get("success") and result.get("instances"):
        for inst in result.get("instances", []):
            return inst.get("id")
    return None


def get_cluster_name(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> str:
    """获取集群名称"""
    result = list_cce_clusters(region, ak, sk, project_id)
    if result.get("success") and result.get("clusters"):
        for cluster in result.get("clusters", []):
            if cluster.get("id") == cluster_id:
                return cluster.get("name", cluster_id)
    return cluster_id


def get_nodepool_info(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """获取节点池信息"""
    from huawei_cloud import list_cce_node_pools
    result = list_cce_node_pools(region, cluster_id, ak, sk, project_id)
    nodepools = {}
    if result.get("success") and result.get("nodepools"):
        for np in result.get("nodepools", []):
            nodepools[np.get("id")] = {
                "name": np.get("name"),
                "flavor": np.get("flavor"),
                "status": np.get("status"),
                "node_count": np.get("node_count")
            }
    return nodepools


def check_npd_installed(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> bool:
    """检查是否安装了NPD插件"""
    result = list_cce_addons(region, cluster_id, ak, sk, project_id)
    if result.get("success") and result.get("addons"):
        for addon in result.get("addons", []):
            if "npd" in addon.get("name", "").lower() or "node-problem" in addon.get("name", "").lower():
                if addon.get("status") == "running":
                    return True
    return False


def get_node_events(node_ip: str, region: str, cluster_id: str, ak: str, sk: str, 
                    project_id: str = None, limit: int = 200) -> List[Dict]:
    """获取节点相关的事件"""
    events_result = get_kubernetes_events(region, cluster_id, ak, sk, project_id, limit=limit)
    node_events = []
    
    if events_result.get("success") and events_result.get("events"):
        for event in events_result.get("events", []):
            # 检查事件是否与该节点相关
            involved = event.get("involved_object", {})
            if "node" in involved.get("kind", "").lower() or node_ip in str(event):
                node_events.append({
                    "type": event.get("type"),
                    "reason": event.get("reason"),
                    "message": event.get("message"),
                    "first_timestamp": event.get("first_timestamp"),
                    "last_timestamp": event.get("last_timestamp"),
                    "count": event.get("count", 1)
                })
    
    return node_events


def get_node_monitoring(node_ip: str, region: str, cluster_id: str, ak: str, sk: str, 
                        project_id: str = None, hours: int = 1) -> Dict[str, Any]:
    """获取节点监控数据（近1小时）
    
    使用 huawei_get_cce_node_metrics 获取节点的CPU/内存/磁盘监控
    """
    metrics = {
        "cpu": {},
        "memory": {},
        "disk": {},
        "network": {},
        "raw": {}
    }
    
    try:
        # 使用 huawei_get_cce_node_metrics 获取所有节点监控
        node_metrics_result = huawei_cloud.get_cce_node_metrics(
            region, cluster_id, ak, sk, project_id, top_n=10, hours=hours
        )
        
        if node_metrics_result.get("success"):
            metrics_data = node_metrics_result.get("metrics", {})
            metrics["raw"] = {
                "success": node_metrics_result.get("success"),
                "cluster_name": node_metrics_result.get("cluster_name")
            }
            
            # 从返回的所有节点数据中筛选目标节点
            for metric_type in ["cpu_top_n", "memory_top_n", "disk_top_n"]:
                metric_list = metrics_data.get(metric_type, [])
                for node_data in metric_list:
                    # 兼容多种IP字段名
                    node_ip_addr = node_data.get("node_ip") or node_data.get("instance") or ""
                    if node_ip_addr == node_ip:
                        if metric_type == "cpu_top_n":
                            metrics["cpu"] = {
                                "usage_percent": node_data.get("cpu_usage_percent", 0),
                                "status": node_data.get("status", "unknown"),
                                "time_series": node_data.get("time_series", [])
                            }
                        elif metric_type == "memory_top_n":
                            metrics["memory"] = {
                                "usage_percent": node_data.get("memory_usage_percent", 0),
                                "status": node_data.get("status", "unknown"),
                                "time_series": node_data.get("time_series", [])
                            }
                        elif metric_type == "disk_top_n":
                            metrics["disk"] = {
                                "usage_percent": node_data.get("disk_usage_percent", 0),
                                "status": node_data.get("status", "unknown"),
                                "time_series": node_data.get("time_series", [])
                            }
        
    except Exception as e:
        metrics["error"] = str(e)
    
    return metrics


def get_workloads_on_node(node_ip: str, region: str, cluster_id: str, ak: str, sk: str,
                          project_id: str = None) -> List[Dict]:
    """获取节点上部署的工作负载"""
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id)
    workloads = []
    
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            if pod.get("node") == node_ip or pod.get("host_ip") == node_ip:
                workloads.append({
                    "name": pod.get("name"),
                    "namespace": pod.get("namespace"),
                    "status": pod.get("status"),
                    "ip": pod.get("ip"),
                    "labels": pod.get("labels", {}),
                    "containers": len(pod.get("containers", []))
                })
    
    return workloads


def get_pods_resource_usage(node_ip: str, region: str, cluster_id: str, 
                            cluster_name: str, aom_instance_id: str,
                            ak: str, sk: str, project_id: str = None) -> List[Dict]:
    """获取节点上Pod的资源占用情况
    
    使用 huawei_get_cce_pod_metrics 获取节点的Pod监控数据
    """
    resource_usage = []
    
    try:
        # 使用 huawei_get_cce_pod_metrics 获取节点上的Pod监控
        pod_metrics_result = huawei_cloud.get_cce_pod_metrics(
            region, cluster_id, ak, sk, project_id,
            node_ip=node_ip, top_n=20, hours=1
        )
        
        if pod_metrics_result.get("success"):
            metrics_data = pod_metrics_result.get("metrics", {})
            
            # 获取CPU数据
            cpu_data = metrics_data.get("cpu_top_n", [])
            for pod in cpu_data:
                resource_usage.append({
                    "pod": pod.get("pod", ""),
                    "namespace": pod.get("namespace", ""),
                    "cpu_percent": pod.get("cpu_usage_percent", 0),
                    "cpu_status": pod.get("status", "unknown")
                })
            
            # 获取内存数据并合并
            mem_data = metrics_data.get("memory_top_n", [])
            mem_map = {}
            for pod in mem_data:
                key = f"{pod.get('namespace', '')}/{pod.get('pod', '')}"
                mem_map[key] = pod.get("memory_usage_percent", 0)
            
            for usage in resource_usage:
                key = f"{usage['namespace']}/{usage['pod']}"
                usage["memory_percent"] = mem_map.get(key, 0)
                # 标记状态
                if usage.get("cpu_percent", 0) > 90:
                    usage["status"] = "critical"
                elif usage.get("cpu_percent", 0) > 80:
                    usage["status"] = "warning"
                elif usage.get("memory_percent", 0) > 80:
                    usage["status"] = "warning"
                else:
                    usage["status"] = "normal"
            
            # 按CPU使用率排序
            resource_usage.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
        
    except Exception as e:
        resource_usage.append({"error": str(e), "details": str(e)})
    
    return resource_usage[:20]  # 返回Top 20


def check_vpc_security_group(region: str, cluster_id: str, ak: str, sk: str, 
                             project_id: str = None) -> Dict[str, Any]:
    """检查VPC安全组配置"""
    result = {
        "checked": False,
        "vpc_id": None,
        "security_groups": [],
        "issues": []
    }
    
    try:
        # 获取集群信息获取VPC
        from huawei_cloud import list_cce_clusters
        cluster_result = list_cce_clusters(region, ak, sk, project_id)
        
        vpc_id = None
        if cluster_result.get("success") and cluster_result.get("clusters"):
            for cluster in cluster_result.get("clusters", []):
                if cluster.get("id") == cluster_id:
                    vpc_id = cluster.get("vpc_id")
                    break
        
        if not vpc_id:
            result["issues"].append("未找到集群VPC信息")
            return result
        
        result["vpc_id"] = vpc_id
        result["checked"] = True
        
        # 查询安全组
        sg_result = list_security_groups(region, vpc_id, ak, sk, project_id)
        if sg_result.get("success") and sg_result.get("security_groups"):
            result["security_groups"] = sg_result.get("security_groups", [])
            
    except Exception as e:
        result["issues"].append(str(e))
    
    return result


# ========== 单节点诊断 ==========

def diagnose_single_node(node_ip: str, region: str, cluster_id: str, 
                         ak: str, sk: str, project_id: str = None,
                         aom_instance_id: str = None, cluster_name: str = None) -> Dict[str, Any]:
    """单个节点诊断
    
    诊断步骤：
    1.1 - 检查节点状态和事件
    1.2 - 检查NPD插件事件
    1.3 - 分析节点监控（CPU/内存/磁盘/网络）
    1.4 - 分析工作负载资源占用
    1.5 - 检查VPC安全组（针对NotReady）
    """
    report = {
        "node_ip": node_ip,
        "diagnosis_time": datetime.now().isoformat(),
        "steps_completed": [],
        "node_info": {},
        "events": [],
        "npd_events": [],
        "monitoring": {},
        "workloads": [],
        "top_resources": [],
        "vpc_check": {},
        "issues": [],
        "recommendations": []
    }
    
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    project_id = project_id or proj_id
    
    # 步骤1.1: 检查节点状态
    report["steps_completed"].append("1.1 检查节点状态")
    
    # 使用Kubernetes API获取节点信息（包含IP）
    k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, project_id)
    node_info = {}
    
    if k8s_nodes_result.get("success"):
        for node in k8s_nodes_result.get("nodes", []):
            internal_ip = node.get("internal_ip") or node.get("hostname")
            if internal_ip == node_ip:
                labels = node.get("labels", {})
                node_info = {
                    "name": node.get("name"),
                    "ready": node.get("ready"),
                    "internal_ip": internal_ip,
                    "cpu": node.get("cpu"),
                    "memory": node.get("memory"),
                    "max_pods": node.get("max_pods"),
                    "nodepool_id": labels.get("cce.cloud.com/cce-nodepool-id", ""),
                    "nodepool_name": labels.get("cce.cloud.com/cce-nodepool", ""),
                    "os": labels.get("os.name", ""),
                    "os_version": labels.get("os.version", ""),
                    "instance_type": labels.get("node.kubernetes.io/instance-type", ""),
                    "created": node.get("created")
                }
                break
    
    report["node_info"] = node_info
    
    # 获取节点事件
    report["steps_completed"].append("1.2 检查节点事件")
    events = get_node_events(node_ip, region, cluster_id, ak, sk, project_id)
    report["events"] = events
    
    # 检查NPD插件
    npd_installed = check_npd_installed(region, cluster_id, ak, sk, project_id)
    report["npd_installed"] = npd_installed
    
    if npd_installed:
        # NPD安装了的，查找NPD事件
        for event in events:
            if "NPD" in event.get("reason", "") or "NodeProblem" in event.get("reason", ""):
                report["npd_events"].append(event)
    
    # 步骤1.3: 分析节点监控
    report["steps_completed"].append("1.3 分析节点监控")
    monitoring = get_node_monitoring(node_ip, region, cluster_id, access_key, secret_key, project_id)
    report["monitoring"] = monitoring
    
    # 分析监控异常
    cpu_high = False
    mem_high = False
    
    # 从新格式的监控数据中提取CPU/内存使用率
    cpu_usage = monitoring.get("cpu", {}).get("usage_percent", 0)
    mem_usage = monitoring.get("memory", {}).get("memory_usage_percent") or monitoring.get("memory", {}).get("usage_percent", 0)
    disk_usage = monitoring.get("disk", {}).get("usage_percent", 0)
    
    # 检查CPU
    if cpu_usage > 0:
        cpu_value = float(cpu_usage)
        if cpu_value > 80:
            cpu_high = True
            report["issues"].append({
                "category": "CPU",
                "severity": "WARNING" if cpu_value < 90 else "CRITICAL",
                "detail": f"CPU使用率 {cpu_value:.1f}%",
                "suggestion": "检查高CPU占用的工作负载"
            })
    
    # 检查内存
    if mem_usage > 0:
        mem_value = float(mem_usage)
        if mem_value > 80:
            mem_high = True
            report["issues"].append({
                "category": "内存",
                "severity": "WARNING" if mem_value < 90 else "CRITICAL",
                "detail": f"内存使用率 {mem_value:.1f}%",
                "suggestion": "检查高内存占用的工作负载"
            })
    
    # 步骤1.4: 分析工作负载资源占用
    if cpu_high or mem_high:
        report["steps_completed"].append("1.4 分析工作负载资源占用")
        
        workloads = get_workloads_on_node(node_ip, region, cluster_id, ak, sk, project_id)
        report["workloads"] = workloads
        
        # 获取Pod资源占用
        if aom_instance_id and cluster_name and (cpu_high or mem_high):
            top_resources = get_pods_resource_usage(node_ip, region, cluster_id, 
                                                    cluster_name, aom_instance_id,
                                                    access_key, secret_key, project_id)
            report["top_resources"] = top_resources
            # 同时设置 high_cpu_pods 以保持兼容性
            if top_resources and not any('error' in r for r in top_resources):
                report["high_cpu_pods"] = [
                    {
                        "pod": r.get("pod", ""),
                        "namespace": r.get("namespace", ""),
                        "cpu_percent": r.get("cpu_percent", 0)
                    }
                    for r in top_resources
                ]
            else:
                report["high_cpu_pods"] = []
    
    # 步骤1.5: 检查VPC安全组（针对NotReady节点）
    status = node_info.get("status", "")
    if status in ["NotReady", "Error", "Abnormal"]:
        report["steps_completed"].append("1.5 检查VPC安全组")
        vpc_check = check_vpc_security_group(region, cluster_id, ak, sk, project_id)
        report["vpc_check"] = vpc_check
        
        if vpc_check.get("issues"):
            report["issues"].append({
                "category": "VPC",
                "severity": "WARNING",
                "detail": "VPC安全组检查异常",
                "suggestion": "检查安全组规则是否阻断了Master和Node之间的通信"
            })
    
    # 生成建议
    for issue in report.get("issues", []):
        category = issue.get("category", "")
        if category == "CPU":
            report["recommendations"].append({
                "type": "evict",
                "suggestion": "节点CPU负载过高，建议驱逐高CPU占用的Pod"
            })
        elif category == "内存":
            report["recommendations"].append({
                "type": "evict",
                "suggestion": "节点内存负载过高，建议驱逐高内存占用的Pod"
            })
        elif category == "VPC":
            report["recommendations"].append({
                "type": "check",
                "suggestion": "检查VPC安全组配置，确保Master和Node通信正常"
            })
    
    return report


# ========== 批量节点诊断 ==========

def get_abnormal_nodes(region: str, cluster_id: str, ak: str, sk: str, 
                       project_id: str = None) -> List[Dict]:
    """获取集群中状态异常的节点"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    project_id = project_id or proj_id
    
    abnormal_nodes = []
    
    # 使用Kubernetes API获取节点（更准确地反映节点Ready状态）
    k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, project_id)
    
    if k8s_nodes_result.get("success"):
        for node in k8s_nodes_result.get("nodes", []):
            ready = node.get("ready", "")
            # 如果节点不是Ready状态，认为是异常
            if ready != "True":
                nodepool_id = ""
                nodepool_name = ""
                labels = node.get("labels", {})
                if "cce.cloud.com/cce-nodepool-id" in labels:
                    nodepool_id = labels.get("cce.cloud.com/cce-nodepool-id", "")
                if "cce.cloud.com/cce-nodepool" in labels:
                    nodepool_name = labels.get("cce.cloud.com/cce-nodepool", "")
                
                abnormal_nodes.append({
                    "name": node.get("name"),
                    "ip": node.get("internal_ip") or node.get("hostname"),
                    "status": "NotReady" if ready == "False" else ready,
                    "nodepool_id": nodepool_id,
                    "nodepool_name": nodepool_name,
                    "labels": labels
                })
    
    return abnormal_nodes


def write_abnormal_node_list(region: str, cluster_id: str, session_id: str,
                             nodes: List[Dict], ak: str, sk: str, 
                             project_id: str = None) -> str:
    """将异常节点列表写入文件"""
    # 创建报告目录
    os.makedirs(REPORT_DIR, exist_ok=True)
    
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"node-abnormal-list-{session_id}-{timestamp}.json"
    filepath = os.path.join(REPORT_DIR, filename)
    
    # 获取集群名称
    cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
    
    # 写入文件
    data = {
        "generated_at": datetime.now().isoformat(),
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "region": region,
        "total_abnormal": len(nodes),
        "nodes": nodes
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return filepath


def update_node_list_completion(filepath: str, completed_nodes: List[str]):
    """更新节点列表，标记已完成的节点"""
    if not os.path.exists(filepath):
        return
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    for node in data.get("nodes", []):
        if node.get("ip") in completed_nodes:
            node["diagnosis_completed"] = True
            node["completed_at"] = datetime.now().isoformat()
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def batch_node_diagnose(region: str, cluster_id: str, node_ips: List[str] = None,
                        ak: str = None, sk: str = None, project_id: str = None,
                        batch_size: int = BATCH_SIZE) -> Dict[str, Any]:
    """批量节点诊断
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        node_ips: 指定节点IP列表（可选）
        ak/sk: 认证信息
        project_id: Project ID
        batch_size: 每批节点数
    
    Returns:
        诊断结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    project_id = project_id or proj_id
    
    cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
    aom_instance_id = get_aom_instance(region, ak, sk, project_id)
    
    result = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "diagnosis_time": datetime.now().isoformat(),
        "node_list_file": None,
        "total_nodes": 0,
        "batches": [],
        "results": []
    }
    
    # 获取要诊断的节点列表
    target_nodes = []
    
    if node_ips:
        # 用户指定了节点
        if len(node_ips) > MAX_NODES_ONCE:
            return {
                "success": False,
                "error": f"单次最多分析{MAX_NODES_ONCE}个节点，请选择不超过{MAX_NODES_ONCE}个节点",
                "hint": f"您指定了{len(node_ips)}个节点，请减少到{MAX_NODES_ONCE}个以内"
            }
        
        # 获取节点信息（使用Kubernetes API）
        k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, project_id)
        if k8s_nodes_result.get("success"):
            for node in k8s_nodes_result.get("nodes", []):
                node_ip = node.get("internal_ip") or node.get("hostname")
                if node_ip in node_ips:
                    labels = node.get("labels", {})
                    target_nodes.append({
                        "name": node.get("name"),
                        "ip": node_ip,
                        "ready": node.get("ready"),
                        "nodepool_id": labels.get("cce.cloud.com/cce-nodepool-id", ""),
                        "nodepool_name": labels.get("cce.cloud.com/cce-nodepool", "")
                    })
    else:
        # 用户未指定节点，获取异常节点列表
        abnormal = get_abnormal_nodes(region, cluster_id, access_key, secret_key, project_id)
        
        if len(abnormal) > MAX_NODES_ONCE:
            # 超过10个，写入文件
            session_id = str(uuid.uuid4())[:8]
            filepath = write_abnormal_node_list(region, cluster_id, session_id, abnormal, access_key, secret_key, project_id)
            result["node_list_file"] = filepath
            result["total_abnormal"] = len(abnormal)
            
            return {
                "success": True,
                "message": f"发现{len(abnormal)}个异常节点，已写入文件",
                "node_list_file": filepath,
                "total_abnormal": len(abnormal),
                "batch_size": batch_size,
                "hint": f"由于节点数量超过{MAX_NODES_ONCE}，将分批进行分析。请选择最多10个节点，或按文件中的顺序进行批量分析"
            }
        
        target_nodes = abnormal
    
    result["total_nodes"] = len(target_nodes)
    
    # 分批处理
    batches = [target_nodes[i:i+batch_size] for i in range(0, len(target_nodes), batch_size)]
    
    for batch_idx, batch in enumerate(batches):
        batch_result = {
            "batch_index": batch_idx + 1,
            "total_batches": len(batches),
            "nodes": [],
            "diagnoses": []
        }
        
        for node in batch:
            node_ip = node.get("ip")
            diagnosis = diagnose_single_node(node_ip, region, cluster_id, 
                                            access_key, secret_key, project_id,
                                            aom_instance_id, cluster_name)
            batch_result["diagnoses"].append(diagnosis)
            batch_result["nodes"].append({
                "ip": node_ip,
                "status": diagnosis.get("node_info", {}).get("status"),
                "issues_count": len(diagnosis.get("issues", []))
            })
        
        result["batches"].append(batch_result)
        result["results"].extend(batch_result["diagnoses"])
    
    return result


# ========== CLI 入口 ==========

def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "Missing action parameter"
        }))
        sys.exit(1)

    action = sys.argv[1]

    params = {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            params[key] = value

    region = params.get("region")
    ak = params.get("ak")
    sk = params.get("sk")
    project_id = params.get("project_id")
    cluster_id = params.get("cluster_id")
    node_ips_str = params.get("node_ips")
    
    if action == "huawei_node_batch_diagnose":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        node_ips = None
        if node_ips_str:
            node_ips = [ip.strip() for ip in node_ips_str.split(",")]
        
        result = batch_node_diagnose(region, cluster_id, node_ips, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_node_diagnose":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        node_ip = params.get("node_ip")
        if not node_ip:
            print(json.dumps({"success": False, "error": "node_ip is required"}))
            sys.exit(1)
        
        aom_instance_id = get_aom_instance(region, ak, sk, project_id)
        cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
        
        result = diagnose_single_node(node_ip, region, cluster_id, ak, sk, project_id,
                                     aom_instance_id, cluster_name)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_list_abnormal_nodes":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
        abnormal = get_abnormal_nodes(region, cluster_id, access_key, secret_key, proj_id)
        
        result = {
            "success": True,
            "cluster_id": cluster_id,
            "total": len(abnormal),
            "nodes": abnormal
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({
            "success": False,
            "error": f"Unknown action: {action}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()