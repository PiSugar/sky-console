from pathlib import Path


path = Path("/home/pi/sky-tracker/runtime/run-client.sh")
text = path.read_text()

if "reset_sdr_usb()" not in text:
    text = text.replace(
        "mkdir -p /home/pi/sky-tracker/run/readsb /home/pi/sky-tracker/data\n",
        """mkdir -p /home/pi/sky-tracker/run/readsb /home/pi/sky-tracker/data

reset_sdr_usb() {
  if command -v sudo >/dev/null 2>&1; then
    sudo -n /usr/local/sbin/adsb-reset-sdr-usb || true
  fi
}

rtl_present() {
  lsusb 2>/dev/null | grep -qi "0bda:2832"
}

reset_sdr_usb
""",
    )
    text = text.replace(
        """if ! kill -0 "$readsb_pid" 2>/dev/null; then
  echo "readsb exited; restarting service." >&2
else
""",
        """if ! kill -0 "$readsb_pid" 2>/dev/null; then
  echo "readsb exited; checking RTL-SDR USB state." >&2
  if ! rtl_present; then
    echo "RTL-SDR missing; attempting USB reset before service restart." >&2
    reset_sdr_usb
  fi
else
""",
    )

path.write_text(text)
