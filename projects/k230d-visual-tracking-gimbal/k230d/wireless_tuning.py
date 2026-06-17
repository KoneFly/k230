"""
Wireless tuning link for K230D tracking demo.

The board only sends small UDP text packets and receives parameter commands.
The web UI and data buffering run on the PC bridge, so this module keeps K230D
memory and CPU usage low.
"""
import time
import socket

try:
    import network
except ImportError:
    network = None


class WirelessTuner:
    def __init__(self, ssid, password, pc_ip="255.255.255.255",
                 stat_port=9001, cmd_port=9002, device_id="k230d-tracker"):
        self.ssid = ssid
        self.password = password
        self.pc_ip = pc_ip
        self.stat_port = stat_port
        self.cmd_port = cmd_port
        self.device_id = device_id
        self.enabled = False
        self.ip = "0.0.0.0"
        self._stat_sock = None
        self._cmd_sock = None
        self._last_send = 0

    def start(self):
        if network is None:
            print("[TUNE] network module not available")
            return False

        try:
            sta = network.WLAN(network.STA_IF)
            sta.active(True)
            if not self._connect_wifi(sta):
                return False

            self.ip = sta.ifconfig()[0]
            self._stat_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._stat_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._cmd_sock.bind(("0.0.0.0", self.cmd_port))
            self._cmd_sock.setblocking(False)
            self.enabled = True
            print("[TUNE] UDP enabled, IP=%s stat=%d cmd=%d" %
                  (self.ip, self.stat_port, self.cmd_port))
            return True
        except BaseException as e:
            print("[TUNE] start failed:", e)
            self.enabled = False
            return False

    def _connect_wifi(self, sta):
        if sta.isconnected():
            print("[TUNE] WiFi already connected")
            return True

        try:
            print("[TUNE] scan WiFi...")
            for ap in sta.scan():
                ssid = ap[0]
                if isinstance(ssid, bytes):
                    try:
                        ssid = ssid.decode()
                    except BaseException:
                        ssid = str(ssid)
                rssi = ap[3] if len(ap) > 3 else 0
                print("  %s (%sdBm)" % (ssid, rssi))
        except BaseException as e:
            print("[TUNE] scan skipped:", e)

        for retry in range(1, 6):
            print("[TUNE] WiFi connecting '%s' retry %d/5..." % (self.ssid, retry))
            try:
                sta.connect(self.ssid, self.password)
            except BaseException as e:
                print("[TUNE] connect call failed:", e)

            start = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), start) < 8000:
                if sta.isconnected():
                    print("[TUNE] WiFi OK:", sta.ifconfig()[0])
                    return True
                time.sleep_ms(250)

            time.sleep_ms(1000)

        print("[TUNE] WiFi timeout, tuning disabled")
        return False

    def send_stat(self, values, interval_ms=100):
        if not self.enabled:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_send) < interval_ms:
            return
        self._last_send = now

        parts = ["STAT", "id=%s" % self.device_id, "ip=%s" % self.ip]
        for key, value in values.items():
            parts.append("%s=%s" % (key, value))
        line = " ".join(parts)
        try:
            self._stat_sock.sendto(line.encode(), (self.pc_ip, self.stat_port))
        except BaseException:
            pass

    def recv_params(self):
        if not self.enabled:
            return None
        try:
            data, _ = self._cmd_sock.recvfrom(256)
        except OSError:
            return None
        except BaseException:
            return None

        try:
            text = data.decode().strip()
        except BaseException:
            return None
        if not text:
            return None
        return parse_command(text)

    def close(self):
        for sock in (self._stat_sock, self._cmd_sock):
            try:
                if sock:
                    sock.close()
            except BaseException:
                pass


def parse_command(text):
    parts = text.replace(",", " ").split()
    if not parts:
        return None

    command = parts[0].upper()
    result = {"cmd": command}
    params = {}
    for item in parts[1:]:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip().lower()
        try:
            params[key] = int(float(value))
        except ValueError:
            continue
    result["params"] = params
    return result


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
