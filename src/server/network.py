"""Network utilities — local IP detection, firewall check, QR code generation."""

import socket
import subprocess
import sys


def get_local_ips():
    """Return all non-loopback IPv4 addresses of this machine."""
    ips = []
    try:
        hostname = socket.gethostname()
        candidates = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        seen = set()
        for info in candidates:
            ip = info[4][0]
            if ip not in seen and not ip.startswith("127."):
                seen.add(ip)
                ips.append(ip)
    except Exception:
        pass

    # Fallback: try connecting a UDP socket (doesn't actually send data)
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                ips.append(ip)
        except Exception:
            pass

    return ips


def _is_firewall_enabled():
    """Check if Windows Firewall is actually enabled on any profile."""
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles", "state"],
            capture_output=True, text=True, errors="replace", timeout=10,
        )
        # "ON" appears in output when firewall is enabled on a profile
        return "ON" in result.stdout.upper()
    except Exception:
        # If we can't check, assume enabled
        return True


def check_firewall_rule(port):
    """Check if a Windows Firewall rule exists for the given port.
    Returns (rule_exists: bool, can_add: bool, message: str).
    """
    if sys.platform != "win32":
        return True, True, ""

    # If firewall is not enabled at all, no rule needed
    if not _is_firewall_enabled():
        return True, True, "firewall_disabled"

    rule_name = "AI_PDF_Trans_Server"
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
            capture_output=True, text=True, errors="replace", timeout=10,
        )
        if "No rules match" in result.stdout or result.returncode != 0:
            return False, False, rule_name
        return True, False, ""
    except Exception:
        return False, False, rule_name


def add_firewall_rule(port):
    """Try to add a Windows Firewall rule. Returns (success, message)."""
    if sys.platform != "win32":
        return True, ""

    rule_name = "AI_PDF_Trans_Server"
    try:
        result = subprocess.run(
            [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={rule_name}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={port}",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def generate_qr_data_url(url):
    """Generate a QR code PNG as a base64 data URL.
    Returns empty string if qrcode or PIL is not installed.
    """
    try:
        import qrcode
        import io
        import base64

        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except ImportError:
        return ""


def test_port(host, port, timeout=2.0):
    """Test if a TCP port is reachable. Returns (success, error_message)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, int(port)))
        s.close()
        return True, ""
    except Exception as e:
        return False, str(e)
