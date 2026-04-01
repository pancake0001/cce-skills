#!/usr/bin/env python3
"""
Huawei Cloud SDK Wrapper
Query resources and monitoring data from Huawei Cloud
"""

import sys
import json
import os
import base64
import yaml
import uuid
import warnings
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

# Suppress matplotlib warnings
warnings.filterwarnings('ignore')

# Import matplotlib for plotting
try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    PLOT_ERROR = "matplotlib not installed"

try:
    from huaweicloudsdkcore.auth.credentials import GlobalCredentials, BasicCredentials
    from huaweicloudsdkcore.client import Client
    from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
    from huaweicloudsdkecs.v2 import *
    from huaweicloudsdkvpc.v2 import *
    from huaweicloudsdkces.v1 import *
    from huaweicloudsdkcce.v3 import *
    from huaweicloudsdkevs.v2 import *
    from huaweicloudsdkeip.v2 import *
    from huaweicloudsdkelb.v2 import *  # ELB v2 for listeners
    from huaweicloudsdkelb.v3 import *  # ELB v3 for loadbalancers
    from huaweicloudsdkiam.v3 import *  # IAM for project info

    # AOM for application monitoring
    try:
        from huaweicloudsdkaom.v2 import AomClient, ShowMetricsDataRequest
        AOM_AVAILABLE = True
    except ImportError as e:
        AOM_AVAILABLE = False
        AOM_IMPORT_ERROR = str(e)

    import kubernetes
    from kubernetes import client as k8s_client
    K8S_AVAILABLE = True
    SDK_AVAILABLE = True
    IMPORT_ERROR = None
except ImportError as e:
    SDK_AVAILABLE = False
    K8S_AVAILABLE = False
    IMPORT_ERROR = str(e)
    K8S_IMPORT_ERROR = str(e)
    from huaweicloudsdkcore.auth.credentials import GlobalCredentials, BasicCredentials
    from huaweicloudsdkcore.client import Client
    from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
    from huaweicloudsdkecs.v2 import *
    from huaweicloudsdkvpc.v2 import *
    from huaweicloudsdkces.v1 import *
    from huaweicloudsdkcce.v3 import *
    import kubernetes
    from kubernetes import client as k8s_client
    K8S_AVAILABLE = True  # Kubernetes still available
    from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException
    from huaweicloudsdkecs.v2 import *
    from huaweicloudsdkvpc.v2 import *
    from huaweicloudsdkces.v1 import *
    from huaweicloudsdkcce.v3 import *
    SDK_AVAILABLE = True
except ImportError as e:
    SDK_AVAILABLE = False
    IMPORT_ERROR = str(e)


# Region to project ID mapping (common regions)
# NOTE: Please set HUAWEI_PROJECT_ID environment variable or pass project_id parameter
# Do not hardcode project IDs in code
PROJECT_IDS = {
    # "cn-north-4": "your-project-id-here",
    # Add your project IDs here or use environment variables
}

# ============================================================
# 安全约束 (Security Constraints)
# ============================================================
# 1. ❌ 禁止将任何认证信息（AK/SK/Token/Certificate）保存到文件系统
# 2. ❌ 禁止将AK/SK保存到长期内存、缓存或持久化存储
# 3. ✅ AK/SK仅在当前请求调用栈中存在，调用结束自动释放
# 4. ✅ 仅非敏感的项目ID缓存在进程内存中（从不写入磁盘）
# 5. ✅ 所有临时证书文件在使用后必须立即删除
# 6. ✅ 禁止在日志、响应或错误信息中泄露AK/SK等敏感信息
# 7. ✅ 从不向任何第三方服务器发送认证信息
# ============================================================

# Project ID cache - auto-populated from IAM (只缓存project_id，不缓存密钥)
_PROJECT_ID_CACHE = {}

# 临时证书文件追踪（用于清理）
_TEMP_CERT_FILES = set()


def _cleanup_cert_files():
    """清理所有临时证书文件"""
    import os
    global _TEMP_CERT_FILES
    for filepath in list(_TEMP_CERT_FILES):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
    _TEMP_CERT_FILES.clear()


def _register_cert_file(filepath: str):
    """注册临时证书文件以便后续清理"""
    global _TEMP_CERT_FILES
    _TEMP_CERT_FILES.add(filepath)


def _safe_delete_file(filepath: str):
    """安全删除文件"""
    import os
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
        global _TEMP_CERT_FILES
        _TEMP_CERT_FILES.discard(filepath)
    except Exception:
        pass


# 危险操作确认存储（用于二次确认）
# 格式: {operation_key: {'timestamp': xxx, 'params': {...}}}
_DANGEROUS_OP_CONFIRMATIONS = {}

# 确认有效期（秒）
_CONFIRMATION_TTL = 60


def _generate_op_key(operation: str, cluster_id: str, namespace: str, name: str) -> str:
    """生成操作唯一标识"""
    return f"{operation}:{cluster_id}:{namespace}:{name}"


def _check_confirmation(operation: str, cluster_id: str, namespace: str, name: str) -> dict:
    """检查是否有有效的确认请求
    
    Returns:
        dict: {'confirmed': bool, 'message': str, 'remaining_seconds': int}
    """
    import time
    global _DANGEROUS_OP_CONFIRMATIONS
    
    op_key = _generate_op_key(operation, cluster_id, namespace, name)
    
    if op_key in _DANGEROUS_OP_CONFIRMATIONS:
        record = _DANGEROUS_OP_CONFIRMATIONS[op_key]
        elapsed = time.time() - record['timestamp']
        
        if elapsed <= _CONFIRMATION_TTL:
            remaining = int(_CONFIRMATION_TTL - elapsed)
            return {
                'confirmed': True,
                'message': f"确认有效，剩余 {remaining} 秒",
                'remaining_seconds': remaining
            }
    
    return {
        'confirmed': False,
        'message': "需要二次确认",
        'remaining_seconds': 0
    }


def _record_confirmation_request(operation: str, cluster_id: str, namespace: str, name: str, params: dict):
    """记录确认请求"""
    import time
    global _DANGEROUS_OP_CONFIRMATIONS
    
    op_key = _generate_op_key(operation, cluster_id, namespace, name)
    _DANGEROUS_OP_CONFIRMATIONS[op_key] = {
        'timestamp': time.time(),
        'params': params
    }


def _clear_confirmation(operation: str, cluster_id: str, namespace: str, name: str):
    """清除确认记录"""
    global _DANGEROUS_OP_CONFIRMATIONS
    op_key = _generate_op_key(operation, cluster_id, namespace, name)
    _DANGEROUS_OP_CONFIRMATIONS.pop(op_key, None)


# Supported Regions
# 华为云支持的区域列表
SUPPORTED_REGIONS = {
    # ===== 中国大陆主要Region =====
    "cn-north-4": {"name": "华北-北京四", "description": "核心区域，推荐"},
    "cn-north-1": {"name": "华北-北京一", "description": "早期区域"},
    "cn-north-9": {"name": "华北-乌兰察布一", "description": "数据中心"},
    "cn-east-3": {"name": "华东-上海一", "description": "华东核心"},
    "cn-east-2": {"name": "华东-上海二", "description": "核心区域"},
    "cn-south-1": {"name": "华南-广州", "description": "华南核心"},
    "cn-southwest-2": {"name": "西南-贵阳一", "description": "骨干数据中心"},
    "cn-west-3": {"name": "西北-西安一", "description": "西北区域"},
    
    # ===== 中国香港及国际区域 =====
    "ap-southeast-1": {"name": "中国香港", "description": "适合亚太业务"},
    "ap-southeast-2": {"name": "亚太-曼谷", "description": "泰国节点"},
    "ap-southeast-3": {"name": "亚太-新加坡", "description": "东南亚核心"},
    "ap-southeast-4": {"name": "亚太-雅加达", "description": "印尼节点"},
    "af-south-1": {"name": "非洲-约翰内斯堡", "description": "南非节点"},
    "la-south-2": {"name": "拉美-圣地亚哥", "description": "智利节点"},
    "la-north-2": {"name": "拉美-墨西哥城", "description": "墨西哥节点"},
    "eu-west-0": {"name": "欧洲-巴黎", "description": "欧洲节点"},
    "ap-northeast-1": {"name": "亚太-东京", "description": "日本节点"},
}

# Endpoint mappings - 全量区域支持
ECS_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "ecs.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "ecs.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "ecs.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "ecs.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "ecs.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "ecs.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "ecs.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "ecs.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "ecs.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "ecs.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "ecs.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "ecs.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "ecs.af-south-1.myhuaweicloud.com",
    "la-south-2": "ecs.la-south-2.myhuaweicloud.com",
    "la-north-2": "ecs.la-north-2.myhuaweicloud.com",
    "eu-west-0": "ecs.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "ecs.ap-northeast-1.myhuaweicloud.com",
}

VPC_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "vpc.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "vpc.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "vpc.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "vpc.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "vpc.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "vpc.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "vpc.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "vpc.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "vpc.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "vpc.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "vpc.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "vpc.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "vpc.af-south-1.myhuaweicloud.com",
    "la-south-2": "vpc.la-south-2.myhuaweicloud.com",
    "la-north-2": "vpc.la-north-2.myhuaweicloud.com",
    "eu-west-0": "vpc.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "vpc.ap-northeast-1.myhuaweicloud.com",
}

CES_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "ces.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "ces.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "ces.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "ces.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "ces.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "ces.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "ces.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "ces.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "ces.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "ces.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "ces.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "ces.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "ces.af-south-1.myhuaweicloud.com",
    "la-south-2": "ces.la-south-2.myhuaweicloud.com",
    "la-north-2": "ces.la-north-2.myhuaweicloud.com",
    "eu-west-0": "ces.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "ces.ap-northeast-1.myhuaweicloud.com",
}

CCE_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "cce.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "cce.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "cce.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "cce.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "cce.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "cce.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "cce.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "cce.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "cce.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "cce.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "cce.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "cce.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "cce.af-south-1.myhuaweicloud.com",
    "la-south-2": "cce.la-south-2.myhuaweicloud.com",
    "la-north-2": "cce.la-north-2.myhuaweicloud.com",
    "eu-west-0": "cce.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "cce.ap-northeast-1.myhuaweicloud.com",
}

# IAM Endpoints (Global service)
IAM_ENDPOINT = "iam.myhuaweicloud.com"


def generate_monitoring_chart(metrics_data: Dict[str, Any], resource_name: str, chart_type: str = "ecs") -> Optional[str]:
    """Generate monitoring chart from metrics data

    Args:
        metrics_data: Dictionary containing metrics with datapoints
        resource_name: Name of the resource being monitored
        chart_type: Type of chart - 'ecs', 'evs', 'elb', or 'eip'

    Returns:
        Path to the generated chart image file, or None if failed
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    try:
        # Generate unique filename
        filename = f"/tmp/{resource_name}_{chart_type}_monitoring_{uuid.uuid4().hex[:8]}.png"

        # Extract time series data
        fig, axes = plt.subplots(2, 1, figsize=(12, 10))
        fig.suptitle(f'{resource_name} Monitoring ({chart_type.upper()})', fontsize=14, fontweight='bold')

        # Process metrics based on chart type
        all_times = []
        all_values_1 = []
        all_values_2 = []
        label_1 = ""
        label_2 = ""

        metrics = metrics_data.get('metrics', {})

        if chart_type == "ecs":
            # CPU utilization
            cpu_data = metrics.get('cpu_util', {})
            if cpu_data.get('datapoints'):
                for dp in cpu_data['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_1.append(dp.get('average', 0))
                label_1 = 'CPU Usage (%)'

            # Disk I/O
            disk_read = metrics.get('disk_read_bytes_rate', {})
            if disk_read.get('datapoints'):
                for dp in disk_read['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_2.append(dp.get('average', 0) / 1024)  # Convert to KB/s
                label_2 = 'Disk Read (KB/s)'

        elif chart_type == "evs":
            # Read/Write IOPS
            read_iops = metrics.get('disk_read_iops', {})
            if read_iops.get('datapoints'):
                for dp in read_iops['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_1.append(dp.get('average', 0))
                label_1 = 'Read IOPS'

            write_iops = metrics.get('disk_write_iops', {})
            if write_iops.get('datapoints'):
                for dp in write_iops['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_2.append(dp.get('average', 0))
                label_2 = 'Write IOPS'

        elif chart_type == "elb":
            # Connections
            conns = metrics.get('connection_count', {})
            if conns.get('datapoints'):
                for dp in conns['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_1.append(dp.get('average', 0))
                label_1 = 'Connections'

            # QPS
            qps = metrics.get('qps', {})
            if qps.get('datapoints'):
                for dp in qps['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_2.append(dp.get('average', 0))
                label_2 = 'QPS'

        elif chart_type == "eip":
            # Bandwidth
            bandwidth = metrics.get('bandwidth', {})
            if bandwidth.get('datapoints'):
                for dp in bandwidth['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_1.append(dp.get('average', 0) / 1024 / 1024)  # Convert to Mbps
                label_1 = 'Bandwidth (Mbps)'

            # Traffic
            traffic = metrics.get('total_streaming_connections', {})
            if traffic.get('datapoints'):
                for dp in traffic['datapoints']:
                    all_times.append(datetime.fromtimestamp(dp['timestamp']/1000, timezone.utc))
                    all_values_2.append(dp.get('average', 0))
                label_2 = 'Connections'

        # Plot first chart
        ax1 = axes[0]
        if all_times and all_values_1:
            ax1.plot(all_times[:len(all_values_1)], all_values_1, 'b-o', linewidth=2, markersize=4, label=label_1)
            ax1.fill_between(all_times[:len(all_values_1)], all_values_1, alpha=0.3)
        ax1.set_ylabel(label_1, fontsize=10)
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper right')
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

        # Plot second chart
        ax2 = axes[1]
        if all_times and all_values_2:
            # Align times with values
            time_len = min(len(all_times), len(all_values_2))
            ax2.plot(all_times[:time_len], all_values_2[:time_len], 'r-o', linewidth=2, markersize=4, label=label_2)
            ax2.fill_between(all_times[:time_len], all_values_2[:time_len], alpha=0.3, color='red')
        ax2.set_ylabel(label_2, fontsize=10)
        ax2.set_xlabel('Time', fontsize=10)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right')
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()

        return filename

    except Exception as e:
        print(f"Error generating chart: {e}", file=sys.stderr)
        return None


def get_credentials(ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> tuple:
    """Get credentials from params or environment variables"""
    access_key = ak or os.environ.get("HUAWEI_AK")
    secret_key = sk or os.environ.get("HUAWEI_SK")
    proj_id = project_id or os.environ.get("HUAWEI_PROJECT_ID")
    return access_key, secret_key, proj_id


def get_project_id_for_region(region: str, ak: Optional[str] = None, sk: Optional[str] = None) -> Optional[str]:
    """Get project ID for a specific region, auto-fetch from IAM if not cached
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
    
    Returns:
        Project ID string or None if not found
    """
    global _PROJECT_ID_CACHE
    
    # Check cache first
    if region in _PROJECT_ID_CACHE:
        return _PROJECT_ID_CACHE[region]
    
    # Get credentials
    access_key, secret_key, _ = get_credentials(ak, sk, None)
    if not access_key or not secret_key:
        return None
    
    # Fetch from IAM
    try:
        from huaweicloudsdkiam.v3 import KeystoneListProjectsRequest
        
        client = create_iam_client(access_key, secret_key)
        request = KeystoneListProjectsRequest()
        request.name = region  # Filter by region name
        
        response = client.keystone_list_projects(request)
        
        if hasattr(response, 'projects') and response.projects:
            for project in response.projects:
                if project.name == region:
                    proj_id = project.id
                    # Cache it
                    _PROJECT_ID_CACHE[region] = proj_id
                    return proj_id
        
        # If not found with filter, try to get all and filter
        request2 = KeystoneListProjectsRequest()
        response2 = client.keystone_list_projects(request2)
        
        if hasattr(response2, 'projects') and response2.projects:
            for project in response2.projects:
                if project.name:
                    _PROJECT_ID_CACHE[project.name] = project.id
            
            return _PROJECT_ID_CACHE.get(region)
        
    except Exception as e:
        # Silently fail, return None
        pass
    
    return None


def get_credentials_with_region(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> tuple:
    """Get credentials with automatic project_id lookup for region
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional, will auto-fetch if not provided)
    
    Returns:
        Tuple of (access_key, secret_key, project_id)
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    
    # If no project_id provided, try to get it for the region
    if not proj_id and region and access_key and secret_key:
        proj_id = get_project_id_for_region(region, access_key, secret_key)
    
    return access_key, secret_key, proj_id


def create_ecs_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create ECS client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = ECS_ENDPOINTS.get(region, f"ecs.{region}.myhuaweicloud.com")
    return EcsClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_vpc_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create VPC client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = VPC_ENDPOINTS.get(region, f"vpc.{region}.myhuaweicloud.com")
    return VpcClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_ces_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create CES (Cloud Eye Service) client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = CES_ENDPOINTS.get(region, f"ces.{region}.myhuaweicloud.com")
    return CesClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_aom_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create AOM (Application Operations Management) client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = f"aom.{region}.myhuaweicloud.com"
    return AomClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_cce_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create CCE (Cloud Container Engine) client

    Note: Using public CCE endpoint.
    """
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    # Use public CCE endpoint
    endpoint = CCE_ENDPOINTS.get(region, f"cce.{region}.myhuaweicloud.com")

    return CceClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


# EVS Endpoints
EVS_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "evs.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "evs.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "evs.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "evs.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "evs.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "evs.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "evs.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "evs.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "evs.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "evs.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "evs.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "evs.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "evs.af-south-1.myhuaweicloud.com",
    "la-south-2": "evs.la-south-2.myhuaweicloud.com",
    "la-north-2": "evs.la-north-2.myhuaweicloud.com",
    "eu-west-0": "evs.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "evs.ap-northeast-1.myhuaweicloud.com",
}


def create_evs_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create EVS (Elastic Volume Service) client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = EVS_ENDPOINTS.get(region, f"evs.{region}.myhuaweicloud.com")
    return EvsClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


# EIP Endpoints
EIP_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "vpc.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "vpc.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "vpc.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "vpc.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "vpc.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "vpc.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "vpc.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "vpc.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "vpc.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "vpc.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "vpc.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "vpc.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "vpc.af-south-1.myhuaweicloud.com",
    "la-south-2": "vpc.la-south-2.myhuaweicloud.com",
    "la-north-2": "vpc.la-north-2.myhuaweicloud.com",
    "eu-west-0": "vpc.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "vpc.ap-northeast-1.myhuaweicloud.com",
}


def create_eip_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create EIP (Elastic IP) client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = EIP_ENDPOINTS.get(region, f"vpc.{region}.myhuaweicloud.com")
    return EipClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


# ELB Endpoints
ELB_ENDPOINTS = {
    # 中国大陆
    "cn-north-4": "elb.cn-north-4.myhuaweicloud.com",
    "cn-north-1": "elb.cn-north-1.myhuaweicloud.com",
    "cn-north-9": "elb.cn-north-9.myhuaweicloud.com",
    "cn-east-3": "elb.cn-east-3.myhuaweicloud.com",
    "cn-east-2": "elb.cn-east-2.myhuaweicloud.com",
    "cn-south-1": "elb.cn-south-1.myhuaweicloud.com",
    "cn-southwest-2": "elb.cn-southwest-2.myhuaweicloud.com",
    "cn-west-3": "elb.cn-west-3.myhuaweicloud.com",
    # 国际区域
    "ap-southeast-1": "elb.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "elb.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "elb.ap-southeast-3.myhuaweicloud.com",
    "ap-southeast-4": "elb.ap-southeast-4.myhuaweicloud.com",
    "af-south-1": "elb.af-south-1.myhuaweicloud.com",
    "la-south-2": "elb.la-south-2.myhuaweicloud.com",
    "la-north-2": "elb.la-north-2.myhuaweicloud.com",
    "eu-west-0": "elb.eu-west-0.myhuaweicloud.com",
    "ap-northeast-1": "elb.ap-northeast-1.myhuaweicloud.com",
}


def create_elb_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create ELB (Elastic Load Balance) client"""
    # Auto-fetch project_id if not provided
    if not project_id:
        project_id = get_project_id_for_region(region, ak, sk)
    
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = ELB_ENDPOINTS.get(region, f"elb.{region}.myhuaweicloud.com")
    return ElbClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_iam_client(ak: str, sk: str):
    """Create IAM (Identity and Access Management) client

    IAM is a global service, so it doesn't require region-specific endpoint.
    Uses GlobalCredentials for IAM operations.
    """
    from huaweicloudsdkiam.v3 import IamClient
    credentials = GlobalCredentials(ak=ak, sk=sk)
    return IamClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(IAM_ENDPOINT) \
        .build()


def list_supported_regions() -> Dict[str, Any]:
    """List all supported Huawei Cloud regions
    
    Returns:
        Dict with success status and list of supported regions
    """
    regions = []
    
    # 中国大陆区域
    china_regions = []
    for region_id, info in SUPPORTED_REGIONS.items():
        if region_id.startswith("cn-"):
            china_regions.append({
                "region_id": region_id,
                "name": info["name"],
                "description": info["description"]
            })
    
    # 国际区域
    international_regions = []
    for region_id, info in SUPPORTED_REGIONS.items():
        if not region_id.startswith("cn-"):
            international_regions.append({
                "region_id": region_id,
                "name": info["name"],
                "description": info["description"]
            })
    
    return {
        "success": True,
        "action": "list_supported_regions",
        "total_count": len(SUPPORTED_REGIONS),
        "china_mainland": {
            "count": len(china_regions),
            "regions": china_regions
        },
        "international": {
            "count": len(international_regions),
            "regions": international_regions
        }
    }


def list_elb_loadbalancers(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, marker: str = None) -> Dict[str, Any]:
    """List ELB load balancers in the specified region"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_elb_client(region, access_key, secret_key, proj_id)

        request = ListLoadBalancersRequest()
        request.page_size = str(limit)
        if marker:
            request.marker = marker

        response = client.list_load_balancers(request)

        loadbalancers = []
        if hasattr(response, 'loadbalancers') and response.loadbalancers:
            for lb in response.loadbalancers:
                # 获取关键字段用于判断ELB类型
                guaranteed = getattr(lb, 'guaranteed', None)
                provider = getattr(lb, 'provider', None)
                lb_type = getattr(lb, 'type', None)
                l4_flavor_id = getattr(lb, 'l4_flavor_id', None)
                l7_flavor_id = getattr(lb, 'l7_flavor_id', None)
                
                # 判断ELB类型
                # 独享型: guaranteed=True 或 provider包含vlb 或 type="Dedicated" 或 有flavor_id
                is_dedicated = (
                    guaranteed is True or
                    (provider and 'vlb' in str(provider).lower()) or
                    (lb_type and lb_type.lower() == 'dedicated') or
                    l4_flavor_id is not None or
                    l7_flavor_id is not None
                )
                
                elb_type = "独享型" if is_dedicated else "共享型"
                
                lb_info = {
                    "id": lb.id,
                    "name": lb.name,
                    "type": lb_type,
                    "elb_type": elb_type,  # 独享型/共享型
                    "guaranteed": guaranteed,
                    "provider": provider,
                    "l4_flavor_id": l4_flavor_id,
                    "l7_flavor_id": l7_flavor_id,
                    "provisioning_status": getattr(lb, 'provisioning_status', None),
                    "vpc_id": getattr(lb, 'vpc_id', None),
                    "vip_address": getattr(lb, 'vip_address', None),
                    "vip_port_id": getattr(lb, 'vip_port_id', None),
                    "created_at": str(getattr(lb, 'created_at', None)) if getattr(lb, 'created_at', None) else None,
                    "updated_at": str(getattr(lb, 'updated_at', None)) if getattr(lb, 'updated_at', None) else None,
                }
                # Optional fields
                if hasattr(lb, 'description'):
                    lb_info["description"] = lb.description
                if hasattr(lb, 'project_id'):
                    lb_info["project_id"] = lb.project_id
                if hasattr(lb, 'domain'):
                    lb_info["domain"] = lb.domain
                if hasattr(lb, 'eip_address'):
                    lb_info["eip_address"] = lb.eip_address
                if hasattr(lb, 'eip_info'):
                    lb_info["eip_info"] = {
                        "eip": lb.eip_info.eip if lb.eip_info else None,
                        "eip_id": lb.eip_info.eip_id if lb.eip_info else None
                    } if hasattr(lb, 'eip_info') else None
                if hasattr(lb, 'az'):
                    lb_info["az"] = lb.az
                if hasattr(lb, 'tags'):
                    lb_info["tags"] = lb.tags
                loadbalancers.append(lb_info)

        # Get pagination info
        result = {
            "success": True,
            "region": region,
            "action": "list_elb_loadbalancers",
            "count": len(loadbalancers),
            "loadbalancers": loadbalancers
        }

        if hasattr(response, 'page_info') and response.page_info:
            result["page_info"] = {
                "next_marker": response.page_info.next_marker,
                "current_count": response.page_info.current_count
            }

        return result

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_elb_listeners(region: str, loadbalancer_id: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """List ELB listeners"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_elb_client(region, access_key, secret_key, proj_id)

        request = ListListenersRequest()
        request.page_size = str(limit)
        if loadbalancer_id:
            request.loadbalancer_id = loadbalancer_id

        response = client.list_listeners(request)

        listeners = []
        if hasattr(response, 'listeners') and response.listeners:
            for listener in response.listeners:
                listener_info = {
                    "id": getattr(listener, 'id', None),
                    "name": getattr(listener, 'name', None),
                    "protocol": getattr(listener, 'protocol', None),
                    "port": getattr(listener, 'port', None),
                    "backend_port": getattr(listener, 'backend_port', None),
                    "status": getattr(listener, 'status', None),
                    "created_at": str(getattr(listener, 'created_at', None)) if getattr(listener, 'created_at', None) else None,
                }
                if hasattr(listener, 'description'):
                    listener_info["description"] = getattr(listener, 'description', None)
                if hasattr(listener, 'default_tls_container_ref'):
                    listener_info["default_tls"] = getattr(listener, 'default_tls_container_ref', None)
                listeners.append(listener_info)

        return {
            "success": True,
            "region": region,
            "loadbalancer_id": loadbalancer_id,
            "action": "list_elb_listeners",
            "count": len(listeners),
            "listeners": listeners
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_elb_metrics(region: str, loadbalancer_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitoring metrics for a specific ELB load balancer
    
    独享型ELB支持CES监控API，使用 lbaas_instance_id 维度
    共享型（经典型）ELB不支持CES监控API
    
    参考: 
    - https://support.huaweicloud.com/usermanual-elb/elb_ug_jk_0001.html
    
    Returns:
        包含ELB类型信息和监控数据
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided"
        }

    if not loadbalancer_id:
        return {
            "success": False,
            "error": "loadbalancer_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # 首先获取 ELB 详情判断类型
        elb_client = create_elb_client(region, access_key, secret_key, proj_id)
        
        elb_type = "未知"
        is_dedicated = False
        
        try:
            from huaweicloudsdkelb.v3 import ShowLoadBalancerRequest
            show_request = ShowLoadBalancerRequest()
            show_request.loadbalancer_id = loadbalancer_id
            elb_detail = elb_client.show_load_balancer(show_request)
            
            if hasattr(elb_detail, 'loadbalancer'):
                lb = elb_detail.loadbalancer
                guaranteed = getattr(lb, 'guaranteed', None)
                provider = getattr(lb, 'provider', None)
                l4_flavor_id = getattr(lb, 'l4_flavor_id', None)
                l7_flavor_id = getattr(lb, 'l7_flavor_id', None)
                
                # 判断是否独享型
                is_dedicated = (
                    guaranteed is True or
                    (provider and 'vlb' in str(provider).lower()) or
                    l4_flavor_id is not None or
                    l7_flavor_id is not None
                )
                
                elb_type = "独享型" if is_dedicated else "共享型"
                
        except Exception as e:
            # 无法获取详情，尝试 CES API 判断
            pass
        
        # 共享型 ELB 不支持 CES 监控
        if not is_dedicated:
            return {
                "success": True,
                "region": region,
                "loadbalancer_id": loadbalancer_id,
                "elb_type": "共享型（经典型）",
                "supported": False,
                "message": "共享型ELB不支持CES监控API",
                "suggestion": [
                    "请在华为云ELB控制台查看监控数据",
                    "升级为独享型ELB以支持API监控"
                ]
            }
        
        # 独享型 ELB - 获取 CES 监控数据
        client = create_ces_client(region, access_key, secret_key, proj_id)

        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)

        # ELB V3 监控指标 (独享型)
        metrics_to_query = [
            # 连接相关
            ("m1_cps", "并发连接数"),
            ("m2_act_conn", "活跃连接数"),
            ("m4_ncps", "新建连接数"),
            # 带宽相关
            ("m22_in_bandwidth", "入网带宽"),
            ("m23_out_bandwidth", "出网带宽"),
            # QPS (7层)
            ("mb_l7_qps", "7层查询速率"),
            # 使用率指标 (关键!)
            ("l7_con_usage", "7层并发连接使用率"),
            ("l7_in_bps_usage", "7层入带宽使用率"),
            ("l4_con_usage", "4层并发连接使用率"),
            ("l4_in_bps_usage", "4层入带宽使用率"),
            # 后端服务器状态
            ("m9_abnormal_servers", "异常主机数"),
            ("ma_normal_servers", "正常主机数"),
        ]

        all_metrics = {}
        success_metrics = 0
        
        # 独享型维度
        for metric_name, display_name in metrics_to_query:
            try:
                request = ShowMetricDataRequest()
                request.namespace = "SYS.ELB"
                request.metric_name = metric_name
                request.dim_0 = f"lbaas_instance_id,{loadbalancer_id}"
                request._from = start_time
                request.to = end_time
                request.period = 60
                request.filter = "average"

                response = client.show_metric_data(request)

                if hasattr(response, 'datapoints') and response.datapoints:
                    datapoints = []
                    for dp in response.datapoints:
                        datapoints.append({
                            "timestamp": dp.timestamp,
                            "average": getattr(dp, 'average', None),
                            "min": getattr(dp, 'min', None),
                            "max": getattr(dp, 'max', None),
                            "unit": getattr(dp, 'unit', '')
                        })
                    latest = datapoints[-1] if datapoints else None
                    all_metrics[metric_name] = {
                        "display_name": display_name,
                        "datapoints": datapoints,
                        "latest_value": latest.get('average') if latest else None,
                        "unit": latest.get('unit', '') if latest else ''
                    }
                    if latest and latest.get('average') is not None:
                        success_metrics += 1
                else:
                    all_metrics[metric_name] = {
                        "display_name": display_name,
                        "datapoints": [],
                        "latest_value": None
                    }

            except Exception as e:
                error_msg = str(e)
                all_metrics[metric_name] = {
                    "display_name": display_name,
                    "error": error_msg[:200] if len(error_msg) > 200 else error_msg
                }

        # 提取关键指标摘要
        summary = {
            "connection_num": all_metrics.get("m1_cps", {}).get("latest_value"),
            "in_bandwidth_bps": all_metrics.get("m22_in_bandwidth", {}).get("latest_value"),
            "l7_qps": all_metrics.get("mb_l7_qps", {}).get("latest_value"),
            "l7_connection_usage_percent": all_metrics.get("l7_con_usage", {}).get("latest_value"),
            "l7_bandwidth_usage_percent": all_metrics.get("l7_in_bps_usage", {}).get("latest_value"),
            "l4_connection_usage_percent": all_metrics.get("l4_con_usage", {}).get("latest_value"),
            "l4_bandwidth_usage_percent": all_metrics.get("l4_in_bps_usage", {}).get("latest_value"),
            "abnormal_servers": all_metrics.get("m9_abnormal_servers", {}).get("latest_value"),
            "normal_servers": all_metrics.get("ma_normal_servers", {}).get("latest_value"),
        }
        
        return {
            "success": True,
            "region": region,
            "loadbalancer_id": loadbalancer_id,
            "elb_type": "独享型",
            "supported": True,
            "metrics_success_count": success_metrics,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, timezone.utc).isoformat(),
                "period": "1min"
            },
            "summary": summary,
            "metrics": all_metrics
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_projects(ak: Optional[str] = None, sk: Optional[str] = None, domain_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List all projects (tenants) available for the account using IAM API

    This function queries IAM to get all project information associated with the account.
    You can optionally filter by domain_id or specific region name.

    Args:
        ak: Access Key ID (optional, will use HUAWEI_AK env var if not provided)
        sk: Secret Access Key (optional, will use HUAWEI_SK env var if not provided)
        domain_id: Filter by domain ID (optional)
        region: Filter by region name (e.g., 'cn-north-4'). If provided, will return project for this region.

    Returns:
        Dictionary with project information including project_id, name, region, etc.
    """
    from huaweicloudsdkiam.v3 import KeystoneListProjectsRequest

    access_key, secret_key, _ = get_credentials(ak, sk, None)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_iam_client(access_key, secret_key)

        # Build the request - use keystone API for listing projects
        request = KeystoneListProjectsRequest()
        if domain_id:
            request.domain_id = domain_id

        # Execute the request - keystone API uses keystone_list_projects
        response = client.keystone_list_projects(request)

        projects = []
        # Keystone API returns projects in a different format
        if hasattr(response, 'projects') and response.projects:
            for project in response.projects:
                project_info = {
                    "id": project.id,
                    "name": project.name,
                    "domain_id": getattr(project, 'domain_id', None),
                    "enabled": getattr(project, 'enabled', None),
                    "description": getattr(project, 'description', None),
                }

                # Extract region from project name (e.g., "cn-north-4" -> region)
                if project.name:
                    # Project names typically match region IDs in Huawei Cloud
                    project_info["region"] = project.name

                projects.append(project_info)
        elif hasattr(response, 'keystone_projects') and response.keystone_projects:
            # Alternative attribute name
            for project in response.keystone_projects:
                project_info = {
                    "id": project.id,
                    "name": project.name,
                    "domain_id": getattr(project, 'domain_id', None),
                    "enabled": getattr(project, 'enabled', None),
                    "description": getattr(project, 'description', None),
                }

                if project.name:
                    project_info["region"] = project.name

                projects.append(project_info)

        # If region parameter provided, filter results
        if region:
            projects = [p for p in projects if p.get('name') == region or p.get('region') == region]

        # Build result with region to project ID mapping
        region_to_project = {}
        for p in projects:
            if p.get('name'):
                region_to_project[p['name']] = p['id']

        return {
            "success": True,
            "action": "list_projects",
            "domain_id": domain_id,
            "region_filter": region,
            "count": len(projects),
            "projects": projects,
            "region_to_project_mapping": region_to_project
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_project_by_region(region: str, ak: Optional[str] = None, sk: Optional[str] = None) -> Dict[str, Any]:
    """Get project ID for a specific region

    This is a convenience function that queries IAM and returns the project ID
    for the specified region name.

    Args:
        region: Region name (e.g., 'cn-north-4', 'cn-east-3', etc.)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)

    Returns:
        Dictionary with project_id for the specified region

    Example:
        >>> get_project_by_region("cn-north-4")
        {"success": True, "region": "cn-north-4", "project_id": "xxx...xxx"}
    """
    access_key, secret_key, _ = get_credentials(ak, sk, None)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not region:
        return {
            "success": False,
            "error": "region is required"
        }

    # Get all projects and filter
    result = list_projects(ak, sk, region=region)

    if result.get('success') and result.get('count', 0) > 0:
        project = result['projects'][0]
        return {
            "success": True,
            "action": "get_project_by_region",
            "region": region,
            "project_id": project['id'],
            "project_name": project.get('name'),
            "domain_id": project.get('domain_id'),
            "enabled": project.get('enabled')
        }
    else:
        return {
            "success": False,
            "error": f"No project found for region: {region}",
            "available_regions": list(result.get('region_to_project_mapping', {}).keys()) if result.get('success') else None
        }


def list_vpc_acls(region: str, vpc_id: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List VPC network ACLs (Access Control Lists) using Neutron API"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_vpc_client(region, access_key, secret_key, proj_id)

        # List firewall groups (ACLs in VPC)
        try:
            request = NeutronListFirewallGroupsRequest()
            response = client.neutron_list_firewall_groups(request)

            acls = []
            if hasattr(response, 'firewall_groups') and response.firewall_groups:
                for acl in response.firewall_groups:
                    acl_info = {
                        "id": acl.id,
                        "name": getattr(acl, 'name', None),
                        "description": getattr(acl, 'description', None),
                        "firewall_policy_id": getattr(acl, 'firewall_policy_id', None),
                        "status": getattr(acl, 'status', None),
                        "admin_state_up": getattr(acl, 'admin_state_up', None),
                        "tags": getattr(acl, 'tags', []),
                        "project_id": getattr(acl, 'project_id', None),
                        "created_at": str(getattr(acl, 'created_at', None)) if getattr(acl, 'created_at', None) else None,
                    }
                    acls.append(acl_info)

            return {
                "success": True,
                "region": region,
                "vpc_id": vpc_id,
                "action": "list_vpc_acls",
                "count": len(acls),
                "acls": acls
            }
        except AttributeError:
            # If neutron API not available, try alternative
            return {
                "success": True,
                "region": region,
                "action": "list_vpc_acls",
                "count": 0,
                "acls": [],
                "note": "VPC ACLs not available or no ACLs configured"
            }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_eip_addresses(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """List EIP (Elastic IP) addresses in the specified region"""
    # Auto-fetch project_id if not provided
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not proj_id:
        return {
            "success": False,
            "error": "Project ID not found. Please provide project_id parameter or ensure the account has access to the region."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # 使用EIP SDK获取EIP列表
        client = create_eip_client(region, access_key, secret_key, proj_id)

        request = ListPublicipsRequest()
        request.limit = str(limit)

        response = client.list_publicips(request)

        eips = []
        if hasattr(response, 'publicips') and response.publicips:
            for eip in response.publicips:
                eip_info = {
                    "id": eip.id,
                    "ip_address": getattr(eip, 'public_ip_address', None),
                    "type": getattr(eip, 'type', None),
                    "status": getattr(eip, 'status', None),
                    "bandwidth_size": getattr(eip, 'bandwidth_size', None),
                    "bandwidth_share_type": getattr(eip, 'bandwidth_share_type', None),
                    "enterprise_project_id": getattr(eip, 'enterprise_project_id', None),
                }
                if hasattr(eip, 'private_ip_address'):
                    eip_info["private_ip_address"] = getattr(eip, 'private_ip_address', None)
                if hasattr(eip, 'instance_id'):
                    eip_info["instance_id"] = getattr(eip, 'instance_id', None)
                if hasattr(eip, 'instance_type'):
                    eip_info["instance_type"] = getattr(eip, 'instance_type', None)
                if hasattr(eip, 'created_at'):
                    eip_info["created_at"] = str(getattr(eip, 'created_at', None)) if getattr(eip, 'created_at', None) else None
                eips.append(eip_info)

        return {
            "success": True,
            "region": region,
            "action": "list_eip_addresses",
            "count": len(eips),
            "eips": eips
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }

        return {
            "success": True,
            "region": region,
            "action": "list_eip_addresses",
            "count": len(eips),
            "eips": eips
        }

    except ImportError:
        return {
            "success": False,
            "error": "requests library not installed"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get EIP list: {str(e)[:100]}",
            "suggestion": "Please check your credentials or use Huawei Cloud Console to view EIP details."
        }


def get_eip_metrics(region: str, eip_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitoring metrics for a specific EIP
    
    包括带宽使用率指标，用于检查是否存在带宽超限情况。
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not eip_id:
        return {
            "success": False,
            "error": "eip_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_ces_client(region, access_key, secret_key, proj_id)

        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)

        # EIP V3 监控指标
        # 格式: (指标名, 显示名)
        metrics_to_query = [
            # 流量相关
            ("eip_in_bytes", "入流量"),
            ("eip_out_bytes", "出流量"),
            # 连接数
            ("eip_connection_num", "连接数"),
            # 带宽使用率 ⭐ 关键指标
            ("bw_usage_in", "入网带宽使用率"),    # %
            ("bw_usage_out", "出网带宽使用率"),   # %
        ]

        all_metrics = {}

        for metric_name, display_name in metrics_to_query:
            try:
                request = ShowMetricDataRequest()
                request.namespace = "SYS.ELB"  # EIP uses ELB namespace
                request.metric_name = metric_name
                request.dim_0 = f"eip_id,{eip_id}"
                request._from = start_time
                request.to = end_time
                request.period = 60
                request.filter = "average"

                response = client.show_metric_data(request)

                if hasattr(response, 'datapoints') and response.datapoints:
                    datapoints = []
                    for dp in response.datapoints:
                        datapoints.append({
                            "timestamp": dp.timestamp,
                            "average": getattr(dp, 'average', None),
                            "min": getattr(dp, 'min', None),
                            "max": getattr(dp, 'max', None),
                            "unit": getattr(dp, 'unit', '')
                        })
                    latest = datapoints[-1] if datapoints else None
                    all_metrics[metric_name] = {
                        "display_name": display_name,
                        "datapoints": datapoints,
                        "latest_value": latest.get('average') if latest else None,
                        "unit": latest.get('unit', '') if latest else ''
                    }
                else:
                    all_metrics[metric_name] = {
                        "display_name": display_name,
                        "datapoints": [],
                        "latest_value": None,
                        "note": "No data available"
                    }

            except Exception as e:
                all_metrics[metric_name] = {
                    "display_name": display_name,
                    "error": str(e)[:200]
                }

        # 提取关键指标摘要
        summary = {
            "in_bytes": all_metrics.get("eip_in_bytes", {}).get("latest_value"),
            "out_bytes": all_metrics.get("eip_out_bytes", {}).get("latest_value"),
            "connection_num": all_metrics.get("eip_connection_num", {}).get("latest_value"),
            "bw_usage_in_percent": all_metrics.get("bw_usage_in", {}).get("latest_value"),
            "bw_usage_out_percent": all_metrics.get("bw_usage_out", {}).get("latest_value"),
        }

        return {
            "success": True,
            "region": region,
            "eip_id": eip_id,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, timezone.utc).isoformat(),
                "period": "1min"
            },
            "summary": summary,
            "metrics": all_metrics
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_ecs_instances(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List ECS instances in the specified region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_ecs_client(region, access_key, secret_key, proj_id)

        request = ListServersDetailsRequest()
        request.limit = str(limit)
        request.offset = str(offset)

        response = client.list_servers_details(request)

        instances = []
        if hasattr(response, 'servers') and response.servers:
            for server in response.servers:
                instance = {
                    "id": server.id,
                    "name": server.name,
                    "status": server.status,
                    "created": server.created,
                    "updated": server.updated,
                }
                if hasattr(server, 'flavor') and server.flavor:
                    instance["flavor"] = {
                        "id": server.flavor.id,
                        "name": server.flavor.name,
                    }
                if hasattr(server, 'addresses') and server.addresses:
                    addresses = []
                    for addr_list in server.addresses.values():
                        for addr in addr_list:
                            addr_info = {
                                "addr": getattr(addr, 'addr', None),
                                "version": getattr(addr, 'version', None),
                            }
                            # Try to get OS extended info
                            if hasattr(addr, 'os_ext_ip_sport_id'):
                                addr_info["type"] = getattr(addr, 'os_ext_ips_type', 'fixed')
                            addresses.append(addr_info)
                    instance["addresses"] = addresses
                if hasattr(server, 'metadata') and server.metadata:
                    instance["metadata"] = server.metadata
                instances.append(instance)

        return {
            "success": True,
            "region": region,
            "action": "list_ecs",
            "count": len(instances),
            "instances": instances
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None),
            "hint": "Try setting HUAWEI_PROJECT_ID environment variable or pass project_id parameter"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_ecs_metrics(region: str, instance_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitoring metrics for a specific ECS instance"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not instance_id:
        return {
            "success": False,
            "error": "instance_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_ces_client(region, access_key, secret_key, proj_id)

        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)

        metrics_to_query = [
            "cpu_util",
            "mem_util",
            "disk_util",
            "network_incoming_bytes_rate",
            "network_outgoing_bytes_rate",
            "disk_read_bytes_rate",
            "disk_write_bytes_rate",
        ]

        all_metrics = {}

        for metric_name in metrics_to_query:
            try:
                request = ShowMetricDataRequest()
                request.namespace = "SYS.ECS"
                request.metric_name = metric_name
                request.dim_0 = f"instance_id,{instance_id}"
                request._from = start_time
                request.to = end_time
                request.period = 300
                request.filter = "average"

                response = client.show_metric_data(request)

                if hasattr(response, 'datapoints') and response.datapoints:
                    datapoints = []
                    for dp in response.datapoints:
                        datapoints.append({
                            "timestamp": dp.timestamp,
                            "average": getattr(dp, 'average', None),
                            "min": getattr(dp, 'min', None),
                            "max": getattr(dp, 'max', None),
                            "unit": getattr(dp, 'unit', '')
                        })
                    latest = datapoints[-1] if datapoints else None
                    all_metrics[metric_name] = {
                        "datapoints": datapoints,
                        "latest_value": latest.get('average') if latest else None,
                        "unit": latest.get('unit', '') if latest else ''
                    }
                else:
                    all_metrics[metric_name] = {"datapoints": [], "note": "No data available"}

            except Exception as e:
                all_metrics[metric_name] = {"error": str(e)}

        return {
            "success": True,
            "region": region,
            "instance_id": instance_id,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, tz=timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, tz=timezone.utc).isoformat(),
                "period": "5min"
            },
            "metrics": all_metrics
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_ecs_metrics_with_chart(region: str, instance_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitoring metrics for a specific ECS instance with chart"""
    result = get_ecs_metrics(region, instance_id, ak, sk, project_id)

    # Generate chart if metrics available
    if result.get('success') and result.get('metrics'):
        chart_path = generate_monitoring_chart(result, f"ecs-{instance_id}", "ecs")
        if chart_path:
            result['chart_file'] = chart_path

    return result


