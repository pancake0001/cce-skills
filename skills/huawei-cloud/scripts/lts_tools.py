#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华为云 LTS (Log Tank Service) 日志服务工具 - SDK版本

使用华为云官方SDK查询LTS日志服务。

功能:
1. 查询日志组列表
2. 查询日志流列表
3. 查询日志内容 (支持时间范围)
4. 查询CCE集群日志
"""

import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# 华为云SDK
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.region.region import Region
from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
from huaweicloudsdklts.v2 import LtsClient, ListLogGroupsRequest, ListLogStreamsRequest

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入主模块的凭证获取函数
import importlib.util
spec = importlib.util.spec_from_file_location("huawei_cloud", os.path.join(os.path.dirname(__file__), "huawei-cloud.py"))
huawei_cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(huawei_cloud)

get_project_id_for_region = huawei_cloud.get_project_id_for_region
get_credentials = huawei_cloud.get_credentials


# LTS 服务端点 (按区域)
LTS_ENDPOINTS = {
    "cn-north-4": "lts.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "lts.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "lts.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "lts.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "lts.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "lts.cn-south-1.myhuaweicloud.com",
    "cn-south-2": "lts.cn-south-2.myhuaweicloud.com",
    "cn-south-4": "lts.cn-south-4.myhuaweicloud.com",
    "cn-west-3": "lts.cn-west-3.myhuaweicloud.com",
    "cn-southwest-2": "lts.cn-southwest-2.myhuaweicloud.com",
    "ap-southeast-1": "lts.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "lts.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "lts.ap-southeast-3.myhuaweicloud.com",
    "eu-west-0": "lts.eu-west-0.myhuaweicloud.com",
}


def get_lts_client(region: str, ak: str, sk: str, project_id: str = None) -> LtsClient:
    """
    创建LTS客户端
    
    Args:
        region: 区域
        ak: Access Key
        sk: Secret Key
        project_id: 项目ID
    
    Returns:
        LtsClient实例
    """
    # 获取项目ID
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    # 创建凭证
    credentials = BasicCredentials(ak, sk, project_id)
    
    # 获取endpoint
    endpoint = LTS_ENDPOINTS.get(region, f"lts.{region}.myhuaweicloud.com")
    
    # 创建客户端
    client = LtsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(Region(id=region, endpoint=endpoint)) \
        .build()
    
    return client


# ========== 日志组管理 ==========

def list_log_groups(region: str, ak: str = None, sk: str = None, 
                    project_id: str = None) -> Dict[str, Any]:
    """
    查询日志组列表
    
    Args:
        region: 区域
        ak: Access Key
        sk: Secret Key
        project_id: 项目ID
    
    Returns:
        日志组列表
    """
    try:
        # Get credentials from environment variables if not provided
        ak, sk, project_id = get_credentials(ak, sk, project_id)
        if not ak or not sk:
            return {"success": False, "error": "Credentials not provided"}
        
        client = get_lts_client(region, ak, sk, project_id)
        
        request = ListLogGroupsRequest()
        response = client.list_log_groups(request)
        
        log_groups = []
        if response.log_groups:
            for group in response.log_groups:
                log_groups.append({
                    "log_group_id": group.log_group_id,
                    "log_group_name": group.log_group_name,
                    "creation_time": group.creation_time,
                    "ttl_in_days": group.ttl_in_days if hasattr(group, 'ttl_in_days') else 7,
                    "tags": group.tags if hasattr(group, 'tags') else []
                })
        
        return {
            "success": True,
            "total": len(log_groups),
            "log_groups": log_groups
        }
        
    except ClientRequestException as e:
        return {
            "success": False,
            "error": e.error_msg,
            "error_code": e.error_code,
            "status_code": e.status_code
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ========== 日志流管理 ==========

def list_log_streams(region: str, log_group_id: str = None, ak: str = None, 
                     sk: str = None, project_id: str = None) -> Dict[str, Any]:
    """
    查询日志流列表
    
    Args:
        region: 区域
        log_group_id: 日志组ID (可选)
        ak: Access Key
        sk: Secret Key
        project_id: 项目ID
    
    Returns:
        日志流列表
    """
    try:
        # Get credentials from environment variables if not provided
        ak, sk, project_id = get_credentials(ak, sk, project_id)
        if not ak or not sk:
            return {"success": False, "error": "Credentials not provided"}
        
        client = get_lts_client(region, ak, sk, project_id)
        
        request = ListLogStreamsRequest()
        if log_group_id:
            request.log_group_id = log_group_id
        
        response = client.list_log_streams(request)
        
        log_streams = []
        if response.log_streams:
            for stream in response.log_streams:
                log_streams.append({
                    "log_stream_id": stream.log_stream_id,
                    "log_stream_name": stream.log_stream_name,
                    "log_group_id": stream.log_group_id if hasattr(stream, 'log_group_id') else log_group_id,
                    "creation_time": stream.creation_time if hasattr(stream, 'creation_time') else None,
                    "filter_count": stream.filter_count if hasattr(stream, 'filter_count') else 0
                })
        
        return {
            "success": True,
            "total": len(log_streams),
            "log_streams": log_streams
        }
        
    except ClientRequestException as e:
        return {
            "success": False,
            "error": e.error_msg,
            "error_code": e.error_code,
            "status_code": e.status_code
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ========== 日志查询 ==========

def query_logs(region: str, log_group_id: str, log_stream_id: str,
               start_time: str = None, end_time: str = None,
               keywords: str = None, limit: int = 1000,
               scroll_id: str = None, is_desc: bool = True,
               is_iterative: bool = False,
               ak: str = None, sk: str = None, 
               project_id: str = None) -> Dict[str, Any]:
    """
    查询日志内容
    
    Args:
        region: 区域
        log_group_id: 日志组ID
        log_stream_id: 日志流ID
        start_time: 开始时间 (格式: YYYY-MM-DD HH:MM:SS)
        end_time: 结束时间 (格式: YYYY-MM-DD HH:MM:SS)
        keywords: 搜索关键词
        limit: 返回条数
        scroll_id: 滚动查询ID（用于分页下一页）
        is_desc: 是否降序（从新到旧，默认True）
        is_iterative: 是否迭代查询
        ak: Access Key
        sk: Secret Key
        project_id: 项目ID
    
    Returns:
        日志内容
    """
    try:
        # Get credentials from environment variables if not provided
        ak, sk, project_id = get_credentials(ak, sk, project_id)
        if not ak or not sk:
            return {"success": False, "error": "Credentials not provided"}
        
        client = get_lts_client(region, ak, sk, project_id)
        
        # 处理时间参数
        if start_time:
            if isinstance(start_time, str) and '-' in start_time:
                start_ts = int(datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
            else:
                start_ts = int(start_time)
        else:
            start_ts = int((datetime.now() - timedelta(hours=1)).timestamp() * 1000)
        
        if end_time:
            if isinstance(end_time, str) and '-' in end_time:
                end_ts = int(datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
            else:
                end_ts = int(end_time)
        else:
            end_ts = int(datetime.now().timestamp() * 1000)
        
        # 构建查询请求
        from huaweicloudsdklts.v2 import ListLogsRequest, QueryLtsLogParams
        
        # 构建查询参数
        query_params = QueryLtsLogParams(
            start_time=start_ts,
            end_time=end_ts,
            limit=limit,
            is_desc=is_desc
        )
        
        if keywords:
            query_params.keywords = keywords
        
        if scroll_id:
            query_params.scroll_id = scroll_id
        
        if is_iterative:
            query_params.is_iterative = is_iterative
        
        # 构建请求
        request = ListLogsRequest(
            log_group_id=log_group_id,
            log_stream_id=log_stream_id,
            body=query_params
        )
        
        response = client.list_logs(request)
        
        logs = []
        if response.logs:
            for log in response.logs:
                logs.append({
                    "content": log.content if hasattr(log, 'content') else str(log),
                    "timestamp": log.timestamp if hasattr(log, 'timestamp') else None,
                    "log_group_id": log_group_id,
                    "log_stream_id": log_stream_id
                })
        
        # 获取滚动ID用于分页
        next_scroll_id = None
        if hasattr(response, 'scroll_id') and response.scroll_id:
            next_scroll_id = response.scroll_id
        
        return {
            "success": True,
            "log_group_id": log_group_id,
            "log_stream_id": log_stream_id,
            "start_time": start_ts,
            "end_time": end_ts,
            "total": len(logs),
            "scroll_id": next_scroll_id,
            "has_more": next_scroll_id is not None,
            "logs": logs
        }
        
    except ClientRequestException as e:
        return {
            "success": False,
            "error": e.error_msg,
            "error_code": e.error_code,
            "status_code": e.status_code
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def query_logs_by_keywords(region: str, log_group_id: str, log_stream_id: str,
                           keywords: str = None, start_time: str = None, 
                           end_time: str = None, limit: int = 100,
                           ak: str = None, sk: str = None,
                           project_id: str = None) -> Dict[str, Any]:
    """
    通过关键词查询日志
    """
    return query_logs(
        region, log_group_id, log_stream_id,
        start_time, end_time, keywords, limit,
        ak, sk, project_id
    )


# ========== CCE集群日志 ==========

def get_cce_logconfigs(region: str, cluster_id: str, ak: str = None,
                       sk: str = None, project_id: str = None,
                       namespace: str = None) -> Dict[str, Any]:
    """
    从CCE集群获取 LogConfig 自定义资源（CR）
    
    LogConfig 是华为云 CCE 中定义应用与 LTS 日志流关联关系的自定义资源
    """
    import sys
    import os
    import base64
    import tempfile
    
    # 检查必要的SDK是否可用
    SDK_AVAILABLE = True
    K8S_AVAILABLE = True
    IMPORT_ERROR = None
    K8S_IMPORT_ERROR = None
    
    try:
        from huaweicloudsdkcore.auth.credentials import BasicCredentials
        from huaweicloudsdkcore.client import Client
        from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
        from huaweicloudsdkcce.v3 import CceClient
        from huaweicloudsdkcce.v3.region.cce_region import CceRegion
        from huaweicloudsdkcce.v3.model.create_kubernetes_cluster_cert_request import CreateKubernetesClusterCertRequest
        from huaweicloudsdkcce.v3.model.cluster_cert_duration import ClusterCertDuration
    except ImportError as e:
        SDK_AVAILABLE = False
        IMPORT_ERROR = str(e)
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }
    
    try:
        import kubernetes
        from kubernetes import client
    except ImportError as e:
        K8S_AVAILABLE = False
        K8S_IMPORT_ERROR = str(e)
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }
    
    # 使用本地的 get_credentials
    ak, sk, project_id = get_credentials(ak, sk, project_id)
    if not ak or not sk:
        return {"success": False, "error": "Credentials not provided"}
    
    # 创建自己的 CCE 客户端
    def _create_cce_client(region_name, access_key, secret_key, proj_id):
        credentials = BasicCredentials(access_key, secret_key)
        client = CceClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(getattr(CceRegion, region_name.upper().replace("-", "_"))) \
            .build()
        return client
    
    temp_files = []
    
    try:
        # 获取集群证书
        cce_client = _create_cce_client(region, ak, sk, project_id)
        
        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body
        
        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()
        
        # 查找外部集群端点
        external_cluster = None
        for c in kubeconfig_data.get('clusters', []):
            if 'external' in c.get('name', '') and 'TLS' not in c.get('name', ''):
                external_cluster = c
                break
        
        if not external_cluster:
            external_cluster = kubeconfig_data.get('clusters', [{}])[0]
        
        if not external_cluster:
            return {
                "success": False,
                "error": "Could not find cluster endpoint"
            }
        
        # 配置Kubernetes客户端
        configuration = kubernetes.client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False
        
        # 写入证书
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break
        
        cert_file = None
        key_file = None
        
        if user_data and user_data.get('client_certificate_data'):
            cert_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.crt', delete=False)
            cert_file.write(base64.b64decode(user_data['client_certificate_data']))
            cert_file.close()
            configuration.cert_file = cert_file.name
            temp_files.append(cert_file.name)
        
        if user_data and user_data.get('client_key_data'):
            key_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.key', delete=False)
            key_file.write(base64.b64decode(user_data['client_key_data']))
            key_file.close()
            configuration.key_file = key_file.name
            temp_files.append(key_file.name)
        
        # 设置默认配置并获取自定义资源
        kubernetes.client.Configuration.set_default(configuration)
        custom_api = kubernetes.client.CustomObjectsApi()
        
        # 尝试常见的 LogConfig Group/Version/Plural 组合
        logconfig_list = []
        tried_combinations = []
        
        # 常见的 LogConfig CR 定义
        cr_combinations = [
            # 华为云常见的 CRD
            ("lts.opentelekomcloud.com", "v1", "logconfigs"),
            ("lts.huaweicloud.com", "v1", "logconfigs"),
            ("lts.io", "v1", "logconfigs"),
            ("logging.huaweicloud.com", "v1", "logconfigs"),
            # 也尝试不带版本的
            ("lts.opentelekomcloud.com", "v1alpha1", "logconfigs"),
            ("lts.opentelekomcloud.com", "v1beta1", "logconfigs"),
        ]
        
        for group, version, plural in cr_combinations:
            tried_combinations.append(f"{group}/{version}/{plural}")
            try:
                if namespace:
                    result = custom_api.list_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural=plural
                    )
                else:
                    result = custom_api.list_cluster_custom_object(
                        group=group,
                        version=version,
                        plural=plural
                    )
                
                if result and 'items' in result:
                    for item in result['items']:
                        lc_info = {
                            "name": item.get('metadata', {}).get('name'),
                            "namespace": item.get('metadata', {}).get('namespace'),
                            "creation_time": str(item.get('metadata', {}).get('creationTimestamp')),
                            "spec": item.get('spec', {}),
                            "status": item.get('status', {}),
                            "api_version": f"{group}/{version}"
                        }
                        logconfig_list.append(lc_info)
                    
                    if logconfig_list:
                        # 找到 LogConfig，跳出循环
                        break
            except Exception as e:
                # 这个组合不存在，继续尝试下一个
                continue
        
        # 清理临时文件
        for f in temp_files:
            try:
                os.unlink(f)
            except:
                pass
        
        return {
            "success": True,
            "cluster_id": cluster_id,
            "namespace": namespace or "all",
            "count": len(logconfig_list),
            "tried_api_combinations": tried_combinations,
            "logconfigs": logconfig_list,
            "note": "如果没有找到LogConfig，说明集群可能没有安装相关CRD，或者使用了不同的API版本"
        }
        
    except Exception as e:
        # 清理临时文件
        for f in temp_files:
            try:
                os.unlink(f)
            except:
                pass
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }
    
    # 获取凭证
    ak, sk, project_id = get_credentials(ak, sk, project_id)
    if not ak or not sk:
        return {"success": False, "error": "Credentials not provided"}
    
    if not K8S_AVAILABLE:
        return {"success": False, "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"}
    
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    temp_files = []
    
    try:
        # 获取集群证书
        cce_client = create_cce_client(region, ak, sk, project_id)
        
        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body
        
        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()
        
        # 查找外部集群端点
        external_cluster = None
        for c in kubeconfig_data.get('clusters', []):
            if 'external' in c.get('name', '') and 'TLS' not in c.get('name', ''):
                external_cluster = c
                break
        
        if not external_cluster:
            external_cluster = kubeconfig_data.get('clusters', [{}])[0]
        
        if not external_cluster:
            return {
                "success": False,
                "error": "Could not find cluster endpoint"
            }
        
        # 配置Kubernetes客户端
        configuration = kubernetes.client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False
        
        # 写入证书
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break
        
        cert_file = None
        key_file = None
        
        if user_data and user_data.get('client_certificate_data'):
            cert_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.crt', delete=False)
            cert_file.write(base64.b64decode(user_data['client_certificate_data']))
            cert_file.close()
            configuration.cert_file = cert_file.name
            temp_files.append(cert_file.name)
        
        if user_data and user_data.get('client_key_data'):
            key_file = tempfile.NamedTemporaryFile(mode='wb', suffix='.key', delete=False)
            key_file.write(base64.b64decode(user_data['client_key_data']))
            key_file.close()
            configuration.key_file = key_file.name
            temp_files.append(key_file.name)
        
        # 设置默认配置并获取自定义资源
        kubernetes.client.Configuration.set_default(configuration)
        custom_api = kubernetes.client.CustomObjectsApi()
        
        # 尝试常见的 LogConfig Group/Version/Plural 组合
        logconfig_list = []
        tried_combinations = []
        
        # 常见的 LogConfig CR 定义
        cr_combinations = [
            # 华为云常见的 CRD
            ("lts.opentelekomcloud.com", "v1", "logconfigs"),
            ("lts.huaweicloud.com", "v1", "logconfigs"),
            ("lts.io", "v1", "logconfigs"),
            ("logging.huaweicloud.com", "v1", "logconfigs"),
            # 也尝试不带版本的
            ("lts.opentelekomcloud.com", "v1alpha1", "logconfigs"),
            ("lts.opentelekomcloud.com", "v1beta1", "logconfigs"),
        ]
        
        for group, version, plural in cr_combinations:
            tried_combinations.append(f"{group}/{version}/{plural}")
            try:
                if namespace:
                    result = custom_api.list_namespaced_custom_object(
                        group=group,
                        version=version,
                        namespace=namespace,
                        plural=plural
                    )
                else:
                    result = custom_api.list_cluster_custom_object(
                        group=group,
                        version=version,
                        plural=plural
                    )
                
                if result and 'items' in result:
                    for item in result['items']:
                        lc_info = {
                            "name": item.get('metadata', {}).get('name'),
                            "namespace": item.get('metadata', {}).get('namespace'),
                            "creation_time": str(item.get('metadata', {}).get('creationTimestamp')),
                            "spec": item.get('spec', {}),
                            "status": item.get('status', {}),
                            "api_version": f"{group}/{version}"
                        }
                        logconfig_list.append(lc_info)
                    
                    if logconfig_list:
                        # 找到 LogConfig，跳出循环
                        break
            except Exception as e:
                # 这个组合不存在，继续尝试下一个
                continue
        
        # 清理临时文件
        for f in temp_files:
            try:
                os.unlink(f)
            except:
                pass
        
        return {
            "success": True,
            "cluster_id": cluster_id,
            "namespace": namespace or "all",
            "count": len(logconfig_list),
            "tried_api_combinations": tried_combinations,
            "logconfigs": logconfig_list,
            "note": "如果没有找到LogConfig，说明集群可能没有安装相关CRD，或者使用了不同的API版本"
        }
        
    except Exception as e:
        # 清理临时文件
        for f in temp_files:
            try:
                os.unlink(f)
            except:
                pass
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


# ========== AOM日志 ==========

def query_aom_logs(region: str, cluster_id: str, namespace: str = None,
                   pod_name: str = None, container_name: str = None,
                   start_time: str = None, end_time: str = None,
                   keywords: str = None, limit: int = 100,
                   ak: str = None, sk: str = None,
                   project_id: str = None) -> Dict[str, Any]:
    """
    查询AOM应用日志
    """
    return {
        "success": True,
        "message": "AOM logs query - requires specific log group/stream IDs",
        "cluster_id": cluster_id,
        "namespace": namespace,
        "pod_name": pod_name,
        "note": "Use query_logs with specific log_group_id and log_stream_id"
    }


# ========== 便捷函数 ==========

def get_recent_logs(region: str, log_group_id: str, log_stream_id: str,
                    hours: int = 1, limit: int = 1000,
                    ak: str = None, sk: str = None,
                    project_id: str = None) -> Dict[str, Any]:
    """
    获取最近的日志
    """
    # Get credentials from environment variables if not provided
    ak, sk, project_id = get_credentials(ak, sk, project_id)
    if not ak or not sk:
        return {"success": False, "error": "Credentials not provided"}
    
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)
    
    return query_logs(
        region, log_group_id, log_stream_id,
        start_time.strftime('%Y-%m-%d %H:%M:%S'),
        end_time.strftime('%Y-%m-%d %H:%M:%S'),
        None, limit, None, True, False,
        ak, sk, project_id
    )


# ========== CLI ==========

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="华为云LTS日志服务工具 (SDK版)")
    subparsers = parser.add_subparsers(dest="action", help="操作")
    
    # list-groups
    grp_parser = subparsers.add_parser("list-groups", help="查询日志组列表")
    grp_parser.add_argument("region", help="区域")
    grp_parser.add_argument("--ak", required=True, help="Access Key")
    grp_parser.add_argument("--sk", required=True, help="Secret Key")
    grp_parser.add_argument("--project-id", help="项目ID")
    
    # list-streams
    stm_parser = subparsers.add_parser("list-streams", help="查询日志流列表")
    stm_parser.add_argument("region", help="区域")
    stm_parser.add_argument("--log-group-id", help="日志组ID")
    stm_parser.add_argument("--ak", required=True, help="Access Key")
    stm_parser.add_argument("--sk", required=True, help="Secret Key")
    stm_parser.add_argument("--project-id", help="项目ID")
    
    # query-logs
    qry_parser = subparsers.add_parser("query-logs", help="查询日志")
    qry_parser.add_argument("region", help="区域")
    qry_parser.add_argument("log_group_id", help="日志组ID")
    qry_parser.add_argument("log_stream_id", help="日志流ID")
    qry_parser.add_argument("--start-time", help="开始时间")
    qry_parser.add_argument("--end-time", help="结束时间")
    qry_parser.add_argument("--keywords", help="关键词")
    qry_parser.add_argument("--limit", type=int, default=100, help="条数")
    qry_parser.add_argument("--ak", required=True, help="Access Key")
    qry_parser.add_argument("--sk", required=True, help="Secret Key")
    qry_parser.add_argument("--project-id", help="项目ID")
    
    args = parser.parse_args()
    
    if args.action == "list-groups":
        result = list_log_groups(args.region, args.ak, args.sk, args.project_id)
    elif args.action == "list-streams":
        result = list_log_streams(args.region, args.log_group_id, args.ak, args.sk, args.project_id)
    elif args.action == "query-logs":
        result = query_logs(
            args.region, args.log_group_id, args.log_stream_id,
            args.start_time, args.end_time, args.keywords, args.limit,
            args.ak, args.sk, args.project_id
        )
    else:
        parser.print_help()
        sys.exit(1)
    
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))