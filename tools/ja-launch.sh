#!/usr/bin/env bash
# Spawns ja-respond as a floating terminal on whichever monitor the cursor is on.
# Bind in hyprland.conf:
#   bind = SUPER, J, exec, ~/whisper.cpp/tools/ja-launch.sh
#
# Requires: jq, and one of: foot, kitty, alacritty

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get cursor position in logical pixels
read -r CX CY < <(hyprctl cursorpos -j | jq -r '[.x, .y] | @tsv')

# Find monitor under cursor.
# hyprctl reports x/y in logical pixels, but width/height in physical pixels —
# divide physical dimensions by scale to get logical bounds.
MONITOR=$(hyprctl monitors -j | jq -r --argjson cx "$CX" --argjson cy "$CY" '
  .[] | select(
    .x <= $cx and $cx < (.x + (.width  / .scale)) and
    .y <= $cy and $cy < (.y + (.height / .scale))
  ) | .name
')

if [[ -z "$MONITOR" ]]; then
    notify-send "ja-respond" "Could not determine active monitor (cursor: $CX,$CY)"
    exit 1
fi

# Pick whichever terminal is available
if command -v foot &>/dev/null; then
    TERM_CMD="foot --app-id=ja-respond -e"
elif command -v kitty &>/dev/null; then
    TERM_CMD="kitty --class ja-respond -e"
elif command -v alacritty &>/dev/null; then
    TERM_CMD="alacritty --class ja-respond -e"
else
    notify-send "ja-respond" "No terminal found — install foot, kitty, or alacritty"
    exit 1
fi

# Batch: focus the monitor, then exec with inline float+center+size+monitor rules.
# Inline rules in exec are more reliable than windowrulev2 for one-shot spawns.
hyprctl --batch \
    "dispatch focusmonitor $MONITOR ; \
     dispatch exec [float;center;size 700 480;monitor $MONITOR] $TERM_CMD python3 $SCRIPT_DIR/ja-respond.py"
