#!/bin/sh
# Ubuntu/Linux x64 onedir portable. Run from a clean venv that has .[desktop],
# PyInstaller and build installed. Mirrors packaging/SlipSurfaceIQ-FEA.spec.
set -eu
cd "$(dirname "$0")/.."
python -m build --outdir python-dist
python scripts/check_distributions.py python-dist
python -m PyInstaller --noconfirm packaging/SlipSurfaceIQ-FEA.spec
python scripts/third_party_licenses.py dist/SlipSurfaceIQ-FEA
cp docs/PORTABLE-README-LINUX.txt dist/SlipSurfaceIQ-FEA/README.txt
cp docs/phase5-release.md dist/SlipSurfaceIQ-FEA/RELEASE-NOTES.md
cp -a docs/images dist/SlipSurfaceIQ-FEA/images
tar -C dist -czf SlipSurfaceIQ-FEA-linux-x64.tar.gz SlipSurfaceIQ-FEA
sha256sum SlipSurfaceIQ-FEA-linux-x64.tar.gz | tee SHA256SUMS-linux.txt
