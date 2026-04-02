#!/usr/bin/env python3
# -*- coding: utf-8
"""
CCE 工作负载异常诊断工具

功能：
1. 基于告警或用户输入的工作负载进行诊断
2. 收集工作负载基础信息
3. 诊断异常Pod（参考CCE_Workload_Troubleshooting_Guide.md）
4. 进行节点诊断（调用节点问题诊断工具）
5. 进行网络链路分析（调用网络问题诊断工具）
6. 检查变更信息，进行关联性分析
7. 提供操作建议和综合分析报告

使用方式：
    # 基于告警诊断
    python3 workload_diagnosis.py huawei_workload_diagnose_by_alarm region=cn-north-4 cluster_id=xxx alarm_info="xxx"
    
    # 直接诊断指定工作负载
    python3 workload_diagnosis.py huawei_workload_diagnose region=cn-north-4 cluster_id=xxx workload_name=xxx namespace=default
    
    # 诊断某命名空间下的所有工作负载
    python3 workload_diagnosis.py huawei_workload_diagnose region=cn-north-4 cluster_id=xxx namespace=default
    
    # 扩容工作负载（需二次确认）
    python3 workload_diagnosis.py huawei_scale_workload region=cn-north-4 cluster_id=xxx workload_name=xxx namespace=default replicas=5 confirm=true
    
    # 扩容节点池（需二次确认）
    python3 workload_diagnosis.py huawei_expand_nodepool region=cn-north-4 cluster_id=xxx nodepool_id=xxx node_count=3 confirm=true
    
    # 恢复操作后检查工作负载状态
    python3 workload_diagnosis.py huawei_verify_workload region=cn-north-4 cluster_id=xxx workload_name=xxx namespace=default
"""

import os
import sys
import json
import re
import time
import warnings
import subprocess
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
list_cce_node_pools = huawei_cloud.list_cce_node_pools
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods
get_kubernetes_deployments = huawei_cloud.get_kubernetes_deployments
get_kubernetes_services = huawei_cloud.get_kubernetes_services
get_kubernetes_ingresses = huawei_cloud.get_kubernetes_ingresses
get_kubernetes_events = huawei_cloud.get_kubernetes_events
get_kubernetes_namespaces = huawei_cloud.get_kubernetes_namespaces
list_cce_addons = huawei_cloud.list_cce_addons
list_aom_instances = huawei_cloud.list_aom_instances
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
get_cce_kubeconfig = huawei_cloud.get_cce_kubeconfig
scale_cce_workload = huawei_cloud.scale_cce_workload
resize_node_pool = huawei_cloud.resize_node_pool


# ========== 工具函数 ==========

def get_cluster_name(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> str:
    """获取集群名称"""
    result = list_cce_clusters(region, ak, sk, project_id)
    if result.get("success") and result.get("clusters"):
        for cluster in result.get("clusters", []):
            if cluster.get("id") == cluster_id:
                return cluster.get("name", cluster_id)
    return cluster_id


def get_aom_instance(region: str, ak: str, sk: str, project_id: str = None) -> Optional[str]:
    """获取CCE类型的AOM实例ID"""
    result = list_aom_instances(region, ak, sk, project_id, prom_type="CCE")
    if result.get("success") and result.get("instances"):
        for inst in result.get("instances", []):
            if inst.get("prom_type") == "CCE" or inst.get("prom_type") == "K8S":
                return inst.get("id")
    return None


def get_workload_pods(region: str, cluster_id: str, workload_name: str, namespace: str,
                      ak: str, sk: str, project_id: str = None) -> List[Dict]:
    """获取工作负载对应的Pod列表"""
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, namespace)
    target_pods = []
    
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            # 匹配工作负载名称（Pod名称通常以deploymentname-xxx格式）
            pod_name = pod.get("name", "")
            if workload_name and workload in pod_name:
                target_pods.append(pod)
            elif not workload_name:
                # 没有指定工作负载名，返回namespace下所有pod
                target_pods.append(pod)
    
    return target_pods


