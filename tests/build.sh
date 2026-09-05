#!/usr/bin/env bash
# Build every layer of every cluster the way Flux does, resolve the substitutions, and
# leave the result where the other checks can read it.
#
#   ./tests/build.sh [outdir]        default: a temp dir, printed on the last line
#
# Nothing here is hardcoded. Clusters are whatever is under clusters/*/ and each layer's
# path is read from its own Kustomization, so a cluster on a different size profile
# (`path: ./environments/small/platform`) is picked up without editing this file. That
# matters: the layer paths moved under the size profiles, and a check that hardcodes
# `./platform` keeps passing while testing a layout nothing deploys any more.
#
# `flux build kustomization --dry-run` runs the real kustomize build with the real
# Kustomization spec, but it cannot read `cluster-vars` from a cluster CI does not have, so
# `${BASE_DOMAIN}` survives into the output. We substitute from that cluster's own
# vars.yaml, which is where the ConfigMap is defined, so there is no second copy to drift.
#
# The check that pays for this script on its own is the last one: **no ${VAR} may survive**.
# A typo'd `${BASE_DOMIAN}` is an error nowhere — Flux leaves an unknown variable alone,
# kustomize is happy, the API server accepts it, and the app comes up serving
# "docs.${BASE_DOMIAN}", which resolves for nobody.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

# `flux build kustomization --path` is resolved against the CURRENT DIRECTORY, not against
# the --kustomization-file. Standing anywhere else, this script silently builds the tree you
# are standing in rather than the one it lives in — which makes a render-diff of two
# checkouts compare a commit against itself and report "unchanged". Anchor it.
cd "$HERE"

# Keycloak's own placeholders are written $${NAME} so that Flux's substitution leaves ONE
# $ behind for KeycloakRealmImport to resolve from a Secret at import time. After the build
# they are supposed to look exactly like an unresolved Flux variable, so they are allowed
# by name — read from the realm's `placeholders:` block rather than listed here, so adding
# a realm user does not mean editing CI.
mapfile -t KC_PLACEHOLDERS < <(python3 -c '
import glob, sys, yaml
for path in glob.glob(sys.argv[1] + "/*/identity/realm.yaml") + glob.glob(sys.argv[1] + "/identity/realm.yaml"):
    for doc in yaml.safe_load_all(open(path)):
        if doc and doc.get("kind") == "KeycloakRealmImport":
            for k in (doc["spec"].get("placeholders") or {}):
                print(k)
' "$HERE/platform" 2>/dev/null | sort -u)

fail=0

for cluster_dir in "$HERE"/clusters/*/; do
  cluster="$(basename "$cluster_dir")"
  vars="$cluster_dir/vars.yaml"
  [[ -f "$vars" ]] || { echo "clusters/$cluster: no vars.yaml, skipped"; continue; }

  mapfile -t SUBS < <(python3 -c '
import sys, yaml
for k, v in (yaml.safe_load(open(sys.argv[1]))["data"] or {}).items():
    print(f"{k}={v}")
' "$vars")

  subst() {
    local expr=()
    for kv in "${SUBS[@]}"; do
      expr+=(-e "s|\\\${${kv%%=*}}|${kv#*=}|g")
    done
    sed "${expr[@]}"
  }

  echo "== clusters/$cluster"
  mkdir -p "$OUT/$cluster"
  built=0

  # Every Kustomization in the cluster dir, with the path it actually declares.
  while IFS=$'\t' read -r name path; do
    [[ -n "$name" ]] || continue
    if ! flux build kustomization "$name" \
        --path "$path" \
        --kustomization-file "$cluster_dir/$name.yaml" \
        --dry-run 2>/dev/null | subst > "$OUT/$cluster/$name.yaml"; then
      echo "   $name: BUILD FAILED"
      fail=1
      continue
    fi
    built=$((built + 1))
    printf '   %-14s %-34s %3s objects\n' "$name" "$path" \
      "$(grep -c '^kind:' "$OUT/$cluster/$name.yaml" || true)"
  done < <(python3 -c '
import glob, os, sys, yaml
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.yaml"))):
    for doc in yaml.safe_load_all(open(f)):
        if doc and doc.get("kind") == "Kustomization" \
           and doc.get("apiVersion", "").startswith("kustomize.toolkit.fluxcd.io"):
            name = doc["metadata"]["name"]
            # The FluxInstance-managed bootstrap kustomization points at the cluster dir
            # itself; it has no layer to render.
            if os.path.basename(f) == name + ".yaml":
                print(name + "\t" + doc["spec"]["path"])
' "$cluster_dir")

  if (( built == 0 )); then
    echo "   no layers built — clusters/$cluster has no Kustomization this script could read"
    fail=1
  fi
done

echo
echo "== unresolved substitutions"
leftover=""
mapfile -t built_files < <(find "$OUT" -name '*.yaml' | sort)
for f in "${built_files[@]}"; do
  while IFS= read -r hit; do
    var="$(sed 's/.*\${\([A-Za-z_][A-Za-z0-9_]*\)}.*/\1/' <<< "$hit")"
    # shellcheck disable=SC2076
    if [[ " ${KC_PLACEHOLDERS[*]} " == *" $var "* ]]; then continue; fi
    leftover+="   $hit"$'\n'
  done < <(grep -no '\${[A-Za-z_][A-Za-z0-9_]*}' "$f" | sed "s|^|${f#$OUT/}:|")
done

if [[ -n "$leftover" ]]; then
  printf '%s' "$leftover"
  echo
  echo "FAIL — a variable is used but not declared in that cluster's vars.yaml."
  echo "Flux leaves an unknown \${VAR} untouched, so it reaches the cluster as a literal."
  exit 1
fi
echo "   none (${#KC_PLACEHOLDERS[@]} Keycloak placeholders allowed by name)"

if (( fail )); then
  echo
  echo "FAIL — a layer did not build."
  exit 1
fi
echo
echo "$OUT"
