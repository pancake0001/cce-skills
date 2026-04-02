#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集群网络问题诊断工具

功能：
1. 基于告警或用户输入的工作负载进行诊断
2. 分析工作负载的监控信息和告警信息
3. 梳理工作负载的链路（Service、Ingress、Nginx-Ingress、ELB、NAT、EIP）
4. 分析链路组件的监控和告警
5. 检查工作负载的事件和日志
6. 检查 CoreDNS 的监控和配置
7. 生成分析报告

使用方式：
    python network_diagnosis.py huawei_network_diagnose region=cn-north-4 cluster_id=xxx workload_name=xxx namespace=default
    
    # 基于告警诊断
    python network_diagnosis.py huawei_network_diagnose_by_alarm region=cn-north-4 cluster_id=xxx alarm_info=xxx
"""

import os
import sys
import json
import time
import warnings
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
list_aom_instances = huawei_cloud.list_aom_instances
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods
get_kubernetes_services = huawei_cloud.get_kubernetes_services
get_kubernetes_ingresses = huawei_cloud.get_kubernetes_ingresses
get_kubernetes_deployments = huawei_cloud.get_kubernetes_deployments
get_kubernetes_nodes = huawei_cloud.get_kubernetes_nodes
get_kubernetes_events = huawei_cloud.get_kubernetes_events
get_kubernetes_namespaces = huawei_cloud.get_kubernetes_namespaces
list_cce_cluster_nodes = huawei_cloud.list_cce_cluster_nodes
list_cce_addons = huawei_cloud.list_cce_addons
get_cce_kubeconfig = huawei_cloud.get_cce_kubeconfig
get_elb_metrics = huawei_cloud.get_elb_metrics
get_eip_metrics = huawei_cloud.get_eip_metrics
list_eip_addresses = huawei_cloud.list_eip_addresses
list_nat_gateways = huawei_cloud.list_nat_gateways


# ========== 诊断工具函数 ==========

def get_aom_instance(region: str, ak: str, sk: str, project_id: str = None) -> Optional[str]:
    """获取CCE类型的AOM实例ID"""
    result = list_aom_instances(region, ak, sk, project_id, prom_type="CCE")
    if result.get("success") and result.get("instances"):
        for inst in result.get("instances", []):
            if inst.get("prom_type") == "CCE" or inst.get("prom_type") == "K8S":
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


def get_target_pods(region: str, cluster_id: str, workload_name: str, namespace: str, 
                    ak: str, sk: str, project_id: str = None) -> List[Dict]:
    """获取目标工作负载的Pod列表"""
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, namespace)
    target_pods = []
    
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            # 匹配工作负载名称（Pod名称通常以deploymentname-xxx格式）
            if workload_name in pod.get("name", ""):
                target_pods.append(pod)
    
    return target_pods


def get_pod_metrics(pod_name: str, namespace: str, cluster_name: str, 
                    aom_instance_id: str, region: str, ak: str, sk: str, 
                    project_id: str = None, hours: int = 1) -> Dict[str, Any]:
    """获取Pod的CPU和内存监控数据（近一个小时）"""
    metrics_result = {
        "cpu": {},
        "memory": {}
    }
    
    try:
        # CPU 使用率查询
        cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{cluster_name="{cluster_name}",namespace="{namespace}",pod=~"{pod_name}.*"}}[5m])) by (pod) * 100'
        cpu_result = get_aom_prom_metrics_http(
            region, aom_instance_id, cpu_query, hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )
        if cpu_result.get("success"):
            metrics_result["cpu"] = cpu_result
        
        # 内存使用率查询
        mem_query = f'container_memory_working_set_bytes{{cluster_name="{cluster_name}",namespace="{namespace}",pod=~"{pod_name}.*"}}'
        mem_result = get_aom_prom_metrics_http(
            region, aom_instance_id, mem_query, hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )
        if mem_result.get("success"):
            metrics_result["memory"] = mem_result
            
    except Exception as e:
        metrics_result["error"] = str(e)
    
    return metrics_result


def get_node_metrics(node_ip: str, region: str, ak: str, sk: str, 
                     project_id: str = None, hours: int = 1) -> Dict[str, Any]:
    """获取节点的CPU、内存、网络监控数据"""
    metrics_result = {
        "cpu": {},
        "memory": {},
        "network": {}
    }
    
    try:
        # CPU 使用率
        cpu_query = f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{instance="{node_ip}",mode="idle"}}[5m])) * 100)'
        cpu_result = get_aom_prom_metrics_http(
            region, "", cpu_query, hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )
        if cpu_result.get("success"):
            metrics_result["cpu"] = cpu_result
        
        # 内存使用率
        mem_query = f'(1 - node_memory_MemAvailable_bytes{{instance="{node_ip}"}} / node_memory_MemTotal_bytes{{instance="{node_ip}"}}) * 100'
        mem_result = get_aom_prom_metrics_http(
            region, "", mem_query, hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )
        if mem_result.get("success"):
            metrics_result["memory"] = mem_result
        
        # 网络流量
        net_query = f'rate(node_network_receive_bytes_total{{instance="{node_ip}"}}[5m])'
        net_result = get_aom_prom_metrics_http(
            region, "", net_query, hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )
        if net_result.get("success"):
            metrics_result["network"] = net_result
            
    except Exception as e:
        metrics_result["error"] = str(e)
    
    return metrics_result


def get_service_chain(workload_name: str, namespace: str, region: str, cluster_id: str,
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
            # 检查ingress的backend是否关联到目标service
            http_rules = ing.get("http_rules", [])
            for rule in http_rules:
                backend = rule.get("backend", {})
                service_name = backend.get("service", {}).get("name")
                if service_name == workload_name or service_name == chain["service"]["name"]:
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
    
    # 如果有ELB，尝试获取EIP信息
    if chain.get("elb") and chain["elb"].get("ip"):
        eip_result = list_eip_addresses(region, ak, sk, project_id)
        if eip_result.get("success") and eip_result.get("eips"):
            for eip in eip_result.get("eips", []):
                if eip.get("ip_address") == chain["elb"].get("ip"):
                    chain["eip"] = {
                        "id": eip.get("id"),
                        "ip_address": eip.get("ip_address"),
                        "bandwidth": eip.get("bandwidth_size"),
                        "type": eip.get("type")
                    }
                    break
    
    # 检查NAT网关 - 需要关联到工作负载所在VPC
    # 简化处理：如果有通过ELB/NLB的LoadBalancer服务，才需要关心NAT
    # ClusterIP类型不需要NAT
    if chain.get("service") and chain["service"].get("type") == "LoadBalancer":
        # 通过ELB访问时，检查该VPC是否有NAT（用于ELB的后端通信）
        nat_result = list_nat_gateways(region, ak, sk, project_id)
        if nat_result.get("success") and nat_result.get("nat_gateways"):
            # 简化：对于CCE集群，通常使用ENI或NAT通过ELB访问
            # 这里只标记有NAT网关存在，不一定与该工作负载直接相关
            chain["nat"] = {
                "count": len(nat_result.get("nat_gateways", [])),
                "note": "NAT网关存在，但无法确定是否与该工作负载直接关联",
                "gateways": [{
                    "id": nat.get("id"),
                    "name": nat.get("name"),
                    "status": nat.get("status")
                } for nat in nat_result.get("nat_gateways", [])[:3]]
            }
        else:
            chain["nat"] = None
    else:
        # ClusterIP服务不需要NAT
        chain["nat"] = None
    
    return chain


def analyze_chain_components(chain: Dict, region: str, ak: str, sk: str, 
                              project_id: str = None, hours: int = 1) -> Dict[str, Any]:
    """分析链路所有组件的监控和告警"""
    analysis = {
        "elb": {"status": "N/A", "metrics": {}, "alerts": []},
        "eip": {"status": "N/A", "metrics": {}, "alerts": []},
        "nat": {"status": "N/A", "metrics": {}, "alerts": []},
        "nodes": {},
        "nginx_ingress": {"status": "N/A", "metrics": {}, "alerts": []}
    }
    
    # 分析ELB
    if chain.get("elb"):
        elb_id = chain["elb"].get("id")
        if elb_id:
            elb_metrics = get_elb_metrics(region, elb_id, ak, sk, project_id)
            if elb_metrics.get("success"):
                summary = elb_metrics.get("summary", {})
                analysis["elb"] = {
                    "status": "WARNING" if summary.get("l4_bandwidth_usage_percent", 0) > 80 else "OK",
                    "metrics": {
                        "connection_num": summary.get("connection_num"),
                        "bandwidth_usage_percent": summary.get("l4_bandwidth_usage_percent"),
                        "connection_usage_percent": summary.get("l4_connection_usage_percent"),
                        "normal_servers": summary.get("normal_servers"),
                        "abnormal_servers": summary.get("abnormal_servers")
                    },
                    "alerts": []
                }
                
                # 检查告警阈值
                if summary.get("l4_bandwidth_usage_percent", 0) > 80:
                    analysis["elb"]["alerts"].append(f"ELB带宽使用率已达 {summary.get('l4_bandwidth_usage_percent')}%")
                if summary.get("l4_connection_usage_percent", 0) > 80:
                    analysis["elb"]["alerts"].append(f"ELB连接使用率已达 {summary.get('l4_connection_usage_percent')}%")
                if summary.get("abnormal_servers", 0) > 0:
                    analysis["elb"]["alerts"].append(f"ELB后端有 {summary.get('abnormal_servers')} 个异常服务器")
    
    # 分析EIP
    if chain.get("eip"):
        eip_id = chain["eip"].get("id")
        if eip_id:
            eip_metrics = get_eip_metrics(region, eip_id, ak, sk, project_id)
            if eip_metrics.get("success"):
                summary = eip_metrics.get("summary", {})
                analysis["eip"] = {
                    "status": "WARNING" if summary.get("bw_usage_in_percent", 0) > 80 else "OK",
                    "metrics": {
                        "bw_usage_in_percent": summary.get("bw_usage_in_percent"),
                        "bw_usage_out_percent": summary.get("bw_usage_out_percent")
                    },
                    "alerts": []
                }
                
                if summary.get("bw_usage_in_percent", 0) > 80:
                    analysis["eip"]["alerts"].append(f"EIP入带宽使用率已达 {summary.get('bw_usage_in_percent')}%")
                if summary.get("bw_usage_out_percent", 0) > 80:
                    analysis["eip"]["alerts"].append(f"EIP出带宽使用率已达 {summary.get('bw_usage_out_percent')}%")
    
    # 分析节点
    for node_ip in chain.get("nodes", []):
        node_metrics = get_node_metrics(node_ip, region, ak, sk, project_id, hours)
        analysis["nodes"][node_ip] = node_metrics
    
    return analysis


def check_coredns_status(region: str, cluster_id: str, ak: str, sk: str, 
                         project_id: str = None, hours: int = 1) -> Dict[str, Any]:
    """检查CoreDNS的监控和配置"""
    result = {
        "status": "OK",
        "pods": [],
        "metrics": {},
        "alerts": [],
        "config": {}
    }
    
    # 获取kube-system命名空间的coredns pods
    pods_result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, "kube-system")
    if pods_result.get("success") and pods_result.get("pods"):
        for pod in pods_result.get("pods", []):
            if "coredns" in pod.get("name", "").lower():
                result["pods"].append({
                    "name": pod.get("name"),
                    "status": pod.get("status"),
                    "ready": pod.get("ready"),
                    "restarts": pod.get("restart_count", 0),
                    "age": pod.get("age")
                })
                
                if "Error" in pod.get("status", "") or "CrashLoopBackOff" in pod.get("status", ""):
                    result["status"] = "ERROR"
                    result["alerts"].append(f"CoreDNS Pod {pod.get('name')} 状态异常: {pod.get('status')}")
    
    # 获取CoreDNS addon信息
    addons_result = list_cce_addons(region, cluster_id, ak, sk, project_id)
    if addons_result.get("success") and addons_result.get("addons"):
        for addon in addons_result.get("addons", []):
            if "coredns" in addon.get("name", "").lower():
                result["config"] = {
                    "name": addon.get("name"),
                    "version": addon.get("version"),
                    "status": addon.get("status")
                }
    
    # 如果有AOM，获取CoreDNS的监控指标
    aom_id = get_aom_instance(region, ak, sk, project_id)
    if aom_id:
        cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
        
        # CoreDNS请求监控
        dns_query = 'sum(rate(coredns_dns_requests_total[5m])) by (pod)'
        dns_result = get_aom_prom_metrics_http(region, aom_id, dns_query, hours=hours, ak=ak, sk=sk, project_id=project_id)
        if dns_result.get("success"):
            result["metrics"]["requests"] = dns_result
        
        # CoreDNS错误监控
        error_query = 'sum(rate(coredns_dns_responses_total{rcode!~"NOERROR|Success"}[5m])) by (pod)'
        error_result = get_aom_prom_metrics_http(region, aom_id, error_query, hours=hours, ak=ak, sk=sk, project_id=project_id)
        if error_result.get("success"):
            result["metrics"]["errors"] = error_result
    
    return result


def get_pod_events(workload_name: str, namespace: str, region: str, cluster_id: str,
                   ak: str, sk: str, project_id: str = None) -> List[Dict]:
    """获取工作负载相关的事件"""
    events_result = get_kubernetes_events(region, cluster_id, ak, sk, project_id, namespace, limit=500)
    target_events = []
    
    if events_result.get("success") and events_result.get("events"):
        for event in events_result.get("events", []):
            # 匹配相关Pod的事件
            if workload_name in event.get("involved_object", {}).get("name", ""):
                target_events.append({
                    "type": event.get("type"),
                    "reason": event.get("reason"),
                    "message": event.get("message"),
                    "first_timestamp": event.get("first_timestamp"),
                    "last_timestamp": event.get("last_timestamp"),
                    "count": event.get("count", 1)
                })
    
    return target_events


def generate_network_topology(chain: Dict, analysis: Dict) -> str:
    """生成网络拓扑图（文本格式）"""
    topology = []
    topology.append("=" * 60)
    topology.append("网络链路拓扑图")
    topology.append("=" * 60)
    
    # 绘制链路
    components = []
    
    # 用户/外部流量
    topology.append("[外部流量] → ")
    
    # EIP
    if chain.get("eip"):
        status = "🔴" if analysis.get("eip", {}).get("status") == "WARNING" else "🟢"
        components.append(f"{status}[EIP: {chain['eip'].get('ip_address')}]")
    
    # ELB
    if chain.get("elb"):
        status = "🔴" if analysis.get("elb", {}).get("status") == "WARNING" else "🟢"
        components.append(f"{status}[ELB: {chain['elb'].get('id')[:8]}...]")
    
    # NAT (如果有)
    if chain.get("nat") and chain["nat"].get("count", 0) > 0:
        components.append(f"[NAT Gateway]")
    
    # Nginx Ingress
    if chain.get("nginx_ingress"):
        components.append(f"[Nginx Ingress Controller]")
    
    # Ingress
    if chain.get("ingress"):
        components.append(f"[Ingress: {chain['ingress'].get('name')}]")
    
    # Service
    if chain.get("service"):
        svc_type = chain["service"].get("type", "ClusterIP")
        components.append(f"[Service: {chain['service'].get('name')} ({svc_type})]")
    
    # Workload (Pods)
    pod_count = len(chain.get("pods", []))
    components.append(f"[Workload: {chain['workload'].get('name')}] ({pod_count} pods)")
    
    # Nodes
    if chain.get("nodes"):
        components.append(f"  └─ 部署节点: {', '.join(chain['nodes'])}")
    
    topology.append(" → ".join(components))
    
    # 告警摘要
    all_alerts = []
    if analysis.get("elb", {}).get("alerts"):
        all_alerts.extend(analysis["elb"]["alerts"])
    if analysis.get("eip", {}).get("alerts"):
        all_alerts.extend(analysis["eip"]["alerts"])
    if analysis.get("nodes"):
        for node_ip, node_data in analysis["nodes"].items():
            if node_data.get("error"):
                all_alerts.append(f"节点 {node_ip} 监控获取失败")
    
    if all_alerts:
        topology.append("\n\n⚠️ 告警摘要:")
        for alert in all_alerts:
            topology.append(f"  - {alert}")
    
    return "\n".join(topology)


def network_diagnose(region: str, cluster_id: str, workload_name: str = None, 
                     namespace: str = "default", ak: str = None, sk: str = None, 
                     project_id: str = None) -> Dict[str, Any]:
    """
    网络问题诊断主函数
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        workload_name: 工作负载名称（可选，如果不提供则诊断整个集群）
        namespace: 命名空间（默认default）
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
    
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
    
    # 初始化诊断报告
    report = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "workload_name": workload_name,
        "namespace": namespace,
        "diagnosis_time": datetime.now().isoformat(),
        "steps_completed": [],
        "workload_info": {},
        "chain": {},
        "chain_analysis": {},
        "coredns_status": {},
        "events": [],
        "topology": "",
        "operations": [],
        "recommendations": []
    }
    
    # 获取集群名称
    cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
    report["cluster_name"] = cluster_name
    
    # 获取AOM实例
    aom_instance_id = get_aom_instance(region, ak, sk, project_id)
    report["aom_instance_id"] = aom_instance_id
    
    # ===== 步骤1: 分析工作负载的监控和告警 =====
    if workload_name:
        report["steps_completed"].append("1. 分析工作负载监控和告警")
        
        # 获取目标Pods
        target_pods = get_target_pods(region, cluster_id, workload_name, namespace, ak, sk, project_id)
        report["workload_info"]["pods"] = target_pods
        report["workload_info"]["pod_count"] = len(target_pods)
        
        if target_pods and aom_instance_id:
            # 获取监控数据
            pod_metrics = get_pod_metrics(workload_name, namespace, cluster_name, aom_instance_id, 
                                          region, ak, sk, project_id)
            report["workload_info"]["metrics"] = pod_metrics
            
            # 分析是否有CPU/内存异常
            cpu_data = pod_metrics.get("cpu", {}).get("data", [])
            mem_data = pod_metrics.get("memory", {}).get("data", [])
            
            if cpu_data:
                cpu_values = []
                for item in cpu_data:
                    values = item.get("values", [])
                    if values:
                        cpu_values.append(float(values[-1][1]) if len(values) > 0 else 0)
                
                if cpu_values:
                    avg_cpu = sum(cpu_values) / len(cpu_values)
                    if avg_cpu > 80:
                        report["recommendations"].append({
                            "category": "CPU告警",
                            "issue": f"工作负载平均CPU使用率 {avg_cpu:.1f}%",
                            "suggestion": "建议扩容工作负载实例或增加CPU资源限制"
                        })
        
        # 获取工作负载的事件
        events = get_pod_events(workload_name, namespace, region, cluster_id, ak, sk, project_id)
        report["events"] = events
        
        if events:
            # 检查关键事件
            error_events = [e for e in events if e.get("type") in ["Warning", "Error"]]
            if error_events:
                report["workload_info"]["has_error_events"] = True
                report["workload_info"]["error_events"] = error_events[:10]  # 只保留前10条
    
    # ===== 步骤2: 梳理工作负载的链路 =====
    if workload_name:
        report["steps_completed"].append("2. 梳理工作负载链路")
        
        chain = get_service_chain(workload_name, namespace, region, cluster_id, ak, sk, project_id)
        report["chain"] = chain
        
        # ===== 步骤3: 分析链路组件的监控和告警 =====
        report["steps_completed"].append("3. 分析链路组件监控和告警")
        
        chain_analysis = analyze_chain_components(chain, region, ak, sk, project_id)
        report["chain_analysis"] = chain_analysis
        
        # 根据分析结果添加建议
        if chain_analysis.get("elb", {}).get("alerts"):
            for alert in chain_analysis["elb"]["alerts"]:
                report["recommendations"].append({
                    "category": "ELB",
                    "issue": alert,
                    "suggestion": "考虑扩容ELB带宽或规格"
                })
        
        if chain_analysis.get("eip", {}).get("alerts"):
            for alert in chain_analysis["eip"]["alerts"]:
                report["recommendations"].append({
                    "category": "EIP",
                    "issue": alert,
                    "suggestion": "考虑增加EIP带宽或更换高带宽EIP"
                })
    
    # ===== 步骤4: 检查CoreDNS状态 =====
    report["steps_completed"].append("4. 检查CoreDNS状态")
    
    coredns_status = check_coredns_status(region, cluster_id, ak, sk, project_id)
    report["coredns_status"] = coredns_status
    
    if coredns_status.get("status") != "OK":
        report["recommendations"].append({
            "category": "CoreDNS",
            "issue": f"CoreDNS状态异常: {coredns_status.get('status')}",
            "suggestion": "检查CoreDNS配置和Pods状态"
        })
    
    # ===== 生成网络拓扑图 =====
    if workload_name and report.get("chain"):
        report["topology"] = generate_network_topology(report["chain"], report.get("chain_analysis", {}))
    
    return report


