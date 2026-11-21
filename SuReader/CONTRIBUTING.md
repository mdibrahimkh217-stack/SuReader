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
bash packaging/build_deb.sh            # -> dist/sureader_amd64.deb         (needs dpkg-deb)
bash packaging/build_rpm.sh            # -> dist/sureader.x86_64.rpm        (needs rpmbuild)
bash packaging/build_appimage.sh       # -> dist/SuReader-x86_64.AppImage
```

## Releasing (maintainer)
Actions tab > Build packages > Run workflow. It builds all three packages and attaches them to the single release called "SuReader" (tag `latest`, no version in the name). The version shown in About and stored inside the packages is `APP_VERSION` in `sureader.py`.
