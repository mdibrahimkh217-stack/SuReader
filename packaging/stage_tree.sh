#!/bin/bash
# Stages the files shared by the .deb and .rpm packages into DEST (a fake filesystem root).
# PyMuPDF is bundled (distros rarely ship a recent one); PyQt comes from the system package manager.
# PyMuPDF 1.24.11 is the last release with a Python 3.8 wheel (abi3), so the package works on
# Python 3.8 (Ubuntu/Mint 20.04) up to current versions.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?usage: stage_tree.sh DEST}"
rm -rf "$DEST"
install -d "$DEST/opt/sureader/lib" "$DEST/usr/bin" "$DEST/usr/share/applications" \
           "$DEST/usr/share/icons/hicolor/scalable/apps"
python3 -m pip install "pymupdf==1.24.11" --target "$DEST/opt/sureader/lib" \
        --platform manylinux2014_x86_64 --python-version 3.8 --implementation cp --abi abi3 \
        --only-binary=:all: --no-compile --no-deps -q
rm -rf "$DEST/opt/sureader/lib/bin"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
install -m644 "$HERE/sureader.py" "$DEST/opt/sureader/sureader.py"
cat > "$DEST/usr/bin/sureader" <<'EOS'
#!/bin/sh
export PYTHONPATH=/opt/sureader/lib${PYTHONPATH:+:$PYTHONPATH}
exec python3 /opt/sureader/sureader.py "$@"
EOS
chmod 755 "$DEST/usr/bin/sureader"
install -m644 "$HERE/packaging/sureader.desktop" "$DEST/usr/share/applications/sureader.desktop"
install -m644 "$HERE/packaging/sureader.svg" "$DEST/usr/share/icons/hicolor/scalable/apps/sureader.svg"
find "$DEST" -type d -exec chmod 755 {} +
