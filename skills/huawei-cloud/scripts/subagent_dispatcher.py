#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CCE 集群巡检 Subagent 任务分发器

提供三种模式:
1. 串行模式 (serial): 主进程使用多线程并行执行
2. Subagent模式 (subagent): 返回任务列表，由主agent启动多个subagent并行执行
3. 自动聚合模式 (auto): 返回所有任务信息，主agent启动subagent后不yield，等待所有结果后一次性输出

使用方式:
    # 串行模式 - 直接执行巡检
    python subagent_dispatcher.py serial cn-north-4 cluster-id ak sk
    
    # Subagent模式 - 生成任务列表供主agent调用
    python subagent_dispatcher.py tasks cn-north-4 cluster-id ak sk
    
    # 自动聚合模式 - 返回任务列表和聚合指令
    python subagent_dispatcher.py auto cn-north-4 cluster-id ak sk
    
    # 执行单个任务 (subagent内部调用)
    python subagent_dispatcher.py execute pods cn-north-4 cluster-id ak sk
"""

import os
import sys
import json
import time
import argparse
from typing import Dict, Any, List, Optional
from datetime import datetime

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入并行巡检模块
from inspection_subagent import (
    INSPECTION_TASKS,
    run_single_inspection,
    get_subagent_tasks,
    format_subagent_prompt,
    cce_cluster_inspection_parallel
)

# 导入主模块的工具函数
import importlib.util
spec = importlib.util.spec_from_file_location("huawei_cloud", os.path.join(os.path.dirname(__file__), "huawei-cloud.py"))
huawei_cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(huawei_cloud)

get_credentials_with_region = huawei_cloud.get_credentials_with_region
list_cce_clusters = huawei_cloud.list_cce_clusters
list_aom_instances = huawei_cloud.list_aom_instances
get_aom_prom_metrics_http = huawei_cloud.get_aom_prom_metrics_http
get_kubernetes_pods = huawei_cloud.get_kubernetes_pods


def get_preprocess_data(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> dict:
    """
    获取预处理数据
    
    Returns:
        包含 cluster_name, aom_instance_id, all_pods_map, all_namespaces 的字典
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
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
    try:
        aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
        if aom_instances.get("success"):
            for instance in aom_instances.get("instances", []):
                if instance.get("type") == "CCE":
                    test_result = get_aom_prom_metrics_http(region, instance.get("id"), "up",
                                                            ak=access_key, sk=secret_key, project_id=proj_id)
                    if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
                        aom_instance_id = instance.get("id")
                        break
    except Exception:
        pass
    
    # 获取所有Pod信息
    all_pods_map = {}
    all_namespaces = set()
    try:
        all_pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
        if all_pods_result.get("success"):
            for pod in all_pods_result.get("pods", []):
                all_pods_map[pod.get("name", "")] = pod
                ns = pod.get("namespace", "")
                if ns and ns not in ["kube-system", "monitoring"]:
                    all_namespaces.add(ns)
    except Exception:
        pass
    
    return {
        "cluster_name": cluster_name,
        "aom_instance_id": aom_instance_id,
        "all_pods_map": all_pods_map,
        "all_namespaces": list(all_namespaces)
    }


def generate_subagent_task_list(region: str, cluster_id: str, ak: str, sk: str, 
                                 project_id: str = None) -> Dict[str, Any]:
    """
    生成 subagent 任务列表
    
    主 agent 调用此函数获取任务列表，然后使用 sessions_spawn 启动多个 subagent。
    
    Returns:
        {
            "success": true,
            "preprocess_data": {...},  # 预处理数据，需传递给每个 subagent
            "tasks": [
                {
                    "task_id": "pods",
                    "name": "Pod状态巡检",
                    "action": "huawei_pod_status_inspection",
                    "description": "...",
                    "command": "cd skills/huawei-cloud/scripts && python3 huawei-cloud.py ..."
                },
                ...
            ]
        }
    """
    # 获取预处理数据
    preprocess_data = get_preprocess_data(region, cluster_id, ak, sk, project_id)
    
    # 生成任务列表
    tasks = []
    for task_id, task in INSPECTION_TASKS.items():
        command = f"cd skills/huawei-cloud/scripts && python3 huawei-cloud.py {task['action']} region={region} cluster_id={cluster_id} ak={ak} sk={sk}"
        if project_id:
            command += f" project_id={project_id}"
        
        tasks.append({
            "task_id": task_id,
            "name": task["name"],
            "action": task["action"],
            "description": task["description"],
            "command": command,
            "preprocess_data": preprocess_data
        })
    
    return {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": preprocess_data["cluster_name"],
        "aom_instance_id": preprocess_data["aom_instance_id"],
        "task_count": len(tasks),
        "tasks": tasks,
        "preprocess_data": preprocess_data
    }


