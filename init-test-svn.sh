#!/bin/bash

# Set up repository and working directory
if [ -z "$SVN_URL" ]; then
    echo "Repository path does not exist: $SVN_URL" >&2
    exit 1
fi

WORKING_DIR=$(mktemp -d)

# Checkout the repository
svn checkout $SVN_URL/trunk $WORKING_DIR

# Function to commit changes
commit_changes() {
    local message=$1
    echo "Making changes: $message" >> $WORKING_DIR/file.txt
    svn status $WORKING_DIR/file.txt
    if ! svn status $WORKING_DIR/file.txt | grep -q '^[AM]'; then
        svn add $WORKING_DIR/file.txt
    fi
    echo "Committing changes"
    svn commit -m "$message" $WORKING_DIR
}

# Create initial file and commit
echo "Initial content" > $WORKING_DIR/file.txt
commit_changes "Initial commit"

# Simulate feature branches and merges
for i in {1..10}; do
    svn copy -m "Create feature branch feature-$i" $SVN_URL/trunk $SVN_URL/branches/feature-$i
    svn switch $SVN_URL/branches/feature-$i $WORKING_DIR
    for j in {1..5}; do
        commit_changes "Feature-$i change $j"
    done
    svn switch $SVN_URL/trunk $WORKING_DIR
    svn merge --reintegrate $SVN_URL/branches/feature-$i $WORKING_DIR
    commit_changes "Merge feature-$i into trunk"
    svn delete -m "Delete feature branch feature-$i" $SVN_URL/branches/feature-$i
done

# Simulate release branches
for i in {1..5}; do
    svn copy -m "Create release branch release-$i" $SVN_URL/trunk $SVN_URL/branches/release-$i
    svn switch $SVN_URL/branches/release-$i $WORKING_DIR
    for j in {1..5}; do
        commit_changes "Release-$i change $j"
    done
    svn switch $SVN_URL/trunk $WORKING_DIR
    svn merge --reintegrate $SVN_URL/branches/release-$i $WORKING_DIR
    commit_changes "Merge release-$i into trunk"
    svn delete -m "Delete release branch release-$i" $SVN_URL/branches/release-$i
done

# Simulate tags
for i in {1..5}; do
    svn copy -m "Create tag tag-$i" $SVN_URL/trunk $SVN_URL/tags/tag-$i
done

echo "Subversion branching simulation complete with at least 100 revisions."