#!/usr/bin/env bash
# Deploy fridge-stats to Home Assistant via a mounted /config directory.
# Point FRIDGE_STATS_CONFIG at it (e.g. a Samba mount of your HA config share).
set -euo pipefail
CFG="${FRIDGE_STATS_CONFIG:?set FRIDGE_STATS_CONFIG to your Home Assistant config dir (e.g. a Samba mount of /config)}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ -f "$CFG/configuration.yaml" ] || { echo "ERROR: config mount not active at $CFG"; exit 1; }

# Language variant: en (canonical, sensor.fridge_* ids) or de (sensor.kuhlschrank_* ids).
# The .de.yaml sources deploy to the SAME target filenames, so a running instance keeps its
# entity ids only if you stay on the same variant — switching en<->de renames the mirror
# sensors and orphans their history.
# --prefix <p>: deploy a SECOND appliance's package (generated via make_package.py) as
# packages/<p>_stats.yaml, leaving the stock fridge package untouched. Blueprints are
# shared and get refreshed either way.
LANG_VARIANT=en
PREFIX=""
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANG_VARIANT="${2:-}"; shift 2 ;;
    --lang=*) LANG_VARIANT="${1#--lang=}"; shift ;;
    --prefix) PREFIX="${2:-}"; shift 2 ;;
    --prefix=*) PREFIX="${1#--prefix=}"; shift ;;
    *) shift ;;
  esac
done
case "$LANG_VARIANT" in
  en) SFX="" ;;
  de) SFX=".de" ;;
  *) echo "ERROR: --lang must be 'en' or 'de'"; exit 1 ;;
esac

mkdir -p "$CFG/packages" "$CFG/blueprints/automation/fridge_stats"
if [ -n "$PREFIX" ] && [ "$PREFIX" != "fridge" ]; then
  # second appliance: generated, validated package under its own prefix
  python3 "$HERE/make_package.py" --lang "$LANG_VARIANT" --prefix "$PREFIX" \
    --out "$CFG/packages/${PREFIX}_stats.yaml"
  PKG_MSG="packages/${PREFIX}_stats.yaml (generated, prefix ${PREFIX})"
else
  cp "$HERE/package/fridge_stats${SFX}.yaml" "$CFG/packages/fridge_stats.yaml"
  PKG_MSG="packages/fridge_stats.yaml"
fi
cp "$HERE/blueprints/fridge_door_monitor${SFX}.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_door_monitor.yaml"
cp "$HERE/blueprints/fridge_sensor_watchdog${SFX}.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_sensor_watchdog.yaml"
echo "deployed (${LANG_VARIANT}): ${PKG_MSG} + blueprints/automation/fridge_stats/{fridge_door_monitor,fridge_sensor_watchdog}.yaml"

grep -q 'packages: !include_dir_named packages' "$CFG/configuration.yaml" \
  && echo "configuration.yaml: packages include present" \
  || echo "TODO: add to configuration.yaml:
homeassistant:
  packages: !include_dir_named packages"
TAU_HELPER="input_number.${PREFIX:-fridge}_tau"
echo "Then: config check -> restart HA -> create automation from blueprint -> seed ${TAU_HELPER} (calibrate per appliance: analysis/calibrate_tau.py)"
