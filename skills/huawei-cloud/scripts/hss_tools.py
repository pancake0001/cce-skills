#!/usr/bin/env python3
"""
HSS 主机安全服务工具集
提供漏洞查询、状态管理、修复触发等能力。

用法：
  python3 hss_tools.py <action> [key=value ...]

Actions:
  huawei_hss_list_vul_host_hosts   查询所有主机的漏洞概览
  huawei_hss_list_host_vuls        查询指定主机漏洞详情
  huawei_hss_list_host_vuls_all    查询指定主机漏洞（全量自动翻页）
  huawei_hss_change_vul_status     修改漏洞状态（忽略/修复/验证）

依赖：
  pip install huaweicloudsdkhss

环境变量：
  HUAWEI_AK / HUAWEI_SK
"""

import os
import sys
import json
from typing import Dict, Any, List, Optional


# ──────────────────────────────────────────────────────────────
# HSS 错误码解释表
# ──────────────────────────────────────────────────────────────

HSS_ERROR_CODES = {
    "HSS.0001": {
        "meaning": "The service is unavailable.",
        "cause": "HSS 服务未开通、已欠费或已到期",
        "suggestion": "确认 HSS 主机安全服务已开通且账号未欠费"
    },
    "HSS.0002": {
        "meaning": "Failed to parse the request.",
        "cause": "请求参数格式错误或缺少必要参数（如 operate_type 不支持）",
        "suggestion": "检查 operate_type、type、data_list/host_data_list 参数组合是否正确"
    },
    "HSS.0003": {
        "meaning": "Incorrect request parameters.",
        "cause": "enterprise_project_id 不存在或值不合法",
        "suggestion": "使用 'all_granted_eps' 查询所有授权企业项目"
    },
    "HSS.0004": {
        "meaning": "Database operation failed.",
        "cause": "华为云 HSS 服务端数据库异常（服务端故障）",
        "suggestion": "非请求问题，等待华为云修复或提交工单"
    },
    "HSS.0005": {
        "meaning": "Request throttled.",
        "cause": "API 请求频率超限",
        "suggestion": "降低 API 调用频率"
    },
    "HSS.0006": {
        "meaning": "Request size exceeds the limit.",
        "cause": "data_list 或 host_data_list 超过500条上限",
        "suggestion": "分批处理，每批不超过500条"
    },
    "HSS.0190": {
        "meaning": "No host agent installed.",
        "cause": "目标主机未安装 HSS Agent",
        "suggestion": "在主机上安装 HSS Agent 后再操作"
    },
    "HSS.0191": {
        "meaning": "Host is not under protection.",
        "cause": "主机未开启防护",
        "suggestion": "先通过 CCE 集成防护或手动方式为主机开启防护"
    },
    "HSS.0192": {
        "meaning": "Feature is not supported for this host.",
        "cause": "HSS 版本不支持该操作（如 Windows 漏洞不支持等）",
        "suggestion": "确认主机防护版本是否支持对应功能"
    },
    "HSS.0193": {
        "meaning": "Host is offline.",
        "cause": "主机不在线或网络不通",
        "suggestion": "检查主机网络状态，确保 Agent 可连通"
    },
    "HSS.0201": {
        "meaning": "Vulnerability does not exist.",
        "cause": "指定的漏洞不存在",
        "suggestion": "使用 list_host_vuls 重新查询漏洞 ID"
    },
    "HSS.0203": {
        "meaning": "Vulnerability does not exist or has been handled.",
        "cause": "漏洞已被修复/忽略/加入白名单",
        "suggestion": "使用 list_host_vuls 重新查询漏洞状态"
    },
    "HSS.0204": {
        "meaning": "Vulnerability cannot be repaired automatically.",
        "cause": "该漏洞不支持自动修复，需要人工介入",
        "suggestion": "查看漏洞详情中的 repair_type 和 repair_cmd 手动处理"
    },
    "HSS.0205": {
        "meaning": "Vulnerability repair failed.",
        "cause": "修复失败（可能修复命令执行失败或需要备份）",
        "suggestion": "检查 repair_cmd 是否正确，确认主机状态，或先手动备份"
    },
    "HSS.1059": {
        "meaning": "Vulnerability operation is not allowed.",
        "cause": "漏洞当前状态不允许此操作（如已修复/已忽略/正在修复中）",
        "suggestion": "使用 list_host_vuls 确认漏洞当前状态，仅对 unhandled 状态执行修复"
    },
    "HSS.1060": {
        "meaning": "Vulnerability fix failed.",
        "cause": "漏洞修复失败（可能修复命令执行失败/权限不足/主机网络异常）",
        "suggestion": "检查主机状态，确认 HSS Agent 正常运行"
    },
    "HSS.1061": {
        "meaning": "Vulnerability is in fixing state.",
        "cause": "漏洞正在修复中，不允许重复操作",
        "suggestion": "等待当前修复完成，或使用 verify 操作验证状态"
    },
    "APIGW.0301": {
        "meaning": "Incorrect IAM authentication information.",
        "cause": "AK/SK 认证失败（格式错误/Token 失效）",
        "suggestion": "检查 HUAWEI_AK/HUAWEI_SK 环境变量是否正确"
    },
    "APIGW.0302": {
        "meaning": "Access denied.",
        "cause": "IAM 权限不足",
        "suggestion": "确认 AK/SK 对应账号具有 HSS 操作权限"
    },
    "APIGW.0305": {
        "meaning": "The requested version does not exist.",
        "cause": "API 版本不存在（endpoint 路径错误）",
        "suggestion": "确认使用的是 v5 版本 API"
    },
}


