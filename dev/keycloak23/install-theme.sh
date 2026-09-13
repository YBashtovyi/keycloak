#!/bin/bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
kc_dist="${1:-$repo_dir/.kc/dev23/keycloak-23.0.7}"
if [[ ! -f "$kc_dist/bin/kc.sh" ]]; then
  printf 'Keycloak distribution not found: %s\n' "$kc_dist" >&2
  exit 1
fi
theme_source="$repo_dir/custom-themes/kub"
theme_target="$kc_dist/themes/kub"
if [[ -L "$theme_target" ]]; then
  printf 'Theme path is a symlink; replace it with a directory first: %s\n' "$theme_target" >&2
  exit 1
fi
mkdir -p "$theme_target"
cp -R "$theme_source/." "$theme_target/"
printf 'KUB theme installed: %s\n' "$theme_target"
