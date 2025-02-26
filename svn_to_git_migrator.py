#!/usr/bin/env python3

import os
import re
import shutil
import sys
from subprocess import CalledProcessError
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, NamedTuple
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

class RevisionInfo(NamedTuple):
    rev_num: str
    message: str

class MappingErrors(NamedTuple):
    missing: List[RevisionInfo]
    mismatch: List[RevisionInfo]
    file_mismatch: List[RevisionInfo]

class SVNToGitMigrator:
    svn_repo_url: str
    git_repo_path: str
    svn_repo_path: str
    git_cmd_prefix: List[str]
    svn_revisions: List[Dict]
    cache_manager: CacheManager
    
    def __init__(self, svn_repo_url: str, git_repo_path: str, svn_repo_path: str):
        self.cache_manager = CacheManager()
        """
        Initialize the SVN to Git migrator

        Args:
            svn_repo_url: URL of the SVN repository
            git_repo_path: Local path where Git repository will be created
        """
        logging.info(f"Initializing SVN to Git migrator with SVN repo: {svn_repo_url}")
        self.svn_repo_url = svn_repo_url.rstrip('/ ')        
        self.git_repo_path = git_repo_path
        self.svn_repo_path = svn_repo_path
        self.git_cmd_prefix = ["git", "-C", self.git_repo_path]
        self.svn_revisions = []
        logging.debug(f"Git repository will be created at: {git_repo_path}")

    def cleanup(self):
        """Clean all the stale files and directories"""
        logging.info("Cleaning up stale files and directories")
        if os.path.exists(self.git_repo_path):
            logging.debug(f"Removing directory {self.git_repo_path}")
            shutil.rmtree(self.git_repo_path)
        if os.path.exists(self.svn_repo_path):
            logging.debug(f"Removing directory {self.svn_repo_path}")
            shutil.rmtree(self.svn_repo_path)

        # Remove the cache directory
        self.cache_manager.cleanup()
        
    def get_svn_revisions(self) -> List[Dict]:
        """Get all SVN revisions with their metadata"""

        logging.debug("Retrieving SVN revision history")
        cmd = ["svn", "log", "--xml", "--verbose", self.svn_repo_url]
            
        logging.debug("Querying SVN server")
        result = self.cache_manager.cached_run(cmd)

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
                    if path.get("kind") != "file":
                        continue
                    action = path.get("action")
                    file_path = path.text

                    revision["changed_paths"].append((action, file_path))
            
            revisions.append(revision)

        return revisions

    def get_git_revisions(self) -> List[Dict]:
        """Get all Git revisions with their metadata"""
        logging.debug("Retrieving Git revision history")
        cmd = [*self.git_cmd_prefix, "log", "--all", "--pretty=format:'<commit><hash>%H</hash><author>%an</author><date>%ai</date><message>%B</message></commit>'"]
        result = self.cache_manager.cached_run(cmd)
        
        if result.returncode != 0:
            logging.error(f"Failed to get Git log: {result.stderr}")
            raise Exception(f"Failed to get Git log: {result.stderr}")
        
        # Parse Git log output
        logging.debug("Parsing Git revision logs")
        revisions = []
        xml_log = f"<git_logs>{result.stdout}</git_logs>"

        root = ET.fromstring(xml_log)
        for commit in root.findall("commit"):
            revision = {
                "hash": commit.find("hash").text,
                "author": commit.find("author").text,
                "date": commit.find("date").text,
                "message": commit.find("message").text
            }
            # extract the svn revision from the message
            svn_revision_match = re.search(r'git-svn-id.*@(\d+)', revision["message"])
            if svn_revision_match:
                revision["revision"] = svn_revision_match.group(1)
                # strip the git-svn-id: line from the message
                revision["message"] = re.sub(r'git-svn-id.*', '', revision["message"]).strip()

            logging.debug(f"Found Git commit {revision["hash"]} for SVN revision {revision["revision"]}")
            revisions.append(revision)

        return revisions
        

    def verify_file_content(self, source: str, target: str) -> bool:
        """Compare files at source and target"""
        logging.debug(f"Comparing files at {source} and {target}")
        cmd = ["diff", source, target]
        result = self.cache_manager.cached_run(cmd)
        content_match = result.returncode == 0
        if not content_match:
            logging.error(f"Files at {source} and {target} are different")
            logging.error(f"Diff: {result.stdout}")
        else:
            logging.debug(f"Files at {source} and {target} are the same")
        
        return content_match

    def clone_svn_repo(self):
        """Clone the SVN repository"""
        logging.info(f"Initializing SVN repository at {self.svn_repo_path}")
        if not os.path.exists(self.svn_repo_path):
            logging.debug(f"Creating directory {self.svn_repo_path}")
            os.makedirs(self.svn_repo_path)

        logging.info("Clone SVN repository")
        cmd = ["svn", "checkout", self.svn_repo_url, self.svn_repo_path]
        self.cache_manager.cached_run(cmd, check=True)
        logging.info("SVN repository successfully Cloned")
    
    def clone_git_svn_repo(self):
        """Clone the Git repository"""
        logging.info(f"Initializing Git SVN repository at {self.git_repo_path}")
        if not os.path.exists(self.git_repo_path):
            logging.debug(f"Creating directory {self.git_repo_path}")
            os.makedirs(self.git_repo_path)

        logging.info("Clone Git SVN repository")
        cmd = [*self.git_cmd_prefix, "svn", "clone", self.svn_repo_url, "--stdlayout", "."]
        self.cache_manager.cached_run(cmd, check=True)
        logging.info("Git SVN repository successfully Cloned")

    def verify_revision_count(self) -> bool:
        """Verify that Git and SVN have same number of revisions"""
        logging.info("Verifying revision count between Git and SVN")        
        git_commit_count = len(self.git_revisions)
        svn_revision_count = len(self.svn_revisions)

        if git_commit_count != svn_revision_count:
            logging.warning(
                f"Revision count mismatch - Git commits: {git_commit_count}, "
                f"SVN revisions: {svn_revision_count}"
            )
            return False
        
        logging.info("Revision count matches between Git and SVN")
        return True

    def get_git_commit_for_revision(self, rev_num: str) -> str:
        """Get Git commit hash for SVN revision number"""
        logging.debug(f"Looking up Git commit for SVN revision {rev_num}")

        commit_for_rev = [commit for commit in self.git_revisions if commit["revision"] == rev_num]
        
        if len(commit_for_rev) == 0:
            logging.warning(f"No Git commit found for SVN revision {rev_num}")
            return None
        
        logging.debug(f"Found Git commit {commit_for_rev[0]} for revision {rev_num}")
        return commit_for_rev[0]

    def verify_changed_files(
        self, rev_num: str, git_commit: str, changed_paths: List[str]
    ) -> bool:
        """Verify changed files match between Git and SVN"""
        def strip_branch_info(path: str) -> str:
            parts = path.split('/')
            start_index = 1
            if parts[1] == 'trunk':
                start_index = 2
            elif parts[1] == 'branches' and len(parts) > 2:
                start_index = 3
            elif parts[1] == 'tags' and len(parts) > 2:
                start_index = 3

            return '/' + '/'.join(parts[start_index:])
        logging.info(f"Verifying changed files for revision {rev_num}")
        logging.debug(f"Files to verify: {changed_paths}")
        for (action, file_path) in changed_paths:
            if action == "A" or action == "M":
                logging.debug(f"Verifying file: {file_path}")
                svn_file_path = file_path
                git_file_path = strip_branch_info(file_path)
                if not self._verify_single_file(rev_num, git_commit['hash'], svn_file_path, git_file_path):
                    logging.warning(f"File verification failed: {file_path}")
                    return False
                
        logging.debug(f"All changed files verified successfully for revision {rev_num} and Git commit {git_commit}")
        return True

    def _verify_single_file(
        self, rev_num: str, commit_hash: str, svn_file_path: str, git_file_path: str
    ) -> bool:
        """Verify a single file matches between Git and SVN"""
        logging.info(f"Verifying single file: {svn_file_path} at revision {rev_num}")
        
        # svn checkout the version rev_num
        svn_cmd = ["svn", "checkout", "@".join([self.svn_repo_url,rev_num]), self.svn_repo_path]

        logging.debug(f"Getting SVN revision for {rev_num}")
        self.cache_manager.cached_run(svn_cmd, check=True).stdout

        # Try to get cached Git content
        git_cmd = [*self.git_cmd_prefix, "switch", "--detach", f"{commit_hash}"]
        
        logging.debug(f"Getting Git commit {commit_hash}")
        self.cache_manager.cached_run(git_cmd, check=True).stdout

        result = self.verify_file_content(f"{self.svn_repo_path}{svn_file_path}", f"{self.git_repo_path}{git_file_path}")

        if not result:
            logging.error(
                f"File content mismatch for {svn_file_path}@{rev_num}, and {git_file_path}@{commit_hash}"
            )
        else:
            logging.debug(f"File content verified successfully: {svn_file_path}@{rev_num}, and {git_file_path}@{commit_hash}")

        return result

    def has_errors(self, mapping_error: MappingErrors) -> bool:
        return len(mapping_error.missing) > 0 or len(mapping_error.mismatch) > 0 or len(mapping_error.file_mismatch) > 0

    def verify_svn_git_mapping(self) -> MappingErrors:
        """Verify SVN to Git mapping of revisions"""
        missing_revisions = []
        mismatch_revisions = []
        file_mismatch_revisions = []

        # Verify each revision
        for revision in self.svn_revisions:
            rev_num = revision["revision"]
            message = revision["message"]
            changed_paths = revision["changed_paths"]
            
            # Get Git commit for SVN revision
            git_commit = self.get_git_commit_for_revision(rev_num)
            if git_commit is None:
                logging.error(f"Could not find Git commit for SVN revision {rev_num}: {message}")
                missing_revisions.append((rev_num, message))
                continue
            
            logging.debug(f"Git commit for revision {rev_num}: {git_commit['hash']}")

            # Verify commit message and track mapping
            if git_commit["message"] != message:
                logging.error(f"Commit message verification failed for revision {rev_num}")
                logging.error(f"Expected: [{message}]")
                logging.error(f"Actual: [{git_commit['message']}]")
                mismatch_revisions.append((rev_num, message, git_commit["message"]))

            # Verify files for this revision
            if not self.verify_changed_files(rev_num, git_commit, changed_paths):
                logging.error(f"File verification failed for revision {rev_num}")
                file_mismatch_revisions.append((rev_num, message, git_commit["message"]))

        return MappingErrors(missing=missing_revisions, mismatch=mismatch_revisions, file_mismatch=file_mismatch_revisions)
        
    def migrate(self) -> bool:
        """Perform the SVN to Git migration with verification"""
        success = True
        logging.info("Starting SVN to Git migration process")
        try:            
            self.svn_revisions = self.get_svn_revisions()
            logging.info(f"Retrieved {len(self.svn_revisions)} SVN revisions")

            if not os.path.exists(os.path.join(self.svn_repo_path, ".svn")):
                logging.info("Creating local copy of Svn repository...")
                self.clone_svn_repo()

            if not os.path.exists(os.path.join(self.git_repo_path,".git")):
                logging.info("Clone to Git repository...")
                self.clone_git_svn_repo()

            self.git_revisions = self.get_git_revisions()
            logging.info(f"Retrieved {len(self.git_revisions)} Git revisions")

            # Verify revision count matches
            if not self.verify_revision_count():
                logging.error("Revision count verification failed.")
                success = False
                
            # Verify each revision
            mapping_errors = self.verify_svn_git_mapping()
            if not self.has_errors(mapping_errors):
                logging.error("SVN to Git mapping verification failed.")
                # write mapping errors to log
                logging.error(f"Missing revisions: {mapping_errors.missing}")
                logging.error(f"Mismatch revisions: {mapping_errors.mismatch}")
                logging.error(f"File mismatch revisions: {mapping_errors.file_mismatch}")
                success = False
                
            if success:
                logging.info("Migration completed successfully!")
            else:
                logging.error("Migration failed.")
            
            return success
        except CalledProcessError as cpe:
            logging.error(f"Error during migration: {str(cpe.stderr)}")
            return False
        except Exception as e:
            logging.error(f"Error during migration: {str(e)}")
            logging.error(f"Migration failed with exception: {e}", exc_info=True)
            return False


def main():
    logging.info("Starting SVN to Git migration tool")
    if len(sys.argv) != 3:
        logging.error("Invalid number of arguments provided")
        print("Usage: python svn_to_git_migrator.py <svn_repo_url> <clone_repo_path>")
        sys.exit(1)

    svn_repo_url = sys.argv[1]
    clone_repo_path = sys.argv[2]

    git_repo_path = os.path.join(clone_repo_path, "git_repo")
    svn_repo_path = os.path.join(clone_repo_path, "svn_repo")

    migrator = SVNToGitMigrator(svn_repo_url, git_repo_path, svn_repo_path)
    
    success = migrator.migrate()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
