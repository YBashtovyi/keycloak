#!/bin/bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
kc_dist="${1:-$repo_dir/.kc/dev23/keycloak-23.0.7}"
exec bash "$repo_dir/custom-themes/install.sh" "$kc_dist"
