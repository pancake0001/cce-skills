#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CCE 集群巡检主模块

整合各子模块执行完整的集群巡检：
- pod_inspection: Pod 状态巡检、插件/业务 Pod 监控巡检
- node_inspection: Node 状态巡检、节点资源监控巡检
- alarm_inspection: Event 巡检、AOM 告警巡检
- network_inspection: ELB 负载均衡监控巡检

报告生成：
- 各独立巡检工具生成各自的详细报告
- 主巡检工具汇总所有结果生成详细汇总报告
"""

import os
import sys
import json
import base64
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入子模块
from pod_inspection import (
    pod_status_inspection,
    addon_pod_monitoring_inspection,
    biz_pod_monitoring_inspection
)
from node_inspection import (
    node_status_inspection,
    node_resource_monitoring_inspection
)
from alarm_inspection import (
    event_inspection,
    aom_alarm_inspection
)
from network_inspection import (
    elb_monitoring_inspection
)

# 导入报告生成器
from report_generator import (
    generate_sub_inspection_report,
    generate_summary_report,
    generate_detailed_html_report,
    generate_sub_inspection_html
)

# 导入主模块的工具函数 - 使用 importlib 导入带横线的模块
import importlib.util
spec = importlib.util.spec_from_file_location("huawei_cloud", os.path.join(os.path.dirname(__file__), "huawei-cloud.py"))
huawei_cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(huawei_cloud)

get_credentials_with_region = huawei_cloud.get_credentials_with_region
get_project_id_for_region = huawei_cloud.get_project_id_for_region
create_cce_client = huawei_cloud.create_cce_client
create_ces_client = huawei_cloud.create_ces_client
create_elb_client = huawei_cloud.create_elb_client
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods
get_kubernetes_nodes = huawei_cloud.get_kubernetes_nodes
get_kubernetes_services = huawei_cloud.get_kubernetes_services
get_kubernetes_events = huawei_cloud.get_kubernetes_events
list_cce_clusters = huawei_cloud.list_cce_clusters
list_aom_instances = huawei_cloud.list_aom_instances
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
get_elb_metrics = huawei_cloud.get_elb_metrics
get_eip_metrics = huawei_cloud.get_eip_metrics
list_eip_addresses = huawei_cloud.list_eip_addresses
SDK_AVAILABLE = huawei_cloud.SDK_AVAILABLE
K8S_AVAILABLE = huawei_cloud.K8S_AVAILABLE


# ========== 辅助函数 (供 action 分发使用) ==========

def _get_aom_instance(region: str, ak: str, sk: str, project_id: str = None) -> str:
    """获取可用的 AOM 实例 ID"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                test_result = get_aom_prom_metrics_http(region, instance.get("id"), "up", ak=access_key, sk=secret_key, project_id=proj_id)
                if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
                    return instance.get("id")
    return None


