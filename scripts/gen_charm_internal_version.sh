#!/bin/sh

if git --version > /dev/null; then
    # Compute base files
    BASE=$(git ls-files -s)
    # Compute diff files
    DIFF=$(git diff --raw)
    # Compute staged files
    STAGED=$(git diff --raw --staged)

    HASH=$(echo $BASE $DIFF $STAGED | git hash-object --stdin | cut -c 1-8)
    echo $HASH > charm_internal_version
    echo "Hash for this build is ${HASH}"
else
    echo "Git is not installed"
    exit 1
fi
