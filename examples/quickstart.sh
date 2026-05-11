#!/usr/bin/env bash
# Quickstart: 0 to "logged a measurement against a real server" in one script.
#
# Prereq: phip-server running locally on port 8080. Easiest way:
#   git clone https://github.com/mfgs-us/phip-server
#   cd phip-server && PHIP_AUTHORITY=tutorial.local docker compose up -d
#
# Then:
#   ./examples/quickstart.sh

set -euo pipefail

export PHIP_HOME="${PHIP_HOME:-/tmp/phip-quickstart-$$}"
trap 'rm -rf "$PHIP_HOME"' EXIT
echo "Using PHIP_HOME=$PHIP_HOME (ephemeral)"

# 1. Setup
phip init --remote http://localhost:8080 --authority tutorial.local
phip key register
phip config set default_namespace elements

# 2. Create an element
phip object new component transducer-quickstart-001 \
    --state prototype \
    --notes "demo element from quickstart.sh"

# 3. Log a measurement
DATA=$(mktemp --suffix=.csv)
cat > "$DATA" <<EOF
freq_hz,mag_db
1000,-1.2
2500,-0.1
4000,-1.8
EOF

phip log transducer-quickstart-001 "$DATA" \
    --metric freq_response \
    --value 2500 --unit Hz \
    --rig bench-2

# 4. Read it back, formatted
phip show transducer-quickstart-001 --table

# 5. Verify the chain end-to-end client-side
phip verify transducer-quickstart-001

# 6. Pack a portable bundle and verify it offline
BUNDLE=$(mktemp --suffix=.phip-bundle)
phip bundle pack transducer-quickstart-001 --out "$BUNDLE"
phip bundle verify "$BUNDLE"

echo
echo "Done. Ephemeral PHIP_HOME and temp files will be cleaned up on exit."
