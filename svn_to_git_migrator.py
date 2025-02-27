#!/usr/bin/env python3

import os
import re
import shutil
import sys
from subprocess import CalledProcessError
import logging
import xml.etree.ElementTree as ET
from typing import NamedTuple, TypedDict
from cache_manager import CacheManager

# Configure logging
# Set up file handler for all logs
file_handler = logging.FileHandler("run.log")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)

# Set up console handler with higher threshold
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)

# Configure root logger
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(file_handler)
logging.getLogger().addHandler(console_handler)

class PathInfo(TypedDict):
    action: str
    kind: str
    path: str

class GitCommitInfo(TypedDict):
    commit_hash: str
    revision: str
    author: str
    date: str
    message: str
    changed_paths: list[PathInfo]


class SVNRevisionInfo(TypedDict):
    revision: str
    author: str
    date: str
    message: str
    changed_paths: list[PathInfo]


class MappingErrors[T: GitCommitInfo | SVNRevisionInfo](NamedTuple):
    missing: list[T]
    mismatch: list[T]
    file_mismatch: list[T]


def _get_revision_info_for_logentry(logentry: ET.Element) -> SVNRevisionInfo:
    """
    Get SVN revision info from logentry element
    """

    revision = logentry.get("revision")
    author = logentry.find("author").text if logentry.find("author") is not None else ""
    date = logentry.find("date").text
    message = logentry.find("msg").text if logentry.find("msg") is not None else ""

    revision_impact_paths = logentry.find("paths")

    if revision_impact_paths is None:
        changed_paths = []
        logging.debug(f"No paths found for revision {revision}")
    else:
        changed_paths = [
            PathInfo(action=path.get("action"), path=path.text, kind=path.get("kind"))
            for path in revision_impact_paths
        ]

    return SVNRevisionInfo(
        revision=revision,
        author=author.strip(),
        date=date.strip(),
        message=message.strip(),
        changed_paths=changed_paths,
    )


def _get_commit_info_for_logentry(logentry: ET.Element) -> GitCommitInfo:
    """
    Get Git commit info from logentry element
    """
    commit_hash = logentry.find("hash").text
    author = logentry.find("author").text
    date = logentry.find("date").text
    message = logentry.find("message").text

    msg_split = message.split("git-svn-id: ", 1)
    message = msg_split[0].strip()
    if len(msg_split) > 1:
        svn_revision_line = msg_split[1].strip()
        revision_line = svn_revision_line.split(" ")
        revision = revision_line[0]
    else:
        svn_revision_line = "(None)"
        revision = None

    logging.debug(f"Revision found for commit {commit_hash}: {revision}: {svn_revision_line}")

    # handle special case: 'Creating standard repository layout'
    if message == "Create initial structure":
        logging.info("Special case: Replace message 'Create initial structure' with 'Creating standard repository layout'")
        message = "Creating standard repository layout"

    commit_impact_paths = logentry.find("paths")

    if commit_impact_paths is None:
        changed_paths = []
        # TODO: Populate paths for commit {commit_hash}
    else:
        changed_paths = [
            PathInfo(action=path.get("action"), path=path.text, kind=path.get("kind"))
            for path in commit_impact_paths
        ]

    return GitCommitInfo(
        commit_hash=commit_hash,
        revision=revision,
        author=author.strip(),
        date=date.strip(),
        message=message.strip(),
        changed_paths=changed_paths,
    )


def get_svn_revisions_from_xml(xml_output: str) -> list[SVNRevisionInfo]:
    """Parse SVN XML log output and return a list of SVNRevisionInfo objects."""
    return [
        _get_revision_info_for_logentry(logentry)
        for logentry in ET.fromstring(xml_output).findall("logentry")
    ]


def get_git_commits_from_xml(xml_output: str) -> list[GitCommitInfo]:
    """Parse Git XML log output and return a list of GitCommitInfo objects."""
    xml_log = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><git_logs>{xml_output}</git_logs>"
    return [
        _get_commit_info_for_logentry(log)
        for log in ET.fromstring(xml_log).findall("commit")
    ]


