#!/bin/bash
# Usage: packaging/build_rpm.sh [version]   ->  dist/sureader-<version>-1.x86_64.rpm
# Needs rpmbuild (apt install rpm  /  dnf install rpm-build).
set -euo pipefail
VER="${1:-1.0}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="$HERE/build/rpm"; STAGE="$W/stage"
rm -rf "$W"; mkdir -p "$W"/{BUILD,RPMS,SOURCES,SPECS,SRPMS} "$HERE/dist"
bash "$HERE/packaging/stage_tree.sh" "$STAGE"
cat > "$W/SPECS/sureader.spec" <<EOS
%global debug_package %{nil}
%global __os_install_post %{nil}
%global _build_id_links none
AutoReqProv: no
Name:      sureader
Version:   $VER
Release:   1
Summary:   Lightweight SumatraPDF-style PDF reader
License:   AGPL-3.0-or-later
URL:       https://github.com/mdibrahimkh217-stack/SuReader
BuildArch: x86_64
Requires:  python3 >= 3.8
Requires:  (python3-qt5 or python3-pyqt6)

%description
Tabs, two-page views, annotations, search, links, outline, thumbnails and bookmarks.
Hold the right mouse button and scroll the wheel to zoom at the pointer.

%install
mkdir -p %{buildroot}
cp -a $STAGE/. %{buildroot}/

%files
/opt/sureader
/usr/bin/sureader
/usr/share/applications/sureader.desktop
/usr/share/icons/hicolor/scalable/apps/sureader.svg
EOS
rpmbuild -bb --define "_topdir $W" "$W/SPECS/sureader.spec"
cp "$W"/RPMS/x86_64/*.rpm "$HERE/dist/"
echo "Built: $(ls "$HERE"/dist/*.rpm)"
