from datetime import datetime
import json
import logging
import os
import subprocess
from typing import Dict, Any, List

cache_enabled: bool = True
cache_key_filename = "_cache_keys.json"

class CacheManager:

    counter: int = 0
    date_time_prefix_for_cache_file: str = datetime.now().strftime("%Y%m%d-%H%M%S-")
    cache_dir: str = ".svn_git_cache"

    def __init__(self):
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def cache_result(self, key: str, result: Dict[str, Any]) -> None:
        """Cache the result for a given key"""
        cache_file = os.path.join(self.cache_dir, f"{key}.json")
        with open(cache_file, 'w') as f:
            json.dump(result, f, indent=4)
    

    def cached_run(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Execute subprocess.run with caching"""
        
        check = kwargs.pop('check', False)
                
        result = subprocess.run(cmd, capture_output=True, universal_newlines=True, **kwargs)
        
        # Cache the result
        file_suffix = self.counter
        self.counter += 1
        self.cache_result(f"{self.date_time_prefix_for_cache_file}{file_suffix}", {
            'returncode': result.returncode,
            'stdout': result.stdout if hasattr(result, 'stdout') else '',
            'stderr': result.stderr if hasattr(result, 'stderr') else ''
        })
        
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr)
                
        return result