def get_namespace_workloads(region: str, cluster_id: str, namespace: str,
                            ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """获取命名空间下的所有工作负载信息"""
    result = {
        "deployments": [],
        "statefulsets": [],
        "pods": []
    }
    
    # 获取Deployments
    dep_result = get_kubernetes_deployments(region, cluster_id, ak, sk, project_id, namespace)
    if dep_result.get("success") and dep_result.get("items"):
        for dep in dep_result.get("items", []):
            result["deployments"].append({
                "name": dep.get("name"),
                "replicas": dep.get("replicas"),
                "ready_replicas": dep.get("ready_replicas", 0),
                "available_replicas": dep.get("available_replicas", 0),
                "unavailable_replicas": dep.get("unavailable_replicas", 0),
                "creation_timestamp": dep.get("creation_timestamp"),
                "images": list(set([c.get("image") for c in dep.get("containers", [])]))
            })
    
    # 获取StatefulSets (暂时跳过，如果需要可后续添加)
    # sfs_result = get_kubernetes_statefulsets(region, cluster_id, ak, sk, project_id, namespace)
    # if sfs_result.get("success") and sfs_result.get("items"):
    #     for sfs in sfs_result.get("items", []):
    #         result["statefulsets"].append({
    #             "name": sfs.get("name"),
    #             "replicas": sfs.get("replicas"),
    #             "ready_replicas": sfs.get("ready_replicas", 0),
    #             "available_replicas": sfs.get("available_replicas", 0),
    #             "unavailable_replicas": sfs.get("unavailable_replicas", 0),
    #             "creation_timestamp": sfs.get("creation_timestamp"),
    #             "images": list(set([c.get("image") for c in sfs.get("containers", [])]))
    #         })
    
    # 获取所有Pods
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, namespace)
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            result["pods"].append({
                "name": pod.get("name"),
                "status": pod.get("status"),
                "ready": pod.get("ready"),
                "restart_count": pod.get("restart_count", 0),
                "node_ip": pod.get("host_ip"),
                "pod_ip": pod.get("ip"),
                "age": pod.get("age"),
                "creation_timestamp": pod.get("creation_timestamp")
            })
    
    return result


def analyze_pod_status(pod: Dict) -> Dict[str, Any]:
    """分析Pod状态，返回异常类型和可能的原因"""
    status = pod.get("status", "")
    ready = pod.get("ready", "")
    restart_count = pod.get("restart_count", 0)
    
    analysis = {
        "status": status,
        "is_abnormal": False,
        "abnormal_type": None,
        "possible_cause": None,
        "suggestion": None
    }
    
    # 分析状态
    if "Pending" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "Pending"
        analysis["possible_cause"] = "实例调度失败/存储卷挂载失败/添加存储失败"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00098.html"
    elif "ImagePullBackOff" in status or "ErrImagePull" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "ImagePullBackOff"
        analysis["possible_cause"] = "镜像拉取失败"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00015.html"
    elif "CrashLoopBackOff" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "CrashLoopBackOff"
        analysis["possible_cause"] = "容器启动失败/健康检查失败/重启"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00018.html"
    elif "Evicted" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "Evicted"
        analysis["possible_cause"] = "Pod被驱逐（资源限制导致）"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00209.html"
    elif "Creating" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "Creating"
        analysis["possible_cause"] = "实例一直处于创建中"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00140.html"
    elif "Terminating" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "Terminating"
        analysis["possible_cause"] = "Pod一直处于结束中"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00210.html"
    elif "Stopped" in status:
        analysis["is_abnormal"] = True
        analysis["abnormal_type"] = "Stopped"
        analysis["possible_cause"] = "实例已停止"
        analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00012.html"
    elif "Running" in status:
        # 检查Ready状态和重启次数
        if ready and "0/" in ready:
            analysis["is_abnormal"] = True
            analysis["abnormal_type"] = "NotReady"
            analysis["possible_cause"] = "容器未就绪"
        elif restart_count > 5:
            analysis["is_abnormal"] = True
            analysis["abnormal_type"] = "FrequentRestart"
            analysis["possible_cause"] = f"容器频繁重启（{restart_count}次）"
    
    # 检查Init容器状态
    init_status = pod.get("init_container_status", [])
    if init_status:
        for init in init_status:
            if "Error" in init.get("state", {}) or "CrashLoopBackOff" in init.get("state", {}):
                analysis["is_abnormal"] = True
                analysis["abnormal_type"] = "InitContainerError"
                analysis["possible_cause"] = "Init容器启动失败"
                analysis["suggestion"] = "参考: https://support.huaweicloud.com/cce_faq/cce_faq_00469.html"
    
    return analysis


