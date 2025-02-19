import json
import logging
import os
import subprocess
from typing import Dict, Any, List

class CacheManager:
    # cache_keys is a dictionary that maps a unique short string to an object 
    # containing the cmd and args
    cache_keys: dict[str, dict[str, dict[str, str]|List[str]]]
    cache_dir: str

    def __init__(self, cache_dir: str = ".svn_git_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        # load cache_keys.json from the cache_dir
        cache_keys_file = os.path.join(cache_dir, "cache_keys.json")
        if os.path.exists(cache_keys_file):
            with open(cache_keys_file, 'r') as f:
                self.cache_keys = json.load(f)
        else:
            self.cache_keys = {}
    
    def get_cache_key(self, cmd: list[str], args: dict[str, str] = {}) -> str:
        # check if the cache_keys values contain cmd and args
        # if so, return the key
        # if not, generate a random string as key, add the cmd and args to the cache_keys and return the key
        for key, value in self.cache_keys.items():
            logging.debug(f"Checking cache key {key} for command: {' '.join(cmd)}")            
            if value.get('cmd') == cmd and value.get('args') == args:
                logging.debug(f"Cache hit {key} for command: {' '.join(cmd)}")
                return key
                
        # Generate random 8 character string for new key
        import random
        import string
        key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        
        # Add new entry to cache_keys
        self.cache_keys[key] = {
            'cmd': cmd,
            'args': args
        }
        
        # Save updated cache_keys
        cache_keys_file = os.path.join(self.cache_dir, "cache_keys.json") 
        with open(cache_keys_file, 'w') as f:
            json.dump(self.cache_keys, f)
            
        return key

        
    
    def get_cached_result(self, key: str) -> Dict[str, str]:
        """Retrieve cached result for a given key"""
        cache_file = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)
        return None
    
    def cache_result(self, key: str, result: Dict[str, Any]) -> None:
        """Cache the result for a given key"""
        cache_file = os.path.join(self.cache_dir, f"{key}.json")
        with open(cache_file, 'w') as f:
            json.dump(result, f)
    

    def cached_run(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Execute subprocess.run with caching"""
        cache_key = self.get_cache_key(cmd)
        cached_result = self.get_cached_result(cache_key)
        check = kwargs.pop('check', False)
        
        if cached_result:
            logging.info(f"Using cached result for command: {' '.join(cmd)}")
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=cached_result.get('returncode', 0),
                stdout=cached_result.get('stdout', ''),
                stderr=cached_result.get('stderr', '')
            )
        else:
            logging.info(f"No cached data found, executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, universal_newlines=True, **kwargs)
            
            # Cache the result
            self.cache_result(cache_key, {
                'returncode': result.returncode,
                'stdout': result.stdout if hasattr(result, 'stdout') else '',
                'stderr': result.stderr if hasattr(result, 'stderr') else ''
            })

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr)
                
        return result