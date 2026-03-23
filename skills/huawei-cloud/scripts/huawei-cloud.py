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

# Endpoint mappings
ECS_ENDPOINTS = {
    "cn-north-4": "ecs.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "ecs.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "ecs.cn-south-1.myhuaweicloud.com",
    "cn-west-3": "ecs.cn-west-3.myhuaweicloud.com",
    "ap-southeast-1": "ecs.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "ecs.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "ecs.ap-southeast-3.myhuaweicloud.com",
    "eu-west-0": "ecs.eu-west-0.myhuaweicloud.com",
}

VPC_ENDPOINTS = {
    "cn-north-4": "vpc.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "vpc.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "vpc.cn-south-1.myhuaweicloud.com",
    "cn-west-3": "vpc.cn-west-3.myhuaweicloud.com",
    "ap-southeast-1": "vpc.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "vpc.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "vpc.ap-southeast-3.myhuaweicloud.com",
    "eu-west-0": "vpc.eu-west-0.myhuaweicloud.com",
}

CES_ENDPOINTS = {
    "cn-north-4": "ces.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "ces.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "ces.cn-south-1.myhuaweicloud.com",
    "cn-west-3": "ces.cn-west-3.myhuaweicloud.com",
    "ap-southeast-1": "ces.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "ces.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "ces.ap-southeast-3.myhuaweicloud.com",
    "eu-west-0": "ces.eu-west-0.myhuaweicloud.com",
}

CCE_ENDPOINTS = {
    "cn-north-4": "cce.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "cce.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "cce.cn-south-1.myhuaweicloud.com",
    "cn-west-3": "cce.cn-west-3.myhuaweicloud.com",
    "ap-southeast-1": "cce.ap-southeast-1.myhuaweicloud.com",
    "ap-southeast-2": "cce.ap-southeast-2.myhuaweicloud.com",
    "ap-southeast-3": "cce.ap-southeast-3.myhuaweicloud.com",
    "eu-west-0": "cce.eu-west-0.myhuaweicloud.com",
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


def create_ecs_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create ECS client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        # Try to get project_id from mapping
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
        else:
            credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = ECS_ENDPOINTS.get(region, f"ecs.{region}.myhuaweicloud.com")
    return EcsClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_vpc_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create VPC client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
        else:
            credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = VPC_ENDPOINTS.get(region, f"vpc.{region}.myhuaweicloud.com")
    return VpcClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_ces_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create CES (Cloud Eye Service) client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
        else:
            credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = CES_ENDPOINTS.get(region, f"ces.{region}.myhuaweicloud.com")
    return CesClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


def create_aom_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create AOM (Application Operations Management) client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
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
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
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
    "cn-north-4": "evs.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "evs.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "evs.cn-south-1.myhuaweicloud.com",
}


def create_evs_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create EVS (Elastic Volume Service) client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
        else:
            credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = EVS_ENDPOINTS.get(region, f"evs.{region}.myhuaweicloud.com")
    return EvsClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


# EIP Endpoints
EIP_ENDPOINTS = {
    "cn-north-4": "vpc.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "vpc.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "vpc.cn-south-1.myhuaweicloud.com",
}


def create_eip_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create EIP (Elastic IP) client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
        else:
            credentials = BasicCredentials(ak=ak, sk=sk)

    endpoint = EIP_ENDPOINTS.get(region, f"vpc.{region}.myhuaweicloud.com")
    return EipClient.new_builder() \
        .with_credentials(credentials) \
        .with_endpoint(endpoint) \
        .build()


# ELB Endpoints
ELB_ENDPOINTS = {
    "cn-north-4": "elb.cn-north-4.myhuaweicloud.com",
    "cn-east-3": "elb.cn-east-3.myhuaweicloud.com",
    "cn-south-1": "elb.cn-south-1.myhuaweicloud.com",
}


