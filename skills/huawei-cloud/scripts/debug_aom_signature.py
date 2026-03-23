#!/usr/bin/env python3
"""
Debug script for AOM Prometheus API signature - Fixed version
"""

import hashlib
import hmac
import base64
import time
import urllib.parse
from urllib.parse import quote, unquote
import requests
import json
import os
import sys


def get_credentials():
    """Get credentials from environment or command line"""
    ak = os.environ.get("HUAWEI_AK")
    sk = os.environ.get("HUAWEI_SK")
    project_id = os.environ.get("HUAWEI_PROJECT_ID")
    region = os.environ.get("HUAWEI_REGION", "cn-north-4")
    
    args = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            args[k] = v
    
    if 'ak' in args:
        ak = args['ak']
    if 'sk' in args:
        sk = args['sk']
    if 'project_id' in args:
        project_id = args['project_id']
    if 'region' in args:
        region = args['region']
    
    return ak, sk, project_id, region


def url_encode(s):
    """SDK style URL encode"""
    return quote(s, safe='~')


def test_sdk_signature(region, project_id, ak, sk, query, start_time, end_time, step=60):
    """Signature logic matching SDK exactly"""
    
    # 构建URL
    base_url = "https://aom.{}.myhuaweicloud.com".format(region)
    
    query_params = [
        ('end', str(end_time)),
        ('query', query),
        ('start', str(start_time)),
        ('step', str(step))
    ]
    
    # 时间戳
    timestamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    
    # 1. HTTP方法
    http_method = 'GET'
    
    # 2. Canonical URI (SDK会确保以/结尾)
    resource_path = "/v1/{}/aom/api/v1/query_range".format(project_id)
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
    signed_headers_list = ['host', 'x-project-id', 'x-sdk-date']
    signed_headers = ';'.join(signed_headers_list)
    canonical_headers = 'host:{}\nx-project-id:{}\nx-sdk-date:{}\n'.format(
        host_header, project_id, timestamp)
    
    # 5. 空body的hash
    hashed_body = hashlib.sha256(b'').hexdigest()
    
    # 6. Canonical Request
    canonical_request = '{}\n{}\n{}\n{}\n{}\n{}'.format(
        http_method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, hashed_body)
    
    # 7. StringToSign (SDK格式：只有3行)
    algorithm = 'SDK-HMAC-SHA256'
    hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    string_to_sign = '{}\n{}\n{}'.format(algorithm, timestamp, hashed_canonical_request)
    
    # 8. 签名 - 使用hex编码
    signature = hmac.new(
        sk.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).digest().hex()
    
    # 9. Authorization
    authorization = '{} Access={}, SignedHeaders={}, Signature={}'.format(
        algorithm, ak, signed_headers, signature)
    
    # 构建请求URL
    url_query_string = '&'.join(['{}={}'.format(k, urllib.parse.quote(str(v))) for k, v in query_params])
    url = "{}/v1/{}/aom/api/v1/query_range?{}".format(base_url, project_id, url_query_string)
    
    headers = {
        'Host': host_header,
        'X-Project-Id': project_id,
        'X-Sdk-Date': timestamp,
        'Authorization': authorization,
    }
    
    return {
        'url': url,
        'headers': headers,
        'method': 'GET',
        'debug': {
            'canonical_uri': canonical_uri,
            'canonical_querystring': canonical_querystring,
            'canonical_request': canonical_request,
            'string_to_sign': string_to_sign,
            'signature': signature,
            'authorization': authorization,
        }
    }


def send_request(url, headers, method='GET'):
    """Send request and return response"""
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, verify=True, timeout=30)
        else:
            resp = requests.post(url, headers=headers, verify=True, timeout=30)
        
        result = {
            'status_code': resp.status_code,
            'headers': dict(resp.headers),
            'body': resp.text[:1000] if resp.text else '',
        }
        if resp.headers.get('content-type', '').startswith('application/json'):
            try:
                result['json'] = resp.json()
            except:
                pass
        return result
    except Exception as e:
        return {'error': str(e)}


def main():
    ak, sk, project_id, region = get_credentials()
    
    if not ak or not sk or not project_id:
        print("Error: Please provide credentials via:")
        print("  Environment variables: HUAWEI_AK, HUAWEI_SK, HUAWEI_PROJECT_ID")
        print("  Or command line: ak=xxx sk=xxx project_id=xxx")
        sys.exit(1)
    
    # Query parameters
    query = "up"
    now = int(time.time())
    end_time = now
    start_time = now - 3600
    step = 60
    
    print("=" * 70)
    print("AOM Prometheus API Signature Debug - SDK Compatible")
    print("=" * 70)
    print(f"Region: {region}")
    print(f"Project ID: {project_id}")
    print(f"AK: {ak[:8]}...")
    print(f"Query: {query}")
    print(f"Time range: {start_time} - {end_time}")
    print("=" * 70)
    
    # Test SDK signature
    print("\n[TEST] SDK-compatible signature")
    result = test_sdk_signature(region, project_id, ak, sk, query, start_time, end_time, step)
    
    print(f"\nURL: {result['url']}")
    print(f"\nCanonical URI: {result['debug']['canonical_uri']}")
    print(f"\nCanonical Query String: {result['debug']['canonical_querystring']}")
    print(f"\nStringToSign:\n---\n{result['debug']['string_to_sign']}\n---")
    print(f"\nSignature: {result['debug']['signature']}")
    print(f"\nAuthorization: {result['debug']['authorization']}")
    
    # Send request
    print("\n" + "-" * 70)
    print("Sending request...")
    resp = send_request(result['url'], result['headers'], 'GET')
    
    print(f"\nResponse Status: {resp.get('status_code')}")
    if resp.get('json'):
        print(f"Response JSON: {json.dumps(resp['json'], indent=2, ensure_ascii=False)[:500]}")
    elif resp.get('body'):
        print(f"Response Body: {resp['body'][:500]}")
    elif resp.get('error'):
        print(f"Error: {resp['error']}")
    
    # Summary
    print("\n" + "=" * 70)
    if resp.get('status_code') == 200:
        print("✓ SUCCESS: Signature verified correctly!")
    else:
        print("✗ FAILED: Check the error message above")
    print("=" * 70)


if __name__ == "__main__":
    main()