#!/bin/bash
# Usage: packaging/build_deb.sh [version]   ->  dist/sureader_amd64.deb   (no version in the file name)
# The version only goes into the package metadata; by default it is APP_VERSION from sureader.py.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VER="${1:-$(grep -oP 'APP_VERSION = "\K[^"]+' "$HERE/sureader.py")}"
P="$HERE/build/deb/sureader_amd64"
rm -rf "$P"
bash "$HERE/packaging/stage_tree.sh" "$P"
mkdir -p "$P/DEBIAN" "$HERE/dist"
SIZE=$(du -sk "$P/opt" "$P/usr" | awk '{s+=$1} END {print s}')
cat > "$P/DEBIAN/control" <<EOC
Package: sureader
Version: $VER
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.8), python3-pyqt5 | python3-pyqt6
Installed-Size: $SIZE
Maintainer: SuReader contributors <noreply@users.noreply.github.com>
Homepage: https://github.com/mdibrahimkh217-stack/SuReader
Description: Lightweight SumatraPDF-style PDF reader
 Tabs, two-page views, annotations, search, links, outline, thumbnails and bookmarks.
 Hold the right mouse button and scroll the wheel to zoom at the pointer.
EOC
dpkg-deb --build --root-owner-group "$P" "$HERE/dist/sureader_amd64.deb"
echo "Built: dist/sureader_amd64.deb"
