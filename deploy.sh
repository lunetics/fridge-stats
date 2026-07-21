#!/usr/bin/env bash
# Deploy fridge-stats to Home Assistant via a mounted /config directory.
# Point FRIDGE_STATS_CONFIG at it (e.g. a Samba mount of your HA config share).
set -euo pipefail
CFG="${FRIDGE_STATS_CONFIG:?set FRIDGE_STATS_CONFIG to your Home Assistant config dir (e.g. a Samba mount of /config)}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ -f "$CFG/configuration.yaml" ] || { echo "ERROR: config mount not active at $CFG"; exit 1; }

mkdir -p "$CFG/packages" "$CFG/blueprints/automation/fridge_stats"
cp "$HERE/package/fridge_stats.yaml" "$CFG/packages/fridge_stats.yaml"
cp "$HERE/blueprints/fridge_door_monitor.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_door_monitor.yaml"
cp "$HERE/blueprints/fridge_sensor_watchdog.yaml" "$CFG/blueprints/automation/fridge_stats/fridge_sensor_watchdog.yaml"
echo "deployed: packages/fridge_stats.yaml + blueprints/automation/fridge_stats/{fridge_door_monitor,fridge_sensor_watchdog}.yaml"

grep -q 'packages: !include_dir_named packages' "$CFG/configuration.yaml" \
  && echo "configuration.yaml: packages include present" \
  || echo "TODO: add to configuration.yaml:
homeassistant:
  packages: !include_dir_named packages"
echo "Then: config check -> restart HA -> create automation from blueprint -> seed input_number.fridge_tau = 1028"