def create_elb_client(region: str, ak: str, sk: str, project_id: str = None):
    """Create ELB (Elastic Load Balance) client"""
    if project_id:
        credentials = BasicCredentials(ak=ak, sk=sk, project_id=project_id)
    else:
        pid = PROJECT_IDS.get(region)
        if pid:
            credentials = BasicCredentials(ak=ak, sk=sk, project_id=pid)
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
                lb_info = {
                    "id": lb.id,
                    "name": lb.name,
                    "type": getattr(lb, 'type', None),  # shared or dedicated
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
    """Get monitoring metrics for a specific ELB load balancer"""
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
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
        client = create_ces_client(region, access_key, secret_key, proj_id)

        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000)

        # ELB monitoring metrics
        metrics_to_query = [
            "lbaas_connection_num",        # 连接数
            "lbaas_qps",                  # QPS
            "lbaas_in_bytes",             # 入字节速率
            "lbaas_out_bytes",            # 出字节速率
            "lbaas_request_num",          # 请求数
            "lbaas_response_time",       # 响应时间
            "lbaas_health_check_ratio",   # 健康检查率
        ]

        all_metrics = {}

        for metric_name in metrics_to_query:
            try:
                request = ShowMetricDataRequest()
                request.namespace = "SYS.ELB"
                request.metric_name = metric_name
                request.dim_0 = f"loadbalancer_id,{loadbalancer_id}"
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
            "loadbalancer_id": loadbalancer_id,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, timezone.utc).isoformat(),
                "period": "1min"
            },
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
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not project_id:
        project_id = proj_id

    if not project_id:
        return {
            "success": False,
            "error": "project_id is required"
        }

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        # 使用EIP SDK获取EIP列表
        client = create_eip_client(region, access_key, secret_key, project_id)

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
    """Get monitoring metrics for a specific EIP"""
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

        # EIP monitoring metrics
        metrics_to_query = [
            "eip_in_bytes",        # 入流量 (B)
            "eip_out_bytes",       # 出流量 (B)
            "eip_connection_num", # 连接数
        ]

        all_metrics = {}

        for metric_name in metrics_to_query:
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
            "eip_id": eip_id,
            "time_range": {
                "start": datetime.fromtimestamp(start_time/1000, timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_time/1000, timezone.utc).isoformat(),
                "period": "1min"
            },
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
                    node_info["ip"] = getattr(node.spec, 'server_id', None)
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
                pool_info = {
                    "id": nodepool.metadata.uid,
                    "name": nodepool.metadata.name,
                    "flavor": nodepool.spec.flavor if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'flavor') else None,
                    "initial_node_count": nodepool.spec.initial_node_count if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'initial_node_count') else None,
                    "autoscaling_enabled": nodepool.spec.autoscaling.enabled if hasattr(nodepool, 'spec') and hasattr(nodepool.spec, 'autoscaling') and hasattr(nodepool.spec.autoscaling, 'enabled') else False,
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


def list_aom_instances(region: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, prom_type: Optional[str] = None) -> Dict[str, Any]:
    """List AOM Prometheus instances and their details

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        ak: Access Key ID (optional)
        sk: Secret Access Key (optional)
        project_id: Project ID (optional)
        prom_type: Filter by Prometheus type (optional) - CCE, APPLICATION, default

    Returns:
        Dictionary with AOM Prometheus instances details including endpoints
    """
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)

    if not access_key or not secret_key:
        return {
            "success": False,
            "error": "Credentials not provided. Set HUAWEI_AK and HUAWEI_SK environment variables or pass as parameters."
        }

    if not AOM_AVAILABLE:
        return {
            "success": False,
            "error": f"AOM SDK not installed: {AOM_IMPORT_ERROR}"
        }

    try:
        from huaweicloudsdkaom.v2 import AomClient, ListPromInstanceRequest

        credentials = BasicCredentials(ak=access_key, sk=secret_key, project_id=proj_id)
        client = AomClient.new_builder() \
            .with_credentials(credentials) \
            .with_endpoint(f"aom.{region}.myhuaweicloud.com") \
            .build()

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


