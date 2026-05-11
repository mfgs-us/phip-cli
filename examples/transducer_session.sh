#!/usr/bin/env bash
# A realistic fUS-style bench session: register the rig, register the
# element, log pre- and post-poling sweeps with attached scope
# screenshots, transition the element to qualified, then bundle the
# whole history.
#
# Prereq: phip-server running on localhost:8080.

set -euo pipefail

phip config set default_namespace elements

# 1. Register the rig + instrument as PhIP objects (so measurements can
#    cite them via --measured-with).
phip object new fixture bench-2 \
    --state deployed \
    --notes "primary characterization rig"

phip object new instrument tek-mso64 \
    --state deployed \
    --notes "Tektronix MSO64 scope, fw 1.4.2"

# 2. Register the element being characterized.
ELEM=transducer-047
phip object new component "$ELEM" \
    --state prototype \
    --notes "PVDF-TrFE batch C, target 2.5 MHz"

# 3. Synthesize fake measurement + screenshot files.
PRE=$(mktemp --suffix=_pre.csv)
POST=$(mktemp --suffix=_post.csv)
SCREEN=$(mktemp --suffix=_scope.png)
printf 'freq_hz,mag_db\n1000,-1.2\n2500,-0.1\n4000,-1.8\n' > "$PRE"
printf 'freq_hz,mag_db\n1000,-2.1\n2500,-0.4\n4000,-2.5\n' > "$POST"
printf '\x89PNG\r\n\x1a\nfake-png-bytes' > "$SCREEN"

# 4. Log pre-poling sweep + screenshot in one event.
phip log "$ELEM" "$PRE" \
    --metric freq_response --value 2500 --unit Hz \
    --rig bench-2 --instrument tek-mso64 \
    --attach "$SCREEN" \
    --notes "pre-poling, RT, 50ohm termination"

# 5. (Pretend we poled the element here.) Log post-poling sweep.
phip log "$ELEM" "$POST" \
    --metric freq_response --value 2400 --unit Hz \
    --rig bench-2 --instrument tek-mso64 \
    --notes "post-poling, RT"

# 6. Transition to qualified.
phip transition "$ELEM" --to qualified --reason "passed pre/post characterization"

# 7. Survey the result.
echo
echo "=== full history ==="
phip show "$ELEM" --table

# 8. Verify and bundle.
phip verify "$ELEM"

BUNDLE=$(mktemp --suffix=_${ELEM}.phip-bundle)
phip bundle pack "$ELEM" --out "$BUNDLE"
phip bundle verify "$BUNDLE"

echo
echo "Done. Element $ELEM has 4 events; bundle at $BUNDLE."