def get_pod_events_for_diagnosis(region: str, cluster_id: str, pod_name: str, namespace: str,
                                  ak: str, sk: str, project_id: str = None) -> List[Dict]:
    """获取Pod的事件用于诊断"""
    events_result = get_kubernetes_events(region, cluster_id, ak, sk, project_id, namespace, limit=100)
    target_events = []
    
    if events_result.get("success") and events_result.get("events"):
        for event in events_result.get("events", []):
            involved = event.get("involved_object", {})
            if pod_name in involved.get("name", ""):
                target_events.append({
                    "type": event.get("type"),
                    "reason": event.get("reason"),
                    "message": event.get("message"),
                    "first_timestamp": event.get("first_timestamp"),
                    "last_timestamp": event.get("last_timestamp"),
                    "count": event.get("count", 1)
                })
    
    return target_events


def get_service_chain(region: str, cluster_id: str, workload_name: str, namespace: str,
                      ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """获取工作负载的完整服务链路"""
    chain = {
        "workload": {"name": workload_name, "namespace": namespace},
        "pods": [],
        "service": None,
        "ingress": None,
        "nginx_ingress": None,
        "elb": None,
        "eip": None,
        "nat": None,
        "nodes": []
    }
    
    # 获取Pods
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, namespace)
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            if workload_name in pod.get("name", ""):
                chain["pods"].append({
                    "name": pod.get("name"),
                    "status": pod.get("status"),
                    "node_ip": pod.get("host_ip"),
                    "ip": pod.get("ip"),
                    "restarts": pod.get("restart_count", 0)
                })
                if pod.get("host_ip") and pod.get("host_ip") not in chain["nodes"]:
                    chain["nodes"].append(pod.get("host_ip"))
    
    # 获取Service
    services_result = get_kubernetes_services(region, cluster_id, ak, sk, project_id, namespace)
    if services_result.get("success") and services_result.get("services"):
        for svc in services_result.get("services", []):
            selector = svc.get("selector") or {}
            if (selector and workload_name in selector.values()) or workload_name in svc.get("name", ""):
                chain["service"] = {
                    "name": svc.get("name"),
                    "type": svc.get("type"),
                    "cluster_ip": svc.get("cluster_ip"),
                    "load_balancer_ip": svc.get("load_balancer_ip"),
                    "ports": svc.get("ports", []),
                    "annotations": svc.get("annotations", {})
                }
                
                # 如果是LoadBalancer类型，获取ELB信息
                if svc.get("type") == "LoadBalancer":
                    annotations = svc.get("annotations", {})
                    elb_id = annotations.get("kubernetes.io/elb.id")
                    if elb_id:
                        chain["elb"] = {
                            "id": elb_id,
                            "ip": svc.get("load_balancer_ip"),
                            "service": svc.get("name")
                        }
    
    # 获取Ingress
    ingress_result = get_kubernetes_ingresses(region, cluster_id, ak, sk, project_id, namespace)
    if ingress_result.get("success") and ingress_result.get("ingresses"):
        for ing in ingress_result.get("ingresses", []):
            http_rules = ing.get("http_rules", [])
            for rule in http_rules:
                backend = rule.get("backend", {})
                service_name = backend.get("service", {}).get("name")
                if service_name == workload_name or (chain.get("service") and service_name == chain["service"].get("name")):
                    chain["ingress"] = {
                        "name": ing.get("name"),
                        "namespace": ing.get("namespace"),
                        "rules": ing.get("rules", []),
                        "tls": ing.get("tls", [])
                    }
                    # 尝试获取nginx-ingress信息
                    annotations = ing.get("annotations", {})
                    if "nginx" in str(annotations).lower():
                        chain["nginx_ingress"] = {
                            "name": ing.get("name"),
                            "annotations": annotations
                        }
    
    return chain


def get_workload_alarms(region: str, cluster_name: str, namespace: str, workload_name: str,
                        ak: str, sk: str, project_id: str = None, hours: int = 1) -> List[Dict]:
    """获取工作负载相关的告警信息（近1小时）"""
    alarms = []
    
    # 通过AOM获取告警
    aom_instance_id = get_aom_instance(region, ak, sk, project_id)
    if aom_instance_id:
        # 查询Pod相关的告警
        query = f'alertmetric{{cluster_name="{cluster_name}",namespace="{namespace}",pod=~"{workload_name}.*"}}'
        try:
            result = get_aom_prom_metrics_http(region, aom_instance_id, query, hours=hours, ak=ak, sk=sk, project_id=project_id)
            if result.get("success") and result.get("data"):
                alarms.extend(result.get("data", []))
        except Exception:
            pass
    
    return alarms


