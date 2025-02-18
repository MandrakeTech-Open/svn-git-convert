#!/usr/bin/env python3

import os
import sys
import subprocess
import hashlib
from datetime import datetime
from typing import Dict, List, Tuple

class SVNToGitMigrator:
    def __init__(self, svn_repo_url: str, git_repo_path: str):
        """
        Initialize the SVN to Git migrator
        
        Args:
            svn_repo_url: URL of the SVN repository
            git_repo_path: Local path where Git repository will be created
        """
        self.svn_repo_url = svn_repo_url
        self.git_repo_path = git_repo_path
        self.svn_revisions = []
        
    def get_svn_revisions(self) -> List[Dict]:
        """Get all SVN revisions with their metadata"""
        cmd = ['svn', 'log', '-v', self.svn_repo_url]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Failed to get SVN log: {result.stderr}")
            
        revisions = []
        current_revision = {}
        
        for line in result.stdout.split('\n'):
            if line.startswith('r'):
                # Parse revision header
                parts = line.split(' | ')
                if len(parts) >= 4:
                    current_revision = {
                        'revision': parts[0][1:],
                        'author': parts[1],
                        'date': parts[2],
                        'message': '',
                        'changed_paths': []
                    }
            elif line.startswith('Changed paths:'):
                continue
            elif line.startswith('   '):
                # Changed paths or commit message
                if 'message' not in current_revision:
                    current_revision['changed_paths'].append(line.strip())
                else:
                    current_revision['message'] += line.strip() + '\n'
            elif line.strip() == '-' * 72:
                if current_revision:
                    revisions.append(current_revision)
                    current_revision = {}
                    
        return revisions
    
    def calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def verify_file_content(self, svn_file: str, git_file: str) -> bool:
        """Verify that file content matches between SVN and Git versions"""
        svn_hash = self.calculate_file_hash(svn_file)
        git_hash = self.calculate_file_hash(git_file)
        return svn_hash == git_hash
    
    def migrate(self) -> bool:
        """
        Perform the SVN to Git migration with verification
        
        Returns:
            bool: True if migration was successful, False otherwise
        """
        try:
            # Get SVN revisions before migration
            print("Fetching SVN revision history...")
            self.svn_revisions = self.get_svn_revisions()
            
            # Initialize git-svn
            print("Initializing git-svn...")
            if not os.path.exists(self.git_repo_path):
                os.makedirs(self.git_repo_path)
            
            os.chdir(self.git_repo_path)
            subprocess.run(['git', 'svn', 'init', self.svn_repo_url], check=True)
            
            # Fetch all revisions
            print("Fetching SVN repository...")
            subprocess.run(['git', 'svn', 'fetch'], check=True)
            
            # Verify all revisions
            print("Verifying revisions...")
            git_log = subprocess.run(
                ['git', 'log', '--pretty=format:%H %s'],
                capture_output=True,
                text=True
            ).stdout
            
            # Compare revision counts
            git_commits = git_log.strip().split('\n')
            if len(git_commits) != len(self.svn_revisions):
                print(f"Warning: Number of Git commits ({len(git_commits)}) "
                      f"doesn't match SVN revisions ({len(self.svn_revisions)})")
                return False
            
            # Verify each revision
            for svn_rev in self.svn_revisions:
                rev_num = svn_rev['revision']
                # Get Git commit for SVN revision
                git_commit = subprocess.run(
                    ['git', 'log', '--pretty=format:%H', f'--grep=git-svn-id.*@{rev_num}'],
                    capture_output=True,
                    text=True
                ).stdout.strip()
                
                if not git_commit:
                    print(f"Error: Could not find Git commit for SVN revision {rev_num}")
                    return False
                
                # Verify commit message
                git_msg = subprocess.run(
                    ['git', 'log', '-1', '--pretty=format:%s%n%b', git_commit],
                    capture_output=True,
                    text=True
                ).stdout
                
                if svn_rev['message'].strip() not in git_msg:
                    print(f"Error: Commit message mismatch for revision {rev_num}")
                    return False
                
                # Verify files for this revision
                for changed_path in svn_rev['changed_paths']:
                    if changed_path.startswith('A ') or changed_path.startswith('M '):
                        file_path = changed_path[2:].strip()
                        # Export SVN version
                        svn_export = f"/tmp/svn_export_{rev_num}"
                        subprocess.run([
                            'svn', 'export', '-r', rev_num,
                            f"{self.svn_repo_url}/{file_path}", svn_export
                        ], check=True)
                        
                        # Get Git version
                        git_export = f"/tmp/git_export_{rev_num}"
                        subprocess.run([
                            'git', 'show', f"{git_commit}:{file_path}",
                            f"> {git_export}"
                        ], shell=True, check=True)
                        
                        # Compare files
                        if not self.verify_file_content(svn_export, git_export):
                            print(f"Error: File content mismatch for {file_path} "
                                  f"at revision {rev_num}")
                            return False
                        
                        # Cleanup
                        os.remove(svn_export)
                        os.remove(git_export)
            
            print("Migration completed successfully with all verifications passed!")
            return True
            
        except Exception as e:
            print(f"Error during migration: {str(e)}")
            return False

def main():
    if len(sys.argv) != 3:
        print("Usage: python svn_to_git_migrator.py <svn_repo_url> <git_repo_path>")
        sys.exit(1)
    
    svn_repo_url = sys.argv[1]
    git_repo_path = sys.argv[2]
    
    migrator = SVNToGitMigrator(svn_repo_url, git_repo_path)
    success = migrator.migrate()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()