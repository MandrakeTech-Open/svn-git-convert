# SVN to Git Migration Tool

This tool helps migrate SVN repositories to Git while ensuring data integrity through various verification steps:

## Verification Features

1. **Commit Message Verification**
   - Exact matching between SVN revision messages and Git commit messages
   - Whitespace normalization to prevent false negatives
   - Maintains a mapping between SVN revisions and Git commits

2. **File Change Verification**
   - Verifies all changed files in each revision
   - Compares file content between SVN and Git versions
   - Handles both added (A) and modified (M) files

3. **Revision Tracking**
   - Maps SVN revisions to corresponding Git commits
   - Ensures all revisions are properly migrated
   - Verifies revision count matches between SVN and Git

## Usage

```python
migrator = SVNToGitMigrator(svn_repo_url, git_repo_path)
success = migrator.migrate()
```

# initialize the subversion repo
SVN_URL="svn://svn-server/myrepo" ./init-test-svn.sh