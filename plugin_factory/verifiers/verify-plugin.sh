#!/bin/sh
set -eu

fail() {
  echo "plugin verification failed" >&2
  exit 1
}

[ "$#" -eq 2 ] || fail
release_root=$(CDPATH= cd -- "$1" 2>/dev/null && pwd -P) || fail
expected_release=$2
case "$expected_release" in
  sha256:[0-9a-f][0-9a-f]*) ;;
  *) fail ;;
esac
[ "${#expected_release}" -eq 71 ] || fail
[ -f "$release_root/SHA256SUMS" ] && [ ! -L "$release_root/SHA256SUMS" ] || fail

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail
  fi
}

[ "sha256:$(sha256_file "$release_root/SHA256SUMS")" = "$expected_release" ] || fail
if find "$release_root" -type l -print | grep -q .; then
  fail
fi

listed=0
while IFS= read -r line || [ -n "$line" ]; do
  digest=${line%%  *}
  relative=${line#*  }
  [ "$digest" != "$line" ] || fail
  [ "${#digest}" -eq 64 ] || fail
  case "$digest" in *[!0-9a-f]*) fail ;; esac
  case "$relative" in
    ""|/*|*\\*|*..*|*[!A-Za-z0-9._/-]*) fail ;;
  esac
  candidate="$release_root/$relative"
  [ -f "$candidate" ] && [ ! -L "$candidate" ] || fail
  [ "$(sha256_file "$candidate")" = "$digest" ] || fail
  listed=$((listed + 1))
done < "$release_root/SHA256SUMS"

actual=$(find "$release_root" -type f -print | wc -l | tr -d ' ')
[ "$actual" -eq $((listed + 1)) ] || fail
echo verified_inert
