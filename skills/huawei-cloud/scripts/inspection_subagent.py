#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CCE 集群巡检 - Subagent 并行版本

使用多个 subagent 并行执行各项巡检任务，提高巡检效率。

巡检项:
1. Pod 状态巡检
2. Node 状态巡检
3. 插件 Pod 监控巡检 (kube-system + monitoring)
4. 业务 Pod 监控巡检 (其他命名空间)
5. 节点资源监控巡检
6. Event 巡检
7. AOM 告警巡检
8. ELB 负载均衡监控巡检

使用方式:
    作为主 agent 调用，会自动启动多个 subagent 并行执行巡检。
    结果会汇总返回。

    python inspection_subagent.py <region> <cluster_id> <ak> <sk> [project_id]
"""

import os
import sys
import json
import time
import subprocess
import concurrent.futures
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入报告生成器
from report_generator import (
    generate_sub_inspection_report,
    generate_summary_report,
    generate_detailed_html_report
)

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


# ========== 巡检任务定义 ==========

INSPECTION_TASKS = {
    "pods": {
        "name": "Pod状态巡检",
        "action": "huawei_pod_status_inspection",
        "description": "检查Pod运行状态、容器重启次数、异常状态"
    },
    "nodes": {
        "name": "Node状态巡检",
        "action": "huawei_node_status_inspection",
        "description": "检查节点状态、Ready/NotReady统计"
    },
    "addon_pod_monitoring": {
        "name": "插件Pod监控巡检",
        "action": "huawei_addon_pod_monitoring_inspection",
        "description": "检查kube-system/monitoring命名空间的CPU/内存使用率"
    },
    "biz_pod_monitoring": {
        "name": "业务Pod监控巡检",
        "action": "huawei_biz_pod_monitoring_inspection",
        "description": "检查业务命名空间的CPU/内存使用率Top 10"
    },
    "node_monitoring": {
        "name": "节点资源监控巡检",
        "action": "huawei_node_resource_inspection",
        "description": "检查CPU/内存/磁盘使用率Top 10"
    },
    "events": {
        "name": "Event巡检",
        "action": "huawei_event_inspection",
        "description": "检查集群事件和Warning事件"
    },
    "alarms": {
        "name": "AOM告警巡检",
        "action": "huawei_aom_alarm_inspection",
        "description": "检查当前活跃告警"
    },
    "elb_monitoring": {
        "name": "ELB负载均衡监控巡检",
        "action": "huawei_elb_monitoring_inspection",
        "description": "检查LoadBalancer类型Service的ELB监控数据"
    }
}


def run_single_inspection(task_id: str, region: str, cluster_id: str, ak: str, sk: str, 
                           project_id: str = None, aom_instance_id: str = None, 
                           cluster_name: str = None, all_pods_map: dict = None,
                           all_namespaces: list = None) -> Tuple[dict, list]:
    """
    执行单个巡检任务
    
    Args:
        task_id: 任务ID
        region: 区域
        cluster_id: 集群ID
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
        aom_instance_id: AOM实例ID
        cluster_name: 集群名称
        all_pods_map: 所有Pod映射
        all_namespaces: 所有命名空间
    
    Returns:
        (check_result, issues)
    """
    task = INSPECTION_TASKS.get(task_id)
    if not task:
        return {"name": task_id, "status": "ERROR", "error": "Unknown task"}, []
    
    try:
        # 根据任务ID调用对应的巡检函数
        if task_id == "pods":
            from pod_inspection import pod_status_inspection
            return pod_status_inspection(region, cluster_id, ak, sk, project_id)
        
        elif task_id == "nodes":
            from node_inspection import node_status_inspection
            return node_status_inspection(region, cluster_id, ak, sk, project_id)
        
        elif task_id == "addon_pod_monitoring":
            from pod_inspection import addon_pod_monitoring_inspection
            return addon_pod_monitoring_inspection(
                region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id, all_pods_map
            )
        
        elif task_id == "biz_pod_monitoring":
            from pod_inspection import biz_pod_monitoring_inspection
            return biz_pod_monitoring_inspection(
                region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id, all_pods_map, all_namespaces
            )
        
        elif task_id == "node_monitoring":
            from node_inspection import node_resource_monitoring_inspection
            return node_resource_monitoring_inspection(
                region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id
            )
        
        elif task_id == "events":
            from alarm_inspection import event_inspection
            return event_inspection(region, cluster_id, ak, sk, project_id)
        
        elif task_id == "alarms":
            from alarm_inspection import aom_alarm_inspection
            return aom_alarm_inspection(region, cluster_id, cluster_name, ak, sk, project_id)
        
        elif task_id == "elb_monitoring":
            from network_inspection import elb_monitoring_inspection
            return elb_monitoring_inspection(
                region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id
            )
        
        else:
            return {"name": task["name"], "status": "ERROR", "error": "Unknown task"}, []
            
    except Exception as e:
        return {
            "name": task["name"],
            "status": "ERROR",
            "error": str(e)
        }, []


def run_single_inspection_subprocess(args: dict) -> dict:
    """
    在子进程中执行单个巡检任务（用于真正的并行执行）
    
    Args:
        args: 包含所有参数的字典
    
    Returns:
        巡检结果
    """
    task_id = args["task_id"]
    region = args["region"]
    cluster_id = args["cluster_id"]
    ak = args["ak"]
    sk = args["sk"]
    project_id = args.get("project_id")
    aom_instance_id = args.get("aom_instance_id")
    cluster_name = args.get("cluster_name")
    all_pods_map = args.get("all_pods_map")
    all_namespaces = args.get("all_namespaces")
    
    check_result, issues = run_single_inspection(
        task_id, region, cluster_id, ak, sk, project_id,
        aom_instance_id, cluster_name, all_pods_map, all_namespaces
    )
    
    return {
        "task_id": task_id,
        "check": check_result,
        "issues": issues
    }


def cce_cluster_inspection_parallel(region: str, cluster_id: str, ak: str = None, sk: str = None,
                                     project_id: str = None, max_workers: int = 4) -> Dict[str, Any]:
    """
    CCE 集群巡检主函数 - 并行版本
    
    使用线程池并行执行各项巡检任务。
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
        max_workers: 最大并行数
    
    Returns:
        巡检结果字典
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
    
    start_time = time.time()
    inspection_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    
    # 初始化巡检结果
    inspection = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "inspection_time": inspection_time,
        "mode": "parallel",
        "max_workers": max_workers,
        "result": {
            "status": "HEALTHY",
            "total_issues": 0,
            "critical_issues": 0,
            "warning_issues": 0
        },
        "checks": {},
        "issues": [],
        "sub_reports": {},
        "timing": {
            "start_time": inspection_time,
            "duration_seconds": 0,
            "task_timings": {}
        }
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
            
            if issue["severity"] == "CRITICAL":
                inspection["result"]["status"] = "CRITICAL"
            elif inspection["result"]["status"] == "HEALTHY":
                inspection["result"]["status"] = "WARNING"
    
    # ========== 预处理：获取公共数据 ==========
    print(f"[预处理] 获取集群信息...")
    preprocess_start = time.time()
    
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
                test_result = get_aom_prom_metrics_http(region, instance.get("id"), "up", 
                                                        ak=access_key, sk=secret_key, project_id=proj_id)
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
    
    preprocess_duration = time.time() - preprocess_start
    print(f"[预处理] 完成，耗时 {preprocess_duration:.2f}s")
    inspection["timing"]["preprocess_seconds"] = round(preprocess_duration, 2)
    
    # ========== 并行执行巡检任务 ==========
    print(f"\n[并行巡检] 启动 {len(INSPECTION_TASKS)} 个巡检任务，最大并行数: {max_workers}")
    
    # 准备任务参数
    task_args_list = []
    for task_id in INSPECTION_TASKS.keys():
        task_args_list.append({
            "task_id": task_id,
            "region": region,
            "cluster_id": cluster_id,
            "ak": access_key,
            "sk": secret_key,
            "project_id": proj_id,
            "aom_instance_id": aom_instance_id,
            "cluster_name": cluster_name,
            "all_pods_map": all_pods_map,
            "all_namespaces": list(all_namespaces)
        })
    
    # 使用线程池并行执行
    parallel_start = time.time()
    results = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(run_single_inspection_subprocess, args): args["task_id"]
            for args in task_args_list
        }
        
        # 收集结果
        for future in concurrent.futures.as_completed(future_to_task):
            task_id = future_to_task[future]
            task_name = INSPECTION_TASKS[task_id]["name"]
            task_start = time.time()
            
            try:
                result = future.result()
                results[task_id] = result
                task_duration = time.time() - task_start
                inspection["timing"]["task_timings"][task_id] = round(task_duration, 2)
                print(f"  ✓ [{task_name}] 完成，耗时 {task_duration:.2f}s")
            except Exception as e:
                results[task_id] = {
                    "task_id": task_id,
                    "check": {"name": task_name, "status": "ERROR", "error": str(e)},
                    "issues": []
                }
                print(f"  ✗ [{task_name}] 失败: {e}")
    
    parallel_duration = time.time() - parallel_start
    print(f"\n[并行巡检] 完成，总耗时 {parallel_duration:.2f}s")
    inspection["timing"]["parallel_seconds"] = round(parallel_duration, 2)
    
    # ========== 汇总结果 ==========
    for task_id, result in results.items():
        check_result = result.get("check", {})
        issues = result.get("issues", [])
        
        inspection["checks"][task_id] = check_result
        add_issues(issues)
        
        # 生成子报告
        inspection["sub_reports"][task_id] = generate_sub_inspection_report(
            task_id, check_result, issues, inspection_time
        )
    
    # 添加问题列表
    inspection["issues"] = all_issues
    
    # 生成汇总报告
    summary_report = generate_summary_report(
        inspection["sub_reports"], cluster_id, region, inspection_time
    )
    
    # 生成文本报告
    inspection["report"] = _generate_detailed_text_report(inspection, cluster_id, region)
    
    # 生成HTML报告
    inspection["html_report"] = generate_detailed_html_report(summary_report)
    
    # 添加汇总报告
    inspection["summary_report"] = summary_report
    
    # 计算总耗时
    total_duration = time.time() - start_time
    inspection["timing"]["duration_seconds"] = round(total_duration, 2)
    inspection["timing"]["total_formatted"] = f"{total_duration:.2f}s"
    
    print(f"\n[巡检完成] 总耗时 {total_duration:.2f}s，状态: {inspection['result']['status']}")
    
    return inspection


