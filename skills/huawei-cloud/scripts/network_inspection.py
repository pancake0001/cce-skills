#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网络巡检模块

包含：
- ELB 负载均衡监控巡检
- EIP 带宽监控
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
get_kubernetes_services = huawei_cloud.get_kubernetes_services
get_elb_metrics = huawei_cloud.get_elb_metrics
get_eip_metrics = huawei_cloud.get_eip_metrics
list_eip_addresses = huawei_cloud.list_eip_addresses


def elb_monitoring_inspection(region: str, cluster_id: str, aom_instance_id: str,
                               cluster_name: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """ELB 负载均衡监控巡检
    
    检查内容：
    - LoadBalancer Service 列表
    - ELB 监控指标 (连接数/带宽/使用率)
    - 公网 EIP 带宽监控
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        aom_instance_id: AOM 实例 ID
        cluster_name: 集群名称
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        ELB 监控巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "ELB负载均衡监控巡检",
        "status": "PASS",
        "checked": False,
        "loadbalancer_services": [],
        "elb_metrics": [],
        "eip_metrics": [],
        "high_bandwidth_usage_elbs": [],
        "high_connection_usage_elbs": [],
        "high_bandwidth_eips": [],
        "total_loadbalancers": 0
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
    
    try:
        services_result = get_kubernetes_services(region, cluster_id, access_key, secret_key, proj_id)
        
        # 获取EIP列表
        eip_list_result = list_eip_addresses(region, access_key, secret_key, proj_id)
        eip_map = {}
        if eip_list_result.get("success"):
            for eip in eip_list_result.get("eips", []):
                eip_map[eip.get("ip_address")] = eip
        
        if services_result.get("success"):
            lb_services = []
            for svc in services_result.get("services", []):
                if svc.get("type") == "LoadBalancer":
                    annotations = svc.get("annotations", {})
                    elb_id = annotations.get("kubernetes.io/elb.id", "")
                    
                    if elb_id:
                        lb_services.append({
                            "service_name": svc.get("name"),
                            "namespace": svc.get("namespace"),
                            "elb_id": elb_id,
                            "cluster_ip": svc.get("cluster_ip"),
                            "load_balancer_ip": svc.get("load_balancer_ip"),
                            "ports": svc.get("ports", []),
                            "annotations": annotations
                        })
            
            result["loadbalancer_services"] = lb_services
            result["total_loadbalancers"] = len(lb_services)
            
            # 获取每个ELB的监控数据
            for lb_svc in lb_services:
                elb_id = lb_svc.get("elb_id")
                if elb_id:
                    elb_metrics_result = get_elb_metrics(region, elb_id, access_key, secret_key, proj_id)
                    
                    if elb_metrics_result.get("success"):
                        summary = elb_metrics_result.get("summary", {})
                        
                        elb_info = {
                            "service_name": lb_svc.get("service_name"),
                            "namespace": lb_svc.get("namespace"),
                            "elb_id": elb_id,
                            "elb_ip": lb_svc.get("load_balancer_ip"),
                            "elb_type": elb_metrics_result.get("elb_type", "未知"),
                            "connection_num": summary.get("connection_num"),
                            "in_bandwidth_bps": summary.get("in_bandwidth_bps"),
                            "l4_connection_usage_percent": summary.get("l4_connection_usage_percent"),
                            "l4_bandwidth_usage_percent": summary.get("l4_bandwidth_usage_percent"),
                            "normal_servers": summary.get("normal_servers"),
                            "abnormal_servers": summary.get("abnormal_servers")
                        }
                        
                        # 检查L4使用率
                        l4_con = summary.get("l4_connection_usage_percent")
                        l4_bw = summary.get("l4_bandwidth_usage_percent")
                        
                        if l4_con and l4_con > 80:
                            result["high_connection_usage_elbs"].append({
                                "service": lb_svc.get("service_name"),
                                "namespace": lb_svc.get("namespace"),
                                "elb_id": elb_id,
                                "layer": "L4",
                                "usage_percent": round(l4_con, 2),
                                "status": "critical" if l4_con > 90 else "warning"
                            })
                            add_issue("WARNING", "ELB连接使用率高", elb_id,
                                f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, L4连接使用率: {round(l4_con, 2)}%")
                        
                        if l4_bw and l4_bw > 80:
                            result["high_bandwidth_usage_elbs"].append({
                                "service": lb_svc.get("service_name"),
                                "namespace": lb_svc.get("namespace"),
                                "elb_id": elb_id,
                                "layer": "L4",
                                "usage_percent": round(l4_bw, 2),
                                "status": "critical" if l4_bw > 90 else "warning"
                            })
                            add_issue("WARNING", "ELB带宽使用率高", elb_id,
                                f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, L4带宽使用率: {round(l4_bw, 2)}%")
                        
                        # 检查是否有公网EIP
                        lb_ip = lb_svc.get("load_balancer_ip")
                        if lb_ip:
                            eip_info = eip_map.get(lb_ip)
                            if eip_info:
                                eip_id = eip_info.get("id")
                                elb_info["has_public_eip"] = True
                                elb_info["public_ip"] = lb_ip
                                elb_info["eip_id"] = eip_id
                                
                                # 获取EIP监控
                                eip_metrics_result = get_eip_metrics(region, eip_id, access_key, secret_key, proj_id)
                                if eip_metrics_result.get("success"):
                                    eip_summary = eip_metrics_result.get("summary", {})
                                    bw_in = eip_summary.get("bw_usage_in_percent")
                                    bw_out = eip_summary.get("bw_usage_out_percent")
                                    
                                    elb_info["eip_bw_usage_in_percent"] = bw_in
                                    elb_info["eip_bw_usage_out_percent"] = bw_out
                                    
                                    result["eip_metrics"].append({
                                        "service_name": lb_svc.get("service_name"),
                                        "namespace": lb_svc.get("namespace"),
                                        "eip_id": eip_id,
                                        "public_ip": lb_ip,
                                        "bw_usage_in_percent": bw_in,
                                        "bw_usage_out_percent": bw_out
                                    })
                                    
                                    # 检查EIP带宽超限
                                    if bw_in and bw_in > 80:
                                        result["high_bandwidth_eips"].append({
                                            "service": lb_svc.get("service_name"),
                                            "namespace": lb_svc.get("namespace"),
                                            "eip_id": eip_id,
                                            "public_ip": lb_ip,
                                            "direction": "in",
                                            "usage_percent": round(bw_in, 2),
                                            "status": "critical" if bw_in > 90 else "warning"
                                        })
                                        add_issue("WARNING", "EIP入带宽超限", eip_id,
                                            f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 公网IP: {lb_ip}, 入带宽使用率: {round(bw_in, 2)}%")
                                    
                                    if bw_out and bw_out > 80:
                                        result["high_bandwidth_eips"].append({
                                            "service": lb_svc.get("service_name"),
                                            "namespace": lb_svc.get("namespace"),
                                            "eip_id": eip_id,
                                            "public_ip": lb_ip,
                                            "direction": "out",
                                            "usage_percent": round(bw_out, 2),
                                            "status": "critical" if bw_out > 90 else "warning"
                                        })
                                        add_issue("WARNING", "EIP出带宽超限", eip_id,
                                            f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 公网IP: {lb_ip}, 出带宽使用率: {round(bw_out, 2)}%")
                        
                        result["elb_metrics"].append(elb_info)
            
            if result["high_bandwidth_usage_elbs"] or result["high_connection_usage_elbs"] or result["high_bandwidth_eips"]:
                result["status"] = "WARN"
                
    except Exception as e:
        result["error"] = str(e)
    
    return result, issues


if __name__ == "__main__":
    print("Network Inspection Module")
    print("Functions:")
    print("  - elb_monitoring_inspection")