def _get_cluster_name(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> str:
    """获取集群名称"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    cluster_name = cluster_id
    try:
        clusters_result = list_cce_clusters(region, access_key, secret_key, proj_id)
        if clusters_result.get("success"):
            for c in clusters_result.get("clusters", []):
                if c.get("id") == cluster_id:
                    cluster_name = c.get("name", cluster_id)
                    break
    except Exception:
        pass
    return cluster_name


def _get_all_pods_map(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> dict:
    """获取所有 Pod 信息映射"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    all_pods_map = {}
    all_pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
    if all_pods_result.get("success"):
        for pod in all_pods_result.get("pods", []):
            all_pods_map[pod.get("name", "")] = pod
    return all_pods_map


def _get_all_namespaces(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> list:
    """获取所有业务命名空间列表"""
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    all_namespaces = set()
    all_pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
    if all_pods_result.get("success"):
        for pod in all_pods_result.get("pods", []):
            ns = pod.get("namespace", "")
            if ns and ns not in ["kube-system", "monitoring"]:
                all_namespaces.add(ns)
    return list(all_namespaces)


def cce_cluster_inspection(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """CCE 集群巡检主函数
    
    执行 8 大检查项，并汇总各独立巡检工具的结果生成详细报告：
    1. Pod 状态巡检
    2. Node 状态巡检
    3. 插件 Pod 监控巡检 (kube-system + monitoring)
    4. 业务 Pod 监控巡检 (其他命名空间)
    5. 节点资源监控巡检
    6. Event 巡检
    7. AOM 告警巡检
    8. ELB 负载均衡监控巡检
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        巡检结果字典，包含各子工具的详细报告和汇总报告
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided"
        }
    
    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }
    
    inspection_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    
    # 初始化巡检结果
    inspection = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "inspection_time": inspection_time,
        "result": {
            "status": "HEALTHY",
            "total_issues": 0,
            "critical_issues": 0,
            "warning_issues": 0
        },
        "checks": {},
        "issues": [],
        "sub_reports": {}  # 各独立巡检工具的详细报告
    }
    
    all_issues = []
    
    def add_issues(issues: list):
        """添加问题到总列表"""
        nonlocal all_issues
        for issue in issues:
            all_issues.append(issue)
            if issue["severity"] == "CRITICAL":
                inspection["result"]["critical_issues"] += 1
            else:
                inspection["result"]["warning_issues"] += 1
            inspection["result"]["total_issues"] += 1
            
            # 更新状态
            if issue["severity"] == "CRITICAL":
                inspection["result"]["status"] = "CRITICAL"
            elif inspection["result"]["status"] == "HEALTHY":
                inspection["result"]["status"] = "WARNING"
    
    # 获取集群名称
    cluster_name = cluster_id
    try:
        clusters_result = list_cce_clusters(region, access_key, secret_key, proj_id)
        if clusters_result.get("success"):
            for c in clusters_result.get("clusters", []):
                if c.get("id") == cluster_id:
                    cluster_name = c.get("name", cluster_id)
                    break
    except Exception:
        pass
    
    # 获取AOM实例
    aom_instance_id = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                test_result = get_aom_prom_metrics_http(region, instance.get("id"), "up", ak=access_key, sk=secret_key, project_id=proj_id)
                if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
                    aom_instance_id = instance.get("id")
                    break
    
    # 获取所有Pod信息
    all_pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
    all_pods_map = {}
    all_namespaces = set()
    if all_pods_result.get("success"):
        for pod in all_pods_result.get("pods", []):
            all_pods_map[pod.get("name", "")] = pod
            ns = pod.get("namespace", "")
            if ns and ns not in ["kube-system", "monitoring"]:
                all_namespaces.add(ns)
    
    # ========== 1. Pod 状态巡检 ==========
    pod_check, pod_issues = pod_status_inspection(region, cluster_id, access_key, secret_key, proj_id)
    inspection["checks"]["pods"] = pod_check
    add_issues(pod_issues)
    # 生成独立报告
    inspection["sub_reports"]["pods"] = generate_sub_inspection_report(
        "pods", pod_check, pod_issues, inspection_time
    )
    
    # ========== 2. Node 状态巡检 ==========
    node_check, node_issues = node_status_inspection(region, cluster_id, access_key, secret_key, proj_id)
    inspection["checks"]["nodes"] = node_check
    add_issues(node_issues)
    inspection["sub_reports"]["nodes"] = generate_sub_inspection_report(
        "nodes", node_check, node_issues, inspection_time
    )
    
    # ========== 3. 插件 Pod 监控巡检 ==========
    addon_check, addon_issues = addon_pod_monitoring_inspection(
        region, cluster_id, aom_instance_id, cluster_name, access_key, secret_key, proj_id, all_pods_map
    )
    inspection["checks"]["addon_pod_monitoring"] = addon_check
    add_issues(addon_issues)
    inspection["sub_reports"]["addon_pod_monitoring"] = generate_sub_inspection_report(
        "addon_pod_monitoring", addon_check, addon_issues, inspection_time
    )
    
    # ========== 4. 业务 Pod 监控巡检 ==========
    biz_check, biz_issues = biz_pod_monitoring_inspection(
        region, cluster_id, aom_instance_id, cluster_name, access_key, secret_key, proj_id, all_pods_map, list(all_namespaces)
    )
    inspection["checks"]["biz_pod_monitoring"] = biz_check
    add_issues(biz_issues)
    inspection["sub_reports"]["biz_pod_monitoring"] = generate_sub_inspection_report(
        "biz_pod_monitoring", biz_check, biz_issues, inspection_time
    )
    
    # ========== 5. 节点资源监控巡检 ==========
    node_mon_check, node_mon_issues = node_resource_monitoring_inspection(
        region, cluster_id, aom_instance_id, cluster_name, access_key, secret_key, proj_id
    )
    inspection["checks"]["node_monitoring"] = node_mon_check
    add_issues(node_mon_issues)
    inspection["sub_reports"]["node_monitoring"] = generate_sub_inspection_report(
        "node_monitoring", node_mon_check, node_mon_issues, inspection_time
    )
    
    # ========== 6. Event 巡检 ==========
    event_check, event_issues = event_inspection(region, cluster_id, access_key, secret_key, proj_id)
    inspection["checks"]["events"] = event_check
    add_issues(event_issues)
    inspection["sub_reports"]["events"] = generate_sub_inspection_report(
        "events", event_check, event_issues, inspection_time
    )
    
    # ========== 7. AOM 告警巡检 ==========
    alarm_check, alarm_issues = aom_alarm_inspection(region, cluster_id, cluster_name, access_key, secret_key, proj_id)
    inspection["checks"]["alarms"] = alarm_check
    add_issues(alarm_issues)
    inspection["sub_reports"]["alarms"] = generate_sub_inspection_report(
        "alarms", alarm_check, alarm_issues, inspection_time
    )
    
    # ========== 8. ELB 监控巡检 ==========
    elb_check, elb_issues = elb_monitoring_inspection(
        region, cluster_id, aom_instance_id, cluster_name, access_key, secret_key, proj_id
    )
    inspection["checks"]["elb_monitoring"] = elb_check
    add_issues(elb_issues)
    inspection["sub_reports"]["elb_monitoring"] = generate_sub_inspection_report(
        "elb_monitoring", elb_check, elb_issues, inspection_time
    )
    
    # 添加问题列表
    inspection["issues"] = all_issues
    
    # 生成汇总报告
    summary_report = generate_summary_report(
        inspection["sub_reports"], cluster_id, region, inspection_time
    )
    
    # 生成文本报告
    inspection["report"] = _generate_detailed_text_report(inspection, cluster_id, region)
    
    # 生成详细HTML报告
    inspection["html_report"] = generate_detailed_html_report(summary_report)
    
    # 添加汇总报告到结果
    inspection["summary_report"] = summary_report
    
    return inspection


def _generate_detailed_text_report(inspection: dict, cluster_id: str, region: str) -> str:
    """生成详细的文本格式巡检报告，包含各巡检子工具的详细情况"""
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("🔍 CCE 集群巡检详细报告")
    report_lines.append("=" * 80)
    report_lines.append(f"集群ID: {cluster_id}")
    report_lines.append(f"区域: {region}")
    report_lines.append(f"巡检时间: {inspection['inspection_time']}")
    report_lines.append(f"巡检结果: {inspection['result']['status']}")
    report_lines.append(f"总问题数: {inspection['result']['total_issues']} (严重: {inspection['result']['critical_issues']}, 警告: {inspection['result']['warning_issues']})")
    report_lines.append("")
    
    # 各巡检子工具详细报告
    sub_reports = inspection.get("sub_reports", {})
    
    for check_name, sub_report in sub_reports.items():
        report_lines.append("=" * 80)
        report_lines.append(f"📋 【{sub_report.get('inspection_name', check_name)}】")
        report_lines.append(f"   状态: {sub_report.get('status', 'UNKNOWN')}")
        report_lines.append(f"   检查状态: {'已检查' if sub_report.get('checked') else '未检查'}")
        report_lines.append("-" * 80)
        
        # 摘要信息
        summary = sub_report.get("summary", {})
        if summary:
            report_lines.append("📊 检查摘要:")
            for key, value in summary.items():
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value) if value else "无"
                report_lines.append(f"   • {_format_key_text(key)}: {value}")
            report_lines.append("")
        
        # 问题列表
        issues = sub_report.get("issues", [])
        if issues:
            report_lines.append("⚠️ 发现的问题:")
            for issue in issues:
                severity = issue.get("severity", "WARNING")
                icon = "🔴" if severity == "CRITICAL" else "🟡"
                report_lines.append(f"   {icon} [{severity}] {issue.get('category')}")
                report_lines.append(f"      对象: {issue.get('item')}")
                report_lines.append(f"      详情: {issue.get('details')}")
            report_lines.append("")
        
        # 建议
        recommendations = sub_report.get("recommendations", [])
        if recommendations:
            report_lines.append("💡 处理建议:")
            for i, rec in enumerate(recommendations[:5], 1):
                report_lines.append(f"   {i}. {rec.get('target')}")
                report_lines.append(f"      问题: {rec.get('issue')}")
                report_lines.append(f"      建议: {rec.get('suggestion')}")
            report_lines.append("")
        
        report_lines.append("")
    
    # 问题汇总
    report_lines.append("=" * 80)
    report_lines.append("📋 问题汇总")
    report_lines.append("=" * 80)
    
    all_issues = inspection.get("issues", [])
    if all_issues:
        critical_issues = [i for i in all_issues if i.get("severity") == "CRITICAL"]
        warning_issues = [i for i in all_issues if i.get("severity") != "CRITICAL"]
        
        if critical_issues:
            report_lines.append("")
            report_lines.append("🔴 严重问题:")
            for i, issue in enumerate(critical_issues, 1):
                report_lines.append(f"   {i}. [{issue.get('category')}] {issue.get('item')}")
                report_lines.append(f"      {issue.get('details')}")
        
        if warning_issues:
            report_lines.append("")
            report_lines.append("🟡 警告问题:")
            for i, issue in enumerate(warning_issues, 1):
                report_lines.append(f"   {i}. [{issue.get('category')}] {issue.get('item')}")
                report_lines.append(f"      {issue.get('details')}")
    else:
        report_lines.append("   ✅ 未发现问题")
    
    report_lines.append("")
    report_lines.append("=" * 80)
    if inspection["result"]["status"] == "HEALTHY":
        report_lines.append("✅ 集群状态健康，无异常问题")
    elif inspection["result"]["status"] == "WARNING":
        report_lines.append("⚠️ 集群存在警告问题，建议关注处理")
    else:
        report_lines.append("❌ 集群存在严重问题，请立即处理！")
    report_lines.append("=" * 80)
    
    return "\n".join(report_lines)


def _format_key_text(key: str) -> str:
    """格式化key为可读的中文标题"""
    key_map = {
        "total_pods": "Pod总数",
        "total_nodes": "节点总数",
        "running": "运行中",
        "pending": "待调度",
        "failed": "失败",
        "ready": "Ready",
        "not_ready": "NotReady",
        "restart_pod_count": "重启Pod数",
        "abnormal_pod_count": "异常Pod数",
        "abnormal_count": "异常节点数",
        "high_cpu_count": "CPU超限数",
        "high_memory_count": "内存超限数",
        "high_disk_count": "磁盘超限数",
        "namespaces": "命名空间",
        "total_events": "事件总数",
        "normal_events": "正常事件",
        "warning_events": "警告事件",
        "critical_events_count": "关键事件数",
        "total_alarms": "告警总数",
        "critical": "严重",
        "major": "重要",
        "minor": "次要",
        "info": "提示",
        "total_loadbalancers": "负载均衡数",
        "high_connection_count": "高连接数ELB",
        "high_bandwidth_count": "高带宽ELB",
        "eip_over_limit_count": "EIP超限数",
    }
    return key_map.get(key, key.replace("_", " ").title())


def _generate_html_report(inspection: dict, cluster_id: str, region: str) -> str:
    """生成HTML格式巡检报告 - 使用报告生成器"""
    summary_report = inspection.get("summary_report", {})
    if not summary_report:
        summary_report = generate_summary_report(
            inspection.get("sub_reports", {}),
            cluster_id,
            region,
            inspection.get("inspection_time", "")
        )
    return generate_detailed_html_report(summary_report)


def export_inspection_report(region: str, cluster_id: str, output_file: str = None, ak: str = None, sk: str = None) -> Dict[str, Any]:
    """导出巡检报告到文件
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        output_file: 输出文件路径（可选）
        ak: Access Key ID
        sk: Secret Access Key
    
    Returns:
        导出结果
    """
    if output_file is None:
        output_file = f"/tmp/cce_inspection_report_{cluster_id[:8]}.html"
    
    inspection_result = cce_cluster_inspection(region, cluster_id, ak, sk)
    
    if inspection_result.get("success") and inspection_result.get("html_report"):
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(inspection_result["html_report"])
        
        return {
            "success": True,
            "message": "HTML巡检报告已生成",
            "file": output_file,
            "cluster_id": cluster_id,
            "inspection_time": inspection_result.get("inspection_time"),
            "status": inspection_result.get("result", {}).get("status"),
            "total_issues": inspection_result.get("result", {}).get("total_issues"),
            "critical_issues": inspection_result.get("result", {}).get("critical_issues"),
            "warning_issues": inspection_result.get("result", {}).get("warning_issues")
        }
    else:
        return inspection_result


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python inspection.py <region> <cluster_id> <ak> <sk>")
        sys.exit(1)
    
    region = sys.argv[1]
    cluster_id = sys.argv[2]
    ak = sys.argv[3]
    sk = sys.argv[4]
    
    result = cce_cluster_inspection(region, cluster_id, ak, sk)
    print(result.get("report", "No report"))