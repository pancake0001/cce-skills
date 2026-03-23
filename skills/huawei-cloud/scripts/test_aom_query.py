#!/usr/bin/env python3
"""
Test AOM Prometheus query with the fixed signature implementation
"""

import sys
import os

# Add the scripts directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from huawei_cloud import get_aom_prom_metrics_http

def main():
    # Parse command line args
    args = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            args[k] = v
    
    region = args.get('region', 'cn-north-4')
    aom_instance_id = args.get('aom_instance_id', 'default')
    query = args.get('query', 'up')
    
    print(f"Testing AOM Prometheus query:")
    print(f"  Region: {region}")
    print(f"  Instance ID: {aom_instance_id}")
    print(f"  Query: {query}")
    print("-" * 50)
    
    result = get_aom_prom_metrics_http(
        region=region,
        aom_instance_id=aom_instance_id,
        query=query
    )
    
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()