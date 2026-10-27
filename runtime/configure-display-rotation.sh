#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: configure-display-rotation.sh ROTATION [OUTPUT] [TOUCH_DEVICE] [TOUCH_ROTATION]

Configure a labwc/kanshi desktop so the display and touchscreen use the same
rotation. ROTATION must be one of: normal, 0, 90, 180, 270.

Defaults:
  OUTPUT        DSI-1
  TOUCH_DEVICE  Goodix Capacitive TouchScreen
  TOUCH_ROTATION
                0; override this only when the touch sensor has a different
                native orientation from the display panel.

Example:
  ./runtime/configure-display-rotation.sh 270

Reboot after applying the configuration so labwc recreates the touch device.
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

rotation=${1:-}
output=${2:-DSI-1}
touch_device=${3:-Goodix Capacitive TouchScreen}
touch_rotation=${4:-}

case "$rotation" in
  normal|0)
    transform=normal
    ;;
  90)
    transform=90
    ;;
  180)
    transform=180
    ;;
  270)
    transform=270
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

touch_rotation=${touch_rotation:-0}
case "$touch_rotation" in
  normal|0) matrix="1 0 0 0 1 0" ;;
  90) matrix="0 -1 1 1 0 0" ;;
  180) matrix="-1 0 1 0 -1 1" ;;
  270) matrix="0 1 0 -1 0 1" ;;
  *)
    echo "TOUCH_ROTATION must be one of: normal, 0, 90, 180, 270" >&2
    exit 2
    ;;
esac

command -v python3 >/dev/null || {
  echo "python3 is required" >&2
  exit 1
}

config_home=${XDG_CONFIG_HOME:-$HOME/.config}
kanshi_dir=$config_home/kanshi
kanshi_config=$kanshi_dir/config
labwc_dir=$config_home/labwc
labwc_config=$labwc_dir/rc.xml
backup_suffix=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$kanshi_dir" "$labwc_dir"

if [[ -f $kanshi_config ]]; then
  cp "$kanshi_config" "$kanshi_config.bak-$backup_suffix"
fi
if [[ -f $labwc_config ]]; then
  cp "$labwc_config" "$labwc_config.bak-$backup_suffix"
fi

ROTATION_OUTPUT=$output ROTATION_TRANSFORM=$transform KANSHI_CONFIG=$kanshi_config \
python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ["KANSHI_CONFIG"])
output = os.environ["ROTATION_OUTPUT"]
transform = os.environ["ROTATION_TRANSFORM"]
text = path.read_text() if path.exists() else ""

begin = "# BEGIN sky-console display rotation"
end = "# END sky-console display rotation"
text = re.sub(
    rf"(?ms)^\s*{re.escape(begin)}\n.*?^\s*{re.escape(end)}\s*\n?",
    "",
    text,
)
# Replace the profile used by the original one-off device setup, if present.
text = re.sub(
    r"(?ms)^\s*profile\s+skytrace-landscape\s*\{[^{}]*\}\s*\n?",
    "",
    text,
)
block = (
    f"{begin}\n"
    "profile skytrace-landscape {\n"
    f"    output {output} enable transform {transform} scale 1 position 0,0\n"
    "}\n"
    f"{end}\n"
)
path.write_text(text.rstrip() + ("\n\n" if text.strip() else "") + block)
PY

ROTATION_OUTPUT=$output ROTATION_TOUCH_DEVICE=$touch_device ROTATION_MATRIX=$matrix LABWC_CONFIG=$labwc_config \
python3 - <<'PY'
import os
import xml.etree.ElementTree as ET
from pathlib import Path

namespace = "http://openbox.org/3.4/rc"
ET.register_namespace("", namespace)

path = Path(os.environ["LABWC_CONFIG"])
device_name = os.environ["ROTATION_TOUCH_DEVICE"]
matrix = os.environ["ROTATION_MATRIX"]

if path.exists() and path.read_text().strip():
    tree = ET.parse(path)
    root = tree.getroot()
else:
    root = ET.Element(f"{{{namespace}}}openbox_config")
    tree = ET.ElementTree(root)

def tag(name: str) -> str:
    return f"{{{namespace}}}{name}"

touch = next(
    (node for node in root.findall(tag("touch")) if node.get("deviceName") == device_name),
    None,
)
if touch is None:
    touch = ET.SubElement(root, tag("touch"))
touch.set("deviceName", device_name)
touch.set("mapToOutput", os.environ["ROTATION_OUTPUT"])
touch.set("mouseEmulation", "no")

libinput = root.find(tag("libinput"))
if libinput is None:
    libinput = ET.SubElement(root, tag("libinput"))
device = next(
    (node for node in libinput.findall(tag("device")) if node.get("category") == device_name),
    None,
)
if device is None:
    device = ET.SubElement(libinput, tag("device"), {"category": device_name})
calibration = device.find(tag("calibrationMatrix"))
if calibration is None:
    calibration = ET.SubElement(device, tag("calibrationMatrix"))
calibration.text = matrix

ET.indent(tree, space="    ")
tree.write(path, encoding="unicode", xml_declaration=True)
with path.open("a") as stream:
    stream.write("\n")
PY

# kanshi watches its config file. A labwc reload updates ordinary settings, but
# a reboot is still required because an existing touchscreen is not recreated.
labwc_pid=$(pgrep -u "$(id -u)" -x labwc | head -n 1 || true)
if [[ -n $labwc_pid ]] && command -v labwc >/dev/null; then
  LABWC_PID=$labwc_pid labwc -r || true
fi

echo "Configured $output for rotation $transform and '$touch_device' for rotation $touch_rotation."
echo "Reboot the device to apply the touchscreen calibration."