def explain_hss_error(error_code: str, http_status: int = None, operate_type: str = None) -> Dict[str, str]:
    """解释 HSS 错误码，返回详细信息字典"""
    info = HSS_ERROR_CODES.get(error_code, {})
    result = {
        "error_code": error_code,
        "http_status": http_status,
        "meaning": info.get("meaning", "Unknown error"),
        "cause": info.get("cause", "Unknown cause"),
        "suggestion": info.get("suggestion", "请参考华为云 HSS 文档或提交工单"),
    }
    if error_code == "HSS.0002" and operate_type == "repair":
        result["cause"] = "repair 操作需要更多参数或权限（如 backup_info_id）"
        result["suggestion"] = "尝试使用 immediate_repair，或确认漏洞是否支持自动修复"
    elif error_code == "HSS.0004":
        result["note"] = "HSS.0004 是服务端数据库故障，与请求格式无关，无需修改请求"
    return result


def format_hss_error(e: Exception, operate_type: str = None) -> str:
    """格式化 HSS 异常，返回带解释的错误字符串"""
    error_code = getattr(e, 'error_code', None)
    http_status = getattr(e, 'status_code', None)
    error_msg = getattr(e, 'error_msg', None)
    request_id = getattr(e, 'request_id', None)
    lines = []
    if error_code:
        info = explain_hss_error(error_code, http_status, operate_type)
        lines.extend([
            f"错误码: {error_code}",
            f"含义: {info['meaning']}",
            f"原因: {info['cause']}",
            f"建议: {info['suggestion']}",
        ])
        if "note" in info:
            lines.append(f"备注: {info['note']}")
    else:
        lines.append(f"错误: {str(e)}")
    if request_id:
        lines.append(f"RequestId: {request_id}")
    return " | ".join(lines)


# ──────────────────────────────────────────────────────────────
# 认证
# ──────────────────────────────────────────────────────────────

def get_credentials(ak: str = None, sk: str = None) -> tuple:
    """获取认证信息，返回 (access_key, secret_key)"""
    _ak = ak or os.environ.get('HUAWEI_AK')
    _sk = sk or os.environ.get('HUAWEI_SECRET_KEY') or os.environ.get('HUAWEI_SK')
    if not _ak or not _sk:
        return None, None, "Missing HUAWEI_AK / HUAWEI_SK"
    return _ak, _sk, None


def create_hss_client(region: str, access_key: str, secret_key: str):
    """创建 HSS client"""
    from huaweicloudsdkcore.auth.credentials import BasicCredentials
    from huaweicloudsdkhss.v5 import HssClient
    from huaweicloudsdkhss.v5.region.hss_region import HssRegion
    credentials = BasicCredentials(ak=access_key, sk=secret_key)
    return HssClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(HssRegion.value_of(region)) \
        .build()


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