def _generate_detailed_text_report(inspection: dict, cluster_id: str, region: str) -> str:
    """生成详细的文本格式巡检报告"""
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("🔍 CCE 集群巡检详细报告 (并行模式)")
    report_lines.append("=" * 80)
    report_lines.append(f"集群ID: {cluster_id}")
    report_lines.append(f"区域: {region}")
    report_lines.append(f"巡检时间: {inspection['inspection_time']}")
    report_lines.append(f"巡检模式: 并行 (max_workers={inspection.get('max_workers', 4)})")
    report_lines.append(f"总耗时: {inspection['timing'].get('total_formatted', 'N/A')}")
    report_lines.append(f"巡检结果: {inspection['result']['status']}")
    report_lines.append(f"总问题数: {inspection['result']['total_issues']} (严重: {inspection['result']['critical_issues']}, 警告: {inspection['result']['warning_issues']})")
    report_lines.append("")
    
    # 任务耗时统计
    task_timings = inspection.get("timing", {}).get("task_timings", {})
    if task_timings:
        report_lines.append("📊 各任务耗时:")
        for task_id, duration in task_timings.items():
            task_name = INSPECTION_TASKS.get(task_id, {}).get("name", task_id)
            report_lines.append(f"   • {task_name}: {duration}s")
        report_lines.append("")
    
    # 各巡检子工具详细报告
    sub_reports = inspection.get("sub_reports", {})
    
    for check_name, sub_report in sub_reports.items():
        report_lines.append("=" * 80)
        report_lines.append(f"📋 【{sub_report.get('inspection_name', check_name)}】")
        report_lines.append(f"   状态: {sub_report.get('status', 'UNKNOWN')}")
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


