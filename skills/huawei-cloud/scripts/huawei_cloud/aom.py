from .common import *

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
            return {
                "success": False,
                "error": "HTTP " + str(resp.status_code) + ": " + resp.text[:500],
                "url": url,
                "request_headers": {k: v for k, v in headers.items() if k != 'Authorization'},
                "request_context": {
                    "canonical_uri": canonical_uri,
                    "signed_headers": signed_headers,
                },
            }
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}

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