def huawei_hss_list_vul_host_hosts(
    region: str,
    enterprise_project_id: str = 'all_granted_eps',
    machine_type: str = None,
    limit: int = 100,
    offset: int = 0,
    ak: Optional[str] = None,
    sk: Optional[str] = None
) -> Dict[str, Any]:
    """查询所有主机的漏洞概览"""
    access_key, secret_key, error = get_credentials(ak, sk)
    if error:
        return {"success": False, "error": error}

    try:
        from huaweicloudsdkhss.v5 import HssClient, ListVulHostHostsRequest
        from huaweicloudsdkhss.v5.region.hss_region import HssRegion

        client = create_hss_client(region, access_key, secret_key)

        kwargs = {
            'enterprise_project_id': enterprise_project_id,
            'limit': str(limit),
            'offset': str(offset),
        }
        if machine_type:
            kwargs['machine_type'] = machine_type

        request = ListVulHostHostsRequest(**kwargs)
        response = client.list_vul_host_hosts(request)

        hosts = []
        for h in (response.data_list or []):
            hosts.append({
                "host_id": h.host_id,
                "host_name": getattr(h, 'host_name', ''),
                "private_ip": getattr(h, 'private_ip', ''),
                "os_type": getattr(h, 'os_type', ''),
                "agent_status": getattr(h, 'agent_status', ''),
                "protect_status": getattr(h, 'protect_status', ''),
                "total_vul_num": getattr(h, 'total_vul_num', 0),
                "serious_vul_num": getattr(h, 'serious_vul_num', 0),
                "high_vul_num": getattr(h, 'high_vul_num', 0),
                "medium_vul_num": getattr(h, 'medium_vul_num', 0),
                "low_vul_num": getattr(h, 'low_vul_num', 0),
            })

        return {
            "success": True,
            "action": "huawei_hss_list_vul_host_hosts",
            "hosts": hosts,
            "count": len(hosts),
            "total": getattr(response, 'total_num', len(hosts)),
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_hss_error(e),
            "error_type": type(e).__name__,
            "error_code": getattr(e, 'error_code', None),
            "http_status": getattr(e, 'status_code', None),
            "request_id": getattr(e, 'request_id', None),
        }


