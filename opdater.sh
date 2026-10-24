#!/usr/bin/env bash
# Opdatér Fangarr fra GitHub: ./opdater.sh  (køres i /opt/fangarr på feeder)
set -euo pipefail
cd "$(dirname "$0")"
echo "Nuværende version: $(cat app/VERSION 2>/dev/null || echo ukendt)"
git fetch --quiet origin
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
  echo "Fangarr er allerede opdateret."
  exit 0
fi
echo "Ændringer siden sidst:"
git log --oneline HEAD..origin/main
# Gem en eksport af regler og indstillinger, før der opdateres
docker exec fangarr python -c "import urllib.request as u;u.urlopen(u.Request('http://127.0.0.1:8080/api/backups/now',method='POST'))" >/dev/null 2>&1 \
  || echo "(kunne ikke gemme eksport før opdatering – fortsætter)"
git merge --ff-only --quiet origin/main
docker compose up -d --build
echo "Ny version: $(cat app/VERSION)"
docker image prune -f >/dev/null 2>&1 || true