def network_diagnose_by_alarm(region: str, cluster_id: str, alarm_info: str,
                               ak: str = None, sk: str = None, project_id: str = None) -> Dict[str, Any]:
    """
    基于告警进行网络诊断
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        alarm_info: 告警信息（通常是告警的名称或JSON）
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
    
    Returns:
        诊断报告
    """
    # 解析告警信息，提取工作负载信息
    workload_name = None
    namespace = "default"
    
    try:
        # 尝试解析JSON
        alarm_data = json.loads(alarm_info)
        # 从告警中提取工作负载信息
        # 这里的解析逻辑可以根据实际告警格式调整
        resource_id = alarm_data.get("resource_id", "")
        # 尝试从resource_id中提取namespace和name
        if "namespace=" in resource_id:
            import re
            ns_match = re.search(r'namespace:([^,;]+)', resource_id)
            if ns_match:
                namespace = ns_match.group(1)
        
    except:
        # 如果不是JSON，可能是告警名称，直接使用
        pass
    
    # 从工作负载名称推断namespace（通常在告警中）
    if not workload_name and "." in alarm_info:
        parts = alarm_info.split(".")
        workload_name = parts[0]
    
    # 执行诊断
    return network_diagnose(region, cluster_id, workload_name, namespace, ak, sk, project_id)


