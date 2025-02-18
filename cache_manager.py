import json
import os
from typing import Dict, Any

class CacheManager:
    def __init__(self, cache_dir: str = ".svn_git_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_cache_key(self, command: list, args: Dict = None) -> str:
        """Generate a unique cache key based on command and args"""
        def clean_string(s: str) -> str:
            """Helper function to clean strings of unwanted characters"""
            return str(s).replace('/', '_').replace('\\', '_').replace(':', '_')
        
        key_parts = []
        # Replace unwanted characters in command parts
        key_parts.extend(clean_string(part) for part in command)
        
        if args:
            # Replace unwanted characters in args and use hyphen as separator
            key_parts += [
                f"{k}-{clean_string(v)}" 
                for k, v in sorted(args.items())
            ]
        
        return "_".join(key_parts)
    
    def get_cached_result(self, key: str) -> Dict[str, Any]:
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