def analyze_change_correlation(workload_info: Dict, events: List[Dict], 
                                fault_time: str = None) -> Dict[str, Any]:
    """分析变更与故障的关联性"""
    correlation = {
        "has_correlation": False,
        "changes": [],
        "analysis": ""
    }
    
    if not fault_time:
        fault_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        fault_dt = datetime.strptime(fault_time, '%Y-%m-%d %H:%M:%S')
    except:
        fault_dt = datetime.now()
    
    # 分析事件中的变更相关信息
    change_events = []
    for event in events:
        reason = event.get("reason", "")
        message = event.get("message", "")
        last_timestamp = event.get("last_timestamp", "")
        
        # 查找变更相关事件
        if any(keyword in reason.lower() or keyword in message.lower() 
               for keyword in ["scaled", "created", "updated", "deleted", "restarted", "scaling", "pull", "kill", "schedule"]):
            change_events.append({
                "reason": reason,
                "message": message,
                "timestamp": last_timestamp
            })
    
    # 检查事件时间与故障时间的关联
    if change_events:
        correlation["has_correlation"] = True
        correlation["changes"] = change_events
        correlation["analysis"] = f"发现{len(change_events)}个变更事件可能与故障相关"
    
    return correlation


def generate_diagnosis_report(diagnosis_data: Dict) -> Dict[str, Any]:
    """生成综合诊断报告"""
    report = {
        "report_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "region": diagnosis_data.get("region"),
        "cluster_id": diagnosis_data.get("cluster_id"),
        "cluster_name": diagnosis_data.get("cluster_name"),
        "workloads": {},
        "abnormal_pods": [],
        "node_diagnosis": {},
        "network_diagnosis": {},
        "change_correlation": {},
        "alarms": [],
        "operations": [],
        "conclusions": [],
        "recommendations": []
    }
    
    # 工作负载基本信息
    workloads = diagnosis_data.get("workloads", {})
    report["workloads"] = {
        "total_deployments": len(workloads.get("deployments", [])),
        "total_statefulsets": len(workloads.get("statefulsets", [])),
        "total_pods": len(workloads.get("pods", [])),
        "details": workloads
    }
    
    # 异常Pod分析
    abnormal_pods = diagnosis_data.get("abnormal_pods", [])
    report["abnormal_pods"] = abnormal_pods
    
    # 节点诊断结果
    node_diag = diagnosis_data.get("node_diagnosis", {})
    if node_diag.get("success"):
        report["node_diagnosis"] = {
            "status": "completed",
            "abnormal_nodes": node_diag.get("abnormal_nodes", []),
            "summary": node_diag.get("summary", {})
        }
    
    # 网络诊断结果
    network_diag = diagnosis_data.get("network_diagnosis", {})
    if network_diag.get("success"):
        report["network_diagnosis"] = {
            "status": "completed",
            "chain": network_diag.get("chain", {}),
            "analysis": network_diag.get("chain_analysis", {})
        }
    
    # 变更关联分析
    report["change_correlation"] = diagnosis_data.get("change_correlation", {})
    
    # 告警信息
    report["alarms"] = diagnosis_data.get("alarms", [])
    
    # 操作记录
    report["operations"] = diagnosis_data.get("operations", [])
    
    # 生成结论和建议
    if abnormal_pods:
        abnormal_types = [p.get("analysis", {}).get("abnormal_type") for p in abnormal_pods]
        most_common = max(set(abnormal_types), key=abnormal_types.count) if abnormal_types else "Unknown"
        
        report["conclusions"].append(f"发现{len(abnormal_pods)}个异常Pod，最常见的异常类型为: {most_common}")
        
        # 根据异常类型给出建议
        if most_common == "Pending":
            report["recommendations"].append({
                "priority": "HIGH",
                "issue": "Pod调度失败",
                "suggestion": "检查节点资源是否充足，确认节点可用性"
            })
        elif most_common == "CrashLoopBackOff":
            report["recommendations"].append({
                "priority": "HIGH",
                "issue": "容器启动失败",
                "suggestion": "检查容器配置、健康检查、镜像是否正常"
            })
        elif most_common == "ImagePullBackOff":
            report["recommendations"].append({
                "priority": "HIGH",
                "issue": "镜像拉取失败",
                "suggestion": "检查镜像地址、仓库认证、网络连接"
            })
    
    if node_diag.get("abnormal_nodes"):
        report["recommendations"].append({
            "priority": "MEDIUM",
            "issue": "节点异常",
            "suggestion": f"发现{len(node_diag.get('abnormal_nodes', []))}个异常节点，建议检查节点状态"
        })
    
    # Top3根因分析
    report["top3_root_causes"] = []
    if abnormal_pods:
        # 基于分析结果生成Top3根因
        causes = []
        for pod in abnormal_pods[:5]:
            cause = pod.get("analysis", {}).get("possible_cause")
            if cause:
                causes.append(cause)
        
        # 统计最常见的根因
        if causes:
            cause_count = {}
            for c in causes:
                cause_count[c] = cause_count.get(c, 0) + 1
            
            top_causes = sorted(cause_count.items(), key=lambda x: x[1], reverse=True)[:3]
            for cause, count in top_causes:
                report["top3_root_causes"].append({
                    "cause": cause,
                    "affected_count": count
                })
    
    return report