# ========== Subagent 模式入口 ==========

def get_subagent_tasks() -> List[Dict[str, str]]:
    """
    获取 subagent 任务列表
    
    用于主 agent 调用，返回需要启动的 subagent 任务列表。
    每个 subagent 执行一个巡检项。
    
    Returns:
        任务列表，每个任务包含 task_id, name, action, description
    """
    return [
        {
            "task_id": task_id,
            "name": task["name"],
            "action": task["action"],
            "description": task["description"]
        }
        for task_id, task in INSPECTION_TASKS.items()
    ]


def format_subagent_prompt(task_id: str, region: str, cluster_id: str, 
                           ak: str, sk: str, project_id: str = None,
                           extra_params: dict = None) -> str:
    """
    生成 subagent 执行提示词
    
    Args:
        task_id: 任务ID
        region: 区域
        cluster_id: 集群ID
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
        extra_params: 额外参数 (aom_instance_id, cluster_name, namespaces等)
    
    Returns:
        subagent 执行提示词
    """
    task = INSPECTION_TASKS.get(task_id)
    if not task:
        return f"错误：未知任务 {task_id}"
    
    prompt = f"""执行华为云CCE集群巡检任务：{task['name']}

任务描述：{task['description']}

参数：
- region: {region}
- cluster_id: {cluster_id}
- ak: {ak}
- sk: {sk}
- project_id: {project_id or '未指定'}
"""
    
    if extra_params:
        prompt += "\n额外参数：\n"
        for key, value in extra_params.items():
            if key in ["ak", "sk"]:
                continue  # 不重复显示敏感信息
            prompt += f"- {key}: {value}\n"
    
    prompt += f"""
执行命令：
cd skills/huawei-cloud/scripts && python3 huawei-cloud.py {task['action']} region={region} cluster_id={cluster_id} ak={ak} sk={sk}

请执行巡检并返回结果JSON。
"""
    return prompt


# ========== 主入口 ==========

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python inspection_subagent.py <region> <cluster_id> <ak> <sk> [project_id] [max_workers]")
        print("\n并行执行CCE集群巡检，使用多线程提高效率。")
        print("\n示例:")
        print("  python inspection_subagent.py cn-north-4 cluster-id ak sk")
        print("  python inspection_subagent.py cn-north-4 cluster-id ak sk project-id 8")
        sys.exit(1)
    
    region = sys.argv[1]
    cluster_id = sys.argv[2]
    ak = sys.argv[3]
    sk = sys.argv[4]
    project_id = sys.argv[5] if len(sys.argv) > 5 else None
    max_workers = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    
    result = cce_cluster_inspection_parallel(region, cluster_id, ak, sk, project_id, max_workers)
    
    # 输出结果摘要
    print("\n" + "=" * 60)
    print("巡检结果摘要:")
    print(f"  状态: {result['result']['status']}")
    print(f"  总问题数: {result['result']['total_issues']}")
    print(f"  严重问题: {result['result']['critical_issues']}")
    print(f"  警告问题: {result['result']['warning_issues']}")
    print(f"  总耗时: {result['timing']['total_formatted']}")
    print("=" * 60)