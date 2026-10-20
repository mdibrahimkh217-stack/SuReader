#!/bin/bash
# Builds SuReader-x86_64.AppImage (bundled Python 3.12 + PyQt5 + PyMuPDF).
# Needs: curl, tar, python3-pip, apt (to fetch a few small xcb helper libs), network access.
# Qt5 is used on purpose: it runs on older distros (glibc 2.31, e.g. Ubuntu/Mint 20.04).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="$HERE/build"; A="$W/SuReader.AppDir"
PYURL="https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz"
rm -rf "$W"; mkdir -p "$W" "$A/usr/fallback-libs"; cd "$W"

curl -fL -o py.tgz "$PYURL"
curl -fL -o appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool
tar xzf py.tgz -C "$A/usr" --strip-components=1

# shrink the bundled interpreter (the shipped libpython has debug symbols)
strip --strip-unneeded "$A/usr/lib/libpython3.12.so.1.0" "$A/usr/bin/python3.12" || true
rm -rf "$A"/usr/lib/python3.12/{test,idlelib,tkinter,turtledemo,ensurepip} "$A"/usr/lib/python3.12/site-packages/pip

SP="$A/usr/lib/python3.12/site-packages"
python3 -m pip install pymupdf PyQt5 --target "$SP" --platform manylinux2014_x86_64 \
        --python-version 3.12 --implementation cp --only-binary=:all: --no-compile
cp "$HERE/sureader.py" "$SP/sureader.py"

# trim unused Qt modules to keep the image small
Q="$SP/PyQt5/Qt5"; rm -rf "$Q/translations" "$Q/qml"
for m in Quick Qml 3D WebEngine WebKit Designer Multimedia Bluetooth Sensors Nfc Location Test Sql Network OpenGL Positioning Help XmlPatterns WebChannel WebSockets SerialPort Charts DataVisualization RemoteObjects Purchasing TextToSpeech Scxml Gamepad; do
  rm -rf "$Q"/lib/libQt5${m}* "$SP"/PyQt5/Qt${m}*.so "$SP"/PyQt5/Qt${m}*.pyi
done
for d in mediaservice audio sensors geoservices position qmltooling sqldrivers playlistformats canbus gamepads sceneparsers geometryloaders renderplugins renderers texttospeech webview bearer; do rm -rf "$Q/plugins/$d"; done

# small xcb helper libs; AppRun only uses them if the host lacks them
mkdir -p libs && (cd libs && apt-get download libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-util1 libxcb-xinerama0 && for d in *.deb; do dpkg-deb -x "$d" x; done)
cp -L libs/x/usr/lib/x86_64-linux-gnu/*.so.* "$A/usr/fallback-libs/"

cp "$HERE/packaging/sureader.desktop" "$A/"
cp "$HERE/packaging/sureader.svg" "$A/sureader.svg"
cat > "$A/AppRun" <<'EOS'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
export QT_QPA_PLATFORM_PLUGIN_PATH="$HERE/usr/lib/python3.12/site-packages/PyQt5/Qt5/plugins/platforms"
TMP="$(mktemp -d)"
LDC=/sbin/ldconfig; [ -x "$LDC" ] || LDC=ldconfig
for f in "$HERE"/usr/fallback-libs/*.so*; do
  n="$(basename "$f")"
  "$LDC" -p 2>/dev/null | grep -q " $n " || ln -s "$f" "$TMP/$n"
done
export LD_LIBRARY_PATH="$TMP${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$HERE/usr/bin/python3" -c "import sys; sys.argv[0]='sureader'; import sureader; sureader.main()" "$@"
RC=$?
rm -rf "$TMP"
exit $RC
EOS
chmod +x "$A/AppRun"
find "$A" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$HERE/dist"
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$A" "$HERE/dist/SuReader-x86_64.AppImage"
echo "Built: dist/SuReader-x86_64.AppImage"
