#!/usr/bin/env python3

import os
import sys
import subprocess
import hashlib
import logging
from typing import Dict, List
from cache_manager import CacheManager

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)


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
        cmd = ["svn", "log", "-v", self.svn_repo_url]
        
        # Try to get cached result
        cache_key = self.cache_manager.get_cache_key(cmd)
        cached_result = self.cache_manager.get_cached_result(cache_key)
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
        current_revision = {}

        for line in result.stdout.split("\n"):
            if line.startswith("r"):
                current_revision = self._parse_svn_log_line(line, current_revision)
                if line.strip() == "-" * 72 and current_revision:
                    revisions.append(current_revision)
                    current_revision = {}
        
        # Cache the parsed revisions
        self.cache_manager.cache_result(cache_key, revisions)
        return revisions

    def _parse_svn_log_line(self, line: str, current_revision: Dict) -> Dict:
        """Parse a single line from SVN log output"""
        logging.debug(f"Parsing SVN log line: '{line}'")
        if line.startswith("r"):
            logging.debug("Found revision header")
            return self._parse_revision_header(line)
        elif line.startswith("Changed paths:"):
            logging.debug("Found changed paths marker")
            return current_revision
        elif line.startswith("   "):
            return self._parse_revision_detail(line, current_revision)
        return current_revision

    def _parse_revision_header(self, line: str) -> Dict:
        """Parse the revision header line"""
        logging.debug(f"Parsing revision header: '{line}'")
        parts = line.split(" | ")
        if len(parts) >= 4:
            revision = parts[0][1:]
            logging.debug(f"Found revision {revision} by {parts[1]}")
            return {
                "revision": revision,
                "author": parts[1],
                "date": parts[2],
                "message": "",
                "changed_paths": [],
            }
        logging.warning("Invalid revision header format")
        return {}

    def _parse_revision_detail(self, line: str, current_revision: Dict) -> Dict:
        """Parse revision details (changed paths or commit message)"""
        logging.debug(f"Parsing revision detail: '{line}'")
        if "message" not in current_revision:
            path = line.strip()
            logging.debug(f"Adding changed path: {path}")
            current_revision["changed_paths"].append(path)
        else:
            current_revision["message"] += line.strip() + "\n"
        return current_revision

    def verify_file_content(self, svn_content: str, git_content: str) -> bool:
        """Verify that file content matches between SVN and Git content strings"""
        logging.debug("Calculating content hashes for comparison")
        svn_hash = hashlib.md5(svn_content.encode()).hexdigest()
        git_hash = hashlib.md5(git_content.encode()).hexdigest()
        return svn_hash == git_hash
        match = svn_hash == git_hash
        if not match:
            logging.debug(
                f"File content mismatch - SVN hash: {svn_hash}, Git hash: {git_hash}"
            )
        return match

    def init_git_repo(self):
        """Initialize the Git repository"""
        logging.info(f"Initializing Git repository at {self.git_repo_path}")
        if not os.path.exists(self.git_repo_path):
            logging.debug(f"Creating directory {self.git_repo_path}")
            os.makedirs(self.git_repo_path)
        logging.debug(f"Changing to directory {self.git_repo_path}")
        os.chdir(self.git_repo_path)
        try:
            logging.info("Initializing git-svn repository")
            subprocess.run(["git", "svn", "init", self.svn_repo_url, "--stdlayout"], check=True)
            logging.info("Fetching SVN history")
            subprocess.run(["git", "svn", "fetch"], check=True)
            logging.info("Git repository successfully initialized")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to initialize Git repository: {str(e)}")
            raise

    def verify_revision_count(self) -> bool:
        """Verify that Git and SVN have same number of revisions"""
        logging.info("Verifying revision count between Git and SVN")
        git_log = subprocess.run(
            ["git", "log", "--pretty=format:%H %s"], capture_output=True, text=True
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
        """Verify commit message matches between Git and SVN"""
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
        match = svn_message.strip() in git_msg
        if not match:
            logging.warning(f"Commit message mismatch for Git commit {git_commit}")
            logging.debug(f"SVN message: {svn_message}")
            logging.debug(f"Git message: {git_msg}")
        else:
            logging.debug("Commit message verified successfully")
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
            logging.info("Retrieving SVN revisions...")
            self.svn_revisions = self.get_svn_revisions()

            # Initialize git-svn
            if not os.path.exists(self.git_repo_path):
                logging.info("Initializing new Git repository...")
                self.init_git_repo()

            logging.info(f"Changing to Git repository directory: {self.git_repo_path}")
            os.chdir(self.git_repo_path)

            if not self.verify_revision_count():
                # Verify each revision
                rev_num = self.svn_revisions["revision"]
                # Get Git commit for SVN revision
                git_commit = self.get_git_commit_for_revision(rev_num)
                if not git_commit:
                    print(
                        f"Error: Could not find Git commit for SVN revision {rev_num}"
                    )
                    return False

                # Verify commit message
                if not self.verify_commit_message(
                    git_commit, self.svn_revisions["message"]
                ):
                    return False

                # Verify files for this revision
                if not self.verify_changed_files(
                    rev_num, git_commit, self.svn_revisions["changed_paths"]
                ):
                    return False
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
