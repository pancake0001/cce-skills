#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警巡检模块

包含：
- Event 巡检
- AOM 告警巡检
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
get_kubernetes_events = huawei_cloud.get_kubernetes_events
list_aom_current_alarms = huawei_cloud.list_aom_current_alarms
SDK_AVAILABLE = huawei_cloud.SDK_AVAILABLE


def event_inspection(region: str, cluster_id: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """Event 巡检
    
    检查内容：
    - 事件类型统计 (Normal/Warning)
    - 关键事件识别
    - 按原因/命名空间归一统计
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        Event 巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "Event巡检",
        "status": "PASS",
        "checked": False,
        "total": 0,
        "normal": 0,
        "warning": 0,
        "critical_events": [],
        "events_by_reason": {},
        "events_by_namespace": {}
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
        events_result = get_kubernetes_events(region, cluster_id, access_key, secret_key, proj_id)
        if events_result.get("success"):
            result["checked"] = True
            events = events_result.get("events", [])
            result["total"] = len(events)
            
            critical_keywords = [
                "Failed", "Error", "CrashLoopBackOff", "OOMKilled",
                "Evicted", "Insufficient", "BackOff", "Unhealthy",
                "FailedScheduling", "Killing", "FailedMount"
            ]
            
            critical_events = []
            events_by_reason = {}
            events_by_namespace = {}
            
            for event in events:
                event_type = event.get("type", "Normal")
                if event_type == "Normal":
                    result["normal"] += 1
                else:
                    result["warning"] += 1
                
                reason = event.get("reason", "Unknown")
                namespace = event.get("namespace", "default")
                
                # 按原因归一
                if reason not in events_by_reason:
                    events_by_reason[reason] = {"count": 0, "events": []}
                events_by_reason[reason]["count"] += 1
                events_by_reason[reason]["events"].append(event)
                
                # 按命名空间归一
                if namespace not in events_by_namespace:
                    events_by_namespace[namespace] = {"count": 0, "events": []}
                events_by_namespace[namespace]["count"] += 1
                events_by_namespace[namespace]["events"].append(event)
                
                # 检查关键事件
                for keyword in critical_keywords:
                    if keyword in reason or keyword in event.get("message", ""):
                        critical_events.append({
                            "reason": reason,
                            "namespace": namespace,
                            "involved_object": event.get("involved_object", ""),
                            "count": event.get("count", 1),
                            "message": event.get("message", "")[:200]
                        })
                        add_issue("WARNING", "关键事件", event.get("involved_object", ""),
                            f"原因: {reason}, 命名空间: {namespace}, 消息: {event.get('message', '')[:100]}")
                        break
            
            result["critical_events"] = critical_events[:20]
            result["events_by_reason"] = {k: v for k, v in list(events_by_reason.items())[:20]}
            result["events_by_namespace"] = {k: v for k, v in list(events_by_namespace.items())[:20]}
            
            if critical_events:
                result["status"] = "WARN"
    except Exception as e:
        result["error"] = str(e)
    
    return result, issues


def aom_alarm_inspection(region: str, cluster_id: str, cluster_name: str, ak: str, sk: str, project_id: str = None) -> Dict[str, Any]:
    """AOM 告警巡检
    
    检查内容：
    - 获取当前活跃告警
    - 严重级别分类 (Critical/Major/Minor/Info)
    - 按告警类型归一统计
    
    Args:
        region: 华为云区域
        cluster_id: CCE 集群 ID
        cluster_name: 集群名称
        ak: Access Key ID
        sk: Secret Access Key
        project_id: Project ID
    
    Returns:
        AOM 告警巡检结果
    """
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    
    result = {
        "name": "AOM告警巡检",
        "status": "PASS",
        "checked": False,
        "total": 0,
        "severity_breakdown": {},
        "cluster_alarms": [],
        "alarms_by_type": {}
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
        # 使用 list_aom_current_alarms 获取活跃告警（使用 ListEvents API）
        alarm_result = list_aom_current_alarms(
            region=region,
            ak=access_key,
            sk=secret_key,
            project_id=proj_id,
            event_type="active_alert",
            limit=100
        )
        
        if alarm_result.get("success"):
            result["checked"] = True
            alarms = alarm_result.get("events", [])
            
            result["total"] = len(alarms)
            
            severity_breakdown = {"Critical": 0, "Major": 0, "Minor": 0, "Info": 0}
            cluster_alarms = []
            alarms_by_type = {}
            
            for alarm in alarms:
                severity = alarm.get("event_severity", "Info")
                if severity in severity_breakdown:
                    severity_breakdown[severity] += 1
                
                alarm_type = alarm.get("event_name", "Unknown")
                if alarm_type not in alarms_by_type:
                    alarms_by_type[alarm_type] = {"count": 0, "alarms": []}
                alarms_by_type[alarm_type]["count"] += 1
                alarms_by_type[alarm_type]["alarms"].append({
                    "name": alarm.get("event_name"),
                    "severity": severity,
                    "resource_id": alarm.get("resource_id"),
                    "message": (alarm.get("message", ""))[:200]
                })
                
                # 过滤当前集群的告警
                resource_id = alarm.get("resource_id", "")
                alarm_cluster_id = alarm.get("cluster_id", "")
                alarm_cluster_name = alarm.get("cluster_name", "")
                
                if cluster_id in resource_id or cluster_id == alarm_cluster_id or cluster_name == alarm_cluster_name:
                    cluster_alarms.append({
                        "name": alarm.get("event_name"),
                        "severity": severity,
                        "resource_id": resource_id,
                        "message": (alarm.get("message", ""))[:200],
                        "pod_name": alarm.get("pod_name"),
                        "namespace": alarm.get("namespace")
                    })
                    if severity == "Critical":
                        add_issue("CRITICAL", "重要告警", alarm.get("event_name"),
                            f"严重级别: {severity}, 资源: {resource_id}")
                    elif severity == "Major":
                        add_issue("WARNING", "重要告警", alarm.get("event_name"),
                            f"严重级别: {severity}, 资源: {resource_id}")
            
            result["severity_breakdown"] = severity_breakdown
            result["cluster_alarms"] = cluster_alarms[:20]
            result["alarms_by_type"] = {k: v for k, v in list(alarms_by_type.items())[:20]}
            
            if severity_breakdown.get("Critical", 0) > 0:
                result["status"] = "FAIL"
            elif severity_breakdown.get("Major", 0) > 0:
                result["status"] = "WARN"
        else:
            result["error"] = alarm_result.get("error", "Unknown error")
    except Exception as e:
        result["error"] = str(e)
    
    return result, issues


if __name__ == "__main__":
    print("Alarm Inspection Module")
    print("Functions:")
    print("  - event_inspection")
    print("  - aom_alarm_inspection")