#!/usr/bin/env bash
# Build a source archive from a commit and exercise the unpacked distribution.
set -euo pipefail
if (( $# < 1 || $# > 2 )); then
  echo "Usage: $0 NEW_OUTPUT_DIRECTORY [COMMIT]" >&2
  exit 2
fi
repo=$(cd "$(dirname "$0")/.." && pwd)
commit=$(git -C "$repo" rev-parse --verify --end-of-options "${2:-HEAD}^{commit}")
mkdir -- "$1"
out=$(cd -- "$1" && pwd)
name="panel2series-$commit"
scratch=$(mktemp -d "$out/.build.XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
git -C "$repo" archive --format=tar --prefix="$name/" "$commit" | gzip -n > "$scratch/$name.tar.gz"
tar -xzf "$scratch/$name.tar.gz" -C "$scratch"
(
  cd "$scratch/$name"
  python3 -m unittest discover -s tests -v
  python3 -m unittest -v test_analysis
  bash integration/quickstart.sh "$out/evidence"
) 2>&1 | tee "$out/verification.log"
mv "$scratch/$name.tar.gz" "$out/$name.tar.gz"
echo "Verified archive: $out/$name.tar.gz"
