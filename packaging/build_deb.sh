#!/bin/bash
# Usage: packaging/build_deb.sh [version]   ->  dist/sureader_<version>_amd64.deb
set -euo pipefail
VER="${1:-1.0}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
P="$HERE/build/deb/sureader_${VER}_amd64"
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
dpkg-deb --build --root-owner-group "$P" "$HERE/dist/sureader_${VER}_amd64.deb"
echo "Built: dist/sureader_${VER}_amd64.deb"
