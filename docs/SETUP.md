# Pi setup

Raspberry Pi 5 setup for the mission code. Software stack and workflow are in
CLAUDE.md. Everything here is done by hand on the Pi.


## Python packages

pymavlink and picamera2 are already installed. The mission code also needs PyYAML.
Install it from apt, since the venv uses system site packages:

```
sudo apt install -y python3-yaml
```

Check: `source ~/drone-venv/bin/activate && python -c "import yaml, pymavlink; print('ok')"`


## Sharing /dev/ttyAMA0 with the flight-data logger

A serial port can only be opened by one process. The logger that starts at boot
already holds /dev/ttyAMA0, so main.py can't open it as well.

**Plan:** [mavlink-router](https://github.com/mavlink-router/mavlink-router) becomes the
only process on /dev/ttyAMA0. It forwards every FC message to two local UDP endpoints,
one for the logger and one for main.py, and routes their messages back to the FC.
Neither the logger nor main.py opens the serial port.

```
FC ── /dev/ttyAMA0 921600 ── mavlink-router ─┬─ udp 127.0.0.1:14550 ── logger
                                             └─ udp 127.0.0.1:14551 ── main.py / tools/
```

### 1. Find out how the logger runs (send me the output)

```
sudo lsof /dev/ttyAMA0                       # which process holds the port
ps -o pid,user,cmd -p $(sudo lsof -t /dev/ttyAMA0)
systemctl list-units --type=service --state=running
crontab -l; sudo crontab -l
cat /etc/rc.local 2>/dev/null
```

If it's a systemd service, also send `systemctl cat <service-name>`. Step 4 is
written once this is known.

### 2. Check the UART

- `/boot/firmware/config.txt` must contain `dtparam=uart0=on`. On a Pi 5, ttyAMA0 is
  the GPIO14/15 UART. The 3-pin debug header is ttyAMA10.
- `sudo raspi-config` → Interface Options → Serial Port: login shell over serial **No**,
  serial port hardware **Yes**.
- The logger already works on ttyAMA0, so both are probably set already. Check anyway.

### 3. Install mavlink-router

It isn't in the Raspberry Pi OS repos, so build it from source:

```
sudo apt install -y git meson ninja-build pkg-config gcc g++ systemd
git clone https://github.com/mavlink-router/mavlink-router.git ~/mavlink-router
cd ~/mavlink-router
git tag --sort=-creatordate | head -3      # check out the newest release tag
git checkout <newest tag>
git submodule update --init --recursive
meson setup build .
ninja -C build
sudo ninja -C build install
```

This installs `mavlink-routerd` and the `mavlink-router.service` systemd unit.

Create `/etc/mavlink-router/main.conf` (`sudo mkdir -p /etc/mavlink-router` first):

```
[General]
# No TCP server: nothing on the network can reach the FC through the router.
TcpServerPort = 0
ReportStats = false

[UartEndpoint fc]
Device = /dev/ttyAMA0
Baud = 921600

[UdpEndpoint logger]
Mode = Normal
Address = 127.0.0.1
Port = 14550

[UdpEndpoint mission]
Mode = Normal
Address = 127.0.0.1
Port = 14551
```

Don't start it yet. The logger still holds the port.

### 4. Move the logger to UDP (TBD until step 1)

In general:
1. Stop the logger: `sudo systemctl stop <logger>`, or kill it if it started from cron
   or rc.local.
2. Change its connection from `/dev/ttyAMA0` to `udpin:127.0.0.1:14550` (pymavlink),
   or `--master=udpin:127.0.0.1:14550` (MAVProxy).
3. Make it start after the router. In its unit file:
   `After=mavlink-router.service` and `Requires=mavlink-router.service`.
4. `sudo systemctl daemon-reload`.

### 5. Start the router, then the logger

```
sudo systemctl enable --now mavlink-router
sudo systemctl restart <logger>
systemctl status mavlink-router <logger>
sudo lsof /dev/ttyAMA0            # must show only mavlink-routerd
```

Reboot once and repeat the checks to confirm the start order works from boot.

### 6. Point the mission code at the router

In `config.yaml` on the Pi:

```yaml
connection:
  connection_string: udpin:127.0.0.1:14551   # baud is ignored for UDP
```

Then run the read-only bench tools:

```
cd ~/drone && source ~/drone-venv/bin/activate
python tools/telemetry.py --duration 20     # prints measured rates per message
python tools/check_params.py
```

Also confirm the logger is still writing logs while these run.

### Notes

- **Message rates are per FC port.** SET_MESSAGE_INTERVAL from main.py changes the
  rates the logger receives as well, and if the logger sends REQUEST_DATA_STREAM it
  can change main.py's rates. `tools/telemetry.py` shows the measured rate next to the
  requested one. If they disagree, tell me what the logger requests.
- STATUSTEXT from the Pi reaches the ground station: the FC forwards it to its other
  ports (checked in SITL).
- **Rollback:** `sudo systemctl disable --now mavlink-router`, point the logger back at
  /dev/ttyAMA0, and restart it.
