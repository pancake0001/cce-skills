#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Node 巡检模块

包含：
- Node 状态巡检
- 节点资源监控巡检 (CPU/内存/磁盘)
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入主模块的工具函数 - 使用 importlib 导入带横线的模块
import importlib.util
spec = importlib.util.spec_from_file_location("huawei_cloud", os.path.join(os.path.dirname(__file__), "huawei-cloud.py"))
huawei_cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(huawei_cloud)

get_credentials_with_region = huawei_cloud.get_credentials_with_region
list_cce_cluster_nodes = huawei_cloud.list_cce_cluster_nodes
get_kubernetes_nodes = huawei_cloud.get_kubernetes_nodes
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http


def node_status_inspection(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """Node 状态巡检
    
    检查内容：
    - 节点状态检查 (Active/Error/Deleting/Installing/Abnormal)
    - Ready/NotReady 统计
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        Node 状态巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "Node状态巡检",
        "status": "PASS",
        "checked": False,
        "total": 0,
        "ready": 0,
        "not_ready": 0,
        "node_details": [],
        "abnormal_nodes": []
    }
    
    issues = []
    
    def add_issue(severity: str, category: str, item: str, details: str):
        issues.append({
            "severity": severity,
            "category": category,
            "item": item,
            "details": details
        })
    
    try:
        nodes_result = list_cce_cluster_nodes(region, cluster_id, access_key, secret_key, proj_id)
        if nodes_result.get("success"):
            result["checked"] = True
            nodes = nodes_result.get("nodes", [])
            result["total"] = len(nodes)
            
            abnormal_nodes = []
            status_map = {
                "Active": "健康",
                "Error": "节点处于错误状态，可能需要重启或重新加入集群",
                "Deleting": "节点正在删除中",
                "Installing": "节点正在安装中，请等待安装完成",
                "Abnormal": "节点状态异常，请检查节点网络或 kubelet 服务"
            }
            
            for node in nodes:
                status = node.get("status", "Unknown")
                if status == "Active":
                    result["ready"] += 1
                else:
                    result["not_ready"] += 1
                    reason = status_map.get(status, "节点状态异常")
                    abnormal_nodes.append({
                        "name": node.get("name"),
                        "id": node.get("id"),
                        "ip": node.get("ip"),
                        "flavor": node.get("flavor"),
                        "status": status,
                        "reason": reason
                    })
                    add_issue("CRITICAL", "节点状态异常", node.get("name"),
                        f"节点: {node.get('name')}, IP: {node.get('ip')}, 状态: {status}, 原因: {reason}")
            
            result["node_details"] = nodes
            result["abnormal_nodes"] = abnormal_nodes
            
            if abnormal_nodes:
                result["status"] = "FAIL"
    except Exception as e:
        result["error"] = str(e)
    
    return result, issues


def node_resource_monitoring_inspection(region: str, cluster_id: str, aom_instance_id: str,
                                         cluster_name: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """节点资源监控巡检
    
    检查内容：
    - CPU 使用率 > 80% 的节点数量及 Top 10
    - 内存使用率 > 80% 的节点数量及 Top 10
    - 磁盘使用率 > 80% 的节点数量及 Top 10
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        aom_instance_id: AOM 实例 ID
        cluster_name: 集群名称
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        节点资源监控巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "节点资源监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_disk_count": 0,
        "high_cpu_nodes_top10": [],
        "high_memory_nodes_top10": [],
        "high_disk_nodes_top10": [],
        "all_high_resource_nodes": [],
        "monitoring_curves": {}  # 新增：存储监控曲线数据
    }
    
    issues = []
    
    def add_issue(severity: str, category: str, item: str, details: str):
        issues.append({
            "severity": severity,
            "category": category,
            "item": item,
            "details": details
        })
    
    if not aom_instance_id:
        result["status"] = "SKIP"
        result["message"] = "未找到CCE类型的AOM实例"
        return result, issues
    
    result["checked"] = True
    result["aom_instance_id"] = aom_instance_id
    
    # 获取节点信息映射
    node_info_map = {}
    k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
    if k8s_nodes_result.get("success"):
        for node in k8s_nodes_result.get("nodes", []):
            node_name = node.get("name", "")
            if node_name:
                node_info_map[node_name] = {
                    "name": node_name,
                    "ip": node_name,
                    "status": node.get("status", "Unknown")
                }
    
    # CPU 数量查询
    cpu_count_query = f"count(100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode='idle', cluster_name='{cluster_name}'}}[5m])) * 100) > 80)"
    cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
    
    if cpu_count_result.get("success") and cpu_count_result.get("result", {}).get("data", {}).get("result"):
        for item in cpu_count_result["result"]["data"]["result"]:
            values = item.get("values", [])
            if values:
                try:
                    result["high_cpu_count"] = int(float(values[-1][1]))
                except (ValueError, IndexError):
                    pass
    
    # CPU Top 10
    if result["high_cpu_count"] > 0:
        cpu_top10_query = f"topk(10, 100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode='idle', cluster_name='{cluster_name}'}}[5m])) * 100))"
        cpu_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if cpu_top10_result.get("success") and cpu_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in cpu_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        instance = metric.get("instance", "unknown")
                        instance_ip = instance.split(":")[0] if ":" in instance else instance
                        
                        if latest_value > 80:
                            node_info = node_info_map.get(instance_ip, {})
                            resource_info = {
                                "instance": instance,
                                "node_ip": instance_ip,
                                "node_name": node_info.get("name", instance_ip),
                                "cpu_usage_percent": round(latest_value, 2),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_cpu_nodes_top10"].append(resource_info)
                            add_issue("WARNING", "节点CPU高", instance_ip,
                                f"节点: {instance_ip}, CPU使用率: {round(latest_value, 2)}%")
                            
                            # 获取该节点的CPU时间序列数据
                            cpu_curve_query = f"100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode='idle', instance='{instance}', cluster_name='{cluster_name}'}}[5m])) * 100)"
                            cpu_curve_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_curve_query, hours=1, step=60, ak=access_key, sk=secret_key, project_id=proj_id)
                            if cpu_curve_result.get("success") and cpu_curve_result.get("result", {}).get("data", {}).get("result"):
                                key = f"cpu_{instance_ip}"
                                result["monitoring_curves"][key] = cpu_curve_result["result"]["data"]["result"][0]
                    except (ValueError, IndexError):
                        pass
    
    # 内存数量查询
    mem_count_query = f"count(avg by (instance) ((1 - node_memory_MemAvailable_bytes{{cluster_name='{cluster_name}'}} / node_memory_MemTotal_bytes{{cluster_name='{cluster_name}'}})) * 100 > 80)"
    mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
    
    if mem_count_result.get("success") and mem_count_result.get("result", {}).get("data", {}).get("result"):
        for item in mem_count_result["result"]["data"]["result"]:
            values = item.get("values", [])
            if values:
                try:
                    result["high_memory_count"] = int(float(values[-1][1]))
                except (ValueError, IndexError):
                    pass
    
    # 内存 Top 10
    if result["high_memory_count"] > 0:
        mem_top10_query = f"topk(10, avg by (instance) ((1 - node_memory_MemAvailable_bytes{{cluster_name='{cluster_name}'}} / node_memory_MemTotal_bytes{{cluster_name='{cluster_name}'}})) * 100)"
        mem_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if mem_top10_result.get("success") and mem_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in mem_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        instance = metric.get("instance", "unknown")
                        instance_ip = instance.split(":")[0] if ":" in instance else instance
                        
                        if latest_value > 80:
                            node_info = node_info_map.get(instance_ip, {})
                            resource_info = {
                                "instance": instance,
                                "node_ip": instance_ip,
                                "node_name": node_info.get("name", instance_ip),
                                "memory_usage_percent": round(latest_value, 2),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_memory_nodes_top10"].append(resource_info)
                            add_issue("WARNING", "节点内存高", instance_ip,
                                f"节点: {instance_ip}, 内存使用率: {round(latest_value, 2)}%")
                            
                            # 获取该节点的内存时间序列数据
                            mem_curve_query = f"avg by (instance) ((1 - node_memory_MemAvailable_bytes{{instance='{instance}', cluster_name='{cluster_name}'}} / node_memory_MemTotal_bytes{{instance='{instance}', cluster_name='{cluster_name}'}})) * 100"
                            mem_curve_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_curve_query, hours=1, step=60, ak=access_key, sk=secret_key, project_id=proj_id)
                            if mem_curve_result.get("success") and mem_curve_result.get("result", {}).get("data", {}).get("result"):
                                key = f"memory_{instance_ip}"
                                result["monitoring_curves"][key] = mem_curve_result["result"]["data"]["result"][0]
                    except (ValueError, IndexError):
                        pass
    
    # 磁盘数量查询
    disk_count_query = f"count(avg by (instance) ((1 - node_filesystem_avail_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}} / node_filesystem_size_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}})) * 100 > 80)"
    disk_count_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
    
    if disk_count_result.get("success") and disk_count_result.get("result", {}).get("data", {}).get("result"):
        for item in disk_count_result["result"]["data"]["result"]:
            values = item.get("values", [])
            if values:
                try:
                    result["high_disk_count"] = int(float(values[-1][1]))
                except (ValueError, IndexError):
                    pass
    
    # 磁盘 Top 10
    if result["high_disk_count"] > 0:
        disk_top10_query = f"topk(10, avg by (instance) ((1 - node_filesystem_avail_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}} / node_filesystem_size_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}})) * 100)"
        disk_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if disk_top10_result.get("success") and disk_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in disk_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        instance = metric.get("instance", "unknown")
                        instance_ip = instance.split(":")[0] if ":" in instance else instance
                        
                        if latest_value > 80:
                            node_info = node_info_map.get(instance_ip, {})
                            resource_info = {
                                "instance": instance,
                                "node_ip": instance_ip,
                                "node_name": node_info.get("name", instance_ip),
                                "disk_usage_percent": round(latest_value, 2),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_disk_nodes_top10"].append(resource_info)
                            add_issue("WARNING", "节点磁盘高", instance_ip,
                                f"节点: {instance_ip}, 磁盘使用率: {round(latest_value, 2)}%")
                            
                            # 获取该节点的磁盘时间序列数据
                            disk_curve_query = f"avg by (instance) ((1 - node_filesystem_avail_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',instance='{instance}',cluster_name='{cluster_name}'}} / node_filesystem_size_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',instance='{instance}',cluster_name='{cluster_name}'}})) * 100"
                            disk_curve_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_curve_query, hours=1, step=60, ak=access_key, sk=secret_key, project_id=proj_id)
                            if disk_curve_result.get("success") and disk_curve_result.get("result", {}).get("data", {}).get("result"):
                                key = f"disk_{instance_ip}"
                                result["monitoring_curves"][key] = disk_curve_result["result"]["data"]["result"][0]
                    except (ValueError, IndexError):
                        pass
    
    # 设置状态
    if result["high_cpu_count"] > 0 or result["high_memory_count"] > 0 or result["high_disk_count"] > 0:
        result["status"] = "WARN"
    
    return result, issues


if __name__ == "__main__":
    print("Node Inspection Module")
    print("Functions:")
    print("  - node_status_inspection")
    print("  - node_resource_monitoring_inspection")