def huawei_hss_list_host_vuls(
    region: str,
    host_id: str = None,
    host_name: str = None,
    status: str = None,
    repair_priority: str = None,
    severity_level: str = None,
    limit: int = 100,
    offset: int = 0,
    enterprise_project_id: str = 'all_granted_eps',
    ak: Optional[str] = None,
    sk: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询主机漏洞详情

    ⚠️ 分页完整性：当 total > limit 时，需要翻页获取完整数据。

    Args:
        region: 区域ID
        host_id: 主机ID（与 host_name 二选一，host_id 优先）
        host_name: 主机名称
        status: 漏洞状态
            - vul_status_unhandled: 未处理
            - vul_status_fix: 已修复
            - vul_status_reboot: 需重启
            - vul_status_ignored: 已忽略
            - vul_status_fixing: 修复中
        repair_priority: 修复优先级（Critical/High/Medium/Low）
        severity_level: 严重程度（Critical/High/Medium/Low）
        limit: 每页数量
        offset: 偏移量

    Returns:
        dict: {
n            "success": bool,
            "vulnerabilities": [...],
            "count": int,    # 本次返回数量
            "total": int,    # 完整总数（必须用这个）
        }
    """
    access_key, secret_key, error = get_credentials(ak, sk)
    if error:
        return {"success": False, "error": error}

    try:
        from huaweicloudsdkhss.v5 import HssClient, ListHostVulsRequest
        from huaweicloudsdkhss.v5.region.hss_region import HssRegion

        client = create_hss_client(region, access_key, secret_key)

        kwargs = {
            'enterprise_project_id': enterprise_project_id,
            'limit': str(limit),
            'offset': str(offset),
        }
        if host_id:
            kwargs['host_id'] = host_id
        if host_name:
            kwargs['host_name'] = host_name
        if status:
            kwargs['status'] = status
        if repair_priority:
            kwargs['repair_priority'] = repair_priority
        if severity_level:
            kwargs['severity_level'] = severity_level

        request = ListHostVulsRequest(**kwargs)
        response = client.list_host_vuls(request)

        vulns = []
        for v in (response.data_list or []):
            vulns.append({
                "vul_id": getattr(v, 'vul_id', ''),
                "vul_name": getattr(v, 'vul_name', ''),
                "severity_level": getattr(v, 'severity_level', ''),
                "repair_priority": getattr(v, 'repair_priority', ''),
                "status": getattr(v, 'status', ''),
                "repair_type": getattr(v, 'repair_type', ''),
                "repair_cmd": getattr(v, 'repair_cmd', ''),
                "is_affect_business": getattr(v, 'is_affect_business', False),
                "host_id": getattr(v, 'host_id', ''),
                "host_name": getattr(v, 'host_name', ''),
                " CVE_id": getattr(v, 'cve_id', ''),
                "NVD_id": getattr(v, 'nvd_id', ''),
                "fixed_version": getattr(v, 'fixed_version', ''),
            })

        return {
            "success": True,
            "action": "huawei_hss_list_host_vuls",
            "vulnerabilities": vulns,
            "count": len(vulns),
            "total": getattr(response, 'total_num', len(vulns)),
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_hss_error(e),
            "error_type": type(e).__name__,
            "error_code": getattr(e, 'error_code', None),
            "http_status": getattr(e, 'status_code', None),
            "request_id": getattr(e, 'request_id', None),
        }


def huawei_hss_list_host_vuls_all(
    region: str,
    host_id: str = None,
    host_name: str = None,
    status: str = None,
    repair_priority: str = None,
    severity_level: str = None,
    limit: int = 100,
    enterprise_project_id: str = 'all_granted_eps',
    ak: Optional[str] = None,
    sk: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询主机漏洞详情（全量，自动翻页）

    自动翻页获取主机漏洞完整列表，适用于需要统计和处理全部漏洞的场景。

    Returns:
        dict: {
            "success": bool,
            "vulnerabilities": [...],  # 完整数据
            "total": int,               # 完整总数
            "pages": int,                # 总页数
            "page_count": int,           # 本次获取的页数
        }
    """
    all_vuls = []
    offset = 0
    page_count = 0
    total = 0

    while True:
        r = huawei_hss_list_host_vuls(
            region=region,
            host_id=host_id,
            host_name=host_name,
            status=status,
            repair_priority=repair_priority,
            severity_level=severity_level,
            limit=limit,
            offset=offset,
            enterprise_project_id=enterprise_project_id,
            ak=ak,
            sk=sk,
        )
        if not r.get('success'):
            return r
        all_vuls.extend(r.get('vulnerabilities', []))
        total = r.get('total', 0)
        page_count += 1
        if offset + limit >= total:
            break
        offset += limit

    return {
        "success": True,
        "action": "huawei_hss_list_host_vuls_all",
        "vulnerabilities": all_vuls,
        "total": total,
        "pages": (total + limit - 1) // limit if total > 0 else 0,
        "page_count": page_count,
    }


def huawei_hss_change_vul_status(
    region: str,
    operate_type: str,
    vul_ids: List[str] = None,
    host_ids: List[str] = None,
    vul_type: str = "linux_vul",
    remark: str = None,
    select_type: str = None,
    confirm: bool = False,
    enterprise_project_id: str = 'all_granted_eps',
    ak: Optional[str] = None,
    sk: Optional[str] = None
) -> Dict[str, Any]:
    """
    修改漏洞状态（忽略/修复/验证/加入白名单）

    ⚠️ 关键：data_list 和 host_data_list 只能二选一，同时传会导致 HSS.0004。

    视图规则（host_ids 优先）：
      - 传入 host_ids → 只用 host_data_list（主机视图）
      - 只传 vul_ids   → 只用 data_list（漏洞视图）

    operate_type 可选值：
      - immediate_repair: 立即修复（自动修复，支持漏洞视图和主机视图）
      - manual_repair: 人工修复
      - verify: 验证漏洞
      - ignore: 忽略漏洞
      - not_ignore: 取消忽略
      - add_to_whitelist: 加入白名单

    Args:
        region: 区域ID
        operate_type: 操作类型
        vul_ids: 漏洞ID列表（漏洞视图，与 host_ids 二选一）
        host_ids: 主机ID列表（主机视图，优先使用）
        vul_type: 漏洞类型，默认 linux_vul
        remark: 备注信息
        select_type: 处置类型（all_vul/all_host）
        confirm: 是否确认执行（默认 False 仅预览）
    """
    access_key, secret_key, error = get_credentials(ak, sk)
    if error:
        return {"success": False, "error": error}

    # 预览模式
    if not confirm:
        view = "host" if host_ids else ("vul" if vul_ids else "unknown")
        return {
            "success": True,
            "action": "huawei_hss_change_vul_status",
            "preview": True,
            "confirm_required": True,
            "message": "危险操作，需要 confirm=True 才会真正执行",
            "operate_type": operate_type,
            "vul_type": vul_type,
            "view": view,
            "vul_ids": (vul_ids or [])[:10],
            "vul_ids_count": len(vul_ids) if vul_ids else 0,
            "host_ids": (host_ids or [])[:10],
            "host_ids_count": len(host_ids) if host_ids else 0,
            "select_type": select_type,
            "note": "data_list 与 host_data_list 二选一（host_ids 优先）",
        }

    try:
        from huaweicloudsdkhss.v5 import HssClient, ChangeVulStatusRequest, ChangeVulStatusRequestInfo
        from huaweicloudsdkhss.v5 import VulOperateInfo, HostVulOperateInfo
        from huaweicloudsdkhss.v5.region.hss_region import HssRegion

        client = create_hss_client(region, access_key, secret_key)

        # ⚠️ 关键修复：data_list 和 host_data_list 互斥，host_ids 优先
        data_list = None
        host_data_list = None

        if host_ids:
            # 主机视图：每个主机关联其漏洞列表
            host_data_list = []
            for _hid in host_ids:
                host_data_list.append(HostVulOperateInfo(
                    host_id=_hid,
                    vul_id_list=vul_ids
                ))
        elif vul_ids:
            # 漏洞视图：只用 data_list
            data_list = [VulOperateInfo(vul_id=_vid) for _vid in vul_ids]

        body = ChangeVulStatusRequestInfo(
            operate_type=operate_type,
            type=vul_type,
            data_list=data_list,
            host_data_list=host_data_list,
            select_type=select_type,
            remark=remark,
        )

        request = ChangeVulStatusRequest(
            enterprise_project_id=enterprise_project_id,
            body=body
        )
        response = client.change_vul_status(request)

        return {
            "success": True,
            "action": "huawei_hss_change_vul_status",
            "region": region,
            "operate_type": operate_type,
            "vul_type": vul_type,
            "view": "host" if host_ids else "vul",
            "affected_vulns": len(vul_ids) if vul_ids else 0,
            "affected_hosts": len(host_ids) if host_ids else 0,
            "response": str(response),
        }

    except Exception as e:
        return {
            "success": False,
            "error": format_hss_error(e, operate_type=operate_type),
            "error_type": type(e).__name__,
            "error_code": getattr(e, 'error_code', None),
            "http_status": getattr(e, 'status_code', None),
            "request_id": getattr(e, 'request_id', None),
        }


# ──────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 hss_tools.py <action> [key=value ...]")
        print("Actions:")
        print("  huawei_hss_list_vul_host_hosts   查询所有主机漏洞概览")
        print("  huawei_hss_list_host_vuls        查询主机漏洞详情")
        print("  huawei_hss_list_host_vuls_all    查询主机漏洞（全量自动翻页）")
        print("  huawei_hss_change_vul_status     修改漏洞状态")
        sys.exit(1)

    action = sys.argv[1]

    # 解析参数
    params = {}
    for arg in sys.argv[2:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            # 尝试解析为列表
            if v.startswith('[') and v.endswith(']'):
                try:
                    v = json.loads(v)
                except Exception:
                    pass
            # 解析布尔值
            elif v.lower() == 'true':
                v = True
            elif v.lower() == 'false':
                v = False
            params[k] = v

    # 提取公共参数
    region = params.pop('region', 'cn-north-4')
    ak = params.pop('ak', None)
    sk = params.pop('sk', None)
    confirm = params.pop('confirm', 'false').lower() == 'true'

    if action == 'huawei_hss_list_vul_host_hosts':
        result = huawei_hss_list_vul_host_hosts(region=region, ak=ak, sk=sk, **params)

    elif action == 'huawei_hss_list_host_vuls':
        result = huawei_hss_list_host_vuls(region=region, ak=ak, sk=sk, **params)

    elif action == 'huawei_hss_list_host_vuls_all':
        result = huawei_hss_list_host_vuls_all(region=region, ak=ak, sk=sk, **params)

    elif action == 'huawei_hss_change_vul_status':
        result = huawei_hss_change_vul_status(
            region=region, ak=ak, sk=sk, confirm=confirm, **params
        )

    else:
        result = {"success": False, "error": f"Unknown action: {action}"}

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
