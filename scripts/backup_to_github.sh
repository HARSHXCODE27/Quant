#!/bin/bash
# Back up everything to GitHub: commit all changes and push. Run manually:
#   ./scripts/backup_to_github.sh                  (message: "Backup YYYY-MM-DD HH:MM")
#   ./scripts/backup_to_github.sh "what changed"   (your own message)
# Never force-pushes or deletes; if nothing changed it only pushes any
# earlier commits that haven't reached GitHub yet.

cd "$(dirname "$0")/.." || exit 1

MESSAGE="${1:-Backup $(date '+%Y-%m-%d %H:%M')}"

git add -A
if git diff --cached --quiet; then
    echo "No changes to commit."
else
    git commit -q -m "$MESSAGE" && echo "Committed: $MESSAGE"
fi

git push origin HEAD
