#!/usr/bin/env bash
set -euo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 1 ]]; then
  printf 'Usage: bash %s /path/to/keycloak\n' "$0" >&2
  exit 1
fi
kc_dist="$1"
if [[ ! -f "$kc_dist/bin/kc.sh" && ! -f "$kc_dist/bin/kc.bat" ]]; then
  printf 'Keycloak distribution not found: %s\n' "$kc_dist" >&2
  exit 1
fi
theme_target="$kc_dist/themes/kub"
if [[ -L "$theme_target" ]]; then
  printf 'Theme path is a symlink; replace it with a directory first: %s\n' "$theme_target" >&2
  exit 1
fi
mkdir -p "$theme_target"
cp -R "$package_dir/kub/." "$theme_target/"
printf 'KUB theme installed: %s\nRestart Keycloak, then select Login theme: kub in Realm settings > Themes.\n' "$theme_target"
