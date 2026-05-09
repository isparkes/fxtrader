"""
FX Trader Control Console
=========================
Thin wrapper around the daemon's telnet control port.
Prefer using telnet directly:

    telnet localhost 9876

This script is useful for scripting / one-liners:

    python fxctl.py status
    python fxctl.py pause
    python fxctl.py pause_entry
    python fxctl.py resume_entry
    python fxctl.py pause_exit
    python fxctl.py resume_exit
    python fxctl.py materialise_sl
    python fxctl.py materialise_tp
    python fxctl.py be
    python fxctl.py close
    python fxctl.py --host 192.168.1.10 status
"""

import argparse
import socket
import sys

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876


def send_command(cmd: str, host: str, port: int) -> str:
    """Send one command, return the response text."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((host, port))
        except (ConnectionRefusedError, OSError) as exc:
            return f"ERROR: {exc}"
        # Send command then quit so the server closes cleanly.
        s.sendall((cmd.strip() + "\nquit\n").encode())
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks).decode(errors="replace")
    # Server sends: welcome + "> " + response + "> " + "Bye."
    # Split on "> " (max 2 splits) so the response is always parts[1].
    parts = raw.split("> ", 2)
    return parts[1].strip() if len(parts) >= 2 else raw.strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FX Trader one-shot control client")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("command", nargs="+", help="Command to send")
    args = parser.parse_args()
    print(send_command(" ".join(args.command), args.host, args.port))
