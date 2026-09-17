#!/bin/bash
# Job Hunter setup (macOS). Double-click in Finder to run.
# First time only: if macOS warns it's from an unidentified developer,
# right-click this file -> Open once to approve it.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Job Hunter setup (macOS)"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is not available either."
        echo "Install Python 3 manually from https://python.org, then re-run install.command."
        read -p "Press Enter to close..." _
        exit 1
    fi
    echo "Installing Python 3 via Homebrew..."
    brew install python3
fi

python3 scripts/setup-hermes-profile.py
RC=$?

echo
if [ "$RC" -ne 0 ]; then
    echo "Setup reported an error above."
fi
read -p "Press Enter to close..." _
exit $RC