def generate_auto_subagent_info(region: str, cluster_id: str, ak: str, sk: str,
                                 project_id: str = None) -> Dict[str, Any]:
    """
    生成自动聚合模式的subagent信息
    
    返回任务列表和执行指令，主agent启动subagent后不需要yield，
    等待所有结果到达后一次性汇总输出。
    
    Returns:
        {
            "success": true,
            "mode": "auto",
            "instruction": "启动所有subagent后不要yield，等待所有结果到达后一次性输出",
            "total_tasks": 8,
            "expected_results": ["pods", "nodes", "addon_pod_monitoring", ...],
            "tasks": [...],
            "preprocess_data": {...}
        }
    """
    # 获取预处理数据
    preprocess_data = get_preprocess_data(region, cluster_id, ak, sk, project_id)
    
    # 生成任务列表
    tasks = []
    expected_results = []
    
    for task_id, task in INSPECTION_TASKS.items():
        expected_results.append(task_id)
        command = f"cd skills/huawei-cloud/scripts && python3 huawei-cloud.py {task['action']} region={region} cluster_id={cluster_id} ak={ak} sk={sk}"
        if project_id:
            command += f" project_id={project_id}"
        
        tasks.append({
            "task_id": task_id,
            "label": f"inspection-{task_id}",
            "name": task["name"],
            "action": task["action"],
            "description": task["description"],
            "command": command
        })
    
    return {
        "success": True,
        "mode": "auto",
        "instruction": "启动所有subagent后不要调用sessions_yield，收到结果时累积直到全部完成再输出最终报告",
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": preprocess_data["cluster_name"],
        "total_tasks": len(tasks),
        "expected_results": expected_results,
        "tasks": tasks,
        "preprocess_data": preprocess_data,
        "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


def execute_single_task(task_id: str, region: str, cluster_id: str, ak: str, sk: str,
                        project_id: str = None, preprocess_data: dict = None) -> Dict[str, Any]:
    """
    执行单个巡检任务 (subagent 内部调用)
    
    Args:
        task_id: 任务ID
        region: 区域
        cluster_id: 集群ID
        ak: Access Key
        sk: Secret Key
        project_id: Project ID
        preprocess_data: 预处理数据 (可选，如果提供则跳过预处理)
    
    Returns:
        巡检结果
    """
    task = INSPECTION_TASKS.get(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Unknown task: {task_id}"
        }
    
    # 获取或使用预处理数据
    if preprocess_data is None:
        preprocess_data = get_preprocess_data(region, cluster_id, ak, sk, project_id)
    
    # 执行巡检
    check_result, issues = run_single_inspection(
        task_id, region, cluster_id, ak, sk, project_id,
        preprocess_data.get("aom_instance_id"),
        preprocess_data.get("cluster_name"),
        preprocess_data.get("all_pods_map"),
        preprocess_data.get("all_namespaces")
    )
    
    return {
        "success": True,
        "task_id": task_id,
        "task_name": task["name"],
        "check": check_result,
        "issues": issues
    }


def aggregate_subagent_results(results: List[Dict[str, Any]], 
                                cluster_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    聚合所有subagent的结果，生成最终巡检报告
    
    Args:
        results: 所有subagent返回的结果列表
        cluster_info: 集群信息 (region, cluster_id, cluster_name等)
    
    Returns:
        聚合后的巡检报告
    """
    all_issues = []
    checks = {}
    critical_count = 0
    warning_count = 0
    
    for result in results:
        if not result.get("success"):
            continue
        
        task_id = result.get("task_id")
        check = result.get("check", {})
        issues = result.get("issues", [])
        
        checks[task_id] = check
        
        for issue in issues:
            all_issues.append(issue)
            if issue.get("severity") == "CRITICAL":
                critical_count += 1
            else:
                warning_count += 1
    
    # 确定整体状态
    if critical_count > 0:
        overall_status = "CRITICAL"
    elif warning_count > 0:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"
    
    return {
        "success": True,
        "mode": "subagent_aggregated",
        "cluster_id": cluster_info.get("cluster_id"),
        "cluster_name": cluster_info.get("cluster_name"),
        "region": cluster_info.get("region"),
        "inspection_time": cluster_info.get("start_time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        "result": {
            "status": overall_status,
            "total_issues": len(all_issues),
            "critical_issues": critical_count,
            "warning_issues": warning_count
        },
        "checks": checks,
        "issues": all_issues,
        "summary": {
            "total_tasks": len(results),
            "successful_tasks": len([r for r in results if r.get("success")]),
            "failed_tasks": len([r for r in results if not r.get("success")])
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="CCE集群巡检Subagent任务分发器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 串行模式执行巡检
  python subagent_dispatcher.py serial cn-north-4 cluster-id ak sk
  
  # 生成subagent任务列表
  python subagent_dispatcher.py tasks cn-north-4 cluster-id ak sk
  
  # 自动聚合模式 - 返回任务和指令
  python subagent_dispatcher.py auto cn-north-4 cluster-id ak sk
  
  # 执行单个巡检任务
  python subagent_dispatcher.py execute pods cn-north-4 cluster-id ak sk
  
  # 聚合结果
  python subagent_dispatcher.py aggregate '[{...}, {...]' '{"cluster_id": "xxx", ...}'
        """
    )
    
    subparsers = parser.add_subparsers(dest="mode", help="执行模式")
    
    # 串行模式
    serial_parser = subparsers.add_parser("serial", help="串行模式执行巡检")
    serial_parser.add_argument("region", help="华为云区域")
    serial_parser.add_argument("cluster_id", help="CCE集群ID")
    serial_parser.add_argument("ak", help="Access Key")
    serial_parser.add_argument("sk", help="Secret Key")
    serial_parser.add_argument("--project-id", help="Project ID")
    serial_parser.add_argument("--workers", type=int, default=4, help="最大并行数")
    
    # 任务列表模式
    tasks_parser = subparsers.add_parser("tasks", help="生成subagent任务列表")
    tasks_parser.add_argument("region", help="华为云区域")
    tasks_parser.add_argument("cluster_id", help="CCE集群ID")
    tasks_parser.add_argument("ak", help="Access Key")
    tasks_parser.add_argument("sk", help="Secret Key")
    tasks_parser.add_argument("--project-id", help="Project ID")
    
    # 自动聚合模式
    auto_parser = subparsers.add_parser("auto", help="自动聚合模式")
    auto_parser.add_argument("region", help="华为云区域")
    auto_parser.add_argument("cluster_id", help="CCE集群ID")
    auto_parser.add_argument("ak", help="Access Key")
    auto_parser.add_argument("sk", help="Secret Key")
    auto_parser.add_argument("--project-id", help="Project ID")
    
    # 执行单任务模式
    exec_parser = subparsers.add_parser("execute", help="执行单个巡检任务")
    exec_parser.add_argument("task_id", help="任务ID (pods/nodes/events/alarms/...)")
    exec_parser.add_argument("region", help="华为云区域")
    exec_parser.add_argument("cluster_id", help="CCE集群ID")
    exec_parser.add_argument("ak", help="Access Key")
    exec_parser.add_argument("sk", help="Secret Key")
    exec_parser.add_argument("--project-id", help="Project ID")
    exec_parser.add_argument("--preprocess", help="预处理数据(JSON字符串)")
    
    # 聚合结果模式
    agg_parser = subparsers.add_parser("aggregate", help="聚合subagent结果")
    agg_parser.add_argument("results", help="subagent结果列表(JSON字符串)")
    agg_parser.add_argument("cluster_info", help="集群信息(JSON字符串)")
    
    args = parser.parse_args()
    
    if not args.mode:
        parser.print_help()
        sys.exit(1)
    
    if args.mode == "serial":
        # 串行模式执行巡检
        result = cce_cluster_inspection_parallel(
            args.region, args.cluster_id, args.ak, args.sk,
            args.project_id, args.workers
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
    elif args.mode == "tasks":
        # 生成任务列表
        result = generate_subagent_task_list(
            args.region, args.cluster_id, args.ak, args.sk, args.project_id
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
    elif args.mode == "auto":
        # 自动聚合模式
        result = generate_auto_subagent_info(
            args.region, args.cluster_id, args.ak, args.sk, args.project_id
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
    elif args.mode == "execute":
        # 执行单个任务
        preprocess_data = None
        if args.preprocess:
            try:
                preprocess_data = json.loads(args.preprocess)
            except:
                pass
        
        result = execute_single_task(
            args.task_id, args.region, args.cluster_id, args.ak, args.sk,
            args.project_id, preprocess_data
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
    elif args.mode == "aggregate":
        # 聚合结果
        try:
            results = json.loads(args.results)
            cluster_info = json.loads(args.cluster_info)
            result = aggregate_subagent_results(results, cluster_info)
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    main()