def scale_workload(region: str, cluster_id: str, workload_name: str, namespace: str,
                   replica_count: int, ak: str, sk: str, project_id: str = None,
                   confirm: bool = False) -> Dict[str, Any]:
    """扩缩容工作负载（需要确认）
    
    ⚠️ 二次确认机制：
    - 第一步：不带 confirm 参数调用，返回确认提示
    - 第二步：带 confirm=true 再次调用，执行操作
    
    Example:
        # 第一步：预览操作
        huawei_network_scale_workload region=xxx cluster_id=xxx workload_name=my-app namespace=default replica_count=5
        
        # 第二步：确认执行
        huawei_network_scale_workload region=xxx cluster_id=xxx workload_name=my-app namespace=default replica_count=5 confirm=true
    """
    
    # ========== 二次确认机制 ==========
    if not confirm:
        return {
            "success": False,
            "requires_confirmation": True,
            "operation": "scale_workload",
            "warning": f"⚠️ 危险操作：即将扩缩容工作负载 '{workload_name}' (命名空间: {namespace}) 到 {replica_count} 个副本",
            "cluster_id": cluster_id,
            "namespace": namespace,
            "name": workload_name,
            "target_replicas": replica_count,
            "hint": "确认操作请添加 confirm=true 参数",
            "example": f"huawei_network_scale_workload region={region} cluster_id={cluster_id} workload_name={workload_name} namespace={namespace} replica_count={replica_count} confirm=true"
        }
    
    # 获取凭证
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }
    
    # 这里需要调用K8s API进行扩缩容
    # 需要先获取kubeconfig
    kubeconfig_result = get_cce_kubeconfig(region, cluster_id, access_key, secret_key, proj_id)
    
    if not kubeconfig_result.get("success"):
        return kubeconfig_result
    
    # 简化版本：返回操作信息，实际操作需要使用kubectl
    return {
        "success": True,
        "message": f"工作负载扩缩容需要在集群本地执行",
        "operation": "scale_workload",
        "cluster_id": cluster_id,
        "namespace": namespace,
        "name": workload_name,
        "target_replicas": replica_count,
        "command": f"kubectl scale deployment {workload_name} -n {namespace} --replicas={replica_count}",
        "note": "此操作需要集群的kubectl访问权限"
    }