# ========== 主诊断函数 ==========

def workload_diagnose(region: str, cluster_id: str, workload_name: str = None,
                      namespace: str = "default", ak: str = None, sk: str = None,
                      project_id: str = None, fault_time: str = None) -> Dict[str, Any]:
    """
    工作负载异常诊断主函数
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        workload_name: 工作负载名称（可选）
        namespace: 命名空间（默认default）
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
        fault_time: 故障时间点（可选）
    
    Returns:
        诊断报告
    """
    # 获取凭证
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials are required"
        }
    
    project_id = project_id or proj_id
    
    # 初始化诊断数据
    diagnosis_data = {
        "region": region,
        "cluster_id": cluster_id,
        "workload_name": workload_name,
        "namespace": namespace,
        "fault_time": fault_time,
        "workloads": {},
        "abnormal_pods": [],
        "node_diagnosis": {},
        "network_diagnosis": {},
        "change_correlation": {},
        "alarms": [],
        "operations": []
    }
    
    # 获取集群名称
    cluster_name = get_cluster_name(region, cluster_id, access_key, secret_key, project_id)
    diagnosis_data["cluster_name"] = cluster_name
    
    # ===== 步骤1: 收集工作负载基础信息 =====
    # 获取命名空间下所有工作负载
    namespace_workloads = get_namespace_workloads(region, cluster_id, namespace, access_key, secret_key, project_id)
    diagnosis_data["workloads"] = namespace_workloads
    
    # 如果指定了工作负载名称，过滤获取对应的Pods
    target_pods = []
    if workload_name:
        for pod in namespace_workloads.get("pods", []):
            if workload_name in pod.get("name", ""):
                target_pods.append(pod)
    else:
        target_pods = namespace_workloads.get("pods", [])
    
    # ===== 步骤2: 异常Pod诊断 =====
    abnormal_pods = []
    for pod in target_pods:
        # 分析Pod状态
        analysis = analyze_pod_status(pod)
        pod["analysis"] = analysis
        
        if analysis.get("is_abnormal"):
            # 获取Pod事件用于诊断
            events = get_pod_events_for_diagnosis(
                region, cluster_id, pod.get("name"), namespace,
                access_key, secret_key, project_id
            )
            pod["events"] = events[-5:]  # 取最近5条事件
            
            abnormal_pods.append(pod)
    
    diagnosis_data["abnormal_pods"] = abnormal_pods
    
    # ===== 步骤3: 节点诊断 =====
    # 收集异常Pod所在的节点（包括所有Pod的节点）
    all_nodes = list(set([p.get("node_ip") for p in target_pods if p.get("node_ip")]))
    abnormal_nodes = list(set([p.get("node_ip") for p in abnormal_pods if p.get("node_ip")]))
    
    # 执行节点诊断（调用node_diagnosis.py）
    node_diagnosis_result = {
        "success": False,
        "abnormal_nodes": [],
        "summary": {},
        "details": {}
    }
    
    if all_nodes:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            node_diag_script = os.path.join(script_dir, "node_diagnosis.py")
            
            # 调用节点诊断脚本
            cmd = [
                "python3", node_diag_script, "huawei_node_batch_diagnose",
                f"region={region}",
                f"cluster_id={cluster_id}",
                f"node_ips={','.join(all_nodes)}",
                f"ak={access_key}",
                f"sk={secret_key}",
                f"project_id={project_id}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                try:
                    diag_output = json.loads(result.stdout)
                    node_diagnosis_result = {
                        "success": True,
                        "abnormal_nodes": diag_output.get("abnormal_nodes", []),
                        "summary": diag_output.get("summary", {}),
                        "details": diag_output
                    }
                except json.JSONDecodeError:
                    node_diagnosis_result["note"] = "节点诊断完成，但输出解析失败"
        except subprocess.TimeoutExpired:
            node_diagnosis_result["note"] = "节点诊断超时"
        except Exception as e:
            node_diagnosis_result["note"] = f"节点诊断执行失败: {str(e)}"
    
    diagnosis_data["node_diagnosis"] = node_diagnosis_result
    
    # ===== 步骤4: 网络链路诊断 =====
    network_diagnosis_result = {
        "success": False,
        "chain": {},
        "analysis": {},
        "details": {}
    }
    
    if workload_name:
        # 先获取服务链路信息
        service_chain = get_service_chain(region, cluster_id, workload_name, namespace, 
                                          access_key, secret_key, project_id)
        network_diagnosis_result["chain"] = service_chain
        
        # 执行网络诊断（调用network_diagnosis.py）
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            network_diag_script = os.path.join(script_dir, "network_diagnosis.py")
            
            cmd = [
                "python3", network_diag_script, "huawei_network_diagnose",
                f"region={region}",
                f"cluster_id={cluster_id}",
                f"workload_name={workload_name}",
                f"namespace={namespace}",
                f"ak={access_key}",
                f"sk={secret_key}",
                f"project_id={project_id}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                try:
                    diag_output = json.loads(result.stdout)
                    network_diagnosis_result = {
                        "success": True,
                        "chain": service_chain,
                        "analysis": diag_output.get("analysis", {}),
                        "details": diag_output
                    }
                except json.JSONDecodeError:
                    network_diagnosis_result["note"] = "网络诊断输出解析失败"
        except subprocess.TimeoutExpired:
            network_diagnosis_result["note"] = "网络诊断超时"
        except Exception as e:
            network_diagnosis_result["note"] = f"网络诊断执行失败: {str(e)}"
    
    diagnosis_data["network_diagnosis"] = network_diagnosis_result
    
    # ===== 步骤5: 变更信息分析 =====
    # 获取工作负载相关事件
    all_events = []
    events_result = get_kubernetes_events(region, cluster_id, access_key, secret_key, project_id, namespace, limit=500)
    if events_result.get("success") and events_result.get("events"):
        for event in events_result.get("events", []):
            if workload_name and workload_name in event.get("involved_object", {}).get("name", ""):
                all_events.append(event)
            elif not workload_name:
                all_events.append(event)
    
    # 关联性分析
    change_correlation = analyze_change_correlation(diagnosis_data["workloads"], all_events, fault_time)
    diagnosis_data["change_correlation"] = change_correlation
    
    # ===== 步骤6: 获取告警信息 =====
    if workload_name and cluster_name:
        alarms = get_workload_alarms(region, cluster_name, namespace, workload_name, 
                                     access_key, secret_key, project_id, hours=1)
        diagnosis_data["alarms"] = alarms
    
    # ===== 生成诊断报告 =====
    report = generate_diagnosis_report(diagnosis_data)
    report["steps_completed"] = [
        "1. 收集工作负载基础信息",
        "2. 诊断异常Pod状态",
        "3. 准备节点诊断（需要调用hawaii_node_diagnose工具）",
        "4. 准备网络链路诊断（需要调用huawei_network_diagnose工具）",
        "5. 分析变更信息关联性"
    ]
    
    return {
        "success": True,
        "diagnosis": diagnosis_data,
        "report": report
    }


def workload_diagnose_by_alarm(region: str, cluster_id: str, alarm_info: str,
                               ak: str = None, sk: str = None, project_id: str = None) -> Dict[str, Any]:
    """
    基于告警进行工作负载诊断
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        alarm_info: 告警信息（JSON格式或告警名称）
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
    
    Returns:
        诊断报告
    """
    # 解析告警信息，提取工作负载信息
    workload_name = None
    namespace = "default"
    fault_time = None
    
    try:
        alarm_data = json.loads(alarm_info)
        # 从告警中提取工作负载信息
        resource_id = alarm_data.get("resource_id", "")
        alarm_name = alarm_data.get("alarm_name", "")
        alarm_time = alarm_data.get("alarm_time", "")
        
        # 尝试从resource_id中提取namespace和name
        if "namespace=" in resource_id:
            import re
            ns_match = re.search(r'namespace:([^,;]+)', resource_id)
            if ns_match:
                namespace = ns_match.group(1)
        
        # 尝试提取工作负载名称
        if "name=" in resource_id:
            name_match = re.search(r'name:([^,;]+)', resource_id)
            if name_match:
                workload_name = name_match.group(1)
        
        # 告警时间作为故障时间点
        if alarm_time:
            fault_time = alarm_time
            
    except:
        # 如果不是JSON，可能是告警名称
        alarm_name = alarm_info
        # 尝试从名称推断
        if "." in alarm_name:
            parts = alarm_name.split(".")
            if len(parts) >= 2:
                workload_name = parts[0]
                namespace = parts[1] if len(parts) > 1 else "default"
    
    # 执行诊断
    return workload_diagnose(region, cluster_id, workload_name, namespace, ak, sk, project_id, fault_time)


def verify_workload_after_operation(region: str, cluster_id: str, workload_name: str,
                                     namespace: str = "default", ak: str = None, sk: str = None,
                                     project_id: str = None) -> Dict[str, Any]:
    """恢复操作后检查工作负载状态"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials are required"
        }
    
    # 获取工作负载信息
    namespace_workloads = get_namespace_workloads(region, cluster_id, namespace, access_key, secret_key, project_id)
    
    # 找到目标工作负载
    target_pods = []
    for pod in namespace_workloads.get("pods", []):
        if workload_name and workload_name in pod.get("name", ""):
            target_pods.append(pod)
    
    # 分析状态
    abnormal_count = 0
    running_count = 0
    for pod in target_pods:
        analysis = analyze_pod_status(pod)
        if analysis.get("is_abnormal"):
            abnormal_count += 1
        elif "Running" in pod.get("status", ""):
            running_count += 1
    
    return {
        "success": True,
        "workload_name": workload_name,
        "namespace": namespace,
        "total_pods": len(target_pods),
        "running_pods": running_count,
        "abnormal_pods": abnormal_count,
        "status": "RECOVERED" if abnormal_count == 0 else "STILL_ABNORMAL",
        "check_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "pods": target_pods
    }


# ========== CLI 入口 ==========

def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "error": "Missing action parameter"
        }))
        sys.exit(1)

    action = sys.argv[1]

    # 解析参数
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
    workload_name = params.get("workload_name")
    namespace = params.get("namespace", "default")
    alarm_info = params.get("alarm_info")
    fault_time = params.get("fault_time")
    replicas = params.get("replicas", "3")
    nodepool_id = params.get("nodepool_id")
    node_count = params.get("node_count", "1")
    confirm = params.get("confirm", "false").lower() == "true"

    if action == "huawei_workload_diagnose":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        result = workload_diagnose(region, cluster_id, workload_name, namespace, ak, sk, project_id, fault_time)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_workload_diagnose_by_alarm":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        alarm_val = alarm_info or params.get("alarm", "")
        if not alarm_val:
            # 如果没有告警信息，尝试通过namespace查找所有工作负载
            pass
        
        result = workload_diagnose_by_alarm(region, cluster_id, alarm_val, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_verify_workload":
        if not region or not cluster_id or not workload_name:
            print(json.dumps({"success": False, "error": "region, cluster_id, and workload_name are required"}))
            sys.exit(1)
        
        result = verify_workload_after_operation(region, cluster_id, workload_name, namespace, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_scale_workload":
        if not region or not cluster_id or not workload_name:
            print(json.dumps({"success": False, "error": "region, cluster_id, and workload_name are required"}))
            sys.exit(1)
        
        try:
            replicas = int(replicas)
        except:
            replicas = 3
        
        # 调用scale_cce_workload
        result = scale_cce_workload(region, cluster_id, "Deployment", workload_name, 
                                    namespace, replicas, confirm, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_expand_nodepool":
        if not region or not cluster_id or not nodepool_id:
            print(json.dumps({"success": False, "error": "region, cluster_id, and nodepool_id are required"}))
            sys.exit(1)
        
        try:
            node_count = int(node_count)
        except:
            node_count = 1
        
        # 调用resize_node_pool
        result = resize_node_pool(region, cluster_id, nodepool_id, node_count, confirm, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({
            "success": False,
            "error": f"Unknown action: {action}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()