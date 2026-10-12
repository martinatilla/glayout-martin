#!/usr/bin/env bash
# Fetch the AnalogGenie netlists (MIT licence) at a pinned commit, text files only.
#
# A blobless clone with a sparse checkout downloads only the files matched below:
# netlists, port lists, page references and the categorisation file. The textbook
# scans (Book<id>.png) and schematic captures (Cadence<id>.png), which make up most
# of the ~120 MB repository, are never downloaded.
#
#   learn/data/fetch_analoggenie.sh            # into learn/external/AnalogGenie
set -euo pipefail

URL=https://github.com/xz-group/AnalogGenie
SHA=efc25358939c6bedd247f28d3df61066964f3a90     # the commit gLayout PR #127 cites
DEST="$(cd "$(dirname "$0")/.." && pwd)/external/AnalogGenie"

if [ ! -d "$DEST/.git" ]; then
    git clone --quiet --filter=blob:none --no-checkout --sparse "$URL" "$DEST"
fi
cd "$DEST"
git sparse-checkout set --no-cone \
    '/Dataset/*/*.cir' '/Dataset/*/Port*.txt' '/Dataset/*/Pagenumber*.txt' \
    '/Dataset/data_categorization.md' '/LICENSE*' '/README.md'
git -c advice.detachedHead=false checkout --quiet "$SHA"

echo "AnalogGenie at $(git rev-parse HEAD)"
echo "entries: $(ls Dataset | grep -c '^[0-9]*$'), netlists: $(ls Dataset/*/*.cir | wc -l)"
echo "png files: $(find Dataset -name '*.png' | wc -l) (expected 0)"
du -sh --exclude=.git . 2>/dev/null || du -sh .
