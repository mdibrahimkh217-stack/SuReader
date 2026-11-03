# Contributing

Thanks for helping! The easiest ways:

- **Report a bug / request a feature:** open an Issue (what you did, what you expected, your distro).
- **Fix or improve the code:** fork the repo, change `sureader.py`, open a Pull Request.
- **Package SuReader for another distro** (Arch/AUR, Flatpak, Nix, openSUSE, ...): add the *recipe*
  (a spec/PKGBUILD/manifest and a build script) under `packaging/` and open a Pull Request.

## About pre-built binaries (.deb / .rpm / AppImage)
Release packages are **built automatically from the source in this repo** by GitHub Actions
(`.github/workflows/release.yml`) whenever a version tag such as `v1.1` is created. We do not accept
pre-built binaries uploaded by others, because nobody can verify what is inside them. If you want a
package for your distro, contribute the build recipe instead - it will then be built the same trusted way.

You can build locally too:

```bash
bash packaging/build_deb.sh 1.0        # -> dist/sureader_1.0_amd64.deb      (needs dpkg-deb)
bash packaging/build_rpm.sh 1.0        # -> dist/sureader-1.0-1.x86_64.rpm   (needs rpmbuild)
bash packaging/build_appimage.sh       # -> dist/SuReader-x86_64.AppImage
```

## Releasing (maintainer)
Create a Release on GitHub with a new tag (e.g. `v1.1`). The workflow builds all three packages and attaches them.