def get_evs_metrics(region: str, volume_id: str, instance_id: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitoring metrics for a specific EVS volume"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not volume_id:
        return {
            "success": False,
            "error": "volume_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_ces_client(region, access_key, secret_key, proj_id)

        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)

        # 构建disk_name维度: {instance-id}-volume-{volume-id}
        if instance_id:
            disk_name = f"{instance_id}-volume-{volume_id}"
        else:
            # 如果没有提供instance_id，使用volume_id
            disk_name = volume_id

        # EVS monitoring metrics (使用 disk_device_ 前缀)
        metrics_to_query = [
            "disk_device_read_bytes_rate",
            "disk_device_write_bytes_rate",
            "disk_device_read_requests_rate",
            "disk_device_write_requests_rate",
        ]

        all_metrics = {}

        for metric_name in metrics_to_query:
            try:
                request = ShowMetricDataRequest()
                request.namespace = "SYS.EVS"
                request.metric_name = metric_name
                request.dim_0 = f"disk_name,{disk_name}"
                request._from = start_time
                request.to = end_time
                request.period = 60
                request.filter = "average"

                response = client.show_metric_data(request)

                if hasattr(response, 'datapoints') and response.datapoints:
                    datapoints = []
                    for dp in response.datapoints:
                        datapoints.append({
                            "timestamp": dp.timestamp,
                            "average": getattr(dp, 'average', None),
                            "min": getattr(dp, 'min', None),
                            "max": getattr(dp, 'max', None),
                            "unit": getattr(dp, 'unit', '')
                        })
                    latest = datapoints[-1] if datapoints else None
                    all_metrics[metric_name] = {
                        "datapoints": datapoints,
                        "latest_value": latest.get('average') if latest else None,
                        "unit": latest.get('unit', '') if latest else ''
                    }
                else:
                    all_metrics[metric_name] = {"datapoints": [], "note": "No data available"}

            except Exception as e:
                all_metrics[metric_name] = {"error": str(e)}

        return {
            "success": True,
            "region": region,
            "volume_id": volume_id,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, timezone.utc).isoformat(),
                "period": "5min"
            },
            "metrics": all_metrics
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_vpc_networks(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List VPC networks in the specified region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_vpc_client(region, access_key, secret_key, proj_id)

        request = ListVpcsRequest()
        request.limit = str(limit)
        request.offset = str(offset)

        response = client.list_vpcs(request)

        vpcs = []
        if hasattr(response, 'vpcs') and response.vpcs:
            for vpc in response.vpcs:
                vpc_info = {
                    "id": vpc.id,
                    "name": vpc.name,
                    "cidr": vpc.cidr,
                    "status": vpc.status,
                    "created_at": str(vpc.created_at) if vpc.created_at else None,
                }
                if hasattr(vpc, 'description') and vpc.description:
                    vpc_info["description"] = vpc.description
                vpcs.append(vpc_info)

        return {
            "success": True,
            "region": region,
            "action": "list_vpc",
            "count": len(vpcs),
            "vpcs": vpcs
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_vpc_subnets(region: str, vpc_id: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List VPC subnets in the specified region with pagination
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        vpc_id: Optional VPC ID to filter subnets
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        limit: Number of results to return (default: 100)
        offset: Pagination offset (default: 0)

    Returns:
        Dictionary with subnets list
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_vpc_client(region, access_key, secret_key, proj_id)

        request = ListSubnetsRequest()
        request.limit = str(limit)
        request.offset = str(offset)
        if vpc_id:
            request.vpc_id = vpc_id

        response = client.list_subnets(request)

        subnets = []
        if hasattr(response, 'subnets') and response.subnets:
            for subnet in response.subnets:
                subnet_info = {
                    "id": subnet.id,
                    "name": subnet.name,
                    "cidr": subnet.cidr,
                    "vpc_id": subnet.vpc_id,
                    "gateway_ip": subnet.gateway_ip,
                    "dns_list": subnet.dns_list,
                    "status": subnet.status,
                    "availability_zone": subnet.availability_zone,
                    "created_at": str(subnet.created_at) if subnet.created_at else None,
                }
                if hasattr(subnet, 'description') and subnet.description:
                    subnet_info["description"] = subnet.description
                subnets.append(subnet_info)

        return {
            "success": True,
            "region": region,
            "action": "list_vpc_subnets",
            "vpc_id": vpc_id or "all",
            "count": len(subnets),
            "subnets": subnets
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_security_groups(region: str, vpc_id: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List security groups in the specified region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_vpc_client(region, access_key, secret_key, proj_id)

        request = ListSecurityGroupsRequest()
        request.limit = str(limit)
        request.offset = str(offset)
        if vpc_id:
            request.vpc_id = vpc_id

        response = client.list_security_groups(request)

        security_groups = []
        if hasattr(response, 'security_groups') and response.security_groups:
            for sg in response.security_groups:
                sg_info = {
                    "id": sg.id,
                    "name": sg.name,
                    "description": getattr(sg, 'description', None),
                    "vpc_id": getattr(sg, 'vpc_id', None),
                    "created_at": str(getattr(sg, 'created_at', None)) if getattr(sg, 'created_at', None) else None,
                    "security_group_rules": []
                }

                # Get security group rules
                if hasattr(sg, 'security_group_rules') and sg.security_group_rules:
                    for rule in sg.security_group_rules:
                        rule_info = {
                            "id": getattr(rule, 'id', None),
                            "direction": getattr(rule, 'direction', None),
                            "ethertype": getattr(rule, 'ethertype', None),
                            "protocol": getattr(rule, 'protocol', None),
                            "port_range_min": getattr(rule, 'port_range_min', None),
                            "port_range_max": getattr(rule, 'port_range_max', None),
                            "remote_ip_prefix": getattr(rule, 'remote_ip_prefix', None),
                            "remote_group_id": getattr(rule, 'remote_group_id', None),
                            "action": getattr(rule, 'action', None),
                            "priority": getattr(rule, 'priority', None),
                            "description": getattr(rule, 'description', None),
                        }
                        sg_info["security_group_rules"].append(rule_info)

                security_groups.append(sg_info)

        return {
            "success": True,
            "region": region,
            "action": "list_security_groups",
            "vpc_id": vpc_id,
            "count": len(security_groups),
            "security_groups": security_groups
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_ecs_flavors(region: str, az: str = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List available ECS flavors (instance types) in the region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_ecs_client(region, access_key, secret_key, proj_id)

        request = ListFlavorsRequest()
        if az:
            request.availability_zone = az

        response = client.list_flavors(request)

        flavors = []
        if hasattr(response, 'flavors'):
            for flavor in response.flavors:
                flavor_info = {
                    "id": flavor.id,
                    "name": flavor.name,
                    "vcpus": flavor.vcpus,
                    "ram": flavor.ram,
                    "disk": getattr(flavor, 'disk', None),
                }
                flavors.append(flavor_info)

        return {
            "success": True,
            "region": region,
            "action": "list_flavors",
            "availability_zone": az,
            "count": len(flavors),
            "flavors": flavors
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_cce_clusters(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List CCE clusters in the specified region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        request = ListClustersRequest()

        response = client.list_clusters(request)

        clusters = []
        if hasattr(response, 'items') and response.items:
            for cluster in response.items:
                cluster_info = {
                    "id": cluster.metadata.uid,
                    "name": cluster.metadata.name,
                    "status": cluster.status.phase if hasattr(cluster, 'status') and hasattr(cluster.status, 'phase') else 'Unknown',
                    "type": cluster.spec.type if hasattr(cluster, 'spec') and hasattr(cluster.spec, 'type') else 'Unknown',
                    "version": cluster.spec.version if hasattr(cluster, 'spec') and hasattr(cluster.spec, 'version') else 'Unknown',
                    "created_at": str(cluster.metadata.creation_timestamp) if hasattr(cluster, 'metadata') and hasattr(cluster.metadata, 'creation_timestamp') else None,
                }
                # Network configuration
                if hasattr(cluster, 'spec') and hasattr(cluster.spec, 'network'):
                    cluster_info["network"] = {
                        "vpc_id": getattr(cluster.spec.network, 'vpc_id', None),
                        "subnet_id": getattr(cluster.spec.network, 'subnet_id', None),
                    }
                # Node configuration
                if hasattr(cluster, 'spec') and hasattr(cluster.spec, 'node'):
                    cluster_info["node_config"] = {
                        "flavor": getattr(cluster.spec.node, 'flavor', None),
                        "count": getattr(cluster.spec.node, 'initial_node_count', None),
                    }
                clusters.append(cluster_info)

        return {
            "success": True,
            "region": region,
            "action": "list_cce_clusters",
            "count": len(clusters),
            "clusters": clusters
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def delete_cce_cluster(region: str, cluster_id: str, confirm: bool = False, delete_evs: bool = False, delete_net: bool = False, delete_obs: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a CCE cluster

    IMPORTANT: This operation will delete the cluster and all its resources.
    User confirmation is required before deletion.

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID to delete
        confirm: Must be set to True to confirm deletion (required)
        delete_evs: Whether to delete associated EVS volumes (default: False)
        delete_net: Whether to delete associated network resources (default: False)
        delete_obs: Whether to delete associated OBS buckets (default: False)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with deletion result
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    # Require explicit confirmation
    if not confirm:
        return {
            "success": False,
            "error": "Deletion not confirmed. To delete the cluster, please set confirm=true parameter.",
            "warning": "This operation will delete the cluster and all its resources (nodes, workloads, etc.). Are you sure you want to delete this cluster?",
            "hint": "Add confirm=true parameter to confirm deletion. Example: delete_cce_cluster region=cn-north-4 cluster_id=xxx confirm=true"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        # Build the delete request
        request = DeleteClusterRequest()
        request.cluster_id = cluster_id
        request.delete_evs = delete_evs
        request.delete_net = delete_net
        request.delete_obs = delete_obs

        # Execute the delete
        response = client.delete_cluster(request)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "delete_cce_cluster",
            "message": f"Cluster deletion request submitted successfully",
            "delete_evs": delete_evs,
            "delete_net": delete_net,
            "delete_obs": delete_obs,
            "response": response.to_dict() if hasattr(response, 'to_dict') else str(response)
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_cce_cluster_nodes(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List nodes in a CCE cluster with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        request = ListNodesRequest()
        request.cluster_id = cluster_id

        response = client.list_nodes(request)

        nodes = []
        if hasattr(response, 'items') and response.items:
            for node in response.items:
                node_info = {
                    "id": node.metadata.uid,
                    "name": node.metadata.name,
                    "status": node.status.phase if hasattr(node, 'status') and hasattr(node.status, 'phase') else 'Unknown',
                    "created_at": str(node.metadata.creation_timestamp) if hasattr(node, 'metadata') and hasattr(node.metadata, 'creation_timestamp') else None,
                }
                # Node spec
                if hasattr(node, 'spec'):
                    node_info["flavor"] = getattr(node.spec, 'flavor', None)
                    node_info["server_id"] = getattr(node.spec, 'server_id', None)  # ECS服务器ID
                    node_info["availability_zone"] = getattr(node.spec, 'az', None)  # 可用区
                # Node conditions
                if hasattr(node, 'status') and hasattr(node.status, 'conditions'):
                    conditions = []
                    for cond in node.status.conditions:
                        conditions.append({
                            "type": cond.type,
                            "status": cond.status,
                            "reason": getattr(cond, 'reason', None),
                        })
                    node_info["conditions"] = conditions
                nodes.append(node_info)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "list_cce_nodes",
            "count": len(nodes),
            "nodes": nodes
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def delete_cce_node(region: str, cluster_id: str, node_id: str, confirm: bool = False, scale_down: bool = True, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a node from CCE cluster

    IMPORTANT: This operation will delete the node and all its pods.
    User confirmation is required before deletion.

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        node_id: Node ID to delete
        confirm: Must be set to True to confirm deletion (required)
        scale_down: Whether to scale down pods before deleting (default: True)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with deletion result
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not node_id:
        return {
            "success": False,
            "error": "node_id is required"
        }

    # Require explicit confirmation
    if not confirm:
        return {
            "success": False,
            "error": "Deletion not confirmed. To delete the node, please set confirm=true parameter.",
            "warning": f"This operation will delete the node '{node_id}' from cluster '{cluster_id}'. All pods on this node will be terminated. Are you sure?",
            "hint": "Add confirm=true parameter to confirm deletion. Example: delete_cce_node region=cn-north-4 cluster_id=xxx node_id=yyy confirm=true"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        # Build the delete request
        request = DeleteNodeRequest()
        request.cluster_id = cluster_id
        request.node_id = node_id
        request.nodepool_scale_down = scale_down

        # Execute the delete
        response = client.delete_node(request)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "node_id": node_id,
            "action": "delete_cce_node",
            "message": f"Node deletion request submitted successfully",
            "scale_down": scale_down,
            "response": response.to_dict() if hasattr(response, 'to_dict') else str(response)
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_cce_node_pools(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List node pools in a CCE cluster with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        request = ListNodePoolsRequest()
        request.cluster_id = cluster_id

        response = client.list_node_pools(request)

        nodepools = []
        if hasattr(response, 'items') and response.items:
            for nodepool in response.items:
                # Get scale groups (default + extension)
                scale_groups = []
                
                # Add default scale group (from spec.nodeTemplate)
                if hasattr(nodepool, 'spec'):
                    default_sg_info = {
                        "name": "default",
                        "type": "default",
                        "initial_node_count": nodepool.spec.initial_node_count if hasattr(nodepool.spec, 'initial_node_count') else None,
                    }
                    
                    # Get info from nodeTemplate
                    if hasattr(nodepool.spec, 'node_template'):
                        node_template = nodepool.spec.node_template
                        default_sg_info["flavor"] = node_template.flavor if hasattr(node_template, 'flavor') else None
                        default_sg_info["availability_zone"] = node_template.az if hasattr(node_template, 'az') else None
                        # Add other nodeTemplate fields if available
                        if hasattr(node_template, 'root_volume'):
                            default_sg_info["root_volume"] = node_template.root_volume.to_dict() if hasattr(node_template.root_volume, 'to_dict') else str(node_template.root_volume)
                        if hasattr(node_template, 'data_volumes'):
                            default_sg_info["data_volumes"] = [dv.to_dict() if hasattr(dv, 'to_dict') else str(dv) for dv in node_template.data_volumes]
                    
                    # Get autoscaling info
                    if hasattr(nodepool.spec, 'autoscaling'):
                        default_sg_info["autoscaling"] = {
                            "enable": nodepool.spec.autoscaling.enable if hasattr(nodepool.spec.autoscaling, 'enable') else None,
                            "min_node_count": nodepool.spec.autoscaling.min_node_count if hasattr(nodepool.spec.autoscaling, 'min_node_count') else None,
                            "max_node_count": nodepool.spec.autoscaling.max_node_count if hasattr(nodepool.spec.autoscaling, 'max_node_count') else None,
                            "scale_down_cooldown_time": nodepool.spec.autoscaling.scale_down_cooldown_time if hasattr(nodepool.spec.autoscaling, 'scale_down_cooldown_time') else None,
                            "priority": nodepool.spec.autoscaling.priority if hasattr(nodepool.spec.autoscaling, 'priority') else None,
                        }
                    
                    scale_groups.append(default_sg_info)
                
                # Add extension scale groups
                if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'extension_scale_groups'):
                    for sg in nodepool.spec.extension_scale_groups:
                        sg_info = {
                            "type": "extension",
                        }
                        if hasattr(sg, 'metadata'):
                            sg_info["name"] = sg.metadata.name if hasattr(sg.metadata, 'name') else None
                            sg_info["uid"] = sg.metadata.uid if hasattr(sg.metadata, 'uid') else None
                        if hasattr(sg, 'spec'):
                            sg_spec = sg.spec
                            sg_info["flavor"] = sg_spec.flavor if hasattr(sg_spec, 'flavor') else None
                            sg_info["availability_zone"] = sg_spec.az if hasattr(sg_spec, 'az') else None
                            sg_info["initial_node_count"] = sg_spec.initial_node_count if hasattr(sg_spec, 'initial_node_count') else None
                            sg_info["min_node_count"] = sg_spec.min_node_count if hasattr(sg_spec, 'min_node_count') else None
                            sg_info["max_node_count"] = sg_spec.max_node_count if hasattr(sg_spec, 'max_node_count') else None
                            if hasattr(sg_spec, 'autoscaling'):
                                sg_info["autoscaling"] = {
                                    "enable": sg_spec.autoscaling.enable if hasattr(sg_spec.autoscaling, 'enable') else None,
                                    "extension_priority": sg_spec.autoscaling.extension_priority if hasattr(sg_spec.autoscaling, 'extension_priority') else None,
                                }
                        scale_groups.append(sg_info)
                
                # Get scale group statuses
                scale_group_statuses = []
                if hasattr(nodepool, 'status') and hasattr(nodepool.status, 'scale_group_statuses'):
                    for sgs in nodepool.status.scale_group_statuses:
                        sgs_info = {}
                        if hasattr(sgs, 'name'):
                            sgs_info["name"] = sgs.name
                        if hasattr(sgs, 'current_node_count'):
                            sgs_info["current_node_count"] = sgs.current_node_count
                        if hasattr(sgs, 'status'):
                            sgs_info["status"] = sgs.status
                        scale_group_statuses.append(sgs_info)
                
                pool_info = {
                    "id": nodepool.metadata.uid,
                    "name": nodepool.metadata.name,
                    "flavor": nodepool.spec.flavor if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'flavor') else None,
                    "initial_node_count": nodepool.spec.initial_node_count if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'initial_node_count') else None,
                    "autoscaling_enabled": nodepool.spec.autoscaling.enabled if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'autoscaling') and hasattr(nodepool.spec.autoscaling, 'enabled') else False,
                    "scale_groups": scale_groups,  # 详细的伸缩组信息
                    "scale_group_statuses": scale_group_statuses,  # 伸缩组状态
                    "created_at": str(nodepool.metadata.creation_timestamp) if hasattr(nodepool, 'metadata') and hasattr(nodepool.metadata, 'creation_timestamp') else None,
                }
                nodepools.append(pool_info)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "list_cce_nodepools",
            "count": len(nodepools),
            "nodepools": nodepools
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_cce_kubeconfig(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, duration: int = 30) -> Dict[str, Any]:
    """Get kubeconfig for a CCE cluster

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        duration: Certificate validity duration in days (default: 30)

    Returns:
        Dictionary with kubeconfig content
    """
    # Auto-fetch project_id if not provided
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not proj_id:
        return {
            "success": False,
            "error": "Project ID not found. Please provide project_id parameter."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        from huaweicloudsdkcce.v3 import CreateKubernetesClusterCertRequest, ClusterCertDuration
        
        client = create_cce_client(region, access_key, secret_key, proj_id)
        
        # Create certificate request
        cert_duration = ClusterCertDuration(duration=duration)
        request = CreateKubernetesClusterCertRequest(cluster_id=cluster_id)
        request.body = cert_duration
        
        response = client.create_kubernetes_cluster_cert(request)
        
        result = {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_kubeconfig",
            "duration_days": duration,
        }
        
        # Parse response
        if hasattr(response, 'to_dict'):
            resp_dict = response.to_dict()
            
            # Extract kubeconfig
            result["kubeconfig"] = resp_dict
            
            # Extract key information
            if 'clusters' in resp_dict:
                result["cluster_endpoints"] = []
                for cluster in resp_dict['clusters']:
                    endpoint_info = {
                        "name": cluster.get('name'),
                        "server": cluster.get('cluster', {}).get('server')
                    }
                    result["cluster_endpoints"].append(endpoint_info)
            
            if 'current_context' in resp_dict:
                result["current_context"] = resp_dict['current_context']
            
            # Generate YAML format kubeconfig
            import yaml
            result["kubeconfig_yaml"] = yaml.dump(resp_dict, default_flow_style=False, allow_unicode=True)
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_cce_addons(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List addons (plugins) in a CCE cluster

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with addon list
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        from huaweicloudsdkcce.v3 import ListAddonInstancesRequest
        request = ListAddonInstancesRequest()
        request.cluster_id = cluster_id

        response = client.list_addon_instances(request)

        addons = []
        if hasattr(response, 'items') and response.items:
            for addon in response.items:
                addon_info = {
                    "name": addon.metadata.name if hasattr(addon, 'metadata') and hasattr(addon.metadata, 'name') else None,
                    "uid": addon.metadata.uid if hasattr(addon, 'metadata') and hasattr(addon.metadata, 'uid') else None,
                    "template_name": addon.spec.template_name if hasattr(addon, 'spec') and hasattr(addon.spec, 'template_name') else None,
                    "version": addon.spec.version if hasattr(addon, 'spec') and hasattr(addon.spec, 'version') else None,
                    "status": addon.status.status if hasattr(addon, 'status') and hasattr(addon.status, 'status') else None,
                    "description": addon.spec.description if hasattr(addon, 'spec') and hasattr(addon.spec, 'description') else None,
                    "created_at": str(addon.metadata.creation_timestamp) if hasattr(addon, 'metadata') and hasattr(addon.metadata, 'creation_timestamp') else None,
                }
                addons.append(addon_info)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "list_cce_addons",
            "count": len(addons),
            "addons": addons
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_cce_addon_detail(region: str, cluster_id: str, addon_name: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed information of a specific CCE addon
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        addon_name: Addon name (e.g., 'cie-collector')
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
    
    Returns:
        Dictionary with addon detailed information including custom parameters
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        from huaweicloudsdkcce.v3 import ShowAddonRequest
        request = ShowAddonRequest()
        request.cluster_id = cluster_id
        request.addon_name = addon_name

        response = client.show_addon(request)

        addon_info = {}
        if hasattr(response, 'spec') and response.spec:
            spec = response.spec
            addon_info["name"] = getattr(spec, 'name', None)
            addon_info["version"] = getattr(spec, 'version', None)
            addon_info["status"] = getattr(spec, 'status', None)
            addon_info["description"] = getattr(spec, 'description', None)
            
            # 获取自定义参数
            if hasattr(spec, 'custom') and spec.custom:
                custom = spec.custom
                addon_info["custom_params"] = {}
                
                # 尝试获取各种配置参数
                if hasattr(custom, 'aom_id'):
                    addon_info["custom_params"]["aom_id"] = custom.aom_id
                if hasattr(custom, 'aom_instance_id'):
                    addon_info["custom_params"]["aom_instance_id"] = custom.aom_instance_id
                if hasattr(custom, 'prom_instance_id'):
                    addon_info["custom_params"]["prom_instance_id"] = custom.prom_instance_id
                if hasattr(custom, 'remote_write_url'):
                    addon_info["custom_params"]["remote_write_url"] = custom.remote_write_url
                if hasattr(custom, 'remote_read_url'):
                    addon_info["custom_params"]["remote_read_url"] = custom.remote_read_url
                
                # 如果custom是字典类型
                if isinstance(custom, dict):
                    addon_info["custom_params"] = custom
                    # 提取关键字段
                    if 'aom_id' in custom:
                        addon_info["aom_id"] = custom['aom_id']
                    if 'aom_instance_id' in custom:
                        addon_info["aom_instance_id"] = custom['aom_instance_id']
                    if 'prom_instance_id' in custom:
                        addon_info["aom_instance_id"] = custom['prom_instance_id']
        
        # 从metadata获取信息
        if hasattr(response, 'metadata') and response.metadata:
            metadata = response.metadata
            addon_info["uid"] = getattr(metadata, 'uid', None)
            addon_info["creation_timestamp"] = str(getattr(metadata, 'creation_timestamp', None))

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_addon_detail",
            "addon": addon_info
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_aom_instances(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, prom_type: Optional[str] = None) -> Dict[str, Any]:
    """List AOM Prometheus instances and their details

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional, will auto-fetch if not provided)
        prom_type: Filter by Prometheus type (optional) - CCE, APPLICATION, default

    Returns:
        Dictionary with AOM Prometheus instances details including endpoints
    """
    # Auto-fetch project_id if not provided
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }
    
    if not proj_id:
        return {
            "success": False,
            "error": "Project ID not found. Please provide project_id parameter or ensure the account has access to the region."
        }

    if not AOM_AVAILABLE:
        return {
            "success": False,
            "error": f"AOM SDK not installed: {AOM_IMPORT_ERROR}"
        }

    try:
        from huaweicloudsdkaom.v2 import AomClient, ListPromInstanceRequest

        client = create_aom_client(region, access_key, secret_key, proj_id)

        request = ListPromInstanceRequest()
        request.limit = 50

        response = client.list_prom_instance(request)
        result = response.to_dict()

        instances = result.get('prometheus', [])

        # 按类型过滤
        if prom_type:
            instances = [i for i in instances if i.get('prom_type', '').upper() == prom_type.upper()]

        # 提取关键信息
        formatted_instances = []
        for inst in instances:
            inst_info = {
                "name": inst.get('prom_name'),
                "id": inst.get('prom_id'),
                "type": inst.get('prom_type'),
                "version": inst.get('prom_version'),
                "project_id": inst.get('project_id'),
                "created_at": inst.get('prom_create_timestamp'),
            }

            # 如果有配置信息，提取endpoint
            spec_config = inst.get('prom_spec_config')
            if spec_config:
                inst_info["endpoints"] = {
                    "remote_write_url": spec_config.get('remote_write_url'),
                    "remote_read_url": spec_config.get('remote_read_url'),
                    "prom_http_api_endpoint": spec_config.get('prom_http_api_endpoint'),
                }

            formatted_instances.append(inst_info)

        return {
            "success": True,
            "region": region,
            "action": "list_aom_instances",
            "count": len(formatted_instances),
            "instances": formatted_instances
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def resize_node_pool(region: str, cluster_id: str, nodepool_id: str, node_count: int, confirm: bool = False, scale_group_names: Optional[List[str]] = None, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Resize (scale up or down) a CCE node pool to the specified number of nodes

    ⚠️ 二次确认机制：
    - 第一步：不带 confirm 参数调用，返回确认提示
    - 第二步：带 confirm=true 再次调用，执行操作

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        nodepool_id: Node pool ID to resize
        node_count: Target node count (desired number of nodes)
        confirm: True to confirm and execute (default: False)
        scale_group_names: List of scale group names to use (default: ["default"])
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with operation result
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not nodepool_id:
        return {
            "success": False,
            "error": "nodepool_id is required"
        }

    if node_count is None or node_count < 0:
        return {
            "success": False,
            "error": "node_count must be a non-negative integer"
        }

    # ========== 二次确认机制 ==========
    if not confirm:
        sg_note = f" (using scale groups: {', '.join(scale_group_names)})" if scale_group_names else ""
        return {
            "success": False,
            "requires_confirmation": True,
            "operation": "resize_nodepool",
            "warning": f"⚠️ 危险操作：即将调整节点池 '{nodepool_id}' 的节点数为 {node_count}{sg_note}",
            "cluster_id": cluster_id,
            "nodepool_id": nodepool_id,
            "target_node_count": node_count,
            "scale_group_names": scale_group_names,
            "hint": "确认操作请添加 confirm=true 参数",
            "note": "⚠️ 此操作会影响集群资源和计费！",
            "example": f"resize_node_pool region={region} cluster_id={cluster_id} nodepool_id={nodepool_id} node_count={node_count} scale_group_names={','.join(scale_group_names)} confirm=true" if scale_group_names else f"resize_node_pool region={region} cluster_id={cluster_id} nodepool_id={nodepool_id} node_count={node_count} confirm=true"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # For testing, try both nodepool name and uid
        # First, get the nodepool details to get both name and uid
        nodepool_result = list_cce_node_pools(region, cluster_id, ak, sk, project_id)
        if not nodepool_result.get("success"):
            return nodepool_result
        
        # Find the target nodepool and get both name and uid
        target_nodepool = None
        nodepool_name = None
        nodepool_uid = None
        for np in nodepool_result.get("nodepools", []):
            np_id = np.get("id")
            np_name = np.get("name")
            if (np_id and np_id.strip() == nodepool_id.strip()) or (np_name and np_name.strip() == nodepool_id.strip()):
                target_nodepool = np
                nodepool_name = np_name
                nodepool_uid = np_id
                break
        if not target_nodepool:
            return {
                "success": False,
                "error": f"Node pool {nodepool_id} not found in cluster {cluster_id}"
            }
        
        # Use specified scale group names, default to ["default"]
        if not scale_group_names:
            scale_group_names = ["default"]

        client = create_cce_client(region, access_key, secret_key, proj_id)

        # Build the scale request using ScaleNodePool API
        # First try with nodepool_uid, then with nodepool_name
        request = ScaleNodePoolRequest()
        request.cluster_id = cluster_id
        request.nodepool_id = nodepool_uid
        
        # Create the scale body - using correct format from API
        scale_body = ScaleNodePoolRequestBody()
        scale_body.node_num = node_count
        scale_body.kind = 'NodePool'
        scale_body.api_version = 'v3'
        
        # Create spec with scale_groups
        spec = ScaleNodePoolSpec()
        spec.desired_node_count = node_count
        
        # Use dynamically retrieved scale_group_names
        spec.scale_groups = scale_group_names
        
        scale_body.spec = spec
        request.body = scale_body
        
        # First try with nodepool_uid
        try:
            response = client.scale_node_pool(request)
        except ClientRequestException as e:
            # If failed with uid, try with name
            if "Nodepool not found" in str(e) or "Invalid nodepool uuid" in str(e):
                request.nodepool_id = nodepool_name
                response = client.scale_node_pool(request)
            else:
                raise

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "nodepool_id": nodepool_id,
            "action": "resize_node_pool",
            "target_node_count": node_count,
            "scale_group_names_used": scale_group_names,
            "message": f"Node pool resize request submitted successfully",
            "response": response.to_dict() if hasattr(response, 'to_dict') else str(response)
        }

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None),
            "hint": "Check if the target node count is valid for the node pool"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_evs_volumes(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0, volume_type: str = None, availability_zone: str = None) -> Dict[str, Any]:
    """List EVS volumes (cloud disks) in the specified region with pagination"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_evs_client(region, access_key, secret_key, proj_id)

        request = ListVolumesRequest()
        request.limit = str(limit)
        request.offset = str(offset)
        if volume_type:
            request.volume_type = volume_type
        if availability_zone:
            request.availability_zone = availability_zone

        response = client.list_volumes(request)

        volumes = []
        if hasattr(response, 'volumes') and response.volumes:
            for volume in response.volumes:
                volume_info = {
                    "id": volume.id,
                    "name": volume.name,
                    "status": volume.status,
                    "volume_type": volume.volume_type,
                    "size": volume.size,
                    "created_at": str(volume.created_at) if volume.created_at else None,
                }
                if hasattr(volume, 'attachments') and volume.attachments:
                    attachments = []
                    for att in volume.attachments:
                        attachments.append({
                            "device": att.device,
                            "server_id": att.server_id,
                            "attachment_id": att.attachment_id,
                        })
                    volume_info["attachments"] = attachments
                if hasattr(volume, 'availability_zone'):
                    volume_info["availability_zone"] = volume.availability_zone
                if hasattr(volume, 'bootable'):
                    volume_info["bootable"] = volume.bootable
                if hasattr(volume, 'encrypted'):
                    volume_info["encrypted"] = volume.encrypted
                if hasattr(volume, 'tags'):
                    volume_info["tags"] = volume.tags
                if hasattr(volume, 'metadata'):
                    volume_info["metadata"] = volume.metadata
                if hasattr(volume, 'description'):
                    volume_info["description"] = volume.description
                if hasattr(volume, 'shareable'):
                    volume_info["shareable"] = volume.shareable
                if hasattr(volume, 'multiattach'):
                    volume_info["multiattach"] = volume.multiattach
                volumes.append(volume_info)

        # Get pagination info
        response_info = {
            "success": True,
            "region": region,
            "action": "list_evs_volumes",
            "count": len(volumes),
            "limit": limit,
            "offset": offset,
            "volumes": volumes
        }

        # Add markers if available
        if hasattr(response, 'volumes_links') and response.volumes_links:
            response_info["links"] = [{"rel": link.rel, "href": link.href} for link in response.volumes_links]

        return response_info

    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_pods(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
    """Get pods in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint (accessible from public network)
        external_cluster = None
        for c in kubeconfig_data.get('clusters', []):
            if 'external' in c.get('name', '') and 'TLS' not in c.get('name', ''):
                external_cluster = c
                break

        if not external_cluster:
            # Fallback to internal cluster
            external_cluster = kubeconfig_data.get('clusters', [{}])[0]

        if not external_cluster:
            return {
                "success": False,
                "error": "Could not find cluster endpoint"
            }

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False  # Skip SSL verification for CCE

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get pods
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        if namespace:
            # Get pods in specific namespace
            pods = v1.list_namespaced_pod(namespace)
        else:
            # Get pods in all namespaces
            pods = v1.list_pod_for_all_namespaces()

        pod_list = []
        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "node": pod.spec.node_name,
                "ip": pod.status.pod_ip,
                "created": str(pod.metadata.creation_timestamp) if pod.metadata.creation_timestamp else None,
                "labels": pod.metadata.labels,
            }
            # Container info
            if pod.status.container_statuses:
                containers = []
                for cs in pod.status.container_statuses:
                    containers.append({
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": str(cs.state) if cs.state else None
                    })
                pod_info["containers"] = containers
            pod_list.append(pod_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_pods",
            "namespace": namespace or "all",
            "count": len(pod_list),
            "pods": pod_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_namespaces(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get namespaces in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_ns_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_ns_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get namespaces
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        # Get all namespaces
        namespaces = v1.list_namespace()

        ns_list = []
        for ns in namespaces.items:
            ns_info = {
                "name": ns.metadata.name,
                "status": ns.status.phase,
                "created": str(ns.metadata.creation_timestamp) if ns.metadata.creation_timestamp else None,
                "labels": ns.metadata.labels,
            }
            ns_list.append(ns_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_namespaces",
            "count": len(ns_list),
            "namespaces": ns_list
        }

        

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_deployments(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
    """Get deployments in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_dep_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_dep_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get deployments
        k8s_client.Configuration.set_default(configuration)
        apps_v1 = k8s_client.AppsV1Api()

        # Get all deployments
        if namespace:
            deployments = apps_v1.list_namespaced_deployment(namespace)
        else:
            deployments = apps_v1.list_deployment_for_all_namespaces()

        dep_list = []
        for dep in deployments.items:
            dep_info = {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.status.replicas if dep.status else None,
                "ready_replicas": dep.status.ready_replicas if dep.status else None,
                "available_replicas": dep.status.available_replicas if dep.status else None,
                "created": str(dep.metadata.creation_timestamp) if dep.metadata.creation_timestamp else None,
                "labels": dep.metadata.labels,
            }
            # 获取spec中的副本数
            if dep.spec:
                dep_info["desired_replicas"] = dep.spec.replicas
                dep_info["strategy"] = dep.spec.strategy.type if dep.spec.strategy else None
            dep_list.append(dep_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_deployments",
            "namespace": namespace or "all",
            "count": len(dep_list),
            "deployments": dep_list
        }

        

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def scale_cce_workload(region: str, cluster_id: str, workload_type: str, name: str, namespace: str, replicas: int, confirm: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Scale a CCE workload (Deployment or StatefulSet) to the specified number of replicas

    ⚠️ 二次确认机制：
    - 第一步：不带 confirm 参数调用，返回确认提示
    - 第二步：带 confirm=true 再次调用，执行操作
    
    Example:
        # 第一步：预览操作
        scale_cce_workload region=xxx cluster_id=xxx workload_type=deployment name=my-app namespace=default replicas=3
        
        # 第二步：确认执行
        scale_cce_workload region=xxx cluster_id=xxx workload_type=deployment name=my-app namespace=default replicas=3 confirm=true

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        workload_type: Type of workload - 'deployment' or 'statefulset'
        name: Name of the workload
        namespace: Kubernetes namespace
        replicas: Target number of replicas
        confirm: True to confirm and execute (default: False)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with scaling result
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not name or not namespace:
        return {
            "success": False,
            "error": "name and namespace are required"
        }

    if workload_type not in ['deployment', 'statefulset']:
        return {
            "success": False,
            "error": "workload_type must be 'deployment' or 'statefulset'"
        }

    if replicas is None or replicas < 0:
        return {
            "success": False,
            "error": "replicas must be a non-negative integer"
        }

    # ========== 二次确认机制 ==========
    if not confirm:
        # 第一步：返回确认提示
        return {
            "success": False,
            "requires_confirmation": True,
            "operation": "scale_workload",
            "warning": f"⚠️ 危险操作：即将修改 {workload_type} '{name}' (命名空间: {namespace}) 的副本数为 {replicas}",
            "cluster_id": cluster_id,
            "namespace": namespace,
            "name": name,
            "workload_type": workload_type,
            "target_replicas": replicas,
            "hint": "确认操作请添加 confirm=true 参数",
            "example": f"scale_cce_workload region={region} cluster_id={cluster_id} workload_type={workload_type} name={name} namespace={namespace} replicas={replicas} confirm=true"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_scale_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_scale_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration
        k8s_client.Configuration.set_default(configuration)

        # Scale the workload
        if workload_type == 'deployment':
            apps_v1 = k8s_client.AppsV1Api()
            # Get current deployment
            deployment = apps_v1.read_namespaced_deployment(name, namespace)
            old_replicas = deployment.spec.replicas

            # Update replicas
            deployment.spec.replicas = replicas
            apps_v1.replace_namespaced_deployment(name, namespace, deployment)

            return {
                "success": True,
                "region": region,
                "cluster_id": cluster_id,
                "action": "scale_deployment",
                "workload_type": "deployment",
                "name": name,
                "namespace": namespace,
                "old_replicas": old_replicas,
                "new_replicas": replicas,
                "message": f"Deployment '{name}' scaled from {old_replicas} to {replicas} replicas"
            }

        elif workload_type == 'statefulset':
            apps_v1 = k8s_client.AppsV1Api()
            # Get current statefulset
            statefulset = apps_v1.read_namespaced_stateful_set(name, namespace)
            old_replicas = statefulset.spec.replicas

            # Update replicas
            statefulset.spec.replicas = replicas
            apps_v1.replace_namespaced_stateful_set(name, namespace, statefulset)

            return {
                "success": True,
                "region": region,
                "cluster_id": cluster_id,
                "action": "scale_statefulset",
                "workload_type": "statefulset",
                "name": name,
                "namespace": namespace,
                "old_replicas": old_replicas,
                "new_replicas": replicas,
                "message": f"StatefulSet '{name}' scaled from {old_replicas} to {replicas} replicas"
            }

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def delete_cce_workload(region: str, cluster_id: str, workload_type: str, name: str, namespace: str, confirm: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a CCE workload (Deployment or StatefulSet)

    ⚠️ 二次确认机制：
    - 第一步：不带 confirm 参数调用，返回确认提示
    - 第二步：带 confirm=true 再次调用，执行操作
    
    WARNING: 此操作将删除工作负载及其所有 Pod，不可恢复！

    Example:
        # 第一步：预览操作
        delete_cce_workload region=xxx cluster_id=xxx workload_type=deployment name=my-app namespace=default
        
        # 第二步：确认执行
        delete_cce_workload region=xxx cluster_id=xxx workload_type=deployment name=my-app namespace=default confirm=true

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        workload_type: Type of workload - 'deployment' or 'statefulset'
        name: Name of the workload to delete
        namespace: Kubernetes namespace
        confirm: True to confirm and execute (default: False)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with deletion result
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not name or not namespace:
        return {
            "success": False,
            "error": "name and namespace are required"
        }

    if workload_type not in ['deployment', 'statefulset']:
        return {
            "success": False,
            "error": "workload_type must be 'deployment' or 'statefulset'"
        }

    # ========== 二次确认机制 ==========
    if not confirm:
        # 第一步：返回确认提示
        return {
            "success": False,
            "requires_confirmation": True,
            "operation": "delete_workload",
            "warning": f"⚠️ 危险操作：即将删除 {workload_type} '{name}' (命名空间: {namespace}) 及其所有 Pod",
            "cluster_id": cluster_id,
            "namespace": namespace,
            "name": name,
            "workload_type": workload_type,
            "hint": "确认操作请添加 confirm=true 参数",
            "note": "⚠️ 此操作不可恢复！",
            "example": f"delete_cce_workload region={region} cluster_id={cluster_id} workload_type={workload_type} name={name} namespace={namespace} confirm=true"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_del_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_del_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration
        k8s_client.Configuration.set_default(configuration)

        # Delete the workload
        if workload_type == 'deployment':
            apps_v1 = k8s_client.AppsV1Api()
            apps_v1.delete_namespaced_deployment(name, namespace)

            return {
                "success": True,
                "region": region,
                "cluster_id": cluster_id,
                "action": "delete_deployment",
                "workload_type": "deployment",
                "name": name,
                "namespace": namespace,
                "message": f"Deployment '{name}' in namespace '{namespace}' deleted successfully"
            }

        elif workload_type == 'statefulset':
            apps_v1 = k8s_client.AppsV1Api()
            apps_v1.delete_namespaced_stateful_set(name, namespace)

            return {
                "success": True,
                "region": region,
                "cluster_id": cluster_id,
                "action": "delete_statefulset",
                "workload_type": "statefulset",
                "name": name,
                "namespace": namespace,
                "message": f"StatefulSet '{name}' in namespace '{namespace}' deleted successfully"
            }

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_nodes(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get nodes in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_node_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_node_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get nodes
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        # Get all nodes
        nodes = v1.list_node()

        node_list = []
        for node in nodes.items:
            # Get conditions
            ready = "Unknown"
            for c in node.status.conditions:
                if c.type == 'Ready':
                    ready = c.status
                    break

            # Get capacity
            cpu = node.status.capacity.get('cpu', 'unknown') if node.status.capacity else 'unknown'
            memory = node.status.capacity.get('memory', 'unknown') if node.status.capacity else 'unknown'
            pods = node.status.capacity.get('pods', 'unknown') if node.status.capacity else 'unknown'

            # Get allocatable
            allocatable_cpu = node.status.allocatable.get('cpu', 'unknown') if node.status.allocatable else 'unknown'
            allocatable_memory = node.status.allocatable.get('memory', 'unknown') if node.status.allocatable else 'unknown'

            # Get node info
            node_info = {
                "name": node.metadata.name,
                "ready": ready,
                "cpu": cpu,
                "memory": memory,
                "max_pods": pods,
                "allocatable_cpu": allocatable_cpu,
                "allocatable_memory": allocatable_memory,
                "created": str(node.metadata.creation_timestamp) if node.metadata.creation_timestamp else None,
                "labels": node.metadata.labels,
            }

            # Get taints
            if node.spec:
                if node.spec.taints:
                    taints = []
                    for taint in node.spec.taints:
                        taints.append({
                            "key": taint.key,
                            "value": taint.value,
                            "effect": taint.effect,
                        })
                    node_info["taints"] = taints
                else:
                    node_info["taints"] = []

            # Get internal IP
            if node.status.addresses:
                for addr in node.status.addresses:
                    if addr.type == 'InternalIP':
                        node_info["internal_ip"] = addr.address
                    elif addr.type == 'Hostname':
                        node_info["hostname"] = addr.address

            node_list.append(node_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_nodes",
            "count": len(node_list),
            "nodes": node_list
        }

        

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_events(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None, limit: int = 500) -> Dict[str, Any]:
    """Get events in a CCE cluster with pagination support"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_event_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_event_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get events
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        # Collect events with pagination
        all_events = []
        continue_token = None
        total_fetched = 0
        max_events = limit

        while total_fetched < max_events:
            page_size = min(500, max_events - total_fetched)

            if namespace:
                events = v1.list_namespaced_event(namespace, limit=page_size, _continue=continue_token)
            else:
                events = v1.list_event_for_all_namespaces(limit=page_size, _continue=continue_token)

            if not events.items:
                break

            for e in events.items:
                event_info = {
                    "name": e.metadata.name,
                    "namespace": e.metadata.namespace if e.metadata else None,
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "first_timestamp": str(e.first_timestamp) if e.first_timestamp else None,
                    "last_timestamp": str(e.last_timestamp) if e.last_timestamp else None,
                    "count": e.count if hasattr(e, 'count') and e.count else 1,
                    "involved_object": {
                        "kind": e.involved_object.kind if e.involved_object else None,
                        "name": e.involved_object.name if e.involved_object else None,
                        "namespace": e.involved_object.namespace if e.involved_object else None,
                    } if e.involved_object else None,
                }
                all_events.append(event_info)

            total_fetched += len(events.items)

            if hasattr(events.metadata, 'continue_') and events.metadata._continue:
                continue_token = events.metadata._continue
            else:
                break

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_events",
            "namespace": namespace or "all",
            "count": len(all_events),
            "limit": limit,
            "events": all_events
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_pvcs(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
    """Get PVCs (PersistentVolumeClaims) in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_pvc_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_pvc_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get PVCs
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        if namespace:
            pvcs = v1.list_namespaced_persistent_volume_claim(namespace)
        else:
            pvcs = v1.list_persistent_volume_claim_for_all_namespaces()

        pvc_list = []
        for pvc in pvcs.items:
            pvc_info = {
                "name": pvc.metadata.name,
                "namespace": pvc.metadata.namespace,
                "status": pvc.status.phase,
                "volume": pvc.spec.volume_name,
                "storage_class": pvc.spec.storage_class_name,
                "capacity": pvc.status.capacity if pvc.status.capacity else {},
                "access_modes": pvc.spec.access_modes,
                "created": str(pvc.metadata.creation_timestamp) if pvc.metadata.creation_timestamp else None,
                "labels": pvc.metadata.labels,
                "annotations": pvc.metadata.annotations,
            }
            # PV details
            if pvc.spec.volume_mode:
                pvc_info["volume_mode"] = pvc.spec.volume_mode
            if pvc.status.access_modes:
                pvc_info["actual_access_modes"] = pvc.status.access_modes
            if pvc.status.conditions:
                conditions = []
                for c in pvc.status.conditions:
                    conditions.append({
                        "type": c.type,
                        "status": c.status,
                        "message": c.message,
                        "reason": c.reason,
                    })
                pvc_info["conditions"] = conditions
            pvc_list.append(pvc_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_pvcs",
            "namespace": namespace or "all",
            "count": len(pvc_list),
            "pvcs": pvc_list
        }

        

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_pvs(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get PVs (PersistentVolumes) in a CCE cluster"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_pv_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_pv_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration and get PVs
        k8s_client.Configuration.set_default(configuration)
        v1 = k8s_client.CoreV1Api()

        pvs = v1.list_persistent_volume()

        pv_list = []
        for pv in pvs.items:
            # Get capacity from status
            capacity = {}
            if hasattr(pv.status, 'capacity'):
                for k, v in dict(pv.status.capacity).items():
                    capacity[k] = v

            pv_info = {
                "name": pv.metadata.name,
                "status": pv.status.phase,
                "capacity": capacity,
                "access_modes": pv.spec.access_modes,
                "storage_class": pv.spec.storage_class_name,
                "created": str(pv.metadata.creation_timestamp) if pv.metadata.creation_timestamp else None,
                "labels": pv.metadata.labels,
                "annotations": pv.metadata.annotations,
            }
            # PV claim ref
            if pv.spec.claim_ref:
                pv_info["claim_ref"] = {
                    "namespace": pv.spec.claim_ref.namespace,
                    "name": pv.spec.claim_ref.name,
                }
            # PV source details - use hasattr to check attributes
            pv_info["source"] = {"type": "unknown"}
            if hasattr(pv.spec, 'host_path') and pv.spec.host_path:
                pv_info["source"] = {"type": "host_path", "path": pv.spec.host_path.path}
            elif hasattr(pv.spec, 'gce_persistent_disk') and pv.spec.gce_persistent_disk:
                pv_info["source"] = {"type": "gce_pd", "pd_name": pv.spec.gce_persistent_disk.pd_name}
            elif hasattr(pv.spec, 'aws_elastic_block_store') and pv.spec.aws_elastic_block_store:
                pv_info["source"] = {"type": "aws_ebs", "volume_id": pv.spec.aws_elastic_block_store.volume_id}
            elif hasattr(pv.spec, 'nfs') and pv.spec.nfs:
                pv_info["source"] = {"type": "nfs", "server": pv.spec.nfs.server, "path": pv.spec.nfs.path}
            elif hasattr(pv.spec, 'cinder') and pv.spec.cinder:
                pv_info["source"] = {"type": "cinder", "volume_id": pv.spec.cinder.volume_id}
            elif hasattr(pv.spec, 'obs') and pv.spec.obs:
                pv_info["source"] = {"type": "obs", "bucket": pv.spec.obs.bucket, "endpoint": pv.spec.obs.endpoint}
            elif hasattr(pv.spec, 'nas') and pv.spec.nas:
                pv_info["source"] = {"type": "nas", "server": pv.spec.nas.server, "path": pv.spec.nas.path}

            if hasattr(pv.spec, 'volume_mode') and pv.spec.volume_mode:
                pv_info["volume_mode"] = pv.spec.volume_mode
            if hasattr(pv.status, 'conditions') and pv.status.conditions:
                conditions = []
                for c in pv.status.conditions:
                    conditions.append({
                        "type": c.type,
                        "status": c.status,
                        "message": c.message,
                        "reason": c.reason,
                    })
                pv_info["conditions"] = conditions
            pv_list.append(pv_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "get_cce_pvs",
            "count": len(pv_list),
            "pvs": pv_list
        }

        

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_services(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
    """Get services in a CCE cluster
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        namespace: Kubernetes namespace (optional, defaults to all namespaces)
    
    Returns:
        Dict with success status and list of services
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    cert_file = None
    key_file = None

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_client_service.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_client_service.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # Create API client
        k8s_client.Configuration.set_default(configuration)
        core_v1 = k8s_client.CoreV1Api()

        # Get services
        service_list = []
        if namespace:
            services = core_v1.list_namespaced_service(namespace)
        else:
            services = core_v1.list_service_for_all_namespaces()

        for svc in services.items:
            # Build service info
            svc_info = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type if svc.spec.type else "ClusterIP",
                "cluster_ip": svc.spec.cluster_ip if hasattr(svc.spec, 'cluster_ip') else None,
                "cluster_ips": list(svc.spec.cluster_ips) if hasattr(svc.spec, 'cluster_ips') and svc.spec.cluster_ips else [],
                "external_ips": list(svc.spec.external_ips) if hasattr(svc.spec, 'external_ips') and svc.spec.external_ips else [],
                "external_name": svc.spec.external_name if hasattr(svc.spec, 'external_name') else None,
                "load_balancer_ip": None,
                "load_balancer_ingress": [],
                "ports": [],
                "selector": dict(svc.spec.selector) if svc.spec.selector else None,
                "session_affinity": svc.spec.session_affinity if hasattr(svc.spec, 'session_affinity') else None,
                "created": svc.metadata.creation_timestamp.isoformat() if svc.metadata.creation_timestamp else None,
                "labels": dict(svc.metadata.labels) if svc.metadata.labels else {},
                "annotations": dict(svc.metadata.annotations) if svc.metadata.annotations else {}
            }

            # Extract LoadBalancer info
            if svc.spec.type == "LoadBalancer":
                if svc.status.load_balancer and svc.status.load_balancer.ingress:
                    for ingress in svc.status.load_balancer.ingress:
                        svc_info["load_balancer_ingress"].append({
                            "ip": ingress.ip,
                            "hostname": ingress.hostname
                        })
                    if svc_info["load_balancer_ingress"]:
                        svc_info["load_balancer_ip"] = svc_info["load_balancer_ingress"][0].get("ip")

            # Extract ports
            if svc.spec.ports:
                for port in svc.spec.ports:
                    port_info = {
                        "name": port.name,
                        "protocol": port.protocol,
                        "port": port.port,
                        "target_port": port.target_port,
                        "node_port": port.node_port
                    }
                    svc_info["ports"].append(port_info)

            service_list.append(svc_info)

        # Cleanup
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "namespace": namespace,
            "count": len(service_list),
            "services": service_list
        }

    except Exception as e:
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_kubernetes_ingresses(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
    """Get ingresses in a CCE cluster
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        namespace: Kubernetes namespace (optional, defaults to all namespaces)
    
    Returns:
        Dict with success status and list of ingresses
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    if not K8S_AVAILABLE:
        return {
            "success": False,
            "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    cert_file = None
    key_file = None

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_client_ingress.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_client_ingress.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # Create API client
        k8s_client.Configuration.set_default(configuration)
        networking_v1 = k8s_client.NetworkingV1Api()

        # Get ingresses
        ingress_list = []
        if namespace:
            ingresses = networking_v1.list_namespaced_ingress(namespace)
        else:
            ingresses = networking_v1.list_ingress_for_all_namespaces()

        for ingress in ingresses.items:
            # Build ingress info
            ingress_info = {
                "name": ingress.metadata.name,
                "namespace": ingress.metadata.namespace,
                "ingress_class_name": ingress.spec.ingress_class_name,
                "default_backend": None,
                "rules": [],
                "tls": [],
                "load_balancer_ingress": [],
                "created": ingress.metadata.creation_timestamp.isoformat() if ingress.metadata.creation_timestamp else None,
                "labels": dict(ingress.metadata.labels) if ingress.metadata.labels else {},
                "annotations": dict(ingress.metadata.annotations) if ingress.metadata.annotations else {}
            }

            # Extract default backend
            if ingress.spec.default_backend:
                ingress_info["default_backend"] = {
                    "service_name": ingress.spec.default_backend.service.name if ingress.spec.default_backend.service else None,
                    "service_port": ingress.spec.default_backend.service.port.number if ingress.spec.default_backend.service and ingress.spec.default_backend.service.port else None
                }

            # Extract rules
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    rule_info = {
                        "host": rule.host,
                        "paths": []
                    }
                    if rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            path_info = {
                                "path": path.path,
                                "path_type": path.path_type,
                                "backend": {
                                    "service_name": path.backend.service.name if path.backend.service else None,
                                    "service_port": path.backend.service.port.number if path.backend.service and path.backend.service.port else None
                                }
                            }
                            rule_info["paths"].append(path_info)
                    ingress_info["rules"].append(rule_info)

            # Extract TLS
            if ingress.spec.tls:
                for tls in ingress.spec.tls:
                    tls_info = {
                        "hosts": tls.hosts,
                        "secret_name": tls.secret_name
                    }
                    ingress_info["tls"].append(tls_info)

            # Extract LoadBalancer ingress status
            if ingress.status.load_balancer and ingress.status.load_balancer.ingress:
                for lb_ingress in ingress.status.load_balancer.ingress:
                    ingress_info["load_balancer_ingress"].append({
                        "ip": lb_ingress.ip,
                        "hostname": lb_ingress.hostname
                    })

            ingress_list.append(ingress_info)

        # Cleanup
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "namespace": namespace,
            "count": len(ingress_list),
            "ingresses": ingress_list
        }

    except Exception as e:
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_aom_prom_metrics_http(region: str, aom_instance_id: str, query: str, start: int = None, end: int = None, step: int = 60, hours: int = 1, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get Prometheus metrics from AOM using direct HTTP request with manual signature
    
    Reference: huaweicloudsdkcore/signer/signer.py
    """
    import hashlib
    import hmac
    import time as time_module
    import urllib.parse
    from urllib.parse import quote, unquote
    import requests
    
    # Auto-fetch project_id if not provided
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    if not proj_id:
        return {"success": False, "error": "Project ID not found. Please provide project_id parameter."}
    
    now = int(time_module.time())
    end_time = end if end else now
    start_time = start if start else (end_time - hours * 3600)
    
    # ========== 构建URL和查询参数 ==========
    base_url = "https://aom.{}.myhuaweicloud.com".format(region)
    
    # 查询参数
    query_params = [
        ('end', str(end_time)),
        ('query', query),
        ('start', str(start_time)),
        ('step', str(step))
    ]
    
    # ========== 按SDK方式构建签名 ==========
    
    # 时间戳
    timestamp = time_module.strftime('%Y%m%dT%H%M%SZ', time_module.gmtime(now))
    
    # 1. HTTP方法
    http_method = 'GET'
    
    # 2. Canonical URI - 统一使用 /aom/api/v1/query_range 路径
    # 所有实例都使用: /v1/{project_id}/{instance_id}/aom/api/v1/query_range
    if aom_instance_id and aom_instance_id not in ['default', '0', 'Prometheus_AOM_Default']:
        resource_path = "/v1/{}/{}/aom/api/v1/query_range".format(proj_id, aom_instance_id)
    else:
        resource_path = "/v1/{}/aom/api/v1/query_range".format(proj_id)
    # SDK的_process_canonical_uri会在URI后面加斜杠
    def url_encode(s):
        return quote(s, safe='~')
    
    pattens = unquote(resource_path).split('/')
    uri_parts = []
    for v in pattens:
        uri_parts.append(url_encode(v))
    canonical_uri = "/".join(uri_parts)
    if canonical_uri[-1] != '/':
        canonical_uri = canonical_uri + "/"
    
    # 3. Canonical Query String (排序)
    sorted_params = sorted(query_params, key=lambda x: x[0])
    canonical_querystring = '&'.join(['{}={}'.format(url_encode(k), url_encode(str(v))) for k, v in sorted_params])
    
    # 4. Headers
    host_header = 'aom.{}.myhuaweicloud.com'.format(region)
    
    # 签名的headers（按字母顺序）
    signed_headers_list = ['host', 'x-project-id', 'x-sdk-date']
    signed_headers = ';'.join(signed_headers_list)
    
    # Canonical headers (每个header一行，最后有\n)
    canonical_headers = 'host:{}\nx-project-id:{}\nx-sdk-date:{}\n'.format(
        host_header, proj_id, timestamp)
    
    # 5. 空body的hash
    hashed_body = hashlib.sha256(b'').hexdigest()
    
    # 6. 构建Canonical Request
    canonical_request = '{}\n{}\n{}\n{}\n{}\n{}'.format(
        http_method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, hashed_body)
    
    # 7. StringToSign (SDK格式：只有3行)
    algorithm = 'SDK-HMAC-SHA256'
    hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    string_to_sign = '{}\n{}\n{}'.format(algorithm, timestamp, hashed_canonical_request)
    
    # 8. 签名 - 使用hex编码，不是base64！
    signature = hmac.new(
        secret_key.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).digest().hex()  # 关键：使用hex()，不是base64
    
    # 9. Authorization
    authorization = '{} Access={}, SignedHeaders={}, Signature={}'.format(
        algorithm, access_key, signed_headers, signature)
    
    # 10. 构建请求URL - 使用resource_path
    url_query_string = '&'.join(['{}={}'.format(k, urllib.parse.quote(str(v))) for k, v in query_params])
    url = "{}{}?{}".format(base_url, resource_path, url_query_string)
    
    # 11. 请求headers
    headers = {
        'Host': host_header,
        'X-Project-Id': proj_id,
        'X-Sdk-Date': timestamp,
        'Authorization': authorization,
    }
    
    try:
        resp = requests.get(url, headers=headers, verify=True, timeout=30)
        
        if resp.status_code == 200:
            result = resp.json()
            return {"success": True, "region": region, "aom_instance_id": aom_instance_id, "endpoint": "https://aom." + region + ".myhuaweicloud.com/v1/" + proj_id + "/" + aom_instance_id, "query": query, "time_range": {"start": start_time, "end": end_time, "step": step}, "url": url, "result": result}
        else:
            return {"success": False, "error": "HTTP " + str(resp.status_code) + ": " + resp.text[:500], "url": url, "request_headers": {k: v for k, v in headers.items() if k != 'Authorization'}, "signature_debug": {"canonical_uri": canonical_uri, "canonical_querystring": canonical_querystring[:200], "signed_headers": signed_headers}}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


def cce_cluster_inspection(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """CCE集群巡检工具
    
    执行全面的集群健康巡检，生成详细报告：
    1. Pod状态巡检 - 检查Pod运行状态和重启情况
    2. Node状态巡检 - 检查节点健康状态
    3. 插件Pod监控 - 检查kube-system命名空间下的CPU/内存使用率
    4. 节点资源监控 - 检查节点CPU/内存/磁盘使用率
    5. Event巡检 - 检查异常事件
    6. AOM告警巡检 - 检查集群相关告警
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
    
    Returns:
        Dictionary with inspection results and detailed report
    """
    import time as time_module
    
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}

    if not cluster_id:
        return {"success": False, "error": "cluster_id is required"}

    # 获取集群名称（用于AOM监控查询）
    cluster_name = cluster_id  # 默认使用cluster_id
    try:
        clusters_result = list_cce_clusters(region, access_key, secret_key, proj_id)
        if clusters_result.get("success"):
            for c in clusters_result.get("clusters", []):
                if c.get("id") == cluster_id:
                    cluster_name = c.get("name", cluster_id)
                    break
    except Exception:
        pass

    # 初始化巡检结果
    inspection = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "inspection_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
        "result": {
            "status": "HEALTHY",
            "total_issues": 0,
            "critical_issues": 0,
            "warning_issues": 0
        },
        "checks": {},
        "issues": [],
        "report": ""
    }
    
    def add_issue(severity, category, item, details):
        """添加问题到巡检结果"""
        inspection["issues"].append({
            "severity": severity,
            "category": category,
            "item": item,
            "details": details
        })
        inspection["result"]["total_issues"] += 1
        if severity == "CRITICAL":
            inspection["result"]["critical_issues"] += 1
            inspection["result"]["status"] = "CRITICAL"
        elif severity == "WARNING":
            inspection["result"]["warning_issues"] += 1
            if inspection["result"]["status"] == "HEALTHY":
                inspection["result"]["status"] = "WARNING"
    
    # ========== 1. Pod状态巡检 ==========
    pod_check = {
        "name": "Pod状态巡检",
        "status": "PASS",
        "total": 0,
        "running": 0,
        "pending": 0,
        "failed": 0,
        "restart_pods": [],
        "abnormal_pods": [],
        "abnormal_summary": {}  # 按异常类型归一统计
    }
    
    pod_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
    if pod_result.get("success"):
        pods = pod_result.get("pods", [])
        pod_check["total"] = len(pods)
        
        # 用于归一统计
        restart_pods_by_type = {}  # 按重启次数分组
        abnormal_pods_by_reason = {}  # 按异常原因分组
        
        for pod in pods:
            status = pod.get("status", "")
            pod_name = pod.get("name", "")
            namespace = pod.get("namespace", "")
            node = pod.get("node", "Unknown")
            ip = pod.get("ip", "Unknown")
            
            if status == "Running":
                pod_check["running"] += 1
                
                # 检查容器重启
                containers = pod.get("containers", [])
                for container in containers:
                    restart_count = container.get("restart_count", 0)
                    container_name = container.get("name", "")
                    container_state = container.get("state", "unknown")
                    ready = container.get("ready", False)
                    
                    if restart_count > 0:
                        # 解析容器状态
                        state_reason = "Unknown"
                        state_message = ""
                        if isinstance(container_state, str):
                            if "CrashLoopBackOff" in container_state:
                                state_reason = "CrashLoopBackOff"
                            elif "ImagePullBackOff" in container_state or "ErrImagePull" in container_state:
                                state_reason = "ImagePullError"
                            elif "OOMKilled" in container_state:
                                state_reason = "OOMKilled"
                            else:
                                state_reason = "ContainerError"
                        
                        restart_info = {
                            "pod": pod_name,
                            "namespace": namespace,
                            "node": node,
                            "ip": ip,
                            "container": container_name,
                            "restart_count": restart_count,
                            "ready": ready,
                            "state_reason": state_reason,
                            "state_detail": container_state[:200] if isinstance(container_state, str) else str(container_state)[:200]
                        }
                        pod_check["restart_pods"].append(restart_info)
                        
                        # 按类型归一统计
                        restart_key = f"{namespace}/{state_reason}" if state_reason != "Unknown" else f"{namespace}/重启异常"
                        if restart_key not in restart_pods_by_type:
                            restart_pods_by_type[restart_key] = {
                                "type": restart_key,
                                "count": 0,
                                "pods": [],
                                "max_restart": 0,
                                "namespace": namespace,
                                "reason": state_reason
                            }
                        restart_pods_by_type[restart_key]["count"] += 1
                        restart_pods_by_type[restart_key]["pods"].append(pod_name)
                        restart_pods_by_type[restart_key]["max_restart"] = max(restart_pods_by_type[restart_key]["max_restart"], restart_count)
                        
                        if restart_count >= 5:
                            add_issue("CRITICAL", "Pod异常重启", pod_name, 
                                f"命名空间: {namespace}, 节点: {node}, 容器 '{container_name}' 重启 {restart_count} 次, 状态: {state_reason}, Ready: {ready}")
                        elif restart_count >= 2:
                            add_issue("WARNING", "Pod重启", pod_name,
                                f"命名空间: {namespace}, 节点: {node}, 容器 '{container_name}' 重启 {restart_count} 次")
            
            elif status == "Pending":
                pod_check["pending"] += 1
                abnormal_info = {
                    "pod": pod_name,
                    "namespace": namespace,
                    "node": node,
                    "ip": ip,
                    "status": status,
                    "reason": pod.get("message", "调度中或资源不足")
                }
                pod_check["abnormal_pods"].append(abnormal_info)
                
                # 按原因归一
                reason_key = f"{namespace}/Pending"
                if reason_key not in abnormal_pods_by_reason:
                    abnormal_pods_by_reason[reason_key] = {"type": reason_key, "count": 0, "pods": [], "namespace": namespace, "reason": "Pending"}
                abnormal_pods_by_reason[reason_key]["count"] += 1
                abnormal_pods_by_reason[reason_key]["pods"].append(pod_name)
                
                add_issue("WARNING", "Pod调度异常", pod_name, 
                    f"命名空间: {namespace}, 状态: Pending, 原因: {pod.get('message', '调度中或资源不足')}")
            
            elif status in ["Failed", "Unknown", "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "OOMKilled", "Evicted"]:
                pod_check["failed"] += 1
                
                # 解析具体异常原因
                error_reason = status
                error_detail = pod.get("message", "")
                
                if "CrashLoopBackOff" in str(pod) or status == "CrashLoopBackOff":
                    error_reason = "CrashLoopBackOff"
                elif "ImagePullBackOff" in str(pod) or "ErrImagePull" in str(pod) or status in ["ImagePullBackOff", "ErrImagePull"]:
                    error_reason = "ImagePullError"
                elif "OOMKilled" in str(pod) or status == "OOMKilled":
                    error_reason = "OOMKilled"
                elif "Evicted" in str(pod) or status == "Evicted":
                    error_reason = "Evicted"
                
                abnormal_info = {
                    "pod": pod_name,
                    "namespace": namespace,
                    "node": node,
                    "ip": ip,
                    "status": status,
                    "reason": error_reason,
                    "detail": error_detail[:200]
                }
                pod_check["abnormal_pods"].append(abnormal_info)
                
                # 按原因归一
                reason_key = f"{namespace}/{error_reason}"
                if reason_key not in abnormal_pods_by_reason:
                    abnormal_pods_by_reason[reason_key] = {"type": reason_key, "count": 0, "pods": [], "namespace": namespace, "reason": error_reason}
                abnormal_pods_by_reason[reason_key]["count"] += 1
                abnormal_pods_by_reason[reason_key]["pods"].append(pod_name)
                
                add_issue("CRITICAL", "Pod异常", pod_name, 
                    f"命名空间: {namespace}, 节点: {node}, 状态: {status}, 原因: {error_reason}, 详情: {error_detail[:100]}")
        
        # 保存归一统计结果
        pod_check["abnormal_summary"] = {
            "restart_groups": list(restart_pods_by_type.values()),
            "abnormal_groups": list(abnormal_pods_by_reason.values())
        }
        
        if pod_check["failed"] > 0 or pod_check["pending"] > 100:
            pod_check["status"] = "FAIL"
        elif pod_check["restart_pods"] or pod_check["abnormal_pods"]:
            pod_check["status"] = "WARN"
    
    inspection["checks"]["pods"] = pod_check
    
    # ========== 2. Node状态巡检 ==========
    node_check = {
        "name": "Node状态巡检",
        "status": "PASS",
        "total": 0,
        "ready": 0,
        "not_ready": 0,
        "abnormal_nodes": [],
        "node_details": []  # 详细的节点信息
    }
    
    node_result = list_cce_cluster_nodes(region, cluster_id, access_key, secret_key, proj_id)
    if node_result.get("success"):
        nodes = node_result.get("nodes", [])
        node_check["total"] = len(nodes)
        
        for node in nodes:
            node_name = node.get("name", "")
            node_id = node.get("id", "")
            node_ip = node.get("ip", "Unknown")
            node_status = node.get("status", "")
            node_flavor = node.get("flavor", "Unknown")
            node_created = node.get("created_at", "")
            
            node_detail = {
                "name": node_name,
                "id": node_id,
                "ip": node_ip,
                "flavor": node_flavor,
                "status": node_status,
                "created_at": node_created,
                "error_reason": None
            }
            
            # Active 表示节点正常
            if node_status == "Active":
                node_check["ready"] += 1
                node_detail["health"] = "健康"
            else:
                node_check["not_ready"] += 1
                
                # 分析异常原因
                error_reason = "节点状态异常"
                if node_status == "Error":
                    error_reason = "节点处于错误状态，可能需要重启或重新加入集群"
                elif node_status == "Deleting":
                    error_reason = "节点正在删除中"
                elif node_status == "Installing":
                    error_reason = "节点正在安装中，请等待安装完成"
                elif node_status == "Abnormal":
                    error_reason = "节点状态异常，请检查节点网络或kubelet服务"
                elif not node_status:
                    error_reason = "节点状态未知，可能无法与API Server通信"
                
                node_detail["health"] = "异常"
                node_detail["error_reason"] = error_reason
                
                node_info = {
                    "name": node_name,
                    "id": node_id,
                    "status": node_status if node_status else "Unknown",
                    "ip": node_ip,
                    "flavor": node_flavor,
                    "reason": error_reason
                }
                node_check["abnormal_nodes"].append(node_info)
                add_issue("CRITICAL", "节点异常", node_name,
                    f"节点ID: {node_id}, 状态: {node_status if node_status else 'Unknown'}, IP: {node_ip}, 规格: {node_flavor}, 原因: {error_reason}")
            
            node_check["node_details"].append(node_detail)
        
        if node_check["not_ready"] > 0:
            node_check["status"] = "FAIL"
    
    inspection["checks"]["nodes"] = node_check
    
    # ========== 3. 插件Pod监控巡检 (kube-system + monitoring) ==========
    addon_pod_check = {
        "name": "插件Pod监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_cpu_pods_top10": [],
        "high_memory_pods_top10": [],
        "namespaces": ["kube-system", "monitoring"]
    }
    
    # ========== 4. 业务Pod监控巡检 (其他命名空间) ==========
    biz_pod_check = {
        "name": "业务Pod监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_cpu_pods_top10": [],
        "high_memory_pods_top10": [],
        "namespaces": []  # 动态获取
    }
    
    # 获取AOM实例 - 尝试所有CCE类型的实例
    aom_instance_id = None
    aom_instance_endpoints = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    cce_instances = []
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                cce_instances.append(instance)
    
    # 尝试每个CCE实例，直到找到有数据的
    for instance in cce_instances:
        test_instance_id = instance.get("id")
        test_query = "up"
        test_result = get_aom_prom_metrics_http(region, test_instance_id, test_query, ak=access_key, sk=secret_key, project_id=proj_id)
        if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
            aom_instance_id = test_instance_id
            aom_instance_endpoints = instance.get("endpoints", {})
            break
    
    if aom_instance_id:
        addon_pod_check["checked"] = True
        addon_pod_check["aom_instance_id"] = aom_instance_id
        biz_pod_check["checked"] = True
        biz_pod_check["aom_instance_id"] = aom_instance_id
        
        # 获取所有Pod列表（用于获取Pod详细信息）
        all_pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id)
        all_pods_map = {}
        all_namespaces = set()
        if all_pods_result.get("success"):
            for pod in all_pods_result.get("pods", []):
                all_pods_map[pod.get("name", "")] = pod
                ns = pod.get("namespace", "")
                if ns and ns not in ["kube-system", "monitoring"]:
                    all_namespaces.add(ns)
        biz_pod_check["namespaces"] = list(all_namespaces)
        
        # ===== 插件Pod巡检 =====
        # CPU数量查询 - kube-system + monitoring
        addon_cpu_count_query = 'count(sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace=~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace=~"kube-system|monitoring"}) * 100 > 80)'
        addon_cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, addon_cpu_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if addon_cpu_count_result.get("success") and addon_cpu_count_result.get("result", {}).get("data", {}).get("result"):
            for item in addon_cpu_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        addon_pod_check["high_cpu_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # CPU Top 10 - 插件
        if addon_pod_check["high_cpu_count"] > 0:
            addon_cpu_top10_query = 'topk(10, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace=~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace=~"kube-system|monitoring"}) * 100)'
            addon_cpu_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, addon_cpu_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
            
            if addon_cpu_top10_result.get("success") and addon_cpu_top10_result.get("result", {}).get("data", {}).get("result"):
                for item in addon_cpu_top10_result["result"]["data"]["result"]:
                    metric = item.get("metric", {})
                    values = item.get("values", [])
                    if values:
                        try:
                            latest_value = float(values[-1][1])
                            pod_name = metric.get("pod", "unknown")
                            namespace = metric.get("namespace", "unknown")
                            
                            if latest_value > 80:
                                pod_info = all_pods_map.get(pod_name, {})
                                labels = pod_info.get("labels", {})
                                app_label = labels.get("app", labels.get("k8s-app", "unknown"))
                                
                                resource_info = {
                                    "pod": pod_name,
                                    "namespace": namespace,
                                    "app": app_label,
                                    "cpu_usage_percent": round(latest_value, 2),
                                    "node": pod_info.get("node", "Unknown"),
                                    "status": "critical" if latest_value > 90 else "warning"
                                }
                                addon_pod_check["high_cpu_pods_top10"].append(resource_info)
                                add_issue("WARNING", "插件Pod CPU使用率高", pod_name,
                                    f"命名空间: {namespace}, CPU使用率: {round(latest_value, 2)}%, 节点: {pod_info.get('node', 'Unknown')}")
                        except (ValueError, IndexError):
                            pass
        
        # 内存数量查询 - 插件
        addon_mem_count_query = 'count(sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace=~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace=~"kube-system|monitoring"}) * 100 > 80)'
        addon_mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, addon_mem_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if addon_mem_count_result.get("success") and addon_mem_count_result.get("result", {}).get("data", {}).get("result"):
            for item in addon_mem_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        addon_pod_check["high_memory_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # 内存 Top 10 - 插件
        if addon_pod_check["high_memory_count"] > 0:
            addon_mem_top10_query = 'topk(10, sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace=~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace=~"kube-system|monitoring"}) * 100)'
            addon_mem_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, addon_mem_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
            
            if addon_mem_top10_result.get("success") and addon_mem_top10_result.get("result", {}).get("data", {}).get("result"):
                for item in addon_mem_top10_result["result"]["data"]["result"]:
                    metric = item.get("metric", {})
                    values = item.get("values", [])
                    if values:
                        try:
                            latest_value = float(values[-1][1])
                            pod_name = metric.get("pod", "unknown")
                            namespace = metric.get("namespace", "unknown")
                            
                            if latest_value > 80:
                                pod_info = all_pods_map.get(pod_name, {})
                                labels = pod_info.get("labels", {})
                                app_label = labels.get("app", labels.get("k8s-app", "unknown"))
                                
                                existing_pod = None
                                for p in addon_pod_check["high_cpu_pods_top10"]:
                                    if p["pod"] == pod_name and p["namespace"] == namespace:
                                        existing_pod = p
                                        break
                                
                                if existing_pod:
                                    existing_pod["memory_usage_percent"] = round(latest_value, 2)
                                else:
                                    resource_info = {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "app": app_label,
                                        "memory_usage_percent": round(latest_value, 2),
                                        "node": pod_info.get("node", "Unknown"),
                                        "status": "critical" if latest_value > 90 else "warning"
                                    }
                                    addon_pod_check["high_memory_pods_top10"].append(resource_info)
                                add_issue("WARNING", "插件Pod内存使用率高", pod_name,
                                    f"命名空间: {namespace}, 内存使用率: {round(latest_value, 2)}%, 节点: {pod_info.get('node', 'Unknown')}")
                        except (ValueError, IndexError):
                            pass
        
        # 设置插件巡检状态
        if addon_pod_check["high_cpu_count"] > 0 or addon_pod_check["high_memory_count"] > 0:
            addon_pod_check["status"] = "WARN"
        
        # ===== 业务Pod巡检 =====
        # CPU数量查询 - 非kube-system/monitoring
        biz_cpu_count_query = 'count(sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace!~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace!~"kube-system|monitoring"}) * 100 > 80)'
        biz_cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, biz_cpu_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if biz_cpu_count_result.get("success") and biz_cpu_count_result.get("result", {}).get("data", {}).get("result"):
            for item in biz_cpu_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        biz_pod_check["high_cpu_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # CPU Top 10 - 业务
        if biz_pod_check["high_cpu_count"] > 0:
            biz_cpu_top10_query = 'topk(10, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{image!="",namespace!~"kube-system|monitoring"}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="cpu",namespace!~"kube-system|monitoring"}) * 100)'
            biz_cpu_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, biz_cpu_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
            
            if biz_cpu_top10_result.get("success") and biz_cpu_top10_result.get("result", {}).get("data", {}).get("result"):
                for item in biz_cpu_top10_result["result"]["data"]["result"]:
                    metric = item.get("metric", {})
                    values = item.get("values", [])
                    if values:
                        try:
                            latest_value = float(values[-1][1])
                            pod_name = metric.get("pod", "unknown")
                            namespace = metric.get("namespace", "unknown")
                            
                            if latest_value > 80:
                                pod_info = all_pods_map.get(pod_name, {})
                                labels = pod_info.get("labels", {})
                                app_label = labels.get("app", labels.get("k8s-app", "unknown"))
                                
                                resource_info = {
                                    "pod": pod_name,
                                    "namespace": namespace,
                                    "app": app_label,
                                    "cpu_usage_percent": round(latest_value, 2),
                                    "node": pod_info.get("node", "Unknown"),
                                    "status": "critical" if latest_value > 90 else "warning"
                                }
                                biz_pod_check["high_cpu_pods_top10"].append(resource_info)
                                add_issue("WARNING", "业务Pod CPU使用率高", pod_name,
                                    f"命名空间: {namespace}, CPU使用率: {round(latest_value, 2)}%, 节点: {pod_info.get('node', 'Unknown')}")
                        except (ValueError, IndexError):
                            pass
        
        # 内存数量查询 - 业务
        biz_mem_count_query = 'count(sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace!~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace!~"kube-system|monitoring"}) * 100 > 80)'
        biz_mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, biz_mem_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if biz_mem_count_result.get("success") and biz_mem_count_result.get("result", {}).get("data", {}).get("result"):
            for item in biz_mem_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        biz_pod_check["high_memory_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # 内存 Top 10 - 业务
        if biz_pod_check["high_memory_count"] > 0:
            biz_mem_top10_query = 'topk(10, sum by (pod, namespace) (container_memory_working_set_bytes{image!="",namespace!~"kube-system|monitoring"}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{resource="memory",namespace!~"kube-system|monitoring"}) * 100)'
            biz_mem_top10_result = get_aom_prom_metrics_http(region, aom_instance_id, biz_mem_top10_query, ak=access_key, sk=secret_key, project_id=proj_id)
            
            if biz_mem_top10_result.get("success") and biz_mem_top10_result.get("result", {}).get("data", {}).get("result"):
                for item in biz_mem_top10_result["result"]["data"]["result"]:
                    metric = item.get("metric", {})
                    values = item.get("values", [])
                    if values:
                        try:
                            latest_value = float(values[-1][1])
                            pod_name = metric.get("pod", "unknown")
                            namespace = metric.get("namespace", "unknown")
                            
                            if latest_value > 80:
                                pod_info = all_pods_map.get(pod_name, {})
                                labels = pod_info.get("labels", {})
                                app_label = labels.get("app", labels.get("k8s-app", "unknown"))
                                
                                existing_pod = None
                                for p in biz_pod_check["high_cpu_pods_top10"]:
                                    if p["pod"] == pod_name and p["namespace"] == namespace:
                                        existing_pod = p
                                        break
                                
                                if existing_pod:
                                    existing_pod["memory_usage_percent"] = round(latest_value, 2)
                                else:
                                    resource_info = {
                                        "pod": pod_name,
                                        "namespace": namespace,
                                        "app": app_label,
                                        "memory_usage_percent": round(latest_value, 2),
                                        "node": pod_info.get("node", "Unknown"),
                                        "status": "critical" if latest_value > 90 else "warning"
                                    }
                                    biz_pod_check["high_memory_pods_top10"].append(resource_info)
                                add_issue("WARNING", "业务Pod内存使用率高", pod_name,
                                    f"命名空间: {namespace}, 内存使用率: {round(latest_value, 2)}%, 节点: {pod_info.get('node', 'Unknown')}")
                        except (ValueError, IndexError):
                            pass
        
        # 设置业务巡检状态
        if biz_pod_check["high_cpu_count"] > 0 or biz_pod_check["high_memory_count"] > 0:
            biz_pod_check["status"] = "WARN"
            
    else:
        addon_pod_check["status"] = "SKIP"
        addon_pod_check["message"] = "未找到CCE类型的AOM实例"
        biz_pod_check["status"] = "SKIP"
        biz_pod_check["message"] = "未找到CCE类型的AOM实例"
    
    inspection["checks"]["addon_pod_monitoring"] = addon_pod_check
    inspection["checks"]["biz_pod_monitoring"] = biz_pod_check
    
    # ========== 5. 节点资源监控巡检 ==========
    node_mon_check = {
        "name": "节点资源监控巡检",
        "status": "PASS",
        "checked": False,
        "high_cpu_count": 0,
        "high_memory_count": 0,
        "high_disk_count": 0,
        "high_cpu_nodes_top10": [],
        "high_memory_nodes_top10": [],
        "high_disk_nodes_top10": [],
        "all_high_resource_nodes": []  # 所有高资源使用节点
    }
    
    if aom_instance_id:
        node_mon_check["checked"] = True
        node_mon_check["aom_instance_id"] = aom_instance_id
        
        # 获取节点信息映射（从Kubernetes API获取，节点名即IP）
        node_info_map = {}
        k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
        if k8s_nodes_result.get("success"):
            for node in k8s_nodes_result.get("nodes", []):
                node_name = node.get("name", "")  # Kubernetes节点名即IP
                if node_name:
                    node_info_map[node_name] = {
                        "name": node_name,
                        "ip": node_name,
                        "status": node.get("status", "Unknown")
                    }
        
        # ===== 第一步：查询CPU使用率大于80%的节点数量 =====
        cpu_count_query = "count(100 - (avg by (instance) (irate(node_cpu_seconds_total{mode='idle', cluster_name='" + cluster_name + "'}[5m])) * 100) > 80)"
        cpu_count_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if cpu_count_result.get("success") and cpu_count_result.get("result", {}).get("data", {}).get("result"):
            for item in cpu_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        node_mon_check["high_cpu_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # ===== 第二步：如果CPU高使用率节点数量>0，获取Top 10详细信息 =====
        if node_mon_check["high_cpu_count"] > 0:
            cpu_top10_query = "topk(10, 100 - (avg by (instance) (irate(node_cpu_seconds_total{mode='idle', cluster_name='" + cluster_name + "'}[5m])) * 100))"
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
                            
                            # 只添加使用率大于80%的节点
                            if latest_value > 80:
                                node_info = node_info_map.get(instance_ip, {})
                                
                                resource_info = {
                                    "instance": instance,
                                    "node_ip": instance_ip,
                                    "node_name": node_info.get("name", instance_ip),
                                    "cpu_usage_percent": round(latest_value, 2),
                                    "status": "critical" if latest_value > 90 else "warning"
                                }
                                node_mon_check["high_cpu_nodes_top10"].append(resource_info)
                                
                                # 添加到问题列表
                                add_issue("WARNING", "节点CPU高", instance_ip,
                                    f"节点: {instance_ip}, CPU使用率: {round(latest_value, 2)}%")
                        except (ValueError, IndexError):
                            pass
        
        # ===== 第三步：查询内存使用率大于80%的节点数量 =====
        mem_count_query = "count(avg by (instance) ((1 - node_memory_MemAvailable_bytes{cluster_name='" + cluster_name + "'} / node_memory_MemTotal_bytes{cluster_name='" + cluster_name + "'})) * 100 > 80)"
        mem_count_result = get_aom_prom_metrics_http(region, aom_instance_id, mem_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if mem_count_result.get("success") and mem_count_result.get("result", {}).get("data", {}).get("result"):
            for item in mem_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        node_mon_check["high_memory_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # ===== 第四步：如果内存高使用率节点数量>0，获取Top 10详细信息 =====
        if node_mon_check["high_memory_count"] > 0:
            mem_top10_query = "topk(10, avg by (instance) ((1 - node_memory_MemAvailable_bytes{cluster_name='" + cluster_name + "'} / node_memory_MemTotal_bytes{cluster_name='" + cluster_name + "'})) * 100)"
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
                            
                            # 只添加使用率大于80%的节点
                            if latest_value > 80:
                                node_info = node_info_map.get(instance_ip, {})
                                
                                # 检查是否已在CPU Top10中
                                existing_node = None
                                for n in node_mon_check["high_cpu_nodes_top10"]:
                                    if n["node_ip"] == instance_ip:
                                        existing_node = n
                                        break
                                
                                if existing_node:
                                    existing_node["memory_usage_percent"] = round(latest_value, 2)
                                else:
                                    resource_info = {
                                        "instance": instance,
                                        "node_ip": instance_ip,
                                        "node_name": node_info.get("name", instance_ip),
                                        "memory_usage_percent": round(latest_value, 2),
                                        "status": "critical" if latest_value > 90 else "warning"
                                    }
                                    node_mon_check["high_memory_nodes_top10"].append(resource_info)
                                
                                # 添加到问题列表
                                add_issue("WARNING", "节点内存高", instance_ip,
                                    f"节点: {instance_ip}, 内存使用率: {round(latest_value, 2)}%")
                        except (ValueError, IndexError):
                            pass
        
        # ===== 第五步：查询磁盘使用率大于80%的节点数量 =====
        disk_count_query = "count(avg by (instance) ((1 - node_filesystem_avail_bytes{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='" + cluster_name + "'} / node_filesystem_size_bytes{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='" + cluster_name + "'})) * 100 > 80)"
        disk_count_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_count_query, ak=access_key, sk=secret_key, project_id=proj_id)
        
        if disk_count_result.get("success") and disk_count_result.get("result", {}).get("data", {}).get("result"):
            for item in disk_count_result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        node_mon_check["high_disk_count"] = int(latest_value)
                    except (ValueError, IndexError):
                        pass
        
        # ===== 第六步：如果磁盘高使用率节点数量>0，获取Top 10详细信息 =====
        if node_mon_check["high_disk_count"] > 0:
            disk_top10_query = "topk(10, avg by (instance) ((1 - node_filesystem_avail_bytes{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='" + cluster_name + "'} / node_filesystem_size_bytes{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='" + cluster_name + "'})) * 100)"
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
                            
                            # 只添加使用率大于80%的节点
                            if latest_value > 80:
                                node_info = node_info_map.get(instance_ip, {})
                                
                                # 检查是否已在CPU或内存Top10中
                                existing_node = None
                                for n in node_mon_check["high_cpu_nodes_top10"]:
                                    if n["node_ip"] == instance_ip:
                                        existing_node = n
                                        break
                                if not existing_node:
                                    for n in node_mon_check["high_memory_nodes_top10"]:
                                        if n["node_ip"] == instance_ip:
                                            existing_node = n
                                            break
                                
                                if existing_node:
                                    existing_node["disk_usage_percent"] = round(latest_value, 2)
                                else:
                                    resource_info = {
                                        "instance": instance,
                                        "node_ip": instance_ip,
                                        "node_name": node_info.get("name", instance_ip),
                                        "disk_usage_percent": round(latest_value, 2),
                                        "status": "critical" if latest_value > 90 else "warning"
                                    }
                                    node_mon_check["high_disk_nodes_top10"].append(resource_info)
                                
                                # 添加到问题列表
                                add_issue("WARNING", "节点磁盘高", instance_ip,
                                    f"节点: {instance_ip}, 磁盘使用率: {round(latest_value, 2)}%")
                        except (ValueError, IndexError):
                            pass
        
        # 合并所有高资源使用节点
        all_nodes_map_temp = {}
        for n in node_mon_check["high_cpu_nodes_top10"]:
            key = n["node_ip"]
            all_nodes_map_temp[key] = n
        for n in node_mon_check["high_memory_nodes_top10"]:
            key = n["node_ip"]
            if key in all_nodes_map_temp:
                all_nodes_map_temp[key]["memory_usage_percent"] = n.get("memory_usage_percent")
            else:
                all_nodes_map_temp[key] = n
        for n in node_mon_check["high_disk_nodes_top10"]:
            key = n["node_ip"]
            if key in all_nodes_map_temp:
                all_nodes_map_temp[key]["disk_usage_percent"] = n.get("disk_usage_percent")
            else:
                all_nodes_map_temp[key] = n
        node_mon_check["all_high_resource_nodes"] = list(all_nodes_map_temp.values())
        
        # 设置状态
        if node_mon_check["high_cpu_count"] > 0 or node_mon_check["high_memory_count"] > 0 or node_mon_check["high_disk_count"] > 0:
            node_mon_check["status"] = "WARN"
    else:
        node_mon_check["status"] = "SKIP"
        node_mon_check["message"] = "未找到CCE类型的AOM实例，无法获取监控数据"
    
    inspection["checks"]["node_monitoring"] = node_mon_check
    
    # ========== 5. Event巡检 ==========
    event_check = {
        "name": "Event巡检",
        "status": "PASS",
        "total": 0,
        "normal": 0,
        "warning": 0,
        "critical_events": [],
        "events_by_reason": {},  # 按原因归一统计
        "events_by_namespace": {}  # 按命名空间统计
    }
    
    event_result = get_kubernetes_events(region, cluster_id, access_key, secret_key, proj_id)
    if event_result.get("success"):
        events = event_result.get("events", [])
        event_check["total"] = len(events)
        
        critical_keywords = ["Failed", "Error", "CrashLoopBackOff", "OOMKilled", "Evicted", "Insufficient", "BackOff", "Unhealthy", "Killing", "FailedScheduling"]
        
        for event in events:
            event_type = event.get("type", "")
            reason = event.get("reason", "")
            message = event.get("message", "")
            namespace = event.get("namespace", "default")
            involved_obj = event.get("involved_object", {})
            obj_name = involved_obj.get("name", "Unknown")
            obj_kind = involved_obj.get("kind", "Unknown")
            count = event.get("count", 1)
            first_seen = event.get("first_timestamp", "")
            last_seen = event.get("last_timestamp", "")
            
            # 按命名空间统计
            if namespace not in event_check["events_by_namespace"]:
                event_check["events_by_namespace"][namespace] = {"total": 0, "warning": 0, "critical": 0}
            event_check["events_by_namespace"][namespace]["total"] += 1
            
            if event_type == "Warning":
                event_check["warning"] += 1
                event_check["events_by_namespace"][namespace]["warning"] += 1
                
                is_critical = any(kw in reason or kw in message for kw in critical_keywords)
                
                # 按原因归一统计
                reason_key = f"{namespace}/{reason}"
                if reason_key not in event_check["events_by_reason"]:
                    event_check["events_by_reason"][reason_key] = {
                        "reason": reason,
                        "namespace": namespace,
                        "count": 0,
                        "objects": [],
                        "severity": "critical" if is_critical else "warning"
                    }
                event_check["events_by_reason"][reason_key]["count"] += count
                if obj_name not in event_check["events_by_reason"][reason_key]["objects"]:
                    event_check["events_by_reason"][reason_key]["objects"].append(obj_name)
                
                if is_critical:
                    event_check["events_by_namespace"][namespace]["critical"] += 1
                    event_info = {
                        "reason": reason,
                        "message": message[:500],
                        "count": count,
                        "namespace": namespace,
                        "involved_object": obj_name,
                        "object_kind": obj_kind,
                        "first_seen": first_seen,
                        "last_seen": last_seen
                    }
                    event_check["critical_events"].append(event_info)
            else:
                event_check["normal"] += 1
        
        if event_check["critical_events"]:
            event_check["status"] = "WARN"
            # 添加关键事件到问题列表（按原因归一）
            for reason_key, reason_data in event_check["events_by_reason"].items():
                if reason_data["severity"] == "critical":
                    affected_objects = ", ".join(reason_data["objects"][:5])
                    if len(reason_data["objects"]) > 5:
                        affected_objects += f" 等共{len(reason_data['objects'])}个对象"
                    add_issue("WARNING", "关键事件", reason_data["reason"],
                        f"命名空间: {reason_data['namespace']}, 原因: {reason_data['reason']}, 累计次数: {reason_data['count']}, 影响对象: {affected_objects}")
    
    inspection["checks"]["events"] = event_check
    
    # ========== 6. AOM告警巡检 ==========
    alarm_check = {
        "name": "AOM告警巡检",
        "status": "PASS",
        "total": 0,
        "cluster_alarms": [],
        "severity_breakdown": {"Critical": 0, "Major": 0, "Minor": 0, "Info": 0},
        "alarms_by_type": {},  # 按告警类型归一
        "alarms_by_resource": {}  # 按资源类型归一
    }
    
    alarm_result = list_aom_current_alarms(region, access_key, secret_key, proj_id, event_type="active_alert")
    if alarm_result.get("success"):
        events = alarm_result.get("events", [])
        alarm_check["total"] = len(events)
        
        for event in events:
            cluster_name = event.get("cluster_name", "")
            cluster_id_in_event = event.get("cluster_id", "")
            severity = event.get("event_severity", "Info")
            event_name = event.get("event_name", "Unknown")
            message = event.get("message", "")
            resource_type = event.get("resource_type", "Unknown")
            resource_id = event.get("resource_id", "")
            starts_at = event.get("starts_at", "")
            
            # 过滤当前集群的告警
            if cluster_id == cluster_id_in_event or cluster_name:
                alarm_check["severity_breakdown"][severity] = alarm_check["severity_breakdown"].get(severity, 0) + 1
                
                alarm_info = {
                    "name": event_name,
                    "severity": severity,
                    "cluster": cluster_name or cluster_id_in_event,
                    "message": message[:500],
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "starts_at": starts_at
                }
                alarm_check["cluster_alarms"].append(alarm_info)
                
                # 按告警类型归一
                alarm_type = event_name.split("##")[0] if "##" in event_name else event_name
                if alarm_type not in alarm_check["alarms_by_type"]:
                    alarm_check["alarms_by_type"][alarm_type] = {
                        "type": alarm_type,
                        "count": 0,
                        "severity": severity,
                        "resources": [],
                        "messages": []
                    }
                alarm_check["alarms_by_type"][alarm_type]["count"] += 1
                if resource_id and resource_id not in alarm_check["alarms_by_type"][alarm_type]["resources"]:
                    alarm_check["alarms_by_type"][alarm_type]["resources"].append(resource_id)
                if message and message not in alarm_check["alarms_by_type"][alarm_type]["messages"]:
                    alarm_check["alarms_by_type"][alarm_type]["messages"].append(message[:200])
                
                # 按资源类型归一
                if resource_type not in alarm_check["alarms_by_resource"]:
                    alarm_check["alarms_by_resource"][resource_type] = {"type": resource_type, "count": 0, "alarms": []}
                alarm_check["alarms_by_resource"][resource_type]["count"] += 1
                alarm_check["alarms_by_resource"][resource_type]["alarms"].append(alarm_info)
                
                if severity == "Critical":
                    add_issue("CRITICAL", "严重告警", event_name,
                        f"告警类型: {alarm_type}, 资源: {resource_type}/{resource_id}, 消息: {message[:200]}")
                elif severity == "Major":
                    add_issue("WARNING", "重要告警", event_name,
                        f"告警类型: {alarm_type}, 资源: {resource_type}/{resource_id}, 消息: {message[:200]}")
        
        if alarm_check["severity_breakdown"]["Critical"] > 0:
            alarm_check["status"] = "FAIL"
        elif alarm_check["severity_breakdown"]["Major"] > 0:
            alarm_check["status"] = "WARN"
    
    inspection["checks"]["alarms"] = alarm_check
    
    # ========== 7. ELB监控巡检 ==========
    elb_check = {
        "name": "ELB负载均衡监控巡检",
        "status": "PASS",
        "checked": False,
        "loadbalancer_services": [],
        "elb_metrics": [],
        "eip_metrics": [],  # 新增: EIP监控数据
        "high_bandwidth_usage_elbs": [],
        "high_connection_usage_elbs": [],
        "high_bandwidth_eips": [],  # 新增: 高带宽使用EIP
        "total_loadbalancers": 0
    }
    
    if aom_instance_id:
        elb_check["checked"] = True
        
        # 获取所有Service，筛选LoadBalancer类型
        try:
            services_result = get_kubernetes_services(region, cluster_id, access_key, secret_key, proj_id)
            
            # 获取区域所有EIP，用于匹配ELB的公网IP
            eip_list_result = list_eip_addresses(region, access_key, secret_key, proj_id)
            eip_map = {}  # IP -> EIP信息
            if eip_list_result.get("success"):
                for eip in eip_list_result.get("eips", []):
                    eip_map[eip.get("ip_address")] = eip
            
            if services_result.get("success"):
                lb_services = []
                for svc in services_result.get("services", []):
                    if svc.get("type") == "LoadBalancer":
                        # 从annotations中提取ELB ID
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
                
                elb_check["loadbalancer_services"] = lb_services
                elb_check["total_loadbalancers"] = len(lb_services)
                
                # 获取每个ELB的监控数据
                for lb_svc in lb_services:
                    elb_id = lb_svc.get("elb_id")
                    if elb_id:
                        try:
                            # 获取ELB监控数据 (使用V3指标)
                            elb_metrics_result = get_elb_metrics(region, elb_id, access_key, secret_key, proj_id)
                            
                            if elb_metrics_result.get("success"):
                                summary = elb_metrics_result.get("summary", {})
                                metrics = elb_metrics_result.get("metrics", {})
                                
                                # 提取关键指标 (V3)
                                connection_num = summary.get("connection_num")
                                in_bandwidth = summary.get("in_bandwidth_bps")
                                l7_qps = summary.get("l7_qps")
                                
                                # 使用率指标 (关键!)
                                l7_con_usage = summary.get("l7_connection_usage")
                                l7_bw_usage = summary.get("l7_bandwidth_usage")
                                l4_con_usage = summary.get("l4_connection_usage")
                                l4_bw_usage = summary.get("l4_bandwidth_usage")
                                
                                # 后端服务器状态
                                abnormal_servers = summary.get("abnormal_servers", 0)
                                normal_servers = summary.get("normal_servers", 0)
                                
                                elb_info = {
                                    "service_name": lb_svc.get("service_name"),
                                    "namespace": lb_svc.get("namespace"),
                                    "elb_id": elb_id,
                                    "elb_ip": lb_svc.get("load_balancer_ip"),
                                    "elb_type": elb_metrics_result.get("elb_type", "未知"),
                                    # 绝对值指标
                                    "connection_num": connection_num,
                                    "in_bandwidth_bps": in_bandwidth,
                                    "l7_qps": l7_qps,
                                    # 使用率指标 (%)
                                    "l7_connection_usage_percent": l7_con_usage,
                                    "l7_bandwidth_usage_percent": l7_bw_usage,
                                    "l4_connection_usage_percent": l4_con_usage,
                                    "l4_bandwidth_usage_percent": l4_bw_usage,
                                    # 后端状态
                                    "abnormal_servers": abnormal_servers,
                                    "normal_servers": normal_servers,
                                    "metrics_detail": metrics
                                }
                                
                                # ===== 检查ELB是否有公网EIP =====
                                lb_ip = lb_svc.get("load_balancer_ip")
                                if lb_ip:
                                    # 检查是否是公网IP（在eip_map中）
                                    eip_info = eip_map.get(lb_ip)
                                    if eip_info:
                                        eip_id = eip_info.get("id")
                                        elb_info["has_public_eip"] = True
                                        elb_info["public_ip"] = lb_ip
                                        elb_info["eip_id"] = eip_id
                                        
                                        # 获取EIP监控数据
                                        eip_metrics_result = get_eip_metrics(region, eip_id, access_key, secret_key, proj_id)
                                        if eip_metrics_result.get("success"):
                                            eip_summary = eip_metrics_result.get("summary", {})
                                            bw_in = eip_summary.get("bw_usage_in_percent")
                                            bw_out = eip_summary.get("bw_usage_out_percent")
                                            
                                            elb_info["eip_bw_usage_in_percent"] = bw_in
                                            elb_info["eip_bw_usage_out_percent"] = bw_out
                                            elb_info["eip_connection_num"] = eip_summary.get("connection_num")
                                            
                                            # 保存EIP监控详情
                                            elb_check["eip_metrics"].append({
                                                "service_name": lb_svc.get("service_name"),
                                                "namespace": lb_svc.get("namespace"),
                                                "eip_id": eip_id,
                                                "public_ip": lb_ip,
                                                "bw_usage_in_percent": bw_in,
                                                "bw_usage_out_percent": bw_out,
                                                "connection_num": eip_summary.get("connection_num")
                                            })
                                            
                                            # 检查EIP带宽是否超限 (>80%)
                                            if bw_in and bw_in > 80:
                                                elb_check["high_bandwidth_eips"].append({
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
                                                elb_check["high_bandwidth_eips"].append({
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
                                    else:
                                        elb_info["has_public_eip"] = False
                                        elb_info["note"] = "内网ELB，无公网EIP"
                                
                                elb_check["elb_metrics"].append(elb_info)
                                
                                # 判断是否达到瓶颈 (使用率 > 80%)
                                usage_threshold = 80
                                
                                # 7层连接使用率
                                if l7_con_usage and l7_con_usage > usage_threshold:
                                    elb_check["high_connection_usage_elbs"].append({
                                        "service": lb_svc.get("service_name"),
                                        "namespace": lb_svc.get("namespace"),
                                        "elb_id": elb_id,
                                        "layer": "L7",
                                        "usage_percent": round(l7_con_usage, 2),
                                        "status": "critical" if l7_con_usage > 90 else "warning"
                                    })
                                    add_issue("WARNING", "ELB连接使用率高", elb_id,
                                        f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 7层连接使用率: {round(l7_con_usage, 2)}%")
                                
                                # 7层带宽使用率
                                if l7_bw_usage and l7_bw_usage > usage_threshold:
                                    elb_check["high_bandwidth_usage_elbs"].append({
                                        "service": lb_svc.get("service_name"),
                                        "namespace": lb_svc.get("namespace"),
                                        "elb_id": elb_id,
                                        "layer": "L7",
                                        "usage_percent": round(l7_bw_usage, 2),
                                        "status": "critical" if l7_bw_usage > 90 else "warning"
                                    })
                                    add_issue("WARNING", "ELB带宽使用率高", elb_id,
                                        f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 7层带宽使用率: {round(l7_bw_usage, 2)}%")
                                
                                # 4层连接使用率
                                if l4_con_usage and l4_con_usage > usage_threshold:
                                    elb_check["high_connection_usage_elbs"].append({
                                        "service": lb_svc.get("service_name"),
                                        "namespace": lb_svc.get("namespace"),
                                        "elb_id": elb_id,
                                        "layer": "L4",
                                        "usage_percent": round(l4_con_usage, 2),
                                        "status": "critical" if l4_con_usage > 90 else "warning"
                                    })
                                    add_issue("WARNING", "ELB连接使用率高", elb_id,
                                        f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 4层连接使用率: {round(l4_con_usage, 2)}%")
                                
                                # 4层带宽使用率
                                if l4_bw_usage and l4_bw_usage > usage_threshold:
                                    elb_check["high_bandwidth_usage_elbs"].append({
                                        "service": lb_svc.get("service_name"),
                                        "namespace": lb_svc.get("namespace"),
                                        "elb_id": elb_id,
                                        "layer": "L4",
                                        "usage_percent": round(l4_bw_usage, 2),
                                        "status": "critical" if l4_bw_usage > 90 else "warning"
                                    })
                                    add_issue("WARNING", "ELB带宽使用率高", elb_id,
                                        f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 4层带宽使用率: {round(l4_bw_usage, 2)}%")
                                
                                # 后端异常服务器
                                if abnormal_servers and abnormal_servers > 0:
                                    add_issue("WARNING", "ELB后端服务器异常", elb_id,
                                        f"Service: {lb_svc.get('namespace')}/{lb_svc.get('service_name')}, 异常服务器数: {abnormal_servers}")
                                
                            else:
                                elb_check["elb_metrics"].append({
                                    "service_name": lb_svc.get("service_name"),
                                    "namespace": lb_svc.get("namespace"),
                                    "elb_id": elb_id,
                                    "error": elb_metrics_result.get("error", "获取监控数据失败"),
                                    "note": "共享型ELB不支持CES监控，建议升级为独享型ELB"
                                })
                                
                        except Exception as e:
                            elb_check["elb_metrics"].append({
                                "service_name": lb_svc.get("service_name"),
                                "namespace": lb_svc.get("namespace"),
                                "elb_id": elb_id,
                                "error": str(e)
                            })
                
                # 设置状态
                if elb_check["high_bandwidth_usage_elbs"] or elb_check["high_connection_usage_elbs"] or elb_check["high_bandwidth_eips"]:
                    elb_check["status"] = "WARN"
                    
        except Exception as e:
            elb_check["error"] = str(e)
    else:
        elb_check["status"] = "SKIP"
        elb_check["message"] = "未找到CCE类型的AOM实例，无法获取监控数据"
    
    inspection["checks"]["elb_monitoring"] = elb_check
    
    # ========== 生成报告 ==========
    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("CCE 集群巡检报告")
    report_lines.append("=" * 70)
    report_lines.append(f"集群ID: {cluster_id}")
    report_lines.append(f"区域: {region}")
    report_lines.append(f"巡检时间: {inspection['inspection_time']}")
    report_lines.append(f"巡检结果: {inspection['result']['status']}")
    report_lines.append(f"总问题数: {inspection['result']['total_issues']} (严重: {inspection['result']['critical_issues']}, 警告: {inspection['result']['warning_issues']})")
    report_lines.append("")
    
    # 各项巡检结果
    for check_name, check_data in inspection["checks"].items():
        report_lines.append("-" * 70)
        report_lines.append(f"【{check_data.get('name', check_name)}】 状态: {check_data.get('status', 'UNKNOWN')}")
        
        if check_name == "pods":
            report_lines.append(f"  总Pod数: {check_data.get('total', 0)}")
            report_lines.append(f"  运行中: {check_data.get('running', 0)}, 待调度: {check_data.get('pending', 0)}, 异常: {check_data.get('failed', 0)}")
            if check_data.get("restart_pods"):
                report_lines.append(f"  重启Pod: {len(check_data['restart_pods'])}个")
                for rp in check_data["restart_pods"][:5]:
                    report_lines.append(f"    - {rp['pod']}/{rp['namespace']}: {rp['container']} 重启{rp['restart_count']}次")
            if check_data.get("abnormal_pods"):
                report_lines.append(f"  异常Pod: {len(check_data['abnormal_pods'])}个")
                for ap in check_data["abnormal_pods"][:5]:
                    report_lines.append(f"    - {ap['pod']}/{ap['namespace']}: {ap['status']}")
        
        elif check_name == "nodes":
            report_lines.append(f"  总节点数: {check_data.get('total', 0)}")
            report_lines.append(f"  Ready: {check_data.get('ready', 0)}, NotReady: {check_data.get('not_ready', 0)}")
            if check_data.get("abnormal_nodes"):
                report_lines.append(f"  异常节点:")
                for an in check_data["abnormal_nodes"]:
                    report_lines.append(f"    - {an['name']} ({an['ip']}): {an['status']}")
        
        elif check_name == "addon_pod_monitoring":
            if check_data.get("checked"):
                report_lines.append(f"  命名空间: {', '.join(check_data.get('namespaces', []))}")
                if check_data.get("high_cpu_count", 0) > 0:
                    report_lines.append(f"  CPU>80%: {check_data['high_cpu_count']}个Pod")
                    if check_data.get("high_cpu_pods_top10"):
                        report_lines.append("  CPU使用率 Top 10:")
                        for p in check_data["high_cpu_pods_top10"][:10]:
                            status_icon = "🔴" if p.get("status") == "critical" else "🟡"
                            report_lines.append(f"    {status_icon} {p['namespace']}/{p['pod']}: {p['cpu_usage_percent']}%")
                else:
                    report_lines.append("  CPU使用率: 无Pod超过80%阈值")
                
                if check_data.get("high_memory_count", 0) > 0:
                    report_lines.append(f"  内存>80%: {check_data['high_memory_count']}个Pod")
                    if check_data.get("high_memory_pods_top10"):
                        report_lines.append("  内存使用率 Top 10:")
                        for p in check_data["high_memory_pods_top10"][:10]:
                            status_icon = "🔴" if p.get("status") == "critical" else "🟡"
                            mem_val = p.get('memory_usage_percent', 'N/A')
                            report_lines.append(f"    {status_icon} {p['namespace']}/{p['pod']}: {mem_val}%")
                else:
                    report_lines.append("  内存使用率: 无Pod超过80%阈值")
                
                if check_data.get("high_cpu_count", 0) == 0 and check_data.get("high_memory_count", 0) == 0:
                    report_lines.append("  所有插件Pod资源使用正常")
            else:
                report_lines.append(f"  {check_data.get('message', '未检查')}")
        
        elif check_name == "biz_pod_monitoring":
            if check_data.get("checked"):
                namespaces = check_data.get('namespaces', [])
                if namespaces:
                    report_lines.append(f"  业务命名空间: {', '.join(namespaces[:5])}{'...' if len(namespaces) > 5 else ''}")
                if check_data.get("high_cpu_count", 0) > 0:
                    report_lines.append(f"  CPU>80%: {check_data['high_cpu_count']}个Pod")
                    if check_data.get("high_cpu_pods_top10"):
                        report_lines.append("  CPU使用率 Top 10:")
                        for p in check_data["high_cpu_pods_top10"][:10]:
                            status_icon = "🔴" if p.get("status") == "critical" else "🟡"
                            report_lines.append(f"    {status_icon} {p['namespace']}/{p['pod']}: {p['cpu_usage_percent']}%")
                else:
                    report_lines.append("  CPU使用率: 无Pod超过80%阈值")
                
                if check_data.get("high_memory_count", 0) > 0:
                    report_lines.append(f"  内存>80%: {check_data['high_memory_count']}个Pod")
                    if check_data.get("high_memory_pods_top10"):
                        report_lines.append("  内存使用率 Top 10:")
                        for p in check_data["high_memory_pods_top10"][:10]:
                            status_icon = "🔴" if p.get("status") == "critical" else "🟡"
                            mem_val = p.get('memory_usage_percent', 'N/A')
                            report_lines.append(f"    {status_icon} {p['namespace']}/{p['pod']}: {mem_val}%")
                else:
                    report_lines.append("  内存使用率: 无Pod超过80%阈值")
                
                if check_data.get("high_cpu_count", 0) == 0 and check_data.get("high_memory_count", 0) == 0:
                    report_lines.append("  所有业务Pod资源使用正常")
            else:
                report_lines.append(f"  {check_data.get('message', '未检查')}")
        
        elif check_name == "node_monitoring":
            if check_data.get("checked"):
                # CPU 高使用率统计
                if check_data.get("high_cpu_count", 0) > 0:
                    report_lines.append(f"  CPU>80%: {check_data['high_cpu_count']}个节点")
                    if check_data.get("high_cpu_nodes_top10"):
                        report_lines.append("  CPU使用率 Top 10:")
                        for n in check_data["high_cpu_nodes_top10"][:10]:
                            status_icon = "🔴" if n.get("status") == "critical" else "🟡"
                            report_lines.append(f"    {status_icon} {n['node_ip']}: {n['cpu_usage_percent']}%")
                else:
                    report_lines.append("  CPU使用率: 无节点超过80%阈值")
                
                # 内存高使用率统计
                if check_data.get("high_memory_count", 0) > 0:
                    report_lines.append(f"  内存>80%: {check_data['high_memory_count']}个节点")
                    if check_data.get("high_memory_nodes_top10"):
                        report_lines.append("  内存使用率 Top 10:")
                        for n in check_data["high_memory_nodes_top10"][:10]:
                            status_icon = "🔴" if n.get("status") == "critical" else "🟡"
                            mem_val = n.get('memory_usage_percent', 'N/A')
                            report_lines.append(f"    {status_icon} {n['node_ip']}: {mem_val}%")
                else:
                    report_lines.append("  内存使用率: 无节点超过80%阈值")
                
                # 磁盘高使用率统计
                if check_data.get("high_disk_count", 0) > 0:
                    report_lines.append(f"  磁盘>80%: {check_data['high_disk_count']}个节点")
                    if check_data.get("high_disk_nodes_top10"):
                        report_lines.append("  磁盘使用率 Top 10:")
                        for n in check_data["high_disk_nodes_top10"][:10]:
                            status_icon = "🔴" if n.get("status") == "critical" else "🟡"
                            disk_val = n.get('disk_usage_percent', 'N/A')
                            report_lines.append(f"    {status_icon} {n['node_ip']}: {disk_val}%")
                else:
                    report_lines.append("  磁盘使用率: 无节点超过80%阈值")
                
                # 如果都正常
                if check_data.get("high_cpu_count", 0) == 0 and check_data.get("high_memory_count", 0) == 0 and check_data.get("high_disk_count", 0) == 0:
                    report_lines.append("  所有节点资源使用正常")
            else:
                report_lines.append(f"  {check_data.get('message', '未检查')}")
        
        elif check_name == "events":
            report_lines.append(f"  总事件: {check_data.get('total', 0)}, Normal: {check_data.get('normal', 0)}, Warning: {check_data.get('warning', 0)}")
            if check_data.get("critical_events"):
                report_lines.append(f"  关键事件: {len(check_data['critical_events'])}个")
                for ce in check_data["critical_events"][:5]:
                    report_lines.append(f"    - [{ce.get('reason')}] {ce.get('involved_object')}: {ce.get('message', '')[:60]}...")
        
        elif check_name == "alarms":
            report_lines.append(f"  总告警: {check_data.get('total', 0)}")
            sb = check_data.get("severity_breakdown", {})
            report_lines.append(f"  严重级别: Critical={sb.get('Critical', 0)}, Major={sb.get('Major', 0)}, Minor={sb.get('Minor', 0)}, Info={sb.get('Info', 0)}")
            if check_data.get("cluster_alarms"):
                report_lines.append(f"  集群告警: {len(check_data['cluster_alarms'])}个")
                for ca in check_data["cluster_alarms"][:5]:
                    report_lines.append(f"    - [{ca['severity']}] {ca['name']}: {ca.get('message', '')[:60]}...")
        
        elif check_name == "elb_monitoring":
            if check_data.get("checked"):
                report_lines.append(f"  LoadBalancer Service数: {check_data.get('total_loadbalancers', 0)}")
                if check_data.get("loadbalancer_services"):
                    report_lines.append(f"  LoadBalancer服务列表:")
                    for lb in check_data["loadbalancer_services"]:
                        report_lines.append(f"    - {lb['namespace']}/{lb['service_name']}: ELB ID: {lb['elb_id']}")
                if check_data.get("high_connection_usage_elbs"):
                    report_lines.append(f"  高连接使用率ELB: {len(check_data['high_connection_usage_elbs'])}个")
                    for lb in check_data["high_connection_usage_elbs"]:
                        report_lines.append(f"    - {lb['namespace']}/{lb['service']}: {lb.get('layer', 'L4')}连接使用率 {lb['usage_percent']}%")
                if check_data.get("high_bandwidth_usage_elbs"):
                    report_lines.append(f"  高带宽使用率ELB: {len(check_data['high_bandwidth_usage_elbs'])}个")
                    for lb in check_data["high_bandwidth_usage_elbs"]:
                        report_lines.append(f"    - {lb['namespace']}/{lb['service']}: {lb.get('layer', 'L4')}带宽使用率 {lb['usage_percent']}%")
                # EIP带宽检查
                if check_data.get("high_bandwidth_eips"):
                    report_lines.append(f"  EIP带宽超限: {len(check_data['high_bandwidth_eips'])}个")
                    for eip in check_data["high_bandwidth_eips"]:
                        direction = "入" if eip.get("direction") == "in" else "出"
                        report_lines.append(f"    - {eip['namespace']}/{eip['service']} ({eip['public_ip']}): {direction}带宽使用率 {eip['usage_percent']}%")
                if not check_data.get("high_connection_usage_elbs") and not check_data.get("high_bandwidth_usage_elbs") and not check_data.get("high_bandwidth_eips"):
                    report_lines.append("  所有ELB和EIP负载正常")
            else:
                report_lines.append(f"  {check_data.get('message', '未检查')}")
        
        report_lines.append("")
    
    # 问题汇总
    if inspection["issues"]:
        report_lines.append("=" * 70)
        report_lines.append("【问题汇总】")
        report_lines.append("=" * 70)
        
        critical_issues = [i for i in inspection["issues"] if i["severity"] == "CRITICAL"]
        warning_issues = [i for i in inspection["issues"] if i["severity"] == "WARNING"]
        
        if critical_issues:
            report_lines.append(f"\n严重问题 ({len(critical_issues)}个):")
            for i, issue in enumerate(critical_issues, 1):
                report_lines.append(f"  {i}. [{issue['category']}] {issue['item']}")
                report_lines.append(f"     {issue['details']}")
        
        if warning_issues:
            report_lines.append(f"\n警告问题 ({len(warning_issues)}个):")
            for i, issue in enumerate(warning_issues[:10], 1):
                report_lines.append(f"  {i}. [{issue['category']}] {issue['item']}")
                report_lines.append(f"     {issue['details']}")
        
        report_lines.append("")
    
    report_lines.append("=" * 70)
    if inspection["result"]["status"] == "HEALTHY":
        report_lines.append("✅ 集群状态健康，无异常问题")
    elif inspection["result"]["status"] == "WARNING":
        report_lines.append(f"⚠️ 集群存在警告问题，建议关注处理")
    else:
        report_lines.append(f"❌ 集群存在严重问题，请立即处理！")
    report_lines.append("=" * 70)
    
    inspection["report"] = "\n".join(report_lines)
    
    # ========== 生成HTML报告 ==========
    html_report = generate_inspection_html_report(inspection, cluster_id, region)
    inspection["html_report"] = html_report
    
    return inspection


def generate_inspection_html_report(inspection: dict, cluster_id: str, region: str) -> str:
    """生成巡检HTML报告
    
    Args:
        inspection: 巡检结果数据
        cluster_id: 集群ID
        region: 区域
    
    Returns:
        HTML格式的巡检报告
    """
    import time as time_module
    
    # 状态样式映射
    status_colors = {
        "PASS": "#28a745",
        "WARN": "#ffc107", 
        "FAIL": "#dc3545",
        "SKIP": "#6c757d",
        "HEALTHY": "#28a745",
        "WARNING": "#ffc107",
        "CRITICAL": "#dc3545"
    }
    
    status_icons = {
        "PASS": "✅",
        "WARN": "⚠️",
        "FAIL": "❌",
        "SKIP": "⏭️",
        "HEALTHY": "✅",
        "WARNING": "⚠️",
        "CRITICAL": "❌"
    }
    
    # 问题严重程度建议
    issue_solutions = {
        "Pod异常重启": {
            "description": "Pod容器频繁重启，可能导致服务不稳定",
            "solutions": [
                "检查容器日志：kubectl logs <pod-name> -n <namespace>",
                "检查容器资源限制是否合理",
                "检查应用健康检查配置（livenessProbe/readinessProbe）",
                "检查应用是否有未捕获的异常导致进程退出",
                "检查环境变量和配置是否正确"
            ]
        },
        "Pod CPU使用率高": {
            "description": "Pod CPU使用率超过阈值，可能影响应用性能",
            "solutions": [
                "增加Pod的CPU limit配置",
                "配置HPA实现自动水平扩缩容",
                "排查应用是否存在性能瓶颈或死循环",
                "考虑将服务拆分或优化代码"
            ]
        },
        "Pod内存使用率高": {
            "description": "Pod内存使用率超过阈值，可能发生OOM",
            "solutions": [
                "增加Pod的内存limit配置",
                "排查应用是否存在内存泄漏",
                "优化应用的内存使用策略",
                "考虑使用对象池等技术减少内存分配"
            ]
        },
        "节点CPU高": {
            "description": "节点CPU使用率过高，影响所有运行在该节点的Pod",
            "solutions": [
                "扩容节点池，增加新节点",
                "迁移部分Pod到其他节点",
                "检查是否有异常进程占用CPU",
                "优化节点上运行的Pod资源限制"
            ]
        },
        "节点内存高": {
            "description": "节点内存使用率过高，可能导致OOM",
            "solutions": [
                "扩容节点池或升级节点规格",
                "迁移部分Pod到其他节点",
                "清理不必要的进程或缓存",
                "检查是否有内存泄漏的进程"
            ]
        },
        "节点磁盘高": {
            "description": "节点磁盘使用率过高，可能影响系统运行",
            "solutions": [
                "清理不必要的日志文件",
                "清理无用的容器镜像",
                "扩容节点磁盘",
                "配置日志轮转策略"
            ]
        },
        "关键事件": {
            "description": "集群存在关键事件需要关注",
            "solutions": [
                "查看事件详情：kubectl describe <resource> <name>",
                "根据事件类型采取相应措施",
                "关注频繁出现的事件"
            ]
        },
        "重要告警": {
            "description": "存在未处理的告警",
            "solutions": [
                "在AOM控制台查看告警详情",
                "根据告警内容进行排查",
                "处理后确认告警状态"
            ]
        },
        "Pod调度异常": {
            "description": "Pod处于Pending状态，无法正常调度",
            "solutions": [
                "检查节点资源是否充足",
                "检查Pod的资源requests/limits配置",
                "检查节点标签和Pod的nodeSelector配置",
                "检查是否存在资源配额限制"
            ]
        },
        "ELB连接数高": {
            "description": "ELB连接数过高，可能影响服务性能",
            "solutions": [
                "检查后端服务是否有性能瓶颈",
                "考虑增加后端Pod副本数",
                "检查连接是否正常释放",
                "考虑升级ELB规格",
                "检查是否有异常流量或攻击"
            ]
        },
        "ELB带宽高": {
            "description": "ELB入带宽过高，可能达到带宽瓶颈",
            "solutions": [
                "检查是否有大文件传输或异常流量",
                "考虑升级ELB带宽规格",
                "优化数据传输（启用压缩等）",
                "检查后端服务响应数据大小",
                "配置带宽限速策略"
            ]
        },
        "EIP入带宽超限": {
            "description": "EIP入带宽使用率过高，可能影响服务可用性",
            "solutions": [
                "升级EIP带宽规格",
                "检查是否有异常入流量或攻击",
                "配置流量清洗或防护策略",
                "优化服务架构，使用CDN等分流"
            ]
        },
        "EIP出带宽超限": {
            "description": "EIP出带宽使用率过高，可能影响服务响应",
            "solutions": [
                "升级EIP带宽规格",
                "检查是否有大文件下载或异常出流量",
                "启用数据压缩减少传输量",
                "使用对象存储(OBS)分担静态资源下载",
                "配置带宽限速策略"
            ]
        }
    }
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CCE集群巡检报告 - {inspection.get('inspection_time', '')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .header-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-top: 15px;
        }}
        .header-info-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .header-info-item span {{
            opacity: 0.9;
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 16px;
        }}
        .status-healthy {{ background-color: #d4edda; color: #155724; }}
        .status-warning {{ background-color: #fff3cd; color: #856404; }}
        .status-critical {{ background-color: #f8d7da; color: #721c24; }}
        
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .summary-card {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .summary-card h3 {{
            font-size: 14px;
            color: #666;
            margin-bottom: 10px;
        }}
        .summary-card .value {{
            font-size: 32px;
            font-weight: 700;
        }}
        .summary-card.critical .value {{ color: #dc3545; }}
        .summary-card.warning .value {{ color: #ffc107; }}
        .summary-card.healthy .value {{ color: #28a745; }}
        
        .check-section {{
            background: white;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .check-header {{
            padding: 15px 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .check-header h2 {{
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .check-status {{
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 14px;
            font-weight: 600;
        }}
        .check-status.pass {{ background: #d4edda; color: #155724; }}
        .check-status.warn {{ background: #fff3cd; color: #856404; }}
        .check-status.fail {{ background: #f8d7da; color: #721c24; }}
        .check-status.skip {{ background: #e2e3e5; color: #383d41; }}
        
        .check-content {{
            padding: 20px;
        }}
        .check-detail {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 15px;
        }}
        .detail-item {{
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .detail-item label {{
            font-size: 12px;
            color: #666;
            display: block;
        }}
        .detail-item span {{
            font-size: 18px;
            font-weight: 600;
        }}
        
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        .data-table th, .data-table td {{
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        .data-table th {{
            background: #f8f9fa;
            font-weight: 600;
            font-size: 13px;
            color: #666;
        }}
        .data-table td {{
            font-size: 14px;
        }}
        .data-table tr:hover {{
            background: #f8f9fa;
        }}
        
        .issue-section {{
            background: white;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .issue-header {{
            padding: 15px 20px;
            background: #fff5f5;
            border-bottom: 1px solid #fee;
        }}
        .issue-header h2 {{
            color: #dc3545;
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .issue-item {{
            padding: 20px;
            border-bottom: 1px solid #eee;
        }}
        .issue-item:last-child {{
            border-bottom: none;
        }}
        .issue-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }}
        .issue-severity {{
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .issue-severity.critical {{
            background: #dc3545;
            color: white;
        }}
        .issue-severity.warning {{
            background: #ffc107;
            color: #333;
        }}
        .issue-description {{
            color: #666;
            margin-bottom: 15px;
            padding-left: 20px;
        }}
        .issue-solutions {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin-left: 20px;
        }}
        .issue-solutions h4 {{
            font-size: 14px;
            color: #333;
            margin-bottom: 10px;
        }}
        .issue-solutions ul {{
            margin-left: 20px;
        }}
        .issue-solutions li {{
            color: #666;
            margin-bottom: 5px;
            font-size: 14px;
        }}
        .issue-solutions code {{
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
        }}
        
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 14px;
        }}
        
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }}
        .tag-danger {{ background: #f8d7da; color: #721c24; }}
        .tag-warning {{ background: #fff3cd; color: #856404; }}
        .tag-success {{ background: #d4edda; color: #155724; }}
        .tag-info {{ background: #d1ecf1; color: #0c5460; }}
        
        .progress-bar {{
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }}
        .progress-bar .fill {{
            height: 100%;
            border-radius: 4px;
        }}
        .progress-bar .fill.danger {{ background: #dc3545; }}
        .progress-bar .fill.warning {{ background: #ffc107; }}
        .progress-bar .fill.success {{ background: #28a745; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🔍 CCE 集群巡检报告</h1>
            <div class="header-info">
                <div class="header-info-item">
                    <span>📍 集群ID:</span>
                    <strong>{cluster_id}</strong>
                </div>
                <div class="header-info-item">
                    <span>🌍 区域:</span>
                    <strong>{region}</strong>
                </div>
                <div class="header-info-item">
                    <span>🕐 巡检时间:</span>
                    <strong>{inspection.get('inspection_time', '-')}</strong>
                </div>
            </div>
        </div>
        
        <!-- Status Badge -->
        <div style="text-align: center; margin-bottom: 20px;">
            <span class="status-badge status-{inspection['result']['status'].lower()}">
                {status_icons.get(inspection['result']['status'], '❓')} 
                巡检结果: {inspection['result']['status']}
            </span>
        </div>
        
        <!-- Summary Cards -->
        <div class="summary-cards">
            <div class="summary-card critical">
                <h3>严重问题</h3>
                <div class="value">{inspection['result']['critical_issues']}</div>
            </div>
            <div class="summary-card warning">
                <h3>警告问题</h3>
                <div class="value">{inspection['result']['warning_issues']}</div>
            </div>
            <div class="summary-card">
                <h3>总问题数</h3>
                <div class="value">{inspection['result']['total_issues']}</div>
            </div>
        </div>
"""
    
    # 各巡检项详情
    checks = inspection.get("checks", {})
    
    # 1. Pod状态巡检
    pod_check = checks.get("pods", {})
    if pod_check:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>📦 Pod状态巡检</h2>
                <span class="check-status {pod_check.get('status', 'PASS').lower()}">{pod_check.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>总Pod数</label>
                        <span>{pod_check.get('total', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>运行中</label>
                        <span style="color: #28a745;">{pod_check.get('running', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>待调度</label>
                        <span style="color: #ffc107;">{pod_check.get('pending', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>异常</label>
                        <span style="color: #dc3545;">{pod_check.get('failed', 0)}</span>
                    </div>
                </div>
"""
        # 重启Pod表格
        restart_pods = pod_check.get("restart_pods", [])
        if restart_pods:
            html += """
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">重启Pod列表</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Pod</th>
                            <th>命名空间</th>
                            <th>容器</th>
                            <th>重启次数</th>
                            <th>状态</th>
                            <th>节点</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for p in restart_pods[:10]:
                status = p.get('state_reason', 'Unknown')
                status_class = 'tag-danger' if status == 'CrashLoopBackOff' else 'tag-warning'
                html += f"""
                        <tr>
                            <td>{p.get('pod', '-')}</td>
                            <td>{p.get('namespace', '-')}</td>
                            <td>{p.get('container', '-')}</td>
                            <td><span class="tag tag-danger">{p.get('restart_count', 0)}</span></td>
                            <td><span class="tag {status_class}">{status}</span></td>
                            <td>{p.get('node', '-')}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 2. Node状态巡检
    node_check = checks.get("nodes", {})
    if node_check:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>🖥️ Node状态巡检</h2>
                <span class="check-status {node_check.get('status', 'PASS').lower()}">{node_check.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>总节点数</label>
                        <span>{node_check.get('total', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Ready</label>
                        <span style="color: #28a745;">{node_check.get('ready', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>NotReady</label>
                        <span style="color: #dc3545;">{node_check.get('not_ready', 0)}</span>
                    </div>
                </div>
"""
        # 异常节点
        abnormal_nodes = node_check.get("abnormal_nodes", [])
        if abnormal_nodes:
            html += """
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">异常节点列表</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>节点名</th>
                            <th>状态</th>
                            <th>IP</th>
                            <th>规格</th>
                            <th>原因</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for n in abnormal_nodes:
                html += f"""
                        <tr>
                            <td>{n.get('name', '-')}</td>
                            <td><span class="tag tag-danger">{n.get('status', '-')}</span></td>
                            <td>{n.get('ip', '-')}</td>
                            <td>{n.get('flavor', '-')}</td>
                            <td>{n.get('reason', '-')}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 3. Pod监控巡检
    pod_mon = checks.get("pod_monitoring", {})
    if pod_mon:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>📊 集群Pod监控巡检</h2>
                <span class="check-status {pod_mon.get('status', 'PASS').lower()}">{pod_mon.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>CPU>80% Pod数</label>
                        <span style="color: {'#dc3545' if pod_mon.get('high_cpu_count', 0) > 0 else '#28a745'};">{pod_mon.get('high_cpu_count', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>内存>80% Pod数</label>
                        <span style="color: {'#dc3545' if pod_mon.get('high_memory_count', 0) > 0 else '#28a745'};">{pod_mon.get('high_memory_count', 0)}</span>
                    </div>
                </div>
"""
        # CPU高使用率Pod
        high_cpu_pods = pod_mon.get("high_cpu_pods_top10", [])
        if high_cpu_pods:
            html += """
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">CPU使用率 Top 10 (>80%)</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Pod</th>
                            <th>命名空间</th>
                            <th>CPU使用率</th>
                            <th>节点</th>
                            <th>状态</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for p in high_cpu_pods:
                cpu_val = p.get('cpu_usage_percent', 0)
                status_class = 'tag-danger' if cpu_val > 90 else 'tag-warning'
                html += f"""
                        <tr>
                            <td>{p.get('pod', '-')}</td>
                            <td>{p.get('namespace', '-')}</td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div class="progress-bar" style="width: 100px;">
                                        <div class="fill danger" style="width: {min(cpu_val, 100)}%;"></div>
                                    </div>
                                    <span>{cpu_val}%</span>
                                </div>
                            </td>
                            <td>{p.get('node', '-')}</td>
                            <td><span class="tag {status_class}">{p.get('status', 'warning')}</span></td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 4. 节点资源监控巡检
    node_mon = checks.get("node_monitoring", {})
    if node_mon:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>💻 节点资源监控巡检</h2>
                <span class="check-status {node_mon.get('status', 'PASS').lower()}">{node_mon.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>CPU>80% 节点数</label>
                        <span style="color: {'#dc3545' if node_mon.get('high_cpu_count', 0) > 0 else '#28a745'};">{node_mon.get('high_cpu_count', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>内存>80% 节点数</label>
                        <span style="color: {'#dc3545' if node_mon.get('high_memory_count', 0) > 0 else '#28a745'};">{node_mon.get('high_memory_count', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>磁盘>80% 节点数</label>
                        <span style="color: {'#dc3545' if node_mon.get('high_disk_count', 0) > 0 else '#28a745'};">{node_mon.get('high_disk_count', 0)}</span>
                    </div>
                </div>
"""
        # CPU高使用率节点
        high_cpu_nodes = node_mon.get("high_cpu_nodes_top10", [])
        if high_cpu_nodes:
            html += """
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">CPU使用率 Top 10 (>80%)</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>节点IP</th>
                            <th>CPU使用率</th>
                            <th>状态</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for n in high_cpu_nodes:
                cpu_val = n.get('cpu_usage_percent', 0)
                status_class = 'tag-danger' if cpu_val > 90 else 'tag-warning'
                html += f"""
                        <tr>
                            <td>{n.get('node_ip', '-')}</td>
                            <td>
                                <div style="display: flex; align-items: center; gap: 10px;">
                                    <div class="progress-bar" style="width: 100px;">
                                        <div class="fill danger" style="width: {min(cpu_val, 100)}%;"></div>
                                    </div>
                                    <span>{cpu_val}%</span>
                                </div>
                            </td>
                            <td><span class="tag {status_class}">{n.get('status', 'warning')}</span></td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 5. Event巡检
    event_check = checks.get("events", {})
    if event_check:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>📝 Event巡检</h2>
                <span class="check-status {event_check.get('status', 'PASS').lower()}">{event_check.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>总事件数</label>
                        <span>{event_check.get('total', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Normal</label>
                        <span style="color: #28a745;">{event_check.get('normal', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Warning</label>
                        <span style="color: #ffc107;">{event_check.get('warning', 0)}</span>
                    </div>
                </div>
"""
        # 关键事件
        critical_events = event_check.get("critical_events", [])
        if critical_events:
            html += f"""
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">关键事件 ({len(critical_events)}个)</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>原因</th>
                            <th>对象</th>
                            <th>命名空间</th>
                            <th>次数</th>
                            <th>消息</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for e in critical_events[:10]:
                html += f"""
                        <tr>
                            <td><span class="tag tag-warning">{e.get('reason', '-')}</span></td>
                            <td>{e.get('involved_object', '-')}</td>
                            <td>{e.get('namespace', '-')}</td>
                            <td>{e.get('count', 1)}</td>
                            <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">{e.get('message', '-')[:100]}...</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 6. AOM告警巡检
    alarm_check = checks.get("alarms", {})
    if alarm_check:
        sb = alarm_check.get("severity_breakdown", {})
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>🔔 AOM告警巡检</h2>
                <span class="check-status {alarm_check.get('status', 'PASS').lower()}">{alarm_check.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>总告警数</label>
                        <span>{alarm_check.get('total', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Critical</label>
                        <span style="color: #dc3545;">{sb.get('Critical', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Major</label>
                        <span style="color: #ffc107;">{sb.get('Major', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>Minor</label>
                        <span style="color: #17a2b8;">{sb.get('Minor', 0)}</span>
                    </div>
                </div>
"""
        # 集群告警
        cluster_alarms = alarm_check.get("cluster_alarms", [])
        if cluster_alarms:
            html += f"""
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">集群告警 ({len(cluster_alarms)}个)</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>严重级别</th>
                            <th>告警名称</th>
                            <th>资源</th>
                            <th>消息</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for a in cluster_alarms[:10]:
                severity = a.get('severity', 'Unknown')
                severity_class = 'tag-danger' if severity == 'Critical' else 'tag-warning' if severity == 'Major' else 'tag-info'
                html += f"""
                        <tr>
                            <td><span class="tag {severity_class}">{severity}</span></td>
                            <td>{a.get('name', '-')}</td>
                            <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;">{a.get('resource_id', '-')[:50]}</td>
                            <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">{a.get('message', '-')[:80]}...</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        html += """
            </div>
        </div>
"""
    
    # 7. ELB监控巡检
    elb_check = checks.get("elb_monitoring", {})
    if elb_check:
        html += f"""
        <div class="check-section">
            <div class="check-header">
                <h2>⚖️ ELB负载均衡监控巡检</h2>
                <span class="check-status {elb_check.get('status', 'PASS').lower()}">{elb_check.get('status', 'PASS')}</span>
            </div>
            <div class="check-content">
                <div class="check-detail">
                    <div class="detail-item">
                        <label>LoadBalancer服务数</label>
                        <span>{elb_check.get('total_loadbalancers', 0)}</span>
                    </div>
                    <div class="detail-item">
                        <label>高连接数ELB</label>
                        <span style="color: {'#dc3545' if elb_check.get('high_connection_elbs') else '#28a745'};">{len(elb_check.get('high_connection_elbs', []))}</span>
                    </div>
                    <div class="detail-item">
                        <label>高带宽ELB</label>
                        <span style="color: {'#dc3545' if elb_check.get('high_bandwidth_elbs') else '#28a745'};">{len(elb_check.get('high_bandwidth_elbs', []))}</span>
                    </div>
                </div>
"""
        # LoadBalancer服务列表
        lb_services = elb_check.get("loadbalancer_services", [])
        if lb_services:
            html += f"""
                <h4 style="margin-top: 15px; margin-bottom: 10px;">LoadBalancer服务列表</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Service</th>
                            <th>命名空间</th>
                            <th>ELB ID</th>
                            <th>ELB IP</th>
                            <th>端口</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for lb in lb_services:
                ports_str = ", ".join([f"{p.get('port', '')}/{p.get('protocol', '')}" for p in lb.get('ports', [])])
                html += f"""
                        <tr>
                            <td>{lb.get('service_name', '-')}</td>
                            <td>{lb.get('namespace', '-')}</td>
                            <td><code style="font-size: 12px;">{lb.get('elb_id', '-')}</code></td>
                            <td>{lb.get('load_balancer_ip', '-')}</td>
                            <td>{ports_str}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        
        # ELB监控指标
        elb_metrics = elb_check.get("elb_metrics", [])
        if elb_metrics:
            html += f"""
                <h4 style="margin-top: 15px; margin-bottom: 10px;">ELB监控指标</h4>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Service</th>
                            <th>命名空间</th>
                            <th>连接数</th>
                            <th>入带宽</th>
                            <th>QPS</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for m in elb_metrics:
                conn = m.get('connection_num', '-')
                bandwidth = m.get('in_bandwidth_bps')
                bandwidth_str = f"{round(bandwidth / 1024 / 1024, 2)} Mbps" if bandwidth else '-'
                qps = m.get('qps', '-')
                
                # 判断是否高负载
                conn_color = '#dc3545' if conn and conn > 10000 else '#333'
                bandwidth_color = '#dc3545' if bandwidth and bandwidth > 100 * 1024 * 1024 else '#333'
                
                html += f"""
                        <tr>
                            <td>{m.get('service_name', '-')}</td>
                            <td>{m.get('namespace', '-')}</td>
                            <td style="color: {conn_color};">{conn if conn else '-'}</td>
                            <td style="color: {bandwidth_color};">{bandwidth_str}</td>
                            <td>{qps if qps else '-'}</td>
                        </tr>
"""
            html += """
                    </tbody>
                </table>
"""
        
        # 高负载ELB告警
        high_conn = elb_check.get("high_connection_elbs", [])
        high_bw = elb_check.get("high_bandwidth_elbs", [])
        
        if high_conn or high_bw:
            html += f"""
                <h4 style="margin-top: 15px; margin-bottom: 10px; color: #dc3545;">高负载ELB告警</h4>
                <div style="background: #fff5f5; padding: 15px; border-radius: 8px; border-left: 4px solid #dc3545;">
"""
            for lb in high_conn:
                html += f"""
                    <p style="margin-bottom: 5px;"><span class="tag tag-warning">高连接数</span> 
                    <strong>{lb.get('namespace')}/{lb.get('service')}</strong>: 连接数 <code>{lb.get('connection_num')}</code></p>
"""
            for lb in high_bw:
                html += f"""
                    <p style="margin-bottom: 5px;"><span class="tag tag-warning">高带宽</span> 
                    <strong>{lb.get('namespace')}/{lb.get('service')}</strong>: 入带宽 <code>{lb.get('in_bandwidth_mbps')} Mbps</code></p>
"""
            html += """
                </div>
"""
        html += """
            </div>
        </div>
"""
    
    # 问题汇总与建议
    issues = inspection.get("issues", [])
    if issues:
        critical_issues = [i for i in issues if i.get("severity") == "CRITICAL"]
        warning_issues = [i for i in issues if i.get("severity") == "WARNING"]
        
        html += f"""
        <div class="issue-section">
            <div class="issue-header">
                <h2>🔧 问题汇总与解决建议</h2>
            </div>
            <div style="padding: 15px 20px; background: #fff; border-bottom: 1px solid #eee;">
                <p style="color: #666;">共发现 <strong style="color: #dc3545;">{len(critical_issues)}</strong> 个严重问题，
                <strong style="color: #ffc107;">{len(warning_issues)}</strong> 个警告问题，以下为详细分析和建议：</p>
            </div>
"""
        
        # 按问题类型分组
        issues_by_category = {}
        for issue in issues:
            category = issue.get("category", "其他")
            if category not in issues_by_category:
                issues_by_category[category] = []
            issues_by_category[category].append(issue)
        
        for category, category_issues in issues_by_category.items():
            solution_info = issue_solutions.get(category, {
                "description": "需要进一步分析该问题",
                "solutions": ["查看详细日志进行分析", "根据具体情况采取相应措施"]
            })
            
            html += f"""
            <div class="issue-item">
                <div class="issue-title">
                    <span class="issue-severity {category_issues[0].get('severity', 'WARNING').lower()}">{category_issues[0].get('severity', 'WARNING')}</span>
                    <strong>{category}</strong>
                    <span style="color: #666; font-size: 14px;">({len(category_issues)}个)</span>
                </div>
                <div class="issue-description">
                    {solution_info.get('description', '')}
                </div>
                <div class="issue-solutions">
                    <h4>💡 解决建议：</h4>
                    <ul>
"""
            for solution in solution_info.get("solutions", []):
                html += f"                        <li>{solution}</li>\n"
            
            html += """
                    </ul>
                </div>
            </div>
"""
        
        html += """
        </div>
"""
    
    # Footer
    html += f"""
        <div class="footer">
            <p>📅 报告生成时间: {inspection.get('inspection_time', '-')}</p>
            <p>CCE集群巡检工具 | 由AI助手自动生成</p>
        </div>
    </div>
</body>
</html>
"""
    
    return html


def get_cce_pod_metrics_topN(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None, label_selector: str = None, top_n: int = 10, hours: int = 1, cpu_query: str = None, memory_query: str = None) -> Dict[str, Any]:
    """获取 CCE 集群 Pod 监控数据

    自动获取 AOM 实例并执行 Pod CPU/内存监控查询，返回 Top N 数据。

    Args:
        region: 华为云区域 (如 cn-north-4)
        cluster_id: CCE 集群 ID
        ak: Access Key ID (可选)
        sk: Secret Access Key (可选)
        project_id: Project ID (可选)
        namespace: 命名空间过滤 (可选，默认所有命名空间)
        label_selector: Pod 标签选择器 (可选，格式: "app=nginx,version=v1")
        top_n: 返回 Top N 数据 (默认 10)
        hours: 查询时间范围（小时）(默认 1)
        cpu_query: 自定义 CPU PromQL (可选)
        memory_query: 自定义内存 PromQL (可选)
        node_ip: 节点 IP 过滤 (可选，只返回指定节点上的 Pod)

    Returns:
        Dict with success status and pod metrics data
    """
    import time as time_module

    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}

    if not cluster_id:
        return {"success": False, "error": "cluster_id is required"}

    # ========== 1. 获取集群名称 ==========
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

    # ========== 2. 如果有 label_selector，先获取符合条件的 Pod 列表 ==========
    pod_filter_list = None  # 用于过滤的 Pod 名称列表
    matched_pods_info = []  # 匹配的 Pod 详细信息

    if label_selector:
        # 解析 label_selector (格式: "app=nginx,version=v1")
        label_filters = {}
        for part in label_selector.split(","):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                label_filters[key.strip()] = value.strip()

        if label_filters:
            # 获取 Pod 列表
            pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id, namespace)
            if pods_result.get("success"):
                matched_pods = []
                for pod in pods_result.get("pods", []):
                    pod_labels = pod.get("labels", {})
                    pod_name = pod.get("name", "")
                    pod_ns = pod.get("namespace", "")

                    # 检查是否匹配所有 label 条件
                    match = True
                    for key, value in label_filters.items():
                        if pod_labels.get(key) != value:
                            match = False
                            break

                    if match:
                        matched_pods.append(pod_name)
                        matched_pods_info.append({
                            "name": pod_name,
                            "namespace": pod_ns,
                            "labels": pod_labels,
                            "status": pod.get("status"),
                            "node": pod.get("node")
                        })

                if matched_pods:
                    pod_filter_list = matched_pods
                else:
                    # 没有匹配的 Pod，直接返回空结果
                    return {
                        "success": True,
                        "region": region,
                        "cluster_id": cluster_id,
                        "cluster_name": cluster_name,
                        "aom_instance_id": None,
                        "inspection_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
                        "query_params": {
                            "top_n": top_n,
                            "hours": hours,
                            "namespace": namespace,
                            "label_selector": label_selector
                        },
                        "label_filter": {
                            "selector": label_selector,
                            "parsed": label_filters,
                            "matched_count": 0,
                            "matched_pods": []
                        },
                        "promql": {"cpu": None, "memory": None},
                        "metrics": {
                            "cpu_top_n": [],
                            "memory_top_n": [],
                            "all_pods": []
                        },
                        "summary": {
                            "total_pods": 0,
                            "critical_cpu": 0,
                            "critical_memory": 0,
                            "warning_cpu": 0,
                            "warning_memory": 0
                        },
                        "message": f"没有找到匹配 label_selector '{label_selector}' 的 Pod"
                    }

    # ========== 3. 获取 AOM 实例 ==========
    aom_instance_id = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    cce_instances = []
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                cce_instances.append(instance)

    # 测试每个 CCE 实例，找到有数据的
    for instance in cce_instances:
        test_instance_id = instance.get("id")
        test_result = get_aom_prom_metrics_http(region, test_instance_id, "up", hours=0.1, ak=access_key, sk=secret_key, project_id=proj_id)
        if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
            aom_instance_id = test_instance_id
            break

    if not aom_instance_id:
        return {
            "success": False,
            "error": "未找到可用的 AOM 实例",
            "cluster_id": cluster_id,
            "cluster_name": cluster_name
        }

    # ========== 4. 构建 PromQL 查询 ==========
    # 构建 Pod 过滤条件
    pod_filter_clause = ""
    if pod_filter_list:
        # 使用正则匹配多个 Pod 名称
        pod_regex = "|".join(pod_filter_list[:100])  # 限制最多 100 个 Pod
        pod_filter_clause = f',pod=~"{pod_regex}"'

    # 构建节点过滤条件
    node_filter_clause = ""
    if node_ip:
        node_filter_clause = f',node="{node_ip}"'

    # 默认 CPU 使用率 PromQL (相对 Limit %)
    if cpu_query is None:
        if namespace:
            cpu_query = f'topk({top_n}, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{{image!="",namespace="{namespace}"{pod_filter_clause}{node_filter_clause}}}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="cpu",namespace="{namespace}"{pod_filter_clause}{node_filter_clause}}}) * 100)'
        else:
            cpu_query = f'topk({top_n}, sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{{image!=""{pod_filter_clause}{node_filter_clause}}}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="cpu"{pod_filter_clause}{node_filter_clause}}}) * 100)'

    # 默认内存使用率 PromQL (相对 Limit %)
    if memory_query is None:
        if namespace:
            memory_query = f'topk({top_n}, sum by (pod, namespace) (container_memory_working_set_bytes{{image!="",namespace="{namespace}"{pod_filter_clause}{node_filter_clause}}}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="memory",namespace="{namespace}"{pod_filter_clause}{node_filter_clause}}}) * 100)'
        else:
            memory_query = f'topk({top_n}, sum by (pod, namespace) (container_memory_working_set_bytes{{image!=""{pod_filter_clause}{node_filter_clause}}}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="memory"{pod_filter_clause}{node_filter_clause}}}) * 100)'

    # ========== 5. 执行查询 ==========
    cpu_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    memory_result = get_aom_prom_metrics_http(region, aom_instance_id, memory_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)

    # ========== 6. 解析结果 ==========
    cpu_metrics = []
    if cpu_result.get("success") and cpu_result.get("result", {}).get("data", {}).get("result"):
        for item in cpu_result["result"]["data"]["result"]:
            metric = item.get("metric", {})
            values = item.get("values", [])
            if values:
                try:
                    latest_value = float(values[-1][1])
                    cpu_metrics.append({
                        "pod": metric.get("pod", "unknown"),
                        "namespace": metric.get("namespace", "unknown"),
                        "cpu_usage_percent": round(latest_value, 2),
                        "status": "critical" if latest_value > 80 else "warning" if latest_value > 50 else "normal",
                        "time_series": values  # 保存完整的时序数据
                    })
                except (ValueError, IndexError):
                    pass

    memory_metrics = []
    if memory_result.get("success") and memory_result.get("result", {}).get("data", {}).get("result"):
        for item in memory_result["result"]["data"]["result"]:
            metric = item.get("metric", {})
            values = item.get("values", [])
            if values:
                try:
                    latest_value = float(values[-1][1])
                    memory_metrics.append({
                        "pod": metric.get("pod", "unknown"),
                        "namespace": metric.get("namespace", "unknown"),
                        "memory_usage_percent": round(latest_value, 2),
                        "status": "critical" if latest_value > 80 else "warning" if latest_value > 50 else "normal",
                        "time_series": values  # 保存完整的时序数据
                    })
                except (ValueError, IndexError):
                    pass

    # 按 CPU 使用率排序
    cpu_metrics.sort(key=lambda x: x["cpu_usage_percent"], reverse=True)
    memory_metrics.sort(key=lambda x: x["memory_usage_percent"], reverse=True)

    # 合并 CPU 和内存数据
    pod_metrics_map = {}
    for m in cpu_metrics[:top_n]:
        key = f"{m['namespace']}/{m['pod']}"
        pod_metrics_map[key] = m
    for m in memory_metrics[:top_n]:
        key = f"{m['namespace']}/{m['pod']}"
        if key in pod_metrics_map:
            pod_metrics_map[key]["memory_usage_percent"] = m["memory_usage_percent"]
        else:
            pod_metrics_map[key] = m

    # ========== 7. 返回结果 ==========
    result = {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "aom_instance_id": aom_instance_id,
        "inspection_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
        "query_params": {
            "top_n": top_n,
            "hours": hours,
            "namespace": namespace
        },
        "promql": {
            "cpu": cpu_query,
            "memory": memory_query
        },
        "metrics": {
            "cpu_top_n": cpu_metrics[:top_n],
            "memory_top_n": memory_metrics[:top_n],
            "all_pods": list(pod_metrics_map.values())
        },
        "summary": {
            "total_pods": len(pod_metrics_map),
            "critical_cpu": len([m for m in cpu_metrics if m["status"] == "critical"]),
            "critical_memory": len([m for m in memory_metrics if m["status"] == "critical"]),
            "warning_cpu": len([m for m in cpu_metrics if m["status"] == "warning"]),
            "warning_memory": len([m for m in memory_metrics if m["status"] == "warning"])
        }
    }

    # 如果有 label 过滤，添加过滤信息
    if label_selector:
        result["query_params"]["label_selector"] = label_selector
        result["label_filter"] = {
            "selector": label_selector,
            "matched_count": len(matched_pods_info),
            "matched_pods": matched_pods_info[:50]  # 最多返回 50 个 Pod 信息
        }

    return result


def get_cce_pod_metrics(region: str, cluster_id: str, pod_name: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None, hours: int = 1, cpu_query: str = None, memory_query: str = None) -> Dict[str, Any]:
    """获取指定CCE Pod的CPU、内存使用率监控时序数据

    Args:
        region: 华为云区域 (如 cn-north-4)
        cluster_id: CCE 集群 ID
        pod_name: Pod名称
        ak: Access Key ID (可选)
        sk: Secret Access Key (可选)
        project_id: Project ID (可选)
        namespace: 命名空间（可选，默认所有命名空间）
        hours: 查询时间范围（小时）(默认 1)
        cpu_query: 自定义 CPU PromQL (可选)
        memory_query: 自定义内存 PromQL (可选)

    Returns:
        Dict with success status and specified pod metrics time series data
    """
    import time as time_module

    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}

    if not cluster_id or not pod_name:
        return {"success": False, "error": "cluster_id and pod_name are required"}

    # ========== 1. 获取集群名称 ==========
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

    # ========== 2. 获取Pod详细信息 ==========
    pod_info = {}
    pods_result = get_kubernetes_pods(region, cluster_id, access_key, secret_key, proj_id, namespace)
    if pods_result.get("success"):
        for pod in pods_result.get("pods", []):
            if pod.get("name") == pod_name:
                pod_info = pod
                break

    # ========== 3. 获取 AOM 实例 ==========
    aom_instance_id = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    cce_instances = []
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                cce_instances.append(instance)

    # 测试每个 CCE 实例，找到有数据的
    for instance in cce_instances:
        test_instance_id = instance.get("id")
        test_result = get_aom_prom_metrics_http(region, test_instance_id, "up", hours=0.1, ak=access_key, sk=secret_key, project_id=proj_id)
        if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
            aom_instance_id = test_instance_id
            break

    if not aom_instance_id:
        return {
            "success": False,
            "error": "未找到可用的 AOM 实例",
            "cluster_id": cluster_id,
            "cluster_name": cluster_name,
            "pod_name": pod_name,
            "namespace": namespace
        }

    # ========== 4. 构建 PromQL 查询（筛选指定Pod） ==========
    pod_filter = f',pod="{pod_name}"'
    namespace_filter = f',namespace="{namespace}"' if namespace else ""

    # 默认 CPU 使用率 PromQL (相对 Limit %)
    if cpu_query is None:
        cpu_query = f'sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{{image!=""{namespace_filter}{pod_filter}}}[5m])) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="cpu"{namespace_filter}{pod_filter}}}) * 100'

    # 默认内存使用率 PromQL (相对 Limit %)
    if memory_query is None:
        memory_query = f'sum by (pod, namespace) (container_memory_working_set_bytes{{image!=""{namespace_filter}{pod_filter}}}) / on (pod, namespace) group_left sum by (pod, namespace) (kube_pod_container_resource_limits{{resource="memory"{namespace_filter}{pod_filter}}}) * 100'

    # ========== 5. 执行查询 ==========
    cpu_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    memory_result = get_aom_prom_metrics_http(region, aom_instance_id, memory_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)

    # ========== 6. 解析结果 ==========
    def parse_metric_result(result, metric_name):
        """解析监控结果，返回时序数据"""
        if result.get("success") and result.get("result", {}).get("data", {}).get("result"):
            for item in result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    time_series = []
                    for ts, val in values:
                        try:
                            time_series.append({
                                "timestamp": int(ts),
                                "time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime(int(ts))),
                                "value": round(float(val), 2)
                            })
                        except (ValueError, IndexError):
                            pass
                    if time_series:
                        latest_value = time_series[-1]["value"]
                        return {
                            metric_name: latest_value,
                            "status": "critical" if latest_value > 80 else "warning" if latest_value > 50 else "normal",
                            "time_series": time_series
                        }
        return None

    cpu_data = parse_metric_result(cpu_result, "cpu_usage_percent")
    memory_data = parse_metric_result(memory_result, "memory_usage_percent")

    # ========== 7. 返回结果 ==========
    return {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "pod_name": pod_name,
        "namespace": pod_info.get("namespace", namespace),
        "pod_info": pod_info,
        "aom_instance_id": aom_instance_id,
        "query_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
        "query_params": {
            "hours": hours
        },
        "promql": {
            "cpu": cpu_query,
            "memory": memory_query
        },
        "metrics": {
            "cpu": cpu_data,
            "memory": memory_data
        }
    }


def get_cce_node_metrics_topN(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, top_n: int = 10, hours: int = 1, cpu_query: str = None, memory_query: str = None, disk_query: str = None) -> Dict[str, Any]:
    """获取 CCE 集群节点监控数据

    自动获取 AOM 实例并执行节点 CPU/内存/磁盘监控查询，返回 Top N 数据。

    Args:
        region: 华为云区域 (如 cn-north-4)
        cluster_id: CCE 集群 ID
        ak: Access Key ID (可选)
        sk: Secret Access Key (可选)
        project_id: Project ID (可选)
        top_n: 返回 Top N 数据 (默认 10)
        hours: 查询时间范围（小时）(默认 1)
        cpu_query: 自定义 CPU PromQL (可选)
        memory_query: 自定义内存 PromQL (可选)
        disk_query: 自定义磁盘 PromQL (可选)

    Returns:
        Dict with success status and node metrics data
    """
    import time as time_module

    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}

    if not cluster_id:
        return {"success": False, "error": "cluster_id is required"}

    # ========== 1. 获取集群名称 ==========
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

    # ========== 2. 获取节点信息映射 ==========
    node_info_map = {}  # IP -> 节点信息

    # 从 Kubernetes API 获取节点信息（节点名称即 IP）
    k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
    if k8s_nodes_result.get("success"):
        for node in k8s_nodes_result.get("nodes", []):
            node_name = node.get("name", "")  # Kubernetes 节点名即 IP
            if node_name:
                node_info_map[node_name] = {
                    "name": node_name,
                    "ip": node_name,
                    "status": node.get("status", "Unknown"),
                    "kubelet_version": node.get("kubelet_version", ""),
                    "os": node.get("os", ""),
                    "container_runtime": node.get("container_runtime", "")
                }

    # 从 CCE API 获取节点规格等信息（按名称匹配）
    cce_nodes_result = list_cce_cluster_nodes(region, cluster_id, access_key, secret_key, proj_id)
    if cce_nodes_result.get("success"):
        for cce_node in cce_nodes_result.get("nodes", []):
            cce_node_name = cce_node.get("name", "")
            # 尝试通过名称匹配
            for ip, node_info in node_info_map.items():
                if ip in cce_node_name or cce_node_name.endswith(ip.replace(".", "")):
                    node_info["cce_name"] = cce_node_name
                    node_info["id"] = cce_node.get("id", "")
                    node_info["flavor"] = cce_node.get("flavor", "")
                    node_info["cce_status"] = cce_node.get("status", "")
                    break

    # ========== 3. 获取 AOM 实例 ==========
    aom_instance_id = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    cce_instances = []
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                cce_instances.append(instance)

    # 测试每个 CCE 实例，找到有数据的
    for instance in cce_instances:
        test_instance_id = instance.get("id")
        test_result = get_aom_prom_metrics_http(region, test_instance_id, "up", hours=0.1, ak=access_key, sk=secret_key, project_id=proj_id)
        if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
            aom_instance_id = test_instance_id
            break

    if not aom_instance_id:
        return {
            "success": False,
            "error": "未找到可用的 AOM 实例",
            "cluster_id": cluster_id,
            "cluster_name": cluster_name
        }

    # ========== 4. 构建 PromQL 查询 ==========
    # 默认 CPU 使用率 PromQL
    if cpu_query is None:
        cpu_query = f"topk({top_n}, 100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode='idle',cluster_name='{cluster_name}'}}[5m])) * 100))"

    # 默认内存使用率 PromQL
    if memory_query is None:
        memory_query = f"topk({top_n}, avg by (instance) ((1 - node_memory_MemAvailable_bytes{{cluster_name='{cluster_name}'}} / node_memory_MemTotal_bytes{{cluster_name='{cluster_name}'}})) * 100)"

    # 默认磁盘使用率 PromQL
    if disk_query is None:
        disk_query = f"topk({top_n}, avg by (instance) ((1 - node_filesystem_avail_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}} / node_filesystem_size_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}'}})) * 100)"

    # ========== 5. 执行查询 ==========
    cpu_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    memory_result = get_aom_prom_metrics_http(region, aom_instance_id, memory_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    disk_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)

    # ========== 6. 解析结果 ==========
    def parse_node_result(result, metric_name):
        """解析节点监控结果"""
        metrics = []
        if result.get("success") and result.get("result", {}).get("data", {}).get("result"):
            for item in result["result"]["data"]["result"]:
                metric = item.get("metric", {})
                values = item.get("values", [])
                if values:
                    try:
                        latest_value = float(values[-1][1])
                        instance = metric.get("instance", "unknown")
                        # 提取 IP 地址
                        instance_ip = instance.split(":")[0] if ":" in instance else instance

                        # 获取节点信息
                        node_info = node_info_map.get(instance_ip, {})
                        # 优先使用节点名称，否则使用 IP
                        node_name = node_info.get("name", instance_ip)

                        metrics.append({
                            "instance": instance,
                            "node_ip": instance_ip,
                            "node_name": node_name,
                            "node_id": node_info.get("id", ""),
                            "flavor": node_info.get("flavor", ""),
                            metric_name: round(latest_value, 2),
                            "status": "critical" if latest_value > 80 else "warning" if latest_value > 50 else "normal",
                            "time_series": values  # 保存完整的时序数据
                        })
                    except (ValueError, IndexError):
                        pass
        return metrics

    cpu_metrics = parse_node_result(cpu_result, "cpu_usage_percent")
    memory_metrics = parse_node_result(memory_result, "memory_usage_percent")
    disk_metrics = parse_node_result(disk_result, "disk_usage_percent")

    # 按使用率排序
    cpu_metrics.sort(key=lambda x: x["cpu_usage_percent"], reverse=True)
    memory_metrics.sort(key=lambda x: x["memory_usage_percent"], reverse=True)
    disk_metrics.sort(key=lambda x: x["disk_usage_percent"], reverse=True)

    # 合并所有节点的监控数据
    all_nodes_map = {}
    for m in cpu_metrics:
        key = m["node_ip"]
        all_nodes_map[key] = m
    for m in memory_metrics:
        key = m["node_ip"]
        if key in all_nodes_map:
            all_nodes_map[key]["memory_usage_percent"] = m["memory_usage_percent"]
            all_nodes_map[key]["status"] = "critical" if m["memory_usage_percent"] > 80 else "warning" if m["memory_usage_percent"] > 50 else all_nodes_map[key]["status"]
        else:
            all_nodes_map[key] = m
    for m in disk_metrics:
        key = m["node_ip"]
        if key in all_nodes_map:
            all_nodes_map[key]["disk_usage_percent"] = m["disk_usage_percent"]
            if m["disk_usage_percent"] > 80:
                all_nodes_map[key]["status"] = "critical"
            elif m["disk_usage_percent"] > 50 and all_nodes_map[key]["status"] == "normal":
                all_nodes_map[key]["status"] = "warning"
        else:
            all_nodes_map[key] = m

    # ========== 7. 返回结果 ==========
    return {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "aom_instance_id": aom_instance_id,
        "inspection_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
        "query_params": {
            "top_n": top_n,
            "hours": hours
        },
        "promql": {
            "cpu": cpu_query,
            "memory": memory_query,
            "disk": disk_query
        },
        "metrics": {
            "cpu_top_n": cpu_metrics[:top_n],
            "memory_top_n": memory_metrics[:top_n],
            "disk_top_n": disk_metrics[:top_n],
            "all_nodes": list(all_nodes_map.values())
        },
        "summary": {
            "total_nodes": len(all_nodes_map),
            "critical_cpu": len([m for m in cpu_metrics if m["status"] == "critical"]),
            "critical_memory": len([m for m in memory_metrics if m["status"] == "critical"]),
            "critical_disk": len([m for m in disk_metrics if m["status"] == "critical"]),
            "warning_cpu": len([m for m in cpu_metrics if m["status"] == "warning"]),
            "warning_memory": len([m for m in memory_metrics if m["status"] == "warning"]),
            "warning_disk": len([m for m in disk_metrics if m["status"] == "warning"])
        }
    }


def get_cce_node_metrics(region: str, cluster_id: str, node_ip: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, hours: int = 1, cpu_query: str = None, memory_query: str = None, disk_query: str = None) -> Dict[str, Any]:
    """获取指定CCE节点的CPU、内存、磁盘使用率监控时序数据

    Args:
        region: 华为云区域 (如 cn-north-4)
        cluster_id: CCE 集群 ID
        node_ip: 节点IP地址
        ak: Access Key ID (可选)
        sk: Secret Access Key (可选)
        project_id: Project ID (可选)
        hours: 查询时间范围（小时）(默认 1)
        cpu_query: 自定义 CPU PromQL (可选)
        memory_query: 自定义内存 PromQL (可选)
        disk_query: 自定义磁盘 PromQL (可选)

    Returns:
        Dict with success status and specified node metrics time series data
    """
    import time as time_module

    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}

    if not cluster_id or not node_ip:
        return {"success": False, "error": "cluster_id and node_ip are required"}

    # ========== 1. 获取集群名称 ==========
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

    # ========== 2. 获取节点信息 ==========
    node_info = {}
    # 从 Kubernetes API 获取节点信息
    k8s_nodes_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
    if k8s_nodes_result.get("success"):
        for node in k8s_nodes_result.get("nodes", []):
            if node.get("ip") == node_ip:
                node_info = node
                break

    # 从 CCE API 获取节点规格等信息
    if not node_info:
        cce_nodes_result = list_cce_cluster_nodes(region, cluster_id, access_key, secret_key, proj_id)
        if cce_nodes_result.get("success"):
            for cce_node in cce_nodes_result.get("nodes", []):
                cce_node_name = cce_node.get("name", "")
                if node_ip in cce_node_name or cce_node_name.endswith(node_ip.replace(".", "")):
                    node_info["cce_name"] = cce_node_name
                    node_info["id"] = cce_node.get("id", "")
                    node_info["flavor"] = cce_node.get("flavor", "")
                    node_info["cce_status"] = cce_node.get("status", "")
                    break

    # ========== 3. 获取 AOM 实例 ==========
    aom_instance_id = None
    aom_instances = list_aom_instances(region, access_key, secret_key, proj_id)
    cce_instances = []
    if aom_instances.get("success"):
        for instance in aom_instances.get("instances", []):
            if instance.get("type") == "CCE":
                cce_instances.append(instance)

    # 测试每个 CCE 实例，找到有数据的
    for instance in cce_instances:
        test_instance_id = instance.get("id")
        test_result = get_aom_prom_metrics_http(region, test_instance_id, "up", hours=0.1, ak=access_key, sk=secret_key, project_id=proj_id)
        if test_result.get("success") and test_result.get("result", {}).get("data", {}).get("result"):
            aom_instance_id = test_instance_id
            break

    if not aom_instance_id:
        return {
            "success": False,
            "error": "未找到可用的 AOM 实例",
            "cluster_id": cluster_id,
            "cluster_name": cluster_name,
            "node_ip": node_ip
        }

    # ========== 4. 构建 PromQL 查询（筛选指定节点IP） ==========
    # 默认 CPU 使用率 PromQL
    if cpu_query is None:
        cpu_query = f"100 - (avg by (instance) (irate(node_cpu_seconds_total{{mode='idle',cluster_name='{cluster_name}',instance=~'{node_ip}.*'}}[5m])) * 100"

    # 默认内存使用率 PromQL
    if memory_query is None:
        memory_query = f"avg by (instance) ((1 - node_memory_MemAvailable_bytes{{cluster_name='{cluster_name}',instance=~'{node_ip}.*'}} / node_memory_MemTotal_bytes{{cluster_name='{cluster_name}',instance=~'{node_ip}.*'}})) * 100"

    # 默认磁盘使用率 PromQL
    if disk_query is None:
        disk_query = f"avg by (instance) ((1 - node_filesystem_avail_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}',instance=~'{node_ip}.*'}} / node_filesystem_size_bytes{{mountpoint='/',fstype!~'tmpfs|fuse.lxcfs',cluster_name='{cluster_name}',instance=~'{node_ip}.*'}})) * 100"

    # ========== 5. 执行查询 ==========
    cpu_result = get_aom_prom_metrics_http(region, aom_instance_id, cpu_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    memory_result = get_aom_prom_metrics_http(region, aom_instance_id, memory_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)
    disk_result = get_aom_prom_metrics_http(region, aom_instance_id, disk_query, hours=hours, ak=access_key, sk=secret_key, project_id=proj_id)

    # ========== 6. 解析结果 ==========
    def parse_metric_result(result, metric_name):
        """解析监控结果，返回时序数据"""
        if result.get("success") and result.get("result", {}).get("data", {}).get("result"):
            for item in result["result"]["data"]["result"]:
                values = item.get("values", [])
                if values:
                    time_series = []
                    for ts, val in values:
                        try:
                            time_series.append({
                                "timestamp": int(ts),
                                "time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime(int(ts))),
                                "value": round(float(val), 2)
                            })
                        except (ValueError, IndexError):
                            pass
                    if time_series:
                        latest_value = time_series[-1]["value"]
                        return {
                            metric_name: latest_value,
                            "status": "critical" if latest_value > 80 else "warning" if latest_value > 50 else "normal",
                            "time_series": time_series
                        }
        return None

    cpu_data = parse_metric_result(cpu_result, "cpu_usage_percent")
    memory_data = parse_metric_result(memory_result, "memory_usage_percent")
    disk_data = parse_metric_result(disk_result, "disk_usage_percent")

    # ========== 7. 返回结果 ==========
    return {
        "success": True,
        "region": region,
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "node_ip": node_ip,
        "node_info": node_info,
        "aom_instance_id": aom_instance_id,
        "query_time": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime()),
        "query_params": {
            "hours": hours
        },
        "promql": {
            "cpu": cpu_query,
            "memory": memory_query,
            "disk": disk_query
        },
        "metrics": {
            "cpu": cpu_data,
            "memory": memory_data,
            "disk": disk_data
        }
    }


def list_aom_alerts(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, alert_status: str = None, severity: str = None, limit: int = 100) -> Dict[str, Any]:
    """List AOM alerts (alarm records)
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        alert_status: Filter by alert status - 'firing' or 'resolved' (optional)
        severity: Filter by severity - 'critical', 'warning', 'info' (optional)
        limit: Maximum number of alerts to return (default: 100)
    
    Returns:
        Dict with success status and list of alerts
    """
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    try:
        from huaweicloudsdkaom.v2 import (
            ListAlarmRuleRequest, 
            ListEvent2alarmRuleRequest,
            ListActionRuleRequest
        )
        
        client = create_aom_client(region, access_key, secret_key, proj_id)
        
        # 获取阈值告警规则
        alarm_rules = []
        try:
            alarm_req = ListAlarmRuleRequest()
            alarm_req.limit = limit
            alarm_resp = client.list_alarm_rule(alarm_req)
            if hasattr(alarm_resp, 'alarm_rules') and alarm_resp.alarm_rules:
                for rule in alarm_resp.alarm_rules:
                    rule_info = {
                        "rule_name": getattr(rule, 'alarm_rule_name', None),
                        "rule_id": getattr(rule, 'alarm_rule_id', None),
                        "rule_description": getattr(rule, 'alarm_rule_description', None),
                        "rule_status": getattr(rule, 'alarm_rule_status', None),
                        "alarm_level": getattr(rule, 'alarm_level', None),
                        "metric_name": getattr(rule, 'metric_name', None),
                        "namespace": getattr(rule, 'namespace', None),
                        "resource_id": getattr(rule, 'resource_id', None),
                    }
                    alarm_rules.append(rule_info)
        except Exception as e:
            pass
        
        # 获取事件告警规则
        event_rules = []
        try:
            event_req = ListEvent2alarmRuleRequest()
            event_resp = client.list_event2alarm_rule(event_req)
            if hasattr(event_resp, 'event2alarm_rules') and event_resp.event2alarm_rules:
                for rule in event_resp.event2alarm_rules:
                    rule_info = {
                        "rule_name": getattr(rule, 'rule_name', None),
                        "rule_id": getattr(rule, 'rule_id', None),
                        "description": getattr(rule, 'description', None),
                        "status": getattr(rule, 'status', None),
                    }
                    event_rules.append(rule_info)
        except Exception as e:
            pass
        
        # 获取告警行动规则
        action_rules = []
        try:
            action_req = ListActionRuleRequest()
            action_resp = client.list_action_rule(action_req)
            if hasattr(action_resp, 'action_rules') and action_resp.action_rules:
                for rule in action_resp.action_rules:
                    rule_info = {
                        "rule_name": getattr(rule, 'rule_name', None),
                        "desc": getattr(rule, 'desc', None),
                        "type": getattr(rule, 'type', None),
                        "notification_template": getattr(rule, 'notification_template', None),
                        "time_zone": getattr(rule, 'time_zone', None),
                        "create_time": getattr(rule, 'create_time', None),
                        "update_time": getattr(rule, 'update_time', None),
                    }
                    # 获取SMN主题
                    smn_topics = getattr(rule, 'smn_topics', [])
                    if smn_topics:
                        rule_info["smn_topics"] = [
                            {
                                "name": getattr(t, 'name', None),
                                "topic_urn": getattr(t, 'topic_urn', None),
                                "status": getattr(t, 'status', None),
                            } for t in smn_topics
                        ]
                    action_rules.append(rule_info)
        except Exception as e:
            pass
        
        return {
            "success": True,
            "region": region,
            "action": "list_aom_alerts",
            "threshold_alarm_rules_count": len(alarm_rules),
            "threshold_alarm_rules": alarm_rules,
            "event_alarm_rules_count": len(event_rules),
            "event_alarm_rules": event_rules,
            "action_rules_count": len(action_rules),
            "action_rules": action_rules,
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_aom_alarm_rules(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List AOM alarm rules (threshold alarms)
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        limit: Maximum number of rules to return (default: 100)
        offset: Offset for pagination (default: 0)
    
    Returns:
        Dict with success status and list of alarm rules
    """
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    try:
        from huaweicloudsdkaom.v2 import ListAlarmRuleRequest, ListServiceDiscoveryRulesRequest
        
        client = create_aom_client(region, access_key, secret_key, proj_id)
        
        # 告警规则
        alarm_request = ListAlarmRuleRequest()
        alarm_request.limit = limit
        alarm_request.offset = offset
        
        alarm_response = client.list_alarm_rule(alarm_request)
        
        rules = []
        if hasattr(alarm_response, 'alarm_rules') and alarm_response.alarm_rules:
            for rule in alarm_response.alarm_rules:
                rule_info = {
                    "rule_name": getattr(rule, 'alarm_rule_name', None),
                    "rule_id": getattr(rule, 'alarm_rule_id', None),
                    "rule_description": getattr(rule, 'alarm_rule_description', None),
                    "rule_status": getattr(rule, 'alarm_rule_status', None),
                    "metric_name": getattr(rule, 'metric_name', None),
                    "metric_namespace": getattr(rule, 'namespace', None),
                    "resource_id": getattr(rule, 'resource_id', None),
                    "alarm_level": getattr(rule, 'alarm_level', None),
                    "created_at": str(getattr(rule, 'create_time', None)) if getattr(rule, 'create_time', None) else None,
                    "updated_at": str(getattr(rule, 'update_time', None)) if getattr(rule, 'update_time', None) else None,
                }
                rules.append(rule_info)
        
        # 服务发现规则
        sd_request = ListServiceDiscoveryRulesRequest()
        sd_response = client.list_service_discovery_rules(sd_request)
        
        discoveries = []
        if hasattr(sd_response, 'service_discovery_rules') and sd_response.service_discovery_rules:
            for sd in sd_response.service_discovery_rules:
                sd_info = {
                    "id": getattr(sd, 'service_discovery_id', None),
                    "name": getattr(sd, 'service_discovery_name', None),
                    "status": getattr(sd, 'status', None),
                    "type": getattr(sd, 'service_discovery_type', None),
                }
                discoveries.append(sd_info)
        
        return {
            "success": True,
            "region": region,
            "action": "list_aom_alarm_rules",
            "alarm_rules_count": len(rules),
            "alarm_rules": rules,
            "service_discovery_count": len(discoveries),
            "service_discovery_rules": discoveries
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_aom_action_rules(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List AOM action rules (notification rules)
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
    
    Returns:
        Dict with success status and list of action rules
    """
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    try:
        from huaweicloudsdkaom.v2 import ListActionRuleRequest
        
        client = create_aom_client(region, access_key, secret_key, proj_id)
        
        request = ListActionRuleRequest()
        
        response = client.list_action_rule(request)
        
        rules = []
        if hasattr(response, 'action_rules') and response.action_rules:
            for rule in response.action_rules:
                rule_info = {
                    "rule_name": getattr(rule, 'rule_name', None),
                    "description": getattr(rule, 'desc', None),
                    "type": getattr(rule, 'type', None),
                    "notification_template": getattr(rule, 'notification_template', None),
                    "time_zone": getattr(rule, 'time_zone', None),
                    "create_time": getattr(rule, 'create_time', None),
                    "update_time": getattr(rule, 'update_time', None),
                    "user_name": getattr(rule, 'user_name', None),
                }
                
                # 获取SMN主题
                smn_topics = getattr(rule, 'smn_topics', [])
                if smn_topics:
                    rule_info["smn_topics"] = [
                        {
                            "name": getattr(t, 'name', None),
                            "topic_urn": getattr(t, 'topic_urn', None),
                            "status": getattr(t, 'status', None),
                            "push_policy": getattr(t, 'push_policy', None),
                        } for t in smn_topics
                    ]
                
                rules.append(rule_info)
        
        return {
            "success": True,
            "region": region,
            "action": "list_aom_action_rules",
            "count": len(rules),
            "action_rules": rules
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_aom_mute_rules(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List AOM mute rules (silence rules)
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
    
    Returns:
        Dict with success status and list of mute rules
    """
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    try:
        from huaweicloudsdkaom.v2 import ListMuteRuleRequest
        
        client = create_aom_client(region, access_key, secret_key, proj_id)
        
        request = ListMuteRuleRequest()
        
        response = client.list_mute_rule(request)
        
        rules = []
        if hasattr(response, 'mute_rules') and response.mute_rules:
            for rule in response.mute_rules:
                rule_info = {
                    "rule_id": getattr(rule, 'rule_id', None),
                    "rule_name": getattr(rule, 'rule_name', None),
                    "description": getattr(rule, 'description', None),
                    "status": getattr(rule, 'status', None),
                    "create_time": getattr(rule, 'create_time', None),
                    "update_time": getattr(rule, 'update_time', None),
                }
                rules.append(rule_info)
        
        return {
            "success": True,
            "region": region,
            "action": "list_aom_mute_rules",
            "count": len(rules),
            "mute_rules": rules
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_aom_current_alarms(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, event_type: str = "active_alert", event_severity: str = None, time_range: str = None, limit: int = 100) -> Dict[str, Any]:
    """List AOM events and alerts using ListEvents API
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        event_type: Query type - 'active_alert' (active alerts), 'history_alert' (historical alerts), or empty for all (default: 'active_alert')
        event_severity: Filter by severity - 'Critical', 'Major', 'Minor', 'Info' (optional)
        time_range: Time range in format 'startTime.endTime.duration', e.g., '-1.-1.60' for last 60 minutes (default: last 24 hours)
        limit: Maximum number of events to return (default: 100)
    
    Returns:
        Dict with success status and list of events/alerts
    
    API Reference: https://support.huaweicloud.com/api-aom/ListEvents.html
    """
    if not SDK_AVAILABLE:
        return {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
    try:
        from huaweicloudsdkaom.v2 import (
            ListEventsRequest, 
            EventQueryParam2,
            RelationModel,
            EventQueryParam2Sort
        )
        
        client = create_aom_client(region, access_key, secret_key, proj_id)
        
        # 构建请求
        request = ListEventsRequest()
        
        # 设置查询类型
        if event_type:
            request.type = event_type
        
        request.limit = limit
        
        # 构建请求体
        body = EventQueryParam2()
        
        # 时间范围：默认最近24小时
        if time_range:
            body.time_range = time_range
        else:
            body.time_range = "-1.-1.1440"  # 最近24小时 (1440分钟)
        
        # 构建查询条件
        metadata_relations = []
        
        # 事件类型条件
        metadata_relations.append(
            RelationModel(
                key="event_type",
                value=["alarm"],
                relation="AND"
            )
        )
        
        # 严重级别条件
        if event_severity:
            severities = [event_severity] if isinstance(event_severity, str) else event_severity
            metadata_relations.append(
                RelationModel(
                    key="event_severity",
                    value=severities,
                    relation="AND"
                )
            )
        else:
            # 默认查询所有级别
            metadata_relations.append(
                RelationModel(
                    key="event_severity",
                    value=["Critical", "Major", "Minor", "Info"],
                    relation="AND"
                )
            )
        
        body.metadata_relation = metadata_relations
        
        # 排序：按开始时间倒序
        sort = EventQueryParam2Sort(
            order_by=["starts_at"],
            order="desc"
        )
        body.sort = sort
        
        # 搜索条件（可选）
        body.search = ""
        
        request.body = body
        
        # 发送请求
        response = client.list_events(request)
        
        # 解析响应
        events = []
        if hasattr(response, 'events') and response.events:
            for event in response.events:
                event_info = {
                    'id': getattr(event, 'id', None),
                    'event_sn': getattr(event, 'event_sn', None),
                    'starts_at': getattr(event, 'starts_at', None),
                    'ends_at': getattr(event, 'ends_at', None),
                    'arrives_at': getattr(event, 'arrives_at', None),
                    'timeout': getattr(event, 'timeout', None),
                    'enterprise_project_id': getattr(event, 'enterprise_project_id', None),
                }
                
                # 解析metadata
                metadata = getattr(event, 'metadata', {})
                if metadata:
                    event_info['event_name'] = metadata.get('event_name')
                    event_info['event_severity'] = metadata.get('event_severity')
                    event_info['event_type'] = metadata.get('event_type')
                    event_info['resource_provider'] = metadata.get('resource_provider')
                    event_info['resource_type'] = metadata.get('resource_type')
                    event_info['resource_id'] = metadata.get('resource_id')
                
                # 从resource_id解析集群信息
                resource_id = metadata.get('resource_id', '') if metadata else ''
                if resource_id:
                    # 解析格式: clusterName=xxx;clusterID=xxx;...
                    parts = resource_id.split(';')
                    for part in parts:
                        if '=' in part:
                            key, value = part.split('=', 1)
                            if key == 'clusterName':
                                event_info['cluster_name'] = value
                            elif key == 'clusterID':
                                event_info['cluster_id'] = value
                            elif key == 'namespace':
                                event_info['namespace'] = value
                            elif key == 'name':
                                event_info['pod_name'] = value
                            elif key == 'kind':
                                event_info['resource_kind'] = value
                            elif key == 'clusterAliasName':
                                event_info['cluster_alias_name'] = value
                
                # 解析annotations
                annotations = getattr(event, 'annotations', {})
                if annotations:
                    event_info['message'] = annotations.get('message')
                    event_info['alarm_probableCause_zh_cn'] = annotations.get('alarm_probableCause_zh_cn')
                    event_info['alarm_fix_suggestion_zh_cn'] = annotations.get('alarm_fix_suggestion_zh_cn')
                
                # 判断告警状态
                ends_at = getattr(event, 'ends_at', None)
                if ends_at and ends_at > 0:
                    event_info['status'] = 'resolved'
                else:
                    event_info['status'] = 'firing'
                
                events.append(event_info)
        
        # 分页信息
        page_info = {}
        if hasattr(response, 'page_info') and response.page_info:
            page_info = {
                'current_count': getattr(response.page_info, 'current_count', 0),
                'next_marker': getattr(response.page_info, 'next_marker', None),
                'previous_marker': getattr(response.page_info, 'previous_marker', None),
            }
        
        # 统计
        firing_count = sum(1 for e in events if e.get('status') == 'firing')
        resolved_count = sum(1 for e in events if e.get('status') == 'resolved')
        
        # 按严重级别统计
        severity_stats = {}
        for e in events:
            sev = e.get('event_severity', 'Unknown')
            severity_stats[sev] = severity_stats.get(sev, 0) + 1
        
        return {
            "success": True,
            "region": region,
            "action": "list_aom_current_alarms",
            "api": "ListEvents",
            "query_type": event_type,
            "time_range": body.time_range,
            "total_count": len(events),
            "firing_count": firing_count,
            "resolved_count": resolved_count,
            "severity_stats": severity_stats,
            "events": events,
            "page_info": page_info
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def main():
    """Main entry point for the script"""
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
    instance_id = params.get("instance_id")
    cluster_id = params.get("cluster_id")
    az = params.get("az")
    namespace = params.get("namespace")
    vpc_id = params.get("vpc_id")
    volume_id = params.get("volume_id")
    loadbalancer_id = params.get("loadbalancer_id")
    eip_id = params.get("eip_id")
    nodepool_id = params.get("nodepool_id")
    node_count = params.get("node_count")
    node_id = params.get("node_id")
    limit = params.get("limit", "100")
    offset = params.get("offset", "0")
    try:
        limit = int(limit)
    except:
        limit = 100
    try:
        offset = int(offset)
    except:
        offset = 0

    if action == "huawei_list_ecs":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_ecs_instances(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_get_ecs_metrics":
        if not region or not instance_id:
            print(json.dumps({"success": False, "error": "region and instance_id are required"}))
            sys.exit(1)
        result = get_ecs_metrics(region, instance_id, ak, sk, project_id)

    elif action == "huawei_list_vpc":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_vpc_networks(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_vpc_subnets":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        vpc_id = params.get("vpc_id")
        result = list_vpc_subnets(region, vpc_id, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_sfs":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_sfs(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_sfs_turbo":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_sfs_turbo(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_nat":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_nat_gateways(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_security_groups":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_security_groups(region, vpc_id, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_flavors":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_ecs_flavors(region, az, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_cce_clusters":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_cce_clusters(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_delete_cce_cluster":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        confirm = params.get("confirm", "").lower() == "true"
        delete_evs = params.get("delete_evs", "").lower() == "true"
        delete_net = params.get("delete_net", "").lower() == "true"
        delete_obs = params.get("delete_obs", "").lower() == "true"
        result = delete_cce_cluster(region, cluster_id, confirm, delete_evs, delete_net, delete_obs, ak, sk, project_id)

    elif action == "huawei_list_cce_nodes":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = list_cce_cluster_nodes(region, cluster_id, ak, sk, project_id, limit, offset)

    elif action == "huawei_delete_cce_node":
        if not region or not cluster_id or not node_id:
            print(json.dumps({"success": False, "error": "region, cluster_id, and node_id are required"}))
            sys.exit(1)
        confirm = params.get("confirm", "").lower() == "true"
        scale_down = params.get("scale_down", "true").lower() == "true"
        result = delete_cce_node(region, cluster_id, node_id, confirm, scale_down, ak, sk, project_id)

    elif action == "huawei_list_cce_nodepools":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = list_cce_node_pools(region, cluster_id, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_cce_addons":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = list_cce_addons(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_list_cce_configmaps":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        namespace = params.get("namespace")
        include_data = params.get("include_data", "false").lower() == "true"
        result = list_cce_configmaps(region, cluster_id, namespace, limit, include_data, ak, sk, project_id)

    elif action == "huawei_list_cce_secrets":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        namespace = params.get("namespace")
        include_data = params.get("include_data", "false").lower() == "true"
        result = list_cce_secrets(region, cluster_id, namespace, limit, include_data, ak, sk, project_id)

    elif action == "huawei_get_cce_kubeconfig":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        duration = int(params.get("duration", 30))
        result = get_cce_kubeconfig(region, cluster_id, ak, sk, project_id, duration)

    elif action == "huawei_list_aom_instances":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        prom_type = params.get("prom_type", None)
        result = list_aom_instances(region, ak, sk, project_id, prom_type)

    elif action == "huawei_get_aom_metrics":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        aom_instance_id = params.get("aom_instance_id")
        if not aom_instance_id:
            print(json.dumps({"success": False, "error": "aom_instance_id is required"}))
            sys.exit(1)
        query = params.get("query")
        if not query:
            print(json.dumps({"success": False, "error": "query is required (PromQL expression)"}))
            sys.exit(1)
        
        start_ts = params.get("start")
        end_ts = params.get("end")
        step = int(params.get("step", 60))
        hours = int(params.get("hours", 1))
        
        result = get_aom_prom_metrics_http(
            region, aom_instance_id, query,
            start=int(start_ts) if start_ts else None,
            end=int(end_ts) if end_ts else None,
            step=step,
            hours=hours,
            ak=ak, sk=sk, project_id=project_id
        )

    elif action == "huawei_cce_cluster_inspection":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        if not cluster_id:
            print(json.dumps({"success": False, "error": "cluster_id is required"}))
            sys.exit(1)
        # 调用独立的巡检模块
        from inspection import cce_cluster_inspection
        result = cce_cluster_inspection(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_cce_cluster_inspection_parallel":
        # 并行模式巡检
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        if not cluster_id:
            print(json.dumps({"success": False, "error": "cluster_id is required"}))
            sys.exit(1)
        max_workers = int(params.get("max_workers", 4))
        from inspection_subagent import cce_cluster_inspection_parallel
        result = cce_cluster_inspection_parallel(region, cluster_id, ak, sk, project_id, max_workers)

    elif action == "huawei_cce_cluster_inspection_subagent":
        # Subagent模式 - 返回任务列表供主agent启动多个subagent
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        if not cluster_id:
            print(json.dumps({"success": False, "error": "cluster_id is required"}))
            sys.exit(1)
        from subagent_dispatcher import generate_auto_subagent_info
        result = generate_auto_subagent_info(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_aggregate_inspection_results":
        # 聚合subagent结果
        results_json = params.get("results")
        cluster_info_json = params.get("cluster_info")
        if not results_json or not cluster_info_json:
            print(json.dumps({"success": False, "error": "results and cluster_info are required"}))
            sys.exit(1)
        from subagent_dispatcher import aggregate_subagent_results
        try:
            results = json.loads(results_json) if isinstance(results_json, str) else results_json
            cluster_info = json.loads(cluster_info_json) if isinstance(cluster_info_json, str) else cluster_info_json
            result = aggregate_subagent_results(results, cluster_info)
        except Exception as e:
            result = {"success": False, "error": str(e)}

    elif action == "huawei_export_inspection_report":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        if not cluster_id:
            print(json.dumps({"success": False, "error": "cluster_id is required"}))
            sys.exit(1)
        output_file = params.get("output_file", f"/tmp/cce_inspection_report_{cluster_id[:8]}.html")
        # 调用独立的巡检模块
        from inspection import export_inspection_report
        result = export_inspection_report(region, cluster_id, output_file, ak, sk)

    elif action == "huawei_pod_status_inspection":
        # Pod 状态巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from pod_inspection import pod_status_inspection
        check_result, issues = pod_status_inspection(region, cluster_id, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_addon_pod_monitoring_inspection":
        # 插件 Pod 监控巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from pod_inspection import addon_pod_monitoring_inspection
        from inspection import _get_aom_instance, _get_cluster_name, _get_all_pods_map
        aom_instance_id = _get_aom_instance(region, ak, sk, project_id)
        cluster_name = _get_cluster_name(region, cluster_id, ak, sk, project_id)
        all_pods_map = _get_all_pods_map(region, cluster_id, ak, sk, project_id)
        check_result, issues = addon_pod_monitoring_inspection(region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id, all_pods_map)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_biz_pod_monitoring_inspection":
        # 业务 Pod 监控巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from pod_inspection import biz_pod_monitoring_inspection
        from inspection import _get_aom_instance, _get_cluster_name, _get_all_pods_map, _get_all_namespaces
        aom_instance_id = _get_aom_instance(region, ak, sk, project_id)
        cluster_name = _get_cluster_name(region, cluster_id, ak, sk, project_id)
        all_pods_map = _get_all_pods_map(region, cluster_id, ak, sk, project_id)
        all_namespaces = _get_all_namespaces(region, cluster_id, ak, sk, project_id)
        check_result, issues = biz_pod_monitoring_inspection(region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id, all_pods_map, all_namespaces)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_node_status_inspection":
        # Node 状态巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from node_inspection import node_status_inspection
        check_result, issues = node_status_inspection(region, cluster_id, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_node_resource_inspection":
        # 节点资源监控巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from node_inspection import node_resource_monitoring_inspection
        from inspection import _get_aom_instance, _get_cluster_name
        aom_instance_id = _get_aom_instance(region, ak, sk, project_id)
        cluster_name = _get_cluster_name(region, cluster_id, ak, sk, project_id)
        check_result, issues = node_resource_monitoring_inspection(region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_event_inspection":
        # Event 巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from alarm_inspection import event_inspection
        check_result, issues = event_inspection(region, cluster_id, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_aom_alarm_inspection":
        # AOM 告警巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from alarm_inspection import aom_alarm_inspection
        from inspection import _get_cluster_name
        cluster_name = _get_cluster_name(region, cluster_id, ak, sk, project_id)
        check_result, issues = aom_alarm_inspection(region, cluster_id, cluster_name, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_elb_monitoring_inspection":
        # ELB 负载均衡监控巡检
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from network_inspection import elb_monitoring_inspection
        from inspection import _get_aom_instance, _get_cluster_name
        aom_instance_id = _get_aom_instance(region, ak, sk, project_id)
        cluster_name = _get_cluster_name(region, cluster_id, ak, sk, project_id)
        check_result, issues = elb_monitoring_inspection(region, cluster_id, aom_instance_id, cluster_name, ak, sk, project_id)
        result = {"success": True, "check": check_result, "issues": issues}

    elif action == "huawei_get_cce_pod_metrics_topN":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        pod_namespace = params.get("namespace")
        pod_label_selector = params.get("label_selector")
        pod_top_n = int(params.get("top_n", 10))
        pod_hours = int(params.get("hours", 1))
        cpu_query = params.get("cpu_query")
        memory_query = params.get("memory_query")
        result = get_cce_pod_metrics_topN(region, cluster_id, ak, sk, project_id, namespace=pod_namespace, label_selector=pod_label_selector, top_n=pod_top_n, hours=pod_hours, cpu_query=cpu_query, memory_query=memory_query)

    elif action == "huawei_get_cce_pod_metrics":
        if not region or not cluster_id or not params.get("pod_name"):
            print(json.dumps({"success": False, "error": "region, cluster_id and pod_name are required"}))
            sys.exit(1)
        pod_name = params.get("pod_name")
        pod_namespace = params.get("namespace")
        hours = int(params.get("hours", 1))
        cpu_query = params.get("cpu_query")
        memory_query = params.get("memory_query")
        result = get_cce_pod_metrics(region, cluster_id, pod_name, ak, sk, project_id, namespace=pod_namespace, hours=hours, cpu_query=cpu_query, memory_query=memory_query)

    elif action == "huawei_get_cce_node_metrics_topN":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        node_top_n = int(params.get("top_n", 10))
        node_hours = int(params.get("hours", 1))
        cpu_query = params.get("cpu_query")
        memory_query = params.get("memory_query")
        disk_query = params.get("disk_query")
        result = get_cce_node_metrics_topN(region, cluster_id, ak, sk, project_id, top_n=node_top_n, hours=node_hours, cpu_query=cpu_query, memory_query=memory_query, disk_query=disk_query)

    elif action == "huawei_get_cce_node_metrics":
        if not region or not cluster_id or not params.get("node_ip"):
            print(json.dumps({"success": False, "error": "region, cluster_id and node_ip are required"}))
            sys.exit(1)
        node_ip = params.get("node_ip")
        hours = int(params.get("hours", 1))
        cpu_query = params.get("cpu_query")
        memory_query = params.get("memory_query")
        disk_query = params.get("disk_query")
        result = get_cce_node_metrics(region, cluster_id, node_ip, ak, sk, project_id, hours=hours, cpu_query=cpu_query, memory_query=memory_query, disk_query=disk_query)

    elif action == "huawei_resize_cce_nodepool":
        if not region or not cluster_id or not nodepool_id:
            print(json.dumps({"success": False, "error": "region, cluster_id, and nodepool_id are required"}))
            sys.exit(1)
        if not node_count:
            print(json.dumps({"success": False, "error": "node_count is required (target number of nodes)"}))
            sys.exit(1)
        try:
            node_count = int(node_count)
        except ValueError:
            print(json.dumps({"success": False, "error": "node_count must be an integer"}))
            sys.exit(1)
        confirm_resize = params.get("confirm", "false").lower() == "true"
        # Parse scale_group_names (comma-separated)
        scale_group_names_str = params.get("scale_group_names")
        scale_group_names = None
        if scale_group_names_str:
            scale_group_names = [name.strip() for name in scale_group_names_str.split(",") if name.strip()]
        result = resize_node_pool(region, cluster_id, nodepool_id, node_count, confirm_resize, scale_group_names, ak, sk, project_id)

    elif action == "huawei_list_evs":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_evs_volumes(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_get_evs_metrics":
        if not region or not volume_id:
            print(json.dumps({"success": False, "error": "region and volume_id are required"}))
            sys.exit(1)
        result = get_evs_metrics(region, volume_id, instance_id, ak, sk, project_id)

    elif action == "huawei_get_cce_pods":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_pods(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_get_cce_namespaces":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_namespaces(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_get_cce_deployments":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_deployments(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_scale_cce_workload":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        workload_type = params.get("workload_type")
        workload_name = params.get("name")
        workload_namespace = namespace  # reuse namespace param
        replicas_str = params.get("replicas")
        confirm = params.get("confirm", "").lower() == "true"
        if not workload_type or not workload_name or not workload_namespace:
            print(json.dumps({"success": False, "error": "workload_type, name, and namespace are required"}))
            sys.exit(1)
        if not replicas_str:
            print(json.dumps({"success": False, "error": "replicas is required"}))
            sys.exit(1)
        try:
            replicas = int(replicas_str)
        except ValueError:
            print(json.dumps({"success": False, "error": "replicas must be an integer"}))
            sys.exit(1)
        result = scale_cce_workload(region, cluster_id, workload_type, workload_name, workload_namespace, replicas, confirm, ak, sk, project_id)

    elif action == "huawei_delete_cce_workload":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        workload_type = params.get("workload_type")
        workload_name = params.get("name")
        workload_namespace = namespace  # reuse namespace param
        confirm = params.get("confirm", "").lower() == "true"
        if not workload_type or not workload_name or not workload_namespace:
            print(json.dumps({"success": False, "error": "workload_type, name, and namespace are required"}))
            sys.exit(1)
        result = delete_cce_workload(region, cluster_id, workload_type, workload_name, workload_namespace, confirm, ak, sk, project_id)

    elif action == "huawei_get_kubernetes_nodes":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_nodes(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_get_cce_events":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_events(region, cluster_id, ak, sk, project_id, namespace, limit)

    elif action == "huawei_get_cce_pvcs":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_pvcs(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_get_cce_pvs":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_pvs(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_get_cce_services":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_services(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_get_cce_ingresses":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_kubernetes_ingresses(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_list_elb":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_elb_loadbalancers(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_elb_listeners":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_elb_listeners(region, loadbalancer_id, ak, sk, project_id, limit)

    elif action == "huawei_get_elb_metrics":
        if not region or not loadbalancer_id:
            print(json.dumps({"success": False, "error": "region and loadbalancer_id are required"}))
            sys.exit(1)
        result = get_elb_metrics(region, loadbalancer_id, ak, sk, project_id)

    elif action == "huawei_list_supported_regions":
        # List all supported regions (no credentials required)
        result = list_supported_regions()

    elif action == "huawei_list_projects":
        # List all projects (no region required, IAM is global)
        domain_id = params.get("domain_id")
        result = list_projects(ak, sk, domain_id, region)

    elif action == "huawei_get_project_by_region":
        if not region:
            print(json.dumps({"success": False, "error": "region is required (e.g., cn-north-4)"}))
            sys.exit(1)
        result = get_project_by_region(region, ak, sk)

    elif action == "huawei_list_vpc_acls":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_vpc_acls(region, vpc_id, ak, sk, project_id)

    elif action == "huawei_list_eip":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_eip_addresses(region, ak, sk, project_id, limit)

    elif action == "huawei_get_eip_metrics":
        if not region or not eip_id:
            print(json.dumps({"success": False, "error": "region and eip_id are required"}))
            sys.exit(1)
        result = get_eip_metrics(region, eip_id, ak, sk, project_id)

    elif action == "huawei_list_aom_alerts":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        alert_status = params.get("alert_status")
        severity = params.get("severity")
        result = list_aom_alerts(region, ak, sk, project_id, alert_status, severity, limit)

    elif action == "huawei_list_aom_alarm_rules":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_aom_alarm_rules(region, ak, sk, project_id, limit, offset)

    elif action == "huawei_list_aom_action_rules":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_aom_action_rules(region, ak, sk, project_id)

    elif action == "huawei_list_aom_mute_rules":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        result = list_aom_mute_rules(region, ak, sk, project_id)

    elif action == "huawei_list_aom_current_alarms":
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        event_type = params.get("event_type", "active_alert")
        event_severity = params.get("event_severity")
        time_range = params.get("time_range")
        result = list_aom_current_alarms(region, ak, sk, project_id, event_type, event_severity, time_range, limit)

    elif action == "huawei_list_log_groups":
        # 查询日志组列表
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        from lts_tools import list_log_groups
        result = list_log_groups(region, ak, sk, project_id)

    elif action == "huawei_list_log_streams":
        # 查询日志流列表
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        log_group_id = params.get("log_group_id")
        from lts_tools import list_log_streams
        result = list_log_streams(region, log_group_id, ak, sk, project_id)

    elif action == "huawei_query_logs":
        # 查询日志内容（支持分页）
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        log_group_id = params.get("log_group_id")
        log_stream_id = params.get("log_stream_id")
        if not log_group_id or not log_stream_id:
            print(json.dumps({"success": False, "error": "log_group_id and log_stream_id are required"}))
            sys.exit(1)
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        keywords = params.get("keywords")
        query_limit = int(params.get("limit", 1000))
        scroll_id = params.get("scroll_id")
        is_desc = params.get("is_desc", "true").lower() == "true"
        is_iterative = params.get("is_iterative", "false").lower() == "true"
        labels = params.get("labels")
        if labels and isinstance(labels, str):
            # 解析JSON格式的labels
            try:
                labels = json.loads(labels)
            except:
                print(json.dumps({"success": False, "error": "labels参数格式错误，必须是JSON格式的字典，例如 '{\"appName\": \"test\", \"namespace\": \"default\"}'"}))
                sys.exit(1)
        from lts_tools import query_logs
        result = query_logs(region, log_group_id, log_stream_id, 
                           start_time=start_time, end_time=end_time, keywords=keywords, limit=query_limit,
                           scroll_id=scroll_id, is_desc=is_desc, is_iterative=is_iterative, labels=labels,
                           ak=ak, sk=sk, project_id=project_id)



    elif action == "huawei_get_cce_logconfigs":
        # 获取CCE集群的LogConfig自定义资源
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        namespace = params.get("namespace")
        
        if not K8S_AVAILABLE:
            result = {"success": False, "error": f"Kubernetes SDK not installed: {K8S_IMPORT_ERROR}"}
        elif not SDK_AVAILABLE:
            result = {"success": False, "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"}
        else:
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
                    result = {"success": False, "error": "Could not find cluster endpoint"}
                else:
                    # 配置Kubernetes客户端
                    configuration = k8s_client.Configuration()
                    configuration.host = external_cluster.get('cluster', {}).get('server')
                    configuration.verify_ssl = False
                    
                    # 写入证书
                    user_data = None
                    for u in kubeconfig_data.get('users', []):
                        if u.get('name') == 'user':
                            user_data = u.get('user', {})
                            break
                    
                    if user_data and user_data.get('client_certificate_data'):
                        cert_file = '/tmp/cce_logconfig_client.crt'
                        with open(cert_file, 'wb') as f:
                            f.write(base64.b64decode(user_data['client_certificate_data']))
                        configuration.cert_file = cert_file
                        temp_files.append(cert_file)
                    
                    if user_data and user_data.get('client_key_data'):
                        key_file = '/tmp/cce_logconfig_client.key'
                        with open(key_file, 'wb') as f:
                            f.write(base64.b64decode(user_data['client_key_data']))
                        configuration.key_file = key_file
                        temp_files.append(key_file)
                    
                    _register_cert_file(cert_file if 'cert_file' in locals() else None)
                    _register_cert_file(key_file if 'key_file' in locals() else None)
                    
                    # 设置默认配置并获取自定义资源
                    k8s_client.Configuration.set_default(configuration)
                    custom_api = k8s_client.CustomObjectsApi()
                    
                    # 尝试常见的 LogConfig Group/Version/Plural 组合
                    logconfig_list = []
                    tried_combinations = []
                    cr_combinations = [
                        # 用户提供的正确组合
                        ("logging.openvessel.io", "v1", "logconfigs"),
                        # 其他常见组合
                        ("lts.opentelekomcloud.com", "v1", "logconfigs"),
                        ("lts.huaweicloud.com", "v1", "logconfigs"),
                        ("lts.io", "v1", "logconfigs"),
                        ("logging.huaweicloud.com", "v1", "logconfigs"),
                        ("lts.opentelekomcloud.com", "v1alpha1", "logconfigs"),
                        ("lts.opentelekomcloud.com", "v1beta1", "logconfigs"),
                    ]
                    
                    for group, version, plural in cr_combinations:
                        tried_combinations.append(f"{group}/{version}/{plural}")
                        try:
                            if namespace:
                                api_result = custom_api.list_namespaced_custom_object(
                                    group=group, version=version, namespace=namespace, plural=plural
                                )
                            else:
                                api_result = custom_api.list_cluster_custom_object(
                                    group=group, version=version, plural=plural
                                )
                            
                            if api_result and 'items' in api_result:
                                for item in api_result['items']:
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
                                    break
                        except Exception:
                            continue
                    
                    # 清理临时文件
                    for f in temp_files:
                        try:
                            os.unlink(f)
                        except:
                            pass
                    
                    result = {
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
                result = {"success": False, "error": str(e), "error_type": type(e).__name__}



    elif action == "huawei_query_aom_logs":
        # 查询AOM应用日志
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        namespace = params.get("namespace")
        pod_name = params.get("pod_name")
        container_name = params.get("container_name")
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        keywords = params.get("keywords")
        query_limit = int(params.get("limit", 100))
        from lts_tools import query_aom_logs
        result = query_aom_logs(region, cluster_id, namespace, pod_name, container_name, start_time, end_time, keywords, query_limit, ak, sk, project_id)

    elif action == "huawei_get_recent_logs":
        # 获取最近的日志
        if not region:
            print(json.dumps({"success": False, "error": "region is required"}))
            sys.exit(1)
        log_group_id = params.get("log_group_id")
        log_stream_id = params.get("log_stream_id")
        if not log_group_id or not log_stream_id:
            print(json.dumps({"success": False, "error": "log_group_id and log_stream_id are required"}))
            sys.exit(1)
        hours = int(params.get("hours", 1))
        query_limit = int(params.get("limit", 1000))
        labels = params.get("labels")
        if labels and isinstance(labels, str):
            # 解析JSON格式的labels
            try:
                labels = json.loads(labels)
            except:
                print(json.dumps({"success": False, "error": "labels参数格式错误，必须是JSON格式的字典，例如 '{\"appName\": \"test\", \"namespace\": \"default\"}'"}))
                sys.exit(1)
        from lts_tools import get_recent_logs
        result = get_recent_logs(region, log_group_id, log_stream_id, hours, query_limit, labels=labels, ak=ak, sk=sk, project_id=project_id)

    elif action == "huawei_query_application_logs":
        # ✨ 查询CCE集群应用自定义时间范围日志：自动匹配日志流+自动携带appName/nameSpace标签过滤
        if not region:
            print(json.dumps({"success": False, "error": "region为必填参数"}))
            sys.exit(1)
        cluster_id = params.get("cluster_id")
        app_name = params.get("app_name")
        if not cluster_id or not app_name:
            print(json.dumps({"success": False, "error": "cluster_id和app_name为必填参数"}))
            sys.exit(1)
        namespace = params.get("namespace", "default")
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        query_limit = int(params.get("limit", 1000))
        keywords = params.get("keywords")
        labels = params.get("labels")
        if labels and isinstance(labels, str):
            # 解析JSON格式的自定义标签
            try:
                labels = json.loads(labels)
            except:
                print(json.dumps({"success": False, "error": "labels参数格式错误，必须是JSON格式的字典，例如 '{\"app\": \"test\", \"env\": \"prod\"}'"}))
                sys.exit(1)
        
        # 第一步：调用现有工具获取应用对应的日志组和日志流
        from lts_tools import get_application_log_stream
        stream_result = get_application_log_stream(
            region=region,
            cluster_id=cluster_id,
            app_name=app_name,
            namespace=namespace,
            ak=ak, sk=sk, project_id=project_id
        )
        if not stream_result.get("success"):
            print(json.dumps(stream_result, indent=2, ensure_ascii=False))
            sys.exit(1)
        
        log_group_id = stream_result.get("log_group_id")
        log_stream_id = stream_result.get("log_stream_id")
        if not log_group_id or not log_stream_id:
            print(json.dumps({
                "success": False,
                "error": "未找到应用对应的日志组/日志流",
                "cluster_id": cluster_id,
                "namespace": namespace,
                "app_name": app_name
            }, indent=2, ensure_ascii=False))
            sys.exit(1)
        
        # 第二步：自动添加系统标签（appName和nameSpace），合并用户自定义标签
        labels = {
            "appName": app_name,
            "nameSpace": namespace
        }
        
        # 第三步：调用LTS自定义时间范围查询日志，自动携带appName和nameSpace标签过滤
        from lts_tools import query_logs
        # 直接构造华为云LTS要求的字符串格式标签，避免格式转换问题
        result = query_logs(
            region=region,
            log_group_id=log_group_id,
            log_stream_id=log_stream_id,
            start_time=start_time,
            end_time=end_time,
            keywords=keywords, # 保留用户原始传入的keywords，不做修改
            limit=query_limit,
            labels=labels, # 传入字符串格式标签
            ak=ak, sk=sk, project_id=project_id
        )
        
        # 补充应用上下文信息到结果
        result["cluster_id"] = cluster_id
        result["namespace"] = namespace
        result["app_name"] = app_name
        result["auto_label_filter"] = auto_labels
        result["custom_labels"] = labels
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif action == "huawei_get_application_log_stream":
        # ✨ 获取应用对应的日志组/日志流ID（直接调用lts_tools核心匹配逻辑）
        if not region:
            print(json.dumps({"success": False, "error": "region为必填参数"}))
            sys.exit(1)
        cluster_id = params.get("cluster_id")
        app_name = params.get("app_name")
        if not cluster_id or not app_name:
            print(json.dumps({"success": False, "error": "cluster_id和app_name为必填参数"}))
            sys.exit(1)
        namespace = params.get("namespace", "default")
        
        # 直接调用lts_tools中的核心匹配函数
        from lts_tools import get_application_log_stream
        result = get_application_log_stream(
            region=region,
            cluster_id=cluster_id,
            app_name=app_name,
            namespace=namespace,
            ak=ak, sk=sk, project_id=project_id
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    elif action == "huawei_query_application_recent_logs":
        # ✨ 一站式查询集群应用最近日志：自动匹配日志流+自动携带appName/nameSpace标签过滤
        if not region:
            print(json.dumps({"success": False, "error": "region为必填参数"}))
            sys.exit(1)
        cluster_id = params.get("cluster_id")
        app_name = params.get("app_name")
        if not cluster_id or not app_name:
            print(json.dumps({"success": False, "error": "cluster_id和app_name为必填参数"}))
            sys.exit(1)
        namespace = params.get("namespace", "default")
        hours = int(params.get("hours", 1))
        query_limit = int(params.get("limit", 1000))
        keywords = params.get("keywords")
        
        # 第一步：调用现有工具获取应用对应的日志组和日志流
        from lts_tools import get_application_log_stream
        stream_result = get_application_log_stream(
            region=region,
            cluster_id=cluster_id,
            app_name=app_name,
            namespace=namespace,
            ak=ak, sk=sk, project_id=project_id
        )
        if not stream_result.get("success"):
            print(json.dumps(stream_result, indent=2, ensure_ascii=False))
            sys.exit(1)
        
        log_group_id = stream_result.get("log_group_id")
        log_stream_id = stream_result.get("log_stream_id")
        if not log_group_id or not log_stream_id:
            print(json.dumps({
                "success": False,
                "error": "未找到应用对应的日志组/日志流",
                "cluster_id": cluster_id,
                "namespace": namespace,
                "app_name": app_name
            }, indent=2, ensure_ascii=False))
            sys.exit(1)
        
        # 第二步：自动构造标签过滤参数（appName和nameSpace）
        labels = {
            "appName": app_name,
            "nameSpace": namespace
        }
        
        # 第三步：调用LTS查询最近日志，自动携带appName和nameSpace标签过滤
        from lts_tools import get_recent_logs
        # 直接构造华为云LTS要求的字符串格式标签，避免格式转换问题
        #labels_str = f"appName={app_name},nameSpace={namespace}"
        result = get_recent_logs(
            region=region,
            log_group_id=log_group_id,
            log_stream_id=log_stream_id,
            hours=hours,
            limit=query_limit,
            keywords=keywords, # 保留用户原始传入的keywords，不做修改
            labels=labels, # 传入字符串格式标签
            ak=ak, sk=sk, project_id=project_id
        )
        
        # 补充应用上下文信息到结果
        result["cluster_id"] = cluster_id
        result["namespace"] = namespace
        result["app_name"] = app_name
        result["auto_label_filter"] = labels
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif action == "huawei_list_cce_daemonsets":
        # ✨ 查询CCE集群内所有DaemonSet守护进程集信息
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region和cluster_id为必填参数"}))
            sys.exit(1)
        namespace = params.get("namespace")
        
        # 检查依赖
        try:
            import kubernetes
            from kubernetes import client
        except ImportError as e:
            print(json.dumps({"success": False, "error": f"Kubernetes SDK未安装: {str(e)}"}))
            sys.exit(1)
        
        # 重新获取凭证确保不为空
        ak, sk, project_id = get_credentials(ak, sk, project_id)
        if not ak or not sk:
            print(json.dumps({"success": False, "error": "AK/SK未配置，请通过环境变量或参数传入"}))
            sys.exit(1)
        
        import base64
        import tempfile
        import os
        
        temp_files = []
        try:
            # 1. 获取集群kubeconfig
            from huaweicloudsdkcce.v3 import CceClient
            from huaweicloudsdkcce.v3.region.cce_region import CceRegion
            from huaweicloudsdkcce.v3.model.create_kubernetes_cluster_cert_request import CreateKubernetesClusterCertRequest
            from huaweicloudsdkcce.v3.model.cluster_cert_duration import ClusterCertDuration
            
            # 创建CCE客户端
            credentials = BasicCredentials(ak, sk, project_id)
            cce_client = CceClient.new_builder() \
                .with_credentials(credentials) \
                .with_region(getattr(CceRegion, region.upper().replace("-", "_"))) \
                .build()
            
            # 获取集群证书
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
                print(json.dumps({"success": False, "error": "无法获取集群API端点"}))
                sys.exit(1)
            
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
            
            # 初始化客户端
            kubernetes.client.Configuration.set_default(configuration)
            apps_v1_api = client.AppsV1Api()
            
            # 查询DaemonSet
            daemonsets = []
            if namespace:
                resp = apps_v1_api.list_namespaced_daemon_set(namespace=namespace)
            else:
                resp = apps_v1_api.list_daemon_set_for_all_namespaces()
            
            for ds in resp.items:
                ds_info = {
                    "name": ds.metadata.name,
                    "namespace": ds.metadata.namespace,
                    "desired_replicas": ds.status.desired_number_scheduled,
                    "current_replicas": ds.status.current_number_scheduled,
                    "ready_replicas": ds.status.number_ready,
                    "available_replicas": ds.status.number_available,
                    "updated_replicas": ds.status.updated_number_scheduled,
                    "age": str((datetime.now() - ds.metadata.creation_timestamp.replace(tzinfo=None))).split('.')[0],
                    "images": [c.image for c in ds.spec.template.spec.containers]
                }
                daemonsets.append(ds_info)
            
            # 清理临时文件
            for f in temp_files:
                try:
                    os.unlink(f)
                except:
                    pass
            
            print(json.dumps({
                "success": True,
                "region": region,
                "cluster_id": cluster_id,
                "count": len(daemonsets),
                "daemonsets": daemonsets
            }, indent=2, ensure_ascii=False))
            sys.exit(0)
            
        except Exception as e:
            # 清理临时文件
            for f in temp_files:
                try:
                    os.unlink(f)
                except:
                    pass
            print(json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }, indent=2, ensure_ascii=False))
            sys.exit(0)

    elif action == "huawei_network_diagnose":
        # 网络问题诊断 - 按工作负载
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        workload_name = params.get("workload_name")
        namespace = params.get("namespace", "default")
        from network_diagnosis import network_diagnose
        result = network_diagnose(region, cluster_id, workload_name, namespace, ak, sk, project_id)

    elif action == "huawei_network_diagnose_by_alarm":
        # 网络问题诊断 - 按告警触发
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        alarm_info = params.get("alarm_info")
        if not alarm_info:
            print(json.dumps({"success": False, "error": "alarm_info is required"}))
            sys.exit(1)
        from network_diagnosis import network_diagnose_by_alarm
        result = network_diagnose_by_alarm(region, cluster_id, alarm_info, ak, sk, project_id)

    elif action == "huawei_network_scale_workload":
        # 扩缩容工作负载
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        workload_name = params.get("workload_name")
        if not workload_name:
            print(json.dumps({"success": False, "error": "workload_name is required"}))
            sys.exit(1)
        namespace = params.get("namespace", "default")
        replica_count = int(params.get("replica_count", 3))
        confirm = params.get("confirm", "false").lower() == "true"
        from network_diagnosis import scale_workload
        result = scale_workload(region, cluster_id, workload_name, namespace, replica_count, ak, sk, project_id, confirm)

    elif action == "huawei_network_verify_pod_scheduling":
        # 扩缩容后验证Pod调度状态
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        workload_name = params.get("workload_name")
        if not workload_name:
            print(json.dumps({"success": False, "error": "workload_name is required"}))
            sys.exit(1)
        namespace = params.get("namespace", "default")
        from network_diagnosis import verify_pod_scheduling_after_scale
        result = verify_pod_scheduling_after_scale(region, cluster_id, workload_name, namespace, ak, sk, project_id)

    elif action == "huawei_node_batch_diagnose":
        # 批量节点诊断
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        node_ips_str = params.get("node_ips")
        node_ips = [ip.strip() for ip in node_ips_str.split(",")] if node_ips_str else None
        from node_diagnosis import batch_node_diagnose
        result = batch_node_diagnose(region, cluster_id, node_ips, ak, sk, project_id)

    elif action == "huawei_node_diagnose":
        # 单个节点诊断
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        
        node_ip = params.get("node_ip")
        node_name = params.get("node_name")
        
        # 如果提供了 node_name 但没有 node_ip，尝试识别它是CCE节点名还是IP
        if not node_ip and node_name:
            access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
            
            # 策略1: 如果 node_name 看起来像 IP，直接使用
            if '.' in node_name and all(part.isdigit() for part in node_name.split('.') if part):
                node_ip = node_name
            
            # 策略2: 尝试精确匹配 Kubernetes 节点名（Kubernetes节点名就是IP）
            if not node_ip:
                k8s_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
                if k8s_result.get("success"):
                    for node in k8s_result.get("nodes", []):
                        if node_name == node.get("name", "") or node_name == node.get("internal_ip", ""):
                            node_ip = node.get("internal_ip", "")
                            break
            
            # 策略3: 如果提供了完整的CCE节点名，尝试使用节点监控数据映射
            if not node_ip:
                # 获取节点监控数据（包含节点IP）
                node_metrics_result = get_cce_node_metrics(region, cluster_id, access_key, secret_key, proj_id, top_n=20, hours=1)
                
                # CCE节点名格式: test-cce-ai-diagnose-nodepool-{ID}-{RANDOM}
                # 提取 nodepool ID用于匹配
                import re
                nodepool_match = re.search(r'nodepool[-\s]?(\d+)', node_name, re.IGNORECASE)
                nodepool_id = nodepool_match.group(1) if nodepool_match else None
                
                # CCE节点名末尾的随机字符串
                name_parts = node_name.split('-')
                node_suffix = name_parts[-1] if name_parts else ""  # e.g., "kv4ph"
                
                if node_metrics_result.get("success"):
                    # 由于无法直接通过CCE节点名获取IP，这里列出可用的映射
                    k8s_result = k8s_result if k8s_result.get("success") else get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
                    
                    # 构建可用的 CCE 节点名 → K8s节点/IP 的映射
                    # 由于CCE API不直接返回IP，我们通过节点监控推断
                    cce_nodes = []
                    
                    # 同时获取CCE节点列表辅助
                    if k8s_result.get("success"):
                        # 构建提示信息，包含已知的所有映射
                        print(json.dumps({
                            "success": False,
                            "error": f"Cannot automatically convert CCE node name '{node_name}' to IP.",
                            "note": "CCE node names cannot be automatically resolved to IPs via API.",
                            "hint": "Use node_ip parameter instead. Available mappings:",
                            "hint2": "CCE nodepool ID can help identify nodes in the same pool",
                            "cce_nodes_with_nodepool": [
                                {"cce_name": f"test-cce-ai-diagnose-nodepool-48668-xxxx", "nodepool": "48668", "sample_ip": "192.168.32.248"},
                                {"cce_name": f"test-cce-ai-diagnose-nodepool-43986-xxxx", "nodepool": "43986", "sample_ip": "未知"},
                            ] if not k8s_result.get("success") else [
                                {"cce_name_pattern": "nodepool-48668-*", "sample_ip": "192.168.32.248"},
                                {"cce_name_pattern": "nodepool-43986-*", "sample_ip": "使用kubectl get nodes查看"},
                            ],
                            "available_k8s_ips": [n.get("internal_ip") for n in k8s_result.get("nodes", [])] if k8s_result.get("success") else [],
                            "try_directly": f"If you know the IP, use: node_ip=192.168.32.XXX"
                        }))
                        sys.exit(1)
            
            # 如果仍然找不到，返回友好的错误提示
            if not node_ip:
                k8s_result = get_kubernetes_nodes(region, cluster_id, access_key, secret_key, proj_id)
                print(json.dumps({
                    "success": False, 
                    "error": f"Cannot find node '{node_name}'. kubernetes node names in CCE are IP addresses.",
                    "hint": "Try using node_ip parameter, such as:",
                    "available_ips": [n.get("internal_ip", "") for n in k8s_result.get("nodes", [])] if k8s_result.get("success") else [],
                    "example": "huawei_node_diagnose region=cn-north-4 cluster_id=xxx node_ip=192.168.32.248"
                }))
                sys.exit(1)
        
        if not node_ip:
            print(json.dumps({"success": False, "error": "node_ip or node_name is required"}))
            sys.exit(1)
        
        from node_diagnosis import diagnose_single_node, get_aom_instance, get_cluster_name
        aom_instance_id = get_aom_instance(region, ak, sk, project_id)
        cluster_name = get_cluster_name(region, cluster_id, ak, sk, project_id)
        result = diagnose_single_node(node_ip, region, cluster_id, ak, sk, project_id, aom_instance_id, cluster_name)

    elif action == "huawei_list_abnormal_nodes":
        # 获取异常节点列表
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        from node_diagnosis import get_abnormal_nodes
        access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)
        result = get_abnormal_nodes(region, cluster_id, access_key, secret_key, proj_id)

    else:
        result = {
            "success": False,
            "error": f"Unknown action: {action}"
        }

    print(json.dumps(result, indent=2, ensure_ascii=False))


def list_cce_configmaps(region: str, cluster_id: str, namespace: Optional[str] = None, limit: int = 100, offset: int = 0, include_data: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List ConfigMaps in a CCE cluster
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        namespace: Kubernetes namespace (optional, default: all namespaces)
        limit: Number of results to return (default: 100)
        offset: Pagination offset (default: 0)
        include_data: Whether to include ConfigMap data content (default: False, only return keys)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with configmaps list
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_configmaps_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_configmaps_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration
        k8s_client.Configuration.set_default(configuration)

        # List configmaps
        core_v1 = k8s_client.CoreV1Api()
        if namespace:
            configmaps = core_v1.list_namespaced_config_map(namespace, limit=limit)
        else:
            configmaps = core_v1.list_config_map_for_all_namespaces(limit=limit)

        configmap_list = []
        for cm in configmaps.items:
            cm_info = {
                "name": cm.metadata.name,
                "namespace": cm.metadata.namespace,
                "created": str(cm.metadata.creation_timestamp) if cm.metadata.creation_timestamp else None,
                "labels": cm.metadata.labels,
                "annotations": cm.metadata.annotations,
                "data_keys": list(cm.data.keys()) if cm.data else []
            }
            if include_data and cm.data:
                cm_info["data"] = cm.data
            configmap_list.append(cm_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "list_cce_configmaps",
            "namespace": namespace or "all",
            "count": len(configmap_list),
            "configmaps": configmap_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_cce_secrets(region: str, cluster_id: str, namespace: Optional[str] = None, limit: int = 100, include_data: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """List Secrets in a CCE Kubernetes cluster
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        namespace: Kubernetes namespace (optional, default: all namespaces)
        limit: Number of results to return (default: 100)
        include_data: Whether to include Secret data content (default: False, only return keys)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)

    Returns:
        Dictionary with secrets list
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not cluster_id:
        return {
            "success": False,
            "error": "cluster_id is required"
        }

    try:
        # Get cluster credentials
        cce_client = create_cce_client(region, access_key, secret_key, proj_id)

        cert_request = CreateKubernetesClusterCertRequest()
        cert_request.cluster_id = cluster_id
        body = ClusterCertDuration()
        body.duration = 1
        cert_request.body = body

        cert_response = cce_client.create_kubernetes_cluster_cert(cert_request)
        kubeconfig_data = cert_response.to_dict()

        # Find external cluster endpoint
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

        # Configure Kubernetes client
        configuration = k8s_client.Configuration()
        configuration.host = external_cluster.get('cluster', {}).get('server')
        configuration.verify_ssl = False

        # Write certificates
        user_data = None
        for u in kubeconfig_data.get('users', []):
            if u.get('name') == 'user':
                user_data = u.get('user', {})
                break

        if user_data and user_data.get('client_certificate_data'):
            cert_file = '/tmp/cce_secrets_client.crt'
            with open(cert_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_certificate_data']))
            configuration.cert_file = cert_file

        if user_data and user_data.get('client_key_data'):
            key_file = '/tmp/cce_secrets_client.key'
            with open(key_file, 'wb') as f:
                f.write(base64.b64decode(user_data['client_key_data']))
            configuration.key_file = key_file

        # 注册临时证书文件以便后续清理
        _register_cert_file(cert_file)
        _register_cert_file(key_file)

        # Set default configuration
        k8s_client.Configuration.set_default(configuration)

        # List secrets
        core_v1 = k8s_client.CoreV1Api()
        if namespace:
            secrets = core_v1.list_namespaced_secret(namespace, limit=limit)
        else:
            secrets = core_v1.list_secret_for_all_namespaces(limit=limit)

        secret_list = []
        for secret in secrets.items:
            secret_info = {
                "name": secret.metadata.name,
                "namespace": secret.metadata.namespace,
                "type": secret.type,
                "created": str(secret.metadata.creation_timestamp) if secret.metadata.creation_timestamp else None,
                "labels": secret.metadata.labels,
                "annotations": secret.metadata.annotations,
                "data_keys": list(secret.data.keys()) if secret.data else []
            }
            if include_data and secret.data:
                secret_info["data"] = secret.data
            secret_list.append(secret_info)

        # 清理临时证书文件
        _safe_delete_file(cert_file)
        _safe_delete_file(key_file)
        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "action": "list_cce_secrets",
            "namespace": namespace or "all",
            "count": len(secret_list),
            "secrets": secret_list
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_sfs_turbo(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List SFS Turbo file systems in the specified region
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        limit: Number of results to return (default: 100)
        offset: Pagination offset (default: 0)

    Returns:
        Dictionary with SFS Turbo file systems list
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # 基于官方SDK实现：https://github.com/huaweicloud/huaweicloud-sdk-python-v3/tree/master/huaweicloud-sdk-sfsturbo
        from huaweicloudsdksfsturbo.v1 import SFSTurboClient
        from huaweicloudsdksfsturbo.v1.model.list_shares_request import ListSharesRequest
        from huaweicloudsdksfsturbo.v1.region.sfsturbo_region import SFSTurboRegion

        # 初始化SFS Turbo客户端（注意SDK中类名是全大写的SFSTurboClient和SFSTurboRegion）
        client = SFSTurboClient.new_builder() \
            .with_credentials(BasicCredentials(access_key, secret_key, proj_id)) \
            .with_region(SFSTurboRegion.value_of(region)) \
            .build()

        # 构造请求
        request = ListSharesRequest()
        request.limit = limit
        request.offset = offset

        # 发送请求
        response = client.list_shares(request)

        # 处理响应
        turbos = []
        if hasattr(response, 'shares') and response.shares:
            for turbo in response.shares:
                turbo_info = {
                    "id": getattr(turbo, 'id', None),
                    "name": getattr(turbo, 'name', None),
                    "status": getattr(turbo, 'status', None),
                    "size": getattr(turbo, 'size', None),  # 总容量(GB)
                    "used_size": getattr(turbo, 'used_size', None),  # 已用容量(GB)
                    "share_proto": getattr(turbo, 'share_proto', None),  # 协议：NFS/CIFS
                    "share_type": getattr(turbo, 'share_type', None),  # 类型：STANDARD(标准型)/PERFORMANCE(性能型)
                    "availability_zone": getattr(turbo, 'availability_zone', None),
                    "vpc_id": getattr(turbo, 'vpc_id', None),
                    "subnet_id": getattr(turbo, 'subnet_id', None),
                    "security_group_id": getattr(turbo, 'security_group_id', None),
                    "export_location": getattr(turbo, 'export_location', None),  # 挂载地址
                    "created_at": str(getattr(turbo, 'created_at', None)) if getattr(turbo, 'created_at', None) else None,
                    "description": getattr(turbo, 'description', None)
                }
                turbos.append(turbo_info)

        return {
            "success": True,
            "region": region,
            "action": "list_sfs_turbo",
            "count": len(turbos),
            "sfsturbos": turbos
        }

    except ImportError as e:
        return {
            "success": False,
            "error": f"SFS Turbo SDK import error: {str(e)}",
            "hint": "请从GitHub源码安装：\n"
                    "git clone https://github.com/huaweicloud/huaweicloud-sdk-python-v3.git\n"
                    "cd huaweicloud-sdk-python-v3/huaweicloud-sdk-sfsturbo\n"
                    "pip3 install ."
        }
    except ClientRequestException as e:
        return {
            "success": False,
            "error": f"{e.error_code} - {e.error_msg}",
            "request_id": getattr(e, 'request_id', None)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_sfs(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """List SFS (Scalable File Service) file systems in the specified region
    基于官方API实现：OpenStack Manila API (v2)
    使用HTTP直接调用，AK/SK签名参考huawei_get_aom_metrics
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        limit: Number of results to return (default: 100)
        offset: Pagination offset (default: 0)

    Returns:
        Dictionary with SFS file systems list
    """
    import hashlib
    import hmac
    import time as time_module
    import urllib.parse
    from urllib.parse import quote, unquote
    import requests
    
    # 获取凭证（包括project_id）
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key or not proj_id:
        return {
            "success": False,
            "error": "Credentials and project_id are required"
        }

    try:
        now = int(time_module.time())
        
        # ========== 构建URL和查询参数 ==========
        base_url = f"https://sfs.{region}.myhuaweicloud.com"
        resource_path = f"/v2/{proj_id}/shares"
        
        # 查询参数
        query_params = [
            ('limit', str(limit)),
            ('offset', str(offset))
        ]
        
        # ========== 按SDK方式构建签名 ==========
        timestamp = time_module.strftime('%Y%m%dT%H%M%SZ', time_module.gmtime(now))
        
        # 1. HTTP方法
        http_method = 'GET'
        
        # 2. Canonical URI
        def url_encode(s):
            return quote(s, safe='~')
        
        pattens = unquote(resource_path).split('/')
        uri_parts = []
        for v in pattens:
            uri_parts.append(url_encode(v))
        canonical_uri = "/".join(uri_parts)
        if canonical_uri[-1] != '/':
            canonical_uri = canonical_uri + "/"
        
        # 3. Canonical Query String (排序)
        sorted_params = sorted(query_params, key=lambda x: x[0])
        canonical_querystring = '&'.join(['{}={}'.format(url_encode(k), url_encode(str(v))) for k, v in sorted_params])
        
        # 4. Headers
        host_header = f"sfs.{region}.myhuaweicloud.com"
        
        # 签名的headers（按字母顺序）
        signed_headers_list = ['host', 'x-project-id', 'x-sdk-date']
        signed_headers = ';'.join(signed_headers_list)
        
        # Canonical headers (每个header一行，最后有\n)
        canonical_headers = 'host:{}\nx-project-id:{}\nx-sdk-date:{}\n'.format(
            host_header, proj_id, timestamp)
        
        # 5. 空body的hash
        hashed_body = hashlib.sha256(b'').hexdigest()
        
        # 6. 构建Canonical Request
        canonical_request = '{}\n{}\n{}\n{}\n{}\n{}'.format(
            http_method, canonical_uri, canonical_querystring,
            canonical_headers, signed_headers, hashed_body)
        
        # 7. StringToSign (SDK格式：只有3行)
        algorithm = 'SDK-HMAC-SHA256'
        hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = '{}\n{}\n{}'.format(algorithm, timestamp, hashed_canonical_request)
        
        # 8. 签名 - 使用hex编码
        signature = hmac.new(
            secret_key.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).digest().hex()
        
        # 9. Authorization
        authorization = '{} Access={}, SignedHeaders={}, Signature={}'.format(
            algorithm, access_key, signed_headers, signature)
        
        # 10. 构建请求URL
        url_query_string = '&'.join(['{}={}'.format(k, urllib.parse.quote(str(v))) for k, v in query_params])
        url = "{}{}?{}".format(base_url, resource_path, url_query_string)
        
        # 11. 请求headers
        headers = {
            'Host': host_header,
            'X-Project-Id': proj_id,
            'X-Sdk-Date': timestamp,
            'Authorization': authorization,
        }
        
        # 发送请求
        resp = requests.get(url, headers=headers, verify=False, timeout=30)
        
        if resp.status_code == 200:
            data = resp.json()
            sfs_list = []
            if "shares" in data:
                for sfs in data["shares"]:
                    sfs_info = {
                        "id": sfs.get("id"),
                        "name": sfs.get("name"),
                        "status": sfs.get("status"),
                        "size": sfs.get("size"),  # 总容量(GB)
                        "used_size": sfs.get("used_size"),  # 已用容量(GB)
                        "share_proto": sfs.get("share_proto"),  # 协议类型：NFS/CIFS
                        "availability_zone": sfs.get("availability_zone"),
                        "vpc_id": sfs.get("vpc_id"),
                        "export_location": sfs.get("export_location"),  # 挂载地址
                        "created_at": sfs.get("created_at"),
                        "description": sfs.get("description"),
                        "is_public": sfs.get("is_public"),
                        "share_type": sfs.get("share_type")  # 文件系统类型
                    }
                    sfs_list.append(sfs_info)
            
            return {
                "success": True,
                "region": region,
                "action": "list_sfs",
                "count": len(sfs_list),
                "sfs": sfs_list
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
                "url": url,
                "request_headers": {k: v for k, v in headers.items() if k != 'Authorization'}
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def list_nat_gateways(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, limit: int = 100, offset: int = 0, id: str = None, name: str = None, description: str = None, spec: str = None, router_id: str = None, internal_network_id: str = None, status: str = None, admin_state_up: bool = None, created_at: str = None) -> Dict[str, Any]:
    """List NAT gateways in the specified region
    基于官方API实现：https://support.huaweicloud.com/api-natgateway/nat_api_0002.html
    使用HTTP直接调用，AK/SK签名参考huawei_get_aom_metrics
    
    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional if HUAWEI_AK env is set)
        sk: Secret Access Key (optional if HUAWEI_SK env is set)
        project_id: Project ID (optional if HUAWEI_PROJECT_ID env is set)
        limit: Number of results to return (default: 100)
        offset: Offset for pagination (default: 0)
        id: NAT gateway ID (optional filter)
        name: NAT gateway name (optional filter)
        description: NAT gateway description (optional filter)
        spec: NAT gateway specification (optional filter: 1=small, 2=medium, 3=large, 4=extra-large)
        router_id: Router ID (optional filter)
        internal_network_id: Internal network ID (optional filter)
        status: NAT gateway status (optional filter)
        admin_state_up: Admin state up (optional filter)
        created_at: Creation time (optional filter)

    Returns:
        Dictionary with NAT gateways list
    """
    import hashlib
    import hmac
    import time as time_module
    import urllib.parse
    from urllib.parse import quote, unquote
    import requests
    
    # 获取凭证（包括project_id）
    access_key, secret_key, proj_id = get_credentials_with_region(region, ak, sk, project_id)

    if not access_key or not secret_key or not proj_id:
        return {
            "success": False,
            "error": "Credentials and project_id are required"
        }

    try:
        now = int(time_module.time())
        
        # ========== 构建URL和查询参数 ==========
        base_url = f"https://nat.{region}.myhuaweicloud.com"
        resource_path = f"/v2.0/nat_gateways"
        
        # 查询参数
        query_params = []
        if limit:
            query_params.append(('limit', str(limit)))
        if offset:
            query_params.append(('offset', str(offset)))
        if id:
            query_params.append(('id', id))
        if name:
            query_params.append(('name', name))
        if description:
            query_params.append(('description', description))
        if spec:
            query_params.append(('spec', spec))
        if router_id:
            query_params.append(('router_id', router_id))
        if internal_network_id:
            query_params.append(('internal_network_id', internal_network_id))
        if status:
            query_params.append(('status', status))
        if admin_state_up is not None:
            query_params.append(('admin_state_up', str(admin_state_up).lower()))
        if created_at:
            query_params.append(('created_at', created_at))
        
        # ========== 按SDK方式构建签名 ==========
        timestamp = time_module.strftime('%Y%m%dT%H%M%SZ', time_module.gmtime(now))
        
        # 1. HTTP方法
        http_method = 'GET'
        
        # 2. Canonical URI
        def url_encode(s):
            return quote(s, safe='~')
        
        pattens = unquote(resource_path).split('/')
        uri_parts = []
        for v in pattens:
            uri_parts.append(url_encode(v))
        canonical_uri = "/".join(uri_parts)
        if canonical_uri[-1] != '/':
            canonical_uri = canonical_uri + "/"
        
        # 3. Canonical Query String (排序)
        sorted_params = sorted(query_params, key=lambda x: x[0])
        canonical_querystring = '&'.join(['{}={}'.format(url_encode(k), url_encode(str(v))) for k, v in sorted_params])
        
        # 4. Headers
        host_header = f"nat.{region}.myhuaweicloud.com"
        
        # 签名的headers（按字母顺序）
        signed_headers_list = ['host', 'x-project-id', 'x-sdk-date']
        signed_headers = ';'.join(signed_headers_list)
        
        # Canonical headers (每个header一行，最后有\n)
        canonical_headers = 'host:{}\nx-project-id:{}\nx-sdk-date:{}\n'.format(
            host_header, proj_id, timestamp)
        
        # 5. 空body的hash
        hashed_body = hashlib.sha256(b'').hexdigest()
        
        # 6. 构建Canonical Request
        canonical_request = '{}\n{}\n{}\n{}\n{}\n{}'.format(
            http_method, canonical_uri, canonical_querystring,
            canonical_headers, signed_headers, hashed_body)
        
        # 7. StringToSign (SDK格式：只有3行)
        algorithm = 'SDK-HMAC-SHA256'
        hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = '{}\n{}\n{}'.format(algorithm, timestamp, hashed_canonical_request)
        
        # 8. 签名 - 使用hex编码
        signature = hmac.new(
            secret_key.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).digest().hex()
        
        # 9. Authorization
        authorization = '{} Access={}, SignedHeaders={}, Signature={}'.format(
            algorithm, access_key, signed_headers, signature)
        
        # 10. 构建请求URL
        url_query_string = '&'.join(['{}={}'.format(k, urllib.parse.quote(str(v))) for k, v in query_params]) if query_params else ""
        url = "{}{}".format(base_url, resource_path)
        if url_query_string:
            url += "?{}".format(url_query_string)
        
        # 11. 请求headers
        headers = {
            'Host': host_header,
            'X-Project-Id': proj_id,
            'X-Sdk-Date': timestamp,
            'Authorization': authorization,
        }
        
        # 发送请求
        resp = requests.get(url, headers=headers, verify=False, timeout=30)
        
        if resp.status_code == 200:
            data = resp.json()
            nat_list = []
            if "nat_gateways" in data:
                for nat in data["nat_gateways"]:
                    nat_info = {
                        "id": nat.get("id"),
                        "tenant_id": nat.get("tenant_id"),
                        "name": nat.get("name"),
                        "description": nat.get("description"),
                        "spec": nat.get("spec"),
                        "router_id": nat.get("router_id"),
                        "internal_network_id": nat.get("internal_network_id"),
                        "status": nat.get("status"),
                        "admin_state_up": nat.get("admin_state_up"),
                        "created_at": nat.get("created_at"),
                    }
                    nat_list.append(nat_info)
            
            return {
                "success": True,
                "region": region,
                "action": "list_nat_gateways",
                "count": len(nat_list),
                "nat_gateways": nat_list
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
                "url": url,
                "request_headers": {k: v for k, v in headers.items() if k != 'Authorization'}
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


if __name__ == "__main__":
    main()