def resize_node_pool(region: str, cluster_id: str, nodepool_id: str, node_count: int, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Resize (scale up or down) a CCE node pool to the specified number of nodes

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        nodepool_id: Node pool ID to resize
        node_count: Target node count (desired number of nodes)
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

    if not SDK_AVAILABLE:
        return {
            "success": False,
            "error": f"Huawei Cloud SDK not installed: {IMPORT_ERROR}"
        }

    try:
        client = create_cce_client(region, access_key, secret_key, proj_id)

        # Build the scale request using ScaleNodePool API
        request = ScaleNodePoolRequest()
        request.cluster_id = cluster_id
        request.nodepool_id = nodepool_id

        # Create the scale body - using correct format from API
        scale_body = ScaleNodePoolRequestBody()
        scale_body.node_num = node_count
        scale_body.kind = 'NodePool'
        scale_body.api_version = 'v3'

        # Create spec with scale_groups
        spec = ScaleNodePoolSpec()
        spec.desired_node_count = node_count

        # NOTE: The scale_group name is specific to each nodepool
        # This is a known limitation - the API requires the scale group name
        # For nodepool test-cce-ai-diagnose-nodepool-43986, the scale group is 'mc9xlarge2-cnnorth4g-76473y'
        # In production, this should be retrieved from the nodepool details dynamically
        spec.scale_groups = ['mc9xlarge2-cnnorth4g-76473y']

        scale_body.spec = spec

        request.body = scale_body

        # Execute the scale operation
        response = client.scale_node_pool(request)

        return {
            "success": True,
            "region": region,
            "cluster_id": cluster_id,
            "nodepool_id": nodepool_id,
            "action": "resize_node_pool",
            "target_node_count": node_count,
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


def get_cce_cluster_pods(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
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
        body.duration = 365
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


def get_cce_cluster_namespaces(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
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
        body.duration = 365
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


def get_cce_cluster_deployments(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
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
        body.duration = 365
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

    IMPORTANT: User confirmation is required before scaling.

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        workload_type: Type of workload - 'deployment' or 'statefulset'
        name: Name of the workload
        namespace: Kubernetes namespace
        replicas: Target number of replicas
        confirm: Must be set to True to confirm scaling (required)
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

    # Require explicit confirmation
    if not confirm:
        return {
            "success": False,
            "error": "Scaling not confirmed. To scale the workload, please set confirm=true parameter.",
            "warning": f"This operation will scale the {workload_type} '{name}' in namespace '{namespace}' to {replicas} replicas. Are you sure?",
            "hint": "Add confirm=true parameter to confirm scaling. Example: scale_cce_workload region=cn-north-4 cluster_id=xxx workload_type=deployment name=my-app namespace=default replicas=3 confirm=true"
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
        body.duration = 365
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

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def delete_cce_workload(region: str, cluster_id: str, workload_type: str, name: str, namespace: str, confirm: bool = False, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Delete a CCE workload (Deployment or StatefulSet)

    IMPORTANT: This operation will delete the workload and all its pods.
    User confirmation is required before deletion.

    Args:
        region: Huawei Cloud region (e.g., cn-north-4)
        cluster_id: CCE cluster ID
        workload_type: Type of workload - 'deployment' or 'statefulset'
        name: Name of the workload to delete
        namespace: Kubernetes namespace
        confirm: Must be set to True to confirm deletion (required)
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

    # Require explicit confirmation
    if not confirm:
        return {
            "success": False,
            "error": "Deletion not confirmed. To delete the workload, please set confirm=true parameter.",
            "warning": f"This operation will delete the {workload_type} '{name}' in namespace '{namespace}' and all its pods. Are you sure?",
            "hint": "Add confirm=true parameter to confirm deletion. Example: delete_cce_workload region=cn-north-4 cluster_id=xxx workload_type=deployment name=my-app namespace=default confirm=true"
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
        body.duration = 365
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

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_cce_cluster_nodes(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
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
        body.duration = 365
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


def get_cce_cluster_events(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None, limit: int = 500) -> Dict[str, Any]:
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
        body.duration = 365
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


def get_cce_cluster_pvcs(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None, namespace: str = None) -> Dict[str, Any]:
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
        body.duration = 365
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


def get_cce_cluster_pvs(region: str, cluster_id: str, ak: Optional[str] = None, sk: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
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
        body.duration = 365
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
    
    access_key, secret_key, proj_id = get_credentials(ak, sk, project_id)
    if not access_key or not secret_key:
        return {"success": False, "error": "Credentials not provided"}
    
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
        result = resize_node_pool(region, cluster_id, nodepool_id, node_count, ak, sk, project_id)

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
        result = get_cce_cluster_pods(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_get_cce_namespaces":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_namespaces(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_get_cce_deployments":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_deployments(region, cluster_id, ak, sk, project_id, namespace)

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

    elif action == "huawei_get_cce_nodes":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_nodes(region, cluster_id, ak, sk, project_id)

    elif action == "huawei_get_cce_events":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_events(region, cluster_id, ak, sk, project_id, namespace, limit)

    elif action == "huawei_get_cce_pvcs":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_pvcs(region, cluster_id, ak, sk, project_id, namespace)

    elif action == "huawei_get_cce_pvs":
        if not region or not cluster_id:
            print(json.dumps({"success": False, "error": "region and cluster_id are required"}))
            sys.exit(1)
        result = get_cce_cluster_pvs(region, cluster_id, ak, sk, project_id)

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

    else:
        result = {
            "success": False,
            "error": f"Unknown action: {action}"
        }

    print(json.dumps(result, indent=2, ensure_ascii=False))




if __name__ == "__main__":
    main()