class SVNToGitMigrator:
    svn_repo_url: str
    git_repo_path: str
    svn_repo_path: str
    git_cmd_prefix: list[str]
    git_commits: dict[str, GitCommitInfo]
    svn_revisions: dict[str, SVNRevisionInfo]

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
        self.svn_repo_url = svn_repo_url.rstrip("/ ")
        self.git_repo_path = git_repo_path
        self.svn_repo_path = svn_repo_path
        self.git_cmd_prefix = ["git", "-C", self.git_repo_path]
        self.svn_revisions = {}
        self.git_commits = {}
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

    def get_svn_revisions(self) -> dict[str, SVNRevisionInfo]:
        """Get all SVN revisions with their metadata"""
        
        last_rev_cmd = ["svn", "info", "--show-item", "revision", self.svn_repo_url]
        result = self.cache_manager.cached_run(last_rev_cmd, check=True).stdout.strip()
        last_rev = int(result)

        logging.info(f"Last SVN revision: {last_rev}")

        revision_accumulator: dict[str. SVNRevisionInfo] = {}        
        
        batch_size = 100
        range_list: list[tuple[int, int]] = []
        rev_start = 1
        while rev_start < last_rev:
            rev_end = min(rev_start + batch_size - 1, last_rev)
            range_list.append((rev_start, rev_end))
            rev_start = rev_end + 1
            
        for rev_start, rev_end in range_list:
            logging.debug("Retrieving SVN revision history")
            cmd = ["svn", "log", "--xml", "--verbose", "-r", f"{rev_start}:{rev_end}", self.svn_repo_url]

            logging.debug("Querying SVN server")
            result = self.cache_manager.cached_run(cmd)

            if result.returncode != 0:
                logging.error(f"Failed to get SVN log: {result.stderr}")
                raise Exception(f"Failed to get SVN log: {result.stderr}")

            logging.debug("Parsing SVN revision logs")
            
            revisions = [
                _get_revision_info_for_logentry(logentry)
                for logentry in ET.fromstring(result.stdout).findall("logentry")
            ]

            logging.debug(f"Found {len(revisions)} SVN revisions betweeen {rev_start} and {rev_end}")
            
            for revision in revisions:
                revision_accumulator[revision["revision"]] = revision
            
            logging.debug(f"Retrieved {len(revision_accumulator)} SVN revisions till {rev_end}")

            rev_start = rev_end + 1
        
        return revision_accumulator

    def get_git_commits(self) -> dict[str, GitCommitInfo]:
        """Get all Git commits with their metadata"""
        logging.debug("Retrieving Git revision history")
        cmd = [
            *self.git_cmd_prefix,
            "log",
            "--all",
            "--pretty=format:'<commit><hash>%H</hash><author>%an</author><date>%ai</date><message>%B</message></commit>'",
        ]
        result = self.cache_manager.cached_run(cmd)

        if result.returncode != 0:
            logging.error(f"Failed to get Git log: {result.stderr}")
            raise Exception(f"Failed to get Git log: {result.stderr}")

        logging.debug("Parsing Git revision logs")
        commits = get_git_commits_from_xml(result.stdout)
        logging.debug(f"Found {len(commits)} Git commits")

        return { commits["commit_hash"]: commits for commits in commits }

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
        cmd = [
            *self.git_cmd_prefix,
            "svn",
            "clone",
            self.svn_repo_url,
            "--stdlayout",
            ".",
        ]
        self.cache_manager.cached_run(cmd, check=True)
        logging.info("Git SVN repository successfully Cloned")

    def get_git_commit_for_revision(self, rev_num: str) -> GitCommitInfo | None:
        """Get Git commit hash for SVN revision number"""
        logging.debug(f"Looking up Git commit for SVN revision {rev_num}")

        commit_list_for_rev = list[GitCommitInfo](
            filter(lambda commit: commit["revision"] == rev_num, self.git_commits.values())
        )

        if len(commit_list_for_rev) == 0:
            logging.warning(f"No Git commit found for SVN revision [{rev_num}]")
            return None
        
        commit_for_rev = commit_list_for_rev[0]

        if len(commit_list_for_rev) > 1:
            logging.warning(f"Multiple Git commits found for SVN revision [{rev_num}]: {commit_list_for_rev}")

        logging.debug(
            f"Found git commit for revision {rev_num}: {commit_for_rev['commit_hash']}"
        )

        return commit_for_rev

    def get_svn_revision_for_commit(self, commit_hash: str) -> SVNRevisionInfo | None:
        """Get SVN revision number for Git commit hash"""
        logging.debug(f"Looking up SVN revision for Git commit {commit_hash}")

        commit = self.git_commits[commit_hash]

        if commit is None:
            logging.error(f"No Git commit entry [{commit_hash}]")
            return None
        
        rev_for_commit = commit["revision"]
        
        if rev_for_commit is None:
            logging.warning(f"No SVN revision found for Git commit {commit_hash}")
            return None

        # if self.svn_revisions has the key rev_for_commit, then fetch its value
        # else, return None
        revision = self.svn_revisions[rev_for_commit] if rev_for_commit in self.svn_revisions else None
        
        if revision is None:
            logging.error(f"No SVN revision entry [{rev_for_commit}] found for Git commit {commit_hash}")
            return None

        return revision
    
    def verify_changed_files(
        self, revision: SVNRevisionInfo, commit: GitCommitInfo
    ) -> bool:
        """Verify changed files match between Git and SVN"""

        def strip_branch_info(path: str) -> str:
            parts = path.split("/")
            start_index = 1
            if parts[1] == "trunk":
                start_index = 2
            elif parts[1] == "branches" and len(parts) > 2:
                start_index = 3
            elif parts[1] == "tags" and len(parts) > 2:
                start_index = 3

            return "/" + "/".join(parts[start_index:])

        rev_num = revision['revision']
        commit_hash = commit['commit_hash']
        logging.info(f"Verifying changed files for revision {rev_num} and Git commit {commit_hash}")
        logging.debug(f"Files to verify: {revision["changed_paths"]}")
        changed_paths = revision["changed_paths"]
        for action, file_path, kind in changed_paths:
            if kind != "file":
                logging.debug(f"Skipping non-file change: {file_path}")
                continue

            if action == "A" or action == "M":
                logging.debug(f"Verifying file: {file_path}")
                svn_file_path = file_path
                git_file_path = strip_branch_info(file_path)
                if not self._verify_single_file(
                    rev_num, commit_hash, svn_file_path, git_file_path
                ):
                    logging.warning(f"File verification failed: {file_path}")
                    return False

        logging.debug(
            f"All changed files verified successfully for revision {rev_num} and Git commit {commit_hash}"
        )
        return True

    def _verify_single_file(
        self, rev_num: str, commit_hash: str, svn_file_path: str, git_file_path: str
    ) -> bool:
        """Verify a single file matches between Git and SVN"""
        logging.info(f"Verifying single file: {svn_file_path} at revision {rev_num}")

        # svn checkout the version rev_num
        svn_cmd = [
            "svn",
            "checkout",
            "@".join([self.svn_repo_url, rev_num]),
            self.svn_repo_path,
        ]

        logging.debug(f"Getting SVN revision for {rev_num}")
        self.cache_manager.cached_run(svn_cmd, check=True).stdout

        # Try to get cached Git content
        git_cmd = [*self.git_cmd_prefix, "switch", "--detach", f"{commit_hash}"]

        logging.debug(f"Getting Git commit {commit_hash}")
        self.cache_manager.cached_run(git_cmd, check=True).stdout

        result = self.verify_file_content(
            f"{self.svn_repo_path}{svn_file_path}",
            f"{self.git_repo_path}{git_file_path}",
        )

        if not result:
            logging.error(
                f"File content mismatch for {svn_file_path}@{rev_num}, and {git_file_path}@{commit_hash}"
            )
        else:
            logging.debug(
                f"File content verified successfully: {svn_file_path}@{rev_num}, and {git_file_path}@{commit_hash}"
            )

        return result

    def has_errors(self, mapping_error: MappingErrors) -> bool:
        return (
            len(mapping_error.missing) > 0
            or len(mapping_error.mismatch) > 0
            or len(mapping_error.file_mismatch) > 0
        )

    def verify_svn_git_mapping(self) -> MappingErrors:
        """Verify SVN to Git mapping of revisions"""
        missing_revisions = []
        mismatch_revisions = []
        file_mismatch_revisions = []

        # Verify each revision
        for revision in self.svn_revisions.values():
            rev_num = revision["revision"]
            message = revision["message"]

            # Get Git commit for SVN revision
            git_commit = self.get_git_commit_for_revision(rev_num)
            if git_commit is None:
                logging.error(
                    f"Could not find Git commit for SVN revision {rev_num}: {message}"
                )
                missing_revisions.append((rev_num, message))
                continue

            logging.debug(f"Git commit for revision {rev_num}: {git_commit['commit_hash']}")

            # Verify commit message and track mapping
            if git_commit["message"] != message:
                logging.error(
                    f"Commit message verification failed for revision {rev_num}"
                )
                logging.error(f"Expected: [{message}]")
                logging.error(f"Actual: [{git_commit['message']}]")
                mismatch_revisions.append((rev_num, message, git_commit["message"]))

            # Verify files for this revision
            if not self.verify_changed_files(revision, git_commit):
                logging.error(f"File verification failed for revision {rev_num}")
                file_mismatch_revisions.append(
                    (rev_num, message, git_commit["message"])
                )

        return MappingErrors(
            missing=missing_revisions,
            mismatch=mismatch_revisions,
            file_mismatch=file_mismatch_revisions,
        )

    def verify_git_svn_mapping(self) -> MappingErrors:
        """Verify Git to SVN mapping of revisions"""
        missing_commits = []
        mismatch_commits = []
        file_mismatch_commits = []
        # Verify each commit
        for commit in self.git_commits.values():
            commit_hash = commit["commit_hash"]
            message = commit["message"]
            changed_paths = commit["changed_paths"]
            # Get SVN revision for Git commit
            svn_rev_num = commit["revision"]
            svn_revision = self.get_svn_revision_for_commit(commit_hash)
            if svn_revision is None:
                logging.error(
                    f"Could not find SVN revision details for Git commit {commit_hash}: {message} : [{svn_rev_num}]"
                )
                missing_commits.append((commit_hash, message))
                continue

            logging.debug(f"SVN revision for commit {commit_hash}: {svn_rev_num}")
            # Verify commit message and track mapping
            if svn_revision["message"] != message:
                logging.error(
                    f"Commit message verification failed for commit {commit_hash}"
                )
                logging.error(f"Expected: [{message}]")
                logging.error(f"Actual: [{svn_revision["message"]}]")
                mismatch_commits.append((commit_hash, message, svn_rev_num))

            # Verify files for this commit
            if not self.verify_changed_files(svn_revision, commit):
                logging.error(f"File verification failed for commit {commit_hash}")
                file_mismatch_commits.append((commit_hash, message, svn_rev_num))

        return MappingErrors(
            missing=missing_commits,
            mismatch=mismatch_commits,
            file_mismatch=file_mismatch_commits,
        )

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

            if not os.path.exists(os.path.join(self.git_repo_path, ".git")):
                logging.info("Clone to Git repository...")
                self.clone_git_svn_repo()

            self.git_commits = self.get_git_commits()
            logging.info(f"Retrieved {len(self.git_commits)} Git revisions")

            # Verify each revision
            mapping_revision_errors = self.verify_svn_git_mapping()
            if self.has_errors(mapping_revision_errors):
                logging.error("SVN to Git mapping verification failed.")
                # write mapping errors to log
                logging.error(f"Missing revisions: {mapping_revision_errors.missing}")
                logging.error(f"Mismatch revisions: {mapping_revision_errors.mismatch}")
                logging.error(
                    f"File mismatch revisions: {mapping_revision_errors.file_mismatch}"
                )
                success = False

            mapping_commit_errors = self.verify_git_svn_mapping()
            if self.has_errors(mapping_commit_errors):
                logging.error("Git to SVN mapping verification failed.")
                # write mapping errors to log
                logging.error(f"Missing commits: {mapping_commit_errors.missing}")
                logging.error(f"Mismatch commits: {mapping_commit_errors.mismatch}")
                logging.error(
                    f"File mismatch commits: {mapping_commit_errors.file_mismatch}"
                )
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

    return 0 if success else 1


if __name__ == "__main__":
    main()
