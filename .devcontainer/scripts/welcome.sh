#!/usr/bin/env bash
# Printed by ~/.bashrc in every new shell. Kept to a few lines on purpose: it
# appears every time a terminal opens, so it points at the walkthrough rather
# than trying to be the walkthrough.
cd "$(dirname "$0")/../.." 2>/dev/null || exit 0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then B=$'\e[1m'; DIM=$'\e[2m'; OFF=$'\e[0m'
else B=""; DIM=""; OFF=""; fi

printf '\n  %sTetracorder demo%s\n' "$B" "$OFF"
printf '  Run Tetracorder over a real EMIT L2A scene, one step at a time.\n\n'
printf '      %s.devcontainer/get-started.sh%s\n\n' "$B" "$OFF"
printf '  %sNothing has been started for you -- every step is yours to run.%s\n\n' "$DIM" "$OFF"
