#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pod 巡检模块

包含：
- Pod 状态巡检
- 插件 Pod 监控巡检 (kube-system + monitoring)
- 业务 Pod 监控巡检 (其他命名空间)
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
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
K8S_AVAILABLE = huawei_cloud.K8S_AVAILABLE


def pod_status_inspection(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """Pod 状态巡检
    
    检查内容：
    - Pod 运行状态统计
    - 容器重启次数检查
    - 异常状态识别
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        Pod 状态巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "Pod状态巡检",
        "status": "PASS",
        "checked": False,
        "total": 0,
        "running": 0,
        "pending": 0,
        "failed": 0,
        "restart_pods": [],
        "abnormal_pods": [],
        "abnormal_summary": {}
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
        pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
        if pods_result.get("success"):
            result["checked"] = True
            pods = pods_result.get("pods", [])
            result["total"] = len(pods)
            
            restart_pods = []
            abnormal_pods = []
            abnormal_summary = {}
            
            for pod in pods:
                status = pod.get("status", "Unknown")
                if status == "Running":
                    result["running"] += 1
                elif status == "Pending":
                    result["pending"] += 1
                elif status in ["Failed", "Unknown"]:
                    result["failed"] += 1
                
                # 检查重启次数
                containers = pod.get("containers", [])
                for container in containers:
                    restart_count = container.get("restart_count", 0)
                    if restart_count >= 5:
                        add_issue("CRITICAL", "Pod异常重启", pod.get("name"),
                            f"命名空间: {pod.get('namespace')}, 容器: {container.get('name')}, 重启次数: {restart_count}")
                        restart_pods.append({
                            "pod": pod.get("name"),
                            "namespace": pod.get("namespace"),
                            "container": container.get("name"),
                            "restart_count": restart_count,
                            "state_reason": container.get("state_reason", "Unknown"),
                            "node": pod.get("node", "Unknown")
                        })
                    elif restart_count >= 2:
                        add_issue("WARNING", "Pod异常重启", pod.get("name"),
                            f"命名空间: {pod.get('namespace')}, 容器: {container.get('name')}, 重启次数: {restart_count}")
                        restart_pods.append({
                            "pod": pod.get("name"),
                            "namespace": pod.get("namespace"),
                            "container": container.get("name"),
                            "restart_count": restart_count,
                            "state_reason": container.get("state_reason", "Unknown"),
                            "node": pod.get("node", "Unknown")
                        })
                
                # 检查异常状态
                if status in ["Failed", "Unknown"] or pod.get("state_reason") in [
                    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", 
                    "OOMKilled", "Evicted", "CreateContainerConfigError"
                ]:
                    reason = pod.get("state_reason", status)
                    abnormal_pods.append({
                        "pod": pod.get("name"),
                        "namespace": pod.get("namespace"),
                        "status": status,
                        "reason": reason,
                        "node": pod.get("node", "Unknown")
                    })
                    if reason not in abnormal_summary:
                        abnormal_summary[reason] = []
                    abnormal_summary[reason].append(pod.get("name"))
            
            result["restart_pods"] = restart_pods
            result["abnormal_pods"] = abnormal_pods
            result["abnormal_summary"] = abnormal_summary
            
            if restart_pods or abnormal_pods:
                result["status"] = "WARN"
            if result["failed"] > 0:
                result["status"] = "FAIL"
    except Exception as e:
        result["error"] = str(e)
    
    return result, issues


def addon_pod_monitoring_inspection(region: str, cluster_id: str, aom_instance_id: str, 
                                     cluster_name: str, ak: str, sk: str, project_id: str = None,
                                     all_pods_map: dict = None) -> Dict[str, Any]:
    """插件 Pod 监控巡检 (kube-system + monitoring)
    
    检查内容：
    - CPU 使用率 > 80% 的 Pod 数量及 Top 10
    - 内存使用率 > 80% 的 Pod 数量及 Top 10
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        aom_instance_id: AOM 实例 ID
        cluster_name: 集群名称
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
        all_pods_map: Pod 信息映射 (可选)
    
    Returns:
        插件 Pod 监控巡检结果
    """
    result = {
        "name": "插件Pod监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_cpu_pods_top10": [],
        "high_memory_pods_top10": [],
        "namespaces": ["kube-system", "monitoring"]
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
    
    # CPU数量查询
    cpu_count_query = 'count(sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace=~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace=~"kube-system|monitoring"}) * 100 > 80)'
    cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_count_query, ak=ak, sk=sk, project_id=project_id)
    
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
        cpu_top10_query = 'topk(10, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace=~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace=~"kube-system|monitoring"}) * 100)'
        cpu_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_top10_query, ak=ak, sk=sk, project_id=project_id)
        
        if cpu_top10_result.get("success") and cpu_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in cpu_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        pod_name = metric.get("pod", "unknown")
                        namespace = metric.get("namespace", "unknown")
                        
                        if latest_value > 80:
                            pod_info = all_pods_map.get(pod_name, {}) if all_pods_map else {}
                            resource_info = {
                                "pod": pod_name,
                                "namespace": namespace,
                                "cpu_usage_percent": round(latest_value, 2),
                                "node": pod_info.get("node", "Unknown"),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_cpu_pods_top10"].append(resource_info)
                            add_issue("WARNING", "插件Pod CPU使用率高", pod_name,
                                f"命名空间: {namespace}, CPU使用率: {round(latest_value, 2)}%")
                    except (ValueError, IndexError):
                        pass
    
    # 内存数量查询
    mem_count_query = 'count(sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace=~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace=~"kube-system|monitoring"}) * 100 > 80)'
    mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_count_query, ak=ak, sk=sk, project_id=project_id)
    
    if mem_count_result.get("success") and mem_count_result.get("result", {}).get("data", {}).get("result"):
        for item in mem_count_result["result"]["data"]["result"]:
            values = item.get("values", [])
            if values:
                try:
                    result["high_memory_count"] = int(float(values[-1][1]))
                except (ValueError, IndexError):
                    pass
    
    # 设置状态
    if result["high_cpu_count"] > 0 or result["high_memory_count"] > 0:
        result["status"] = "WARN"
    
    return result, issues


def biz_pod_monitoring_inspection(region: str, cluster_id: str, aom_instance_id: str,
                                   cluster_name: str, ak: str, sk: str, project_id: str = None,
                                   all_pods_map: dict = None, all_namespaces: list = None) -> Dict[str, Any]:
    """业务 Pod 监控巡检 (其他命名空间)
    
    检查内容：
    - CPU 使用率 > 80% 的 Pod 数量及 Top 10
    - 内存使用率 > 80% 的 Pod 数量及 Top 10
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        aom_instance_id: AOM 实例 ID
        cluster_name: 集群名称
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
        all_pods_map: Pod 信息映射 (可选)
        all_namespaces: 业务命名空间列表 (可选)
    
    Returns:
        业务 Pod 监控巡检结果
    """
    result = {
        "name": "业务Pod监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_cpu_pods_top10": [],
        "high_memory_pods_top10": [],
        "namespaces": all_namespaces or [],
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
    
    # CPU数量查询
    cpu_count_query = 'count(sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace!~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace!~"kube-system|monitoring"}) * 100 > 80)'
    cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_count_query, ak=ak, sk=sk, project_id=project_id)
    
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
        cpu_top10_query = 'topk(10, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace!~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace!~"kube-system|monitoring"}) * 100)'
        cpu_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_top10_query, ak=ak, sk=sk, project_id=project_id)
        
        if cpu_top10_result.get("success") and cpu_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in cpu_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        pod_name = metric.get("pod", "unknown")
                        namespace = metric.get("namespace", "unknown")
                        
                        if latest_value > 80:
                            pod_info = all_pods_map.get(pod_name, {}) if all_pods_map else {}
                            resource_info = {
                                "pod": pod_name,
                                "namespace": namespace,
                                "cpu_usage_percent": round(latest_value, 2),
                                "node": pod_info.get("node", "Unknown"),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_cpu_pods_top10"].append(resource_info)
                            add_issue("WARNING", "业务Pod CPU使用率高", pod_name,
                                f"命名空间: {namespace}, CPU使用率: {round(latest_value, 2)}%")
                            
                            # 获取该Pod的CPU时间序列数据
                            cpu_curve_query = f'sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{{image!="",pod="{pod_name}",namespace="{namespace}"}}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="cpu",pod="{pod_name}",namespace="{namespace}"}}) * 100'
                            cpu_curve_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_curve_query, hours=1, step=60, ak=ak, sk=sk, project_id=project_id)
                            if cpu_curve_result.get("success") and cpu_curve_result.get("result", {}).get("data", {}).get("result"):
                                key = f"cpu_{namespace}_{pod_name}"
                                result["monitoring_curves"][key] = cpu_curve_result["result"]["data"]["result"][0]
                    except (ValueError, IndexError):
                        pass
    
    # 内存数量查询
    mem_count_query = 'count(sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace!~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace!~"kube-system|monitoring"}) * 100 > 80)'
    mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_count_query, ak=ak, sk=sk, project_id=project_id)
    
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
        mem_top10_query = 'topk(10, sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace!~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace!~"kube-system|monitoring"}) * 100)'
        mem_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_top10_query, ak=ak, sk=sk, project_id=project_id)
        
        if mem_top10_result.get("success") and mem_top10_result.get("result", {}).get("data", {}).get("result"):
            for item in mem_top10_result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        pod_name = metric.get("pod", "unknown")
                        namespace = metric.get("namespace", "unknown")
                        
                        if latest_value > 80:
                            pod_info = all_pods_map.get(pod_name, {}) if all_pods_map else {}
                            resource_info = {
                                "pod": pod_name,
                                "namespace": namespace,
                                "memory_usage_percent": round(latest_value, 2),
                                "node": pod_info.get("node", "Unknown"),
                                "status": "critical" if latest_value > 90 else "warning"
                            }
                            result["high_memory_pods_top10"].append(resource_info)
                            add_issue("WARNING", "业务Pod内存使用率高", pod_name,
                                f"命名空间: {namespace}, 内存使用率: {round(latest_value, 2)}%")
                            
                            # 获取该Pod的内存时间序列数据
                            mem_curve_query = f'sum by (pod, namespace) (container_memory_working_set_bytes{{image!="",pod="{pod_name}",namespace="{namespace}"}}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="memory",pod="{pod_name}",namespace="{namespace}"}}) * 100'
                            mem_curve_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_curve_query, hours=1, step=60, ak=ak, sk=sk, project_id=project_id)
                            if mem_curve_result.get("success") and mem_curve_result.get("result", {}).get("data", {}).get("result"):
                                key = f"memory_{namespace}_{pod_name}"
                                result["monitoring_curves"][key] = mem_curve_result["result"]["data"]["result"][0]
                    except (ValueError, IndexError):
                        pass
    
    # 设置状态
    if result["high_cpu_count"] > 0 or result["high_memory_count"] > 0:
        result["status"] = "WARN"
    
    return result, issues


if __name__ == "__main__":
    print("Pod Inspection Module")
    print("Functions:")
    print("  - pod_status_inspection")
    print("  - addon_pod_monitoring_inspection")
    print("  - biz_pod_monitoring_inspection")