def verify_pod_scheduling_after_scale(region: str, cluster_id: str, workload_name: str, 
                                       namespace: str, ak: str, sk: str, 
                                       project_id: str = None) -> Dict[str, Any]:
    """扩缩容后验证Pod调度状态
    
    检查步骤2.5：扩容节点池后观察工作负载状态
    
    - Pod是否成功调度
    - Pod是否 Running
    - 容器是否有重启
    - Pod是否均匀分布在节点上
    
    Args:
        region: 华为云区域
        cluster_id: CCE集群ID
        workload_name: 工作负载名称
        namespace: 命名空间
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
    
    Returns:
        验证结果报告
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "success": True,
        "operation": "verify_pod_scheduling",
        "workload_name": workload_name,
        "namespace": namespace,
        "timestamp": datetime.now().isoformat(),
        "pods": [],
        "summary": {
            "total": 0,
            "running": 0,
            "pending": 0,
            "failed": 0,
            "restarting": 0
        },
        "node_distribution": {},
        "issues": [],
        "status": "OK"
    }
    
    # 获取Pods
    pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id, namespace)
    
    if not pods_result.get("success"):
        return {
            "success": False,
            "error": f"获取Pod列表失败: {pods_result.get('error')}"
        }
    
    target_pods = []
    for pod in pods_result.get("pods", []):
        if workload_name in pod.get("name", ""):
            target_pods.append(pod)
    
    result["pods"] = target_pods
    result["summary"]["total"] = len(target_pods)
    
    # 分析每个Pod的状态
    for pod in target_pods:
        pod_name = pod.get("name", "")
        pod_status = pod.get("status", "")
        
        # 检查调度状态
        if pod_status == "Pending":
            result["summary"]["pending"] += 1
            result["issues"].append({
                "severity": "ERROR",
                "pod": pod_name,
                "issue": "Pod处于Pending状态，未被调度",
                "reason": pod.get("reason", "Unknown")
            })
            result["status"] = "ERROR"
        
        elif pod_status == "Running":
            result["summary"]["running"] += 1
            
            # 检查容器状态
            containers = pod.get("containers", [])
            for container in containers:
                restart_count = container.get("restart_count", 0)
                if restart_count > 5:
                    result["summary"]["restarting"] += 1
                    # 处理可能的字符串类型state
                    container_state = container.get("state")
                    if isinstance(container_state, dict):
                        reason = container_state.get("waiting", {}).get("reason", "Unknown") if isinstance(container_state.get("waiting"), dict) else "Unknown"
                    else:
                        reason = str(container_state) if container_state else "Unknown"
                    
                    result["issues"].append({
                        "severity": "WARNING",
                        "pod": pod_name,
                        "container": container.get("name"),
                        "issue": f"容器重启次数过多: {restart_count}",
                        "reason": reason
                    })
                    if result["status"] == "OK":
                        result["status"] = "WARNING"
        
        elif pod_status in ["Failed", "Error"]:
            result["summary"]["failed"] += 1
            result["issues"].append({
                "severity": "ERROR",
                "pod": pod_name,
                "issue": f"Pod状态异常: {pod_status}"
            })
            result["status"] = "ERROR"
        
        # 统计节点分布
        node_ip = pod.get("node")
        if node_ip:
            if node_ip not in result["node_distribution"]:
                result["node_distribution"][node_ip] = 0
            result["node_distribution"][node_ip] += 1
    
    # 生成总结
    if result["summary"]["pending"] > 0:
        result["message"] = f"发现 {result['summary']['pending']} 个Pod未被调度，请检查节点资源或调度限制"
    elif result["summary"]["failed"] > 0:
        result["message"] = f"发现 {result['summary']['failed']} 个Pod运行失败"
    elif result["summary"]["restarting"] > 0:
        result["message"] = f"发现 {result['summary']['restarting']} 个容器频繁重启"
    else:
        result["message"] = f"所有 {result['summary']['running']} 个Pod运行正常"
    
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
    workload_name = params.get("workload_name")
    namespace = params.get("namespace", "default")
    alarm_info = params.get("alarm_info")
    replica_count = params.get("replica_count", "3")
    confirm = params.get("confirm", "false").lower() == "true"

    if action == "huawei_network_diagnose":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        result = network_diagnose(region, cluster_id, workload_name, namespace, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_network_diagnose_by_alarm":
        if not region or not cluster_id or not alarm_info:
            print(json.dumps({"success": False, "error": "region, cluster_id, and alarm_info are required"}))
            sys.exit(1)
        
        result = network_diagnose_by_alarm(region, cluster_id, alarm_info, ak, sk, project_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "huawei_network_scale_workload":
        if not region or not cluster_id or not workload_name:
            print(json.dumps({"success": False, "error": "region, cluster_id, and workload_name are required"}))
            sys.exit(1)
        
        try:
            replica_count = int(replica_count)
        except:
            replica_count = 3
        
        result = scale_workload(region, cluster_id, workload_name, namespace, 
                               replica_count, ak, sk, project_id, confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({
            "success": False,
            "error": f"Unknown action: {action}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()