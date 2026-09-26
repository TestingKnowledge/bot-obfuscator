#!/bin/sh
set -eu
for f in /app/prometheus/cli.lua /app/prometheus/src/cli.lua /app/prometheus/src/config.lua /app/prometheus/src/prometheus/pipeline.lua; do
  if [ ! -f "$f" ]; then echo "ERROR: missing Prometheus file: $f" >&2; exit 1; fi
done
echo "Prometheus files verified."
