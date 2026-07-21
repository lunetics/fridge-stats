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
LANG_VARIANT=en
while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANG_VARIANT="${2:-}"; shift 2 ;;
    --lang=*) LANG_VARIANT="${1#--lang=}"; shift ;;
    *) shift ;;
  esac
done
case "$LANG_VARIANT" in
  en) SFX="" ;;
  de) SFX=".de" ;;
  *) echo "ERROR: --lang must be 'en' or 'de'"; exit 1 ;;
esac

mkdir -p "$CFG/packages" "$CFG/blueprints/automation/fridge_stats"
cp "$HERE/package/fridge_stats${SFX}.yaml" "$CFG/packages/fridge_stats.yaml"
cp "$HERE/blueprints/fridge_door_monitor${SFX}.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_door_monitor.yaml"
cp "$HERE/blueprints/fridge_sensor_watchdog${SFX}.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_sensor_watchdog.yaml"
echo "deployed (${LANG_VARIANT}): packages/fridge_stats.yaml + blueprints/automation/fridge_stats/{fridge_door_monitor,fridge_sensor_watchdog}.yaml"

grep -q 'packages: !include_dir_named packages' "$CFG/configuration.yaml" \
  && echo "configuration.yaml: packages include present" \
  || echo "TODO: add to configuration.yaml:
homeassistant:
  packages: !include_dir_named packages"
echo "Then: config check -> restart HA -> create automation from blueprint -> seed input_number.fridge_tau = 1028"
