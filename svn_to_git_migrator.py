#!/usr/bin/env python3

import os
import sys
import subprocess
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List
from cache_manager import CacheManager

# Configure logging
# Set up file handler for all logs
file_handler = logging.FileHandler('run.log')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

# Set up console handler with higher threshold
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

# Configure root logger
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)

class SVNToGitMigrator:
    def __init__(self, svn_repo_url: str, git_repo_path: str):
        self.cache_manager = CacheManager()
        """
        Initialize the SVN to Git migrator

        Args:
            svn_repo_url: URL of the SVN repository
            git_repo_path: Local path where Git repository will be created
        """
        logging.info(f"Initializing SVN to Git migrator with SVN repo: {svn_repo_url}")
        self.svn_repo_url = svn_repo_url
        self.git_repo_path = git_repo_path
        self.svn_revisions = []
        logging.debug(f"Git repository will be created at: {git_repo_path}")

    def get_svn_revisions(self) -> List[Dict]:
        """Get all SVN revisions with their metadata"""
        logging.info("Retrieving SVN revision history")
        cmd = ["svn", "log", "--xml", "--verbose", self.svn_repo_url]
        
        # Try to get cached result
        cache_key = self.cache_manager.get_cache_key(cmd)
        cached_result = self.cache_manager.get_cached_result(cache_key)
        logging.debug(f"Cache key: {cache_key}, found cached result {cached_result != None}")
        if cached_result:
            logging.info("Using cached SVN revision history")
            return cached_result
            
        logging.info("No cached data found, querying SVN server")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logging.error(f"Failed to get SVN log: {result.stderr}")
            raise Exception(f"Failed to get SVN log: {result.stderr}")

        logging.debug("Parsing SVN revision logs")
        revisions = []
        
        # Parse XML output
        root = ET.fromstring(result.stdout)
        for logentry in root.findall("logentry"):
            revision = {
                "revision": logentry.get("revision"),
                "author": logentry.find("author").text if logentry.find("author") is not None else "",
                "date": logentry.find("date").text if logentry.find("date") is not None else "",
                "message": logentry.find("msg").text if logentry.find("msg") is not None else "",
                "changed_paths": []
            }
            
            paths = logentry.find("paths")
            if paths is not None:
                for path in paths.findall("path"):
                    # only if the kind="file"
                    if path.get("kind") != "file":
                        continue
                    revision["changed_paths"].append(path.text)
            
            revisions.append(revision)

        # Cache the parsed revisions
        self.cache_manager.cache_result(cache_key, revisions)
        return revisions

    

    def verify_file_content(self, svn_content: str, git_content: str) -> bool:
        """Verify that file content matches between SVN and Git content strings"""
        logging.debug("Calculating content hashes for comparison")
        svn_hash = hashlib.md5(svn_content.encode()).hexdigest()
        git_hash = hashlib.md5(git_content.encode()).hexdigest()
        return svn_hash == git_hash

    def init_git_repo(self):
        """Initialize the Git repository"""
        logging.info(f"Initializing Git repository at {self.git_repo_path}")
        if not os.path.exists(self.git_repo_path):
            logging.debug(f"Creating directory {self.git_repo_path}")
            os.makedirs(self.git_repo_path)
        logging.debug(f"Changing to directory {self.git_repo_path}")
        os.chdir(self.git_repo_path)
        try:
            logging.info("Clone git-svn repository")
            subprocess.run(["git", "svn", "clone", self.svn_repo_url, "--stdlayout"], check=True)
            logging.info("Git repository successfully initialized")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to initialize Git repository: {str(e)}")
            raise

    def verify_revision_count(self) -> bool:
        """Verify that Git and SVN have same number of revisions"""
        logging.info("Verifying revision count between Git and SVN")
        git_log = subprocess.run(
            ["git", "log", "--all", "--pretty=format:%H %s"], capture_output=True, text=True
        ).stdout

        git_commits = git_log.strip().split("\n")
        if len(git_commits) != len(self.svn_revisions):
            logging.warning(
                f"Revision count mismatch - Git commits: {len(git_commits)}, "
                f"SVN revisions: {len(self.svn_revisions)}"
            )
            return False
        logging.info("Revision count matches between Git and SVN")
        return True

    def get_git_commit_for_revision(self, rev_num: str) -> str:
        """Get Git commit hash for SVN revision number"""
        logging.info(f"Looking up Git commit for SVN revision {rev_num}")
        
        # Try to get cached result
        cmd = ["git", "log", "--pretty=format:%H", f"--grep=git-svn-id.*@{rev_num}"]
        cache_key = self.cache_manager.get_cache_key(cmd)
        cached_result = self.cache_manager.get_cached_result(cache_key)
        
        if cached_result:
            logging.info(f"Using cached Git commit hash for revision {rev_num}")
            return cached_result.get('commit')
            
        logging.info(f"No cached data found, querying Git for revision {rev_num}")
        commit = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        ).stdout.strip()
        
        # Cache the result
        self.cache_manager.cache_result(cache_key, {'commit': commit})
        if not commit:
            logging.warning(f"No Git commit found for SVN revision {rev_num}")
        else:
            logging.debug(f"Found Git commit {commit} for revision {rev_num}")
        return commit

    def verify_commit_message(self, git_commit: str, svn_message: str) -> bool:
        """Verify commit message exactly matches between Git and SVN"""
        logging.info(f"Verifying commit message for Git commit {git_commit}")
        
        # Try to get cached result
        cmd = ["git", "log", "-1", "--pretty=format:%s%n%b", git_commit]
        cache_key = self.cache_manager.get_cache_key(cmd)
        cached_result = self.cache_manager.get_cached_result(cache_key)
        
        if cached_result:
            logging.info(f"Using cached commit message for {git_commit}")
            git_msg = cached_result.get('message')
        else:
            logging.info(f"No cached data found, getting commit message from Git")
            git_msg = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            ).stdout
            # Cache the result
            self.cache_manager.cache_result(cache_key, {'message': git_msg})
            
        # Normalize both messages by stripping whitespace and comparing exactly
        git_msg = ' '.join(git_msg.strip().split())
        svn_message = ' '.join(svn_message.strip().split())
        match = git_msg == svn_message
        
        if not match:
            logging.warning(f"Commit message mismatch for Git commit {git_commit}")
            logging.debug(f"SVN message: {svn_message}")
            logging.debug(f"Git message: {git_msg}")
        else:
            logging.debug("Commit message verified successfully")
            # Store the mapping when messages match
            rev_num = next((rev['revision'] for rev in self.svn_revisions 
                          if ' '.join(rev['message'].strip().split()) == svn_message), None)
            if rev_num:
                self.revision_commit_map[rev_num] = git_commit
                logging.info(f"Mapped SVN revision {rev_num} to Git commit {git_commit}")
        return match

    def verify_changed_files(
        self, rev_num: str, git_commit: str, changed_paths: List[str]
    ) -> bool:
        """Verify changed files match between Git and SVN"""
        logging.info(f"Verifying changed files for revision {rev_num}")
        logging.debug(f"Files to verify: {changed_paths}")
        for changed_path in changed_paths:
            if changed_path.startswith("A ") or changed_path.startswith("M "):
                file_path = changed_path[2:].strip()
                logging.debug(f"Verifying file: {file_path}")
                if not self._verify_single_file(rev_num, git_commit, file_path):
                    logging.warning(f"File verification failed: {file_path}")
                    return False
        logging.info("All changed files verified successfully")
        return True

    def _verify_single_file(
        self, rev_num: str, git_commit: str, file_path: str
    ) -> bool:
        """Verify a single file matches between Git and SVN"""
        logging.info(f"Verifying single file: {file_path} at revision {rev_num}")
        
        # Try to get cached SVN content
        svn_cmd = ["svn", "cat", "-r", rev_num, f"{self.svn_repo_url}/{file_path}"]
        svn_cache_key = self.cache_manager.get_cache_key(svn_cmd)
        svn_cached = self.cache_manager.get_cached_result(svn_cache_key)
        
        if svn_cached:
            logging.info(f"Using cached SVN content for {file_path}@{rev_num}")
            svn_content = svn_cached.get('content')
        else:
            logging.info(f"Getting SVN content for {file_path}@{rev_num}")
            svn_content = subprocess.run(
                svn_cmd,
                capture_output=True,
                text=True,
                check=True
            ).stdout
            self.cache_manager.cache_result(svn_cache_key, {'content': svn_content})

        # Try to get cached Git content
        git_cmd = ["git", "show", f"{git_commit}:{file_path}"]
        git_cache_key = self.cache_manager.get_cache_key(git_cmd)
        git_cached = self.cache_manager.get_cached_result(git_cache_key)
        
        if git_cached:
            logging.info(f"Using cached Git content for {file_path}@{git_commit}")
            git_content = git_cached.get('content')
        else:
            logging.info(f"Getting Git content for {file_path}@{git_commit}")
            git_content = subprocess.run(
                git_cmd,
                capture_output=True,
                text=True,
                check=True
            ).stdout
            self.cache_manager.cache_result(git_cache_key, {'content': git_content})

        result = self.verify_file_content(svn_content, git_content)

        if not result:
            logging.error(
                f"File content mismatch for {file_path} at revision {rev_num}"
            )
        else:
            logging.debug(f"File content verified successfully: {file_path}")

        return result

    def migrate(self) -> bool:
        """Perform the SVN to Git migration with verification"""
        logging.info("Starting SVN to Git migration process")
        try:
            # Initialize tracking map
            self.revision_commit_map = {}
            
            logging.info("Retrieving SVN revisions...")
            self.svn_revisions = self.get_svn_revisions()

            if not os.path.exists(self.git_repo_path):
                logging.info("Initializing new Git repository...")
                self.init_git_repo()

            logging.info(f"Changing to Git repository directory: {self.git_repo_path}")
            os.chdir(self.git_repo_path)

            # Verify revision count matches
            if not self.verify_revision_count():
                logging.error("Revision count verification failed. Lets find which one is missing.")
                return False
                
            # Verify each revision
            for revision in self.svn_revisions:
                rev_num = revision["revision"]
                message = revision["message"]
                changed_paths = revision["changed_paths"]
                
                # Get Git commit for SVN revision
                try:
                    git_commit = self.get_git_commit_for_revision(rev_num)
                except subprocess.CalledProcessError as e:
                    logging.error(f"Could not find Git commit for SVN revision {rev_num}")
                    logging.debug(f"Error: {e}")
                    return False
                
                logging.debug(f"Git commit for revision {rev_num}: {git_commit}")

                # Verify commit message and track mapping
                if not self.verify_commit_message(git_commit, message):
                    logging.error(f"Commit message verification failed for revision {rev_num}")
                    return False

                # Ensure revision was mapped during message verification
                if rev_num not in self.revision_commit_map:
                    logging.error(f"Failed to map revision {rev_num} to Git commit")
                    return False

                # Verify files for this revision
                if not self.verify_changed_files(rev_num, git_commit, changed_paths):
                    logging.error(f"File verification failed for revision {rev_num}")
                    return False
                
                logging.info(f"Successfully verified revision {rev_num} (Git commit: {git_commit})")
                
            
            logging.info(
                "Migration completed successfully with all verifications passed!"
            )
            return True

        except Exception as e:
            logging.error(f"Error during migration: {str(e)}")
            logging.debug(f"Migration failed with exception: {e}", exc_info=True)
            return False


def main():
    logging.info("Starting SVN to Git migration tool")
    if len(sys.argv) != 3:
        logging.error("Invalid number of arguments provided")
        print("Usage: python svn_to_git_migrator.py <svn_repo_url> <git_repo_path>")
        sys.exit(1)

    svn_repo_url = sys.argv[1]
    git_repo_path = sys.argv[2]

    migrator = SVNToGitMigrator(svn_repo_url, git_repo_path)
    success = migrator.migrate()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
