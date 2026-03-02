# connect_four/networking/server.py
# Authoritative lobby server with UUID session IDs, periodic roster pushes,
# pruning on send failure, and heartbeat timeouts.
# Protocol: newline-delimited JSON over TCP.

import socket
import threading
import json
import time
import uuid

HOST = "0.0.0.0"
PORT = 12345

HEARTBEAT_TIMEOUT = 90   # seconds without heartbeat before pruning
REAPER_INTERVAL   = 10   # how often to scan for timeouts
BROADCAST_INTERVAL = 30  # always push roster every 30s, even if unchanged

# Registry: session_id -> info
# info: {"conn":socket, "name":str, "ip":str, "p2p_port":int, "last_seen":float}
_clients = {}
_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _snapshot():
    """Return a list of public client info for broadcasts (no sockets)."""
    with _lock:
        return [
            {"session_id": sid, "name": info["name"], "ip": info["ip"], "p2p_port": info["p2p_port"]}
            for sid, info in _clients.items()
        ]


def _send_line(conn: socket.socket, obj: dict) -> bool:
    try:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        return True
    except Exception:
        return False


def remove_client(session_id: str, reason: str = "leave", suppress_broadcast: bool = False):
    """Remove client from registry, close socket, optionally broadcast."""
    with _lock:
        info = _clients.pop(session_id, None)

    if info:
        try:
            info["conn"].close()
        except Exception:
            pass
        print(f"[REMOVE] {info['name']} ({session_id}) reason={reason}")

        if not suppress_broadcast:
            broadcast_client_list(reason=reason)


def broadcast_client_list(reason: str = "interval"):
    """Send roster to all; if any send fails, prune those clients and rebroadcast once."""
    roster = _snapshot()
    msg = (json.dumps({"type": "client_list", "clients": roster}) + "\n").encode("utf-8")

    dead = []
    with _lock:
        for sid, info in list(_clients.items()):
            try:
                info["conn"].sendall(msg)
            except Exception:
                dead.append(sid)

    if dead:
        for sid in dead:
            remove_client(sid, reason="disconnect", suppress_broadcast=True)
        # One extra pass so survivors converge
        if reason != "prune":
            broadcast_client_list(reason="prune")
            return

    print(f"[BROADCAST] roster to {len(roster)} clients (reason={reason})")


def reaper_loop():
    """Periodically prune clients that missed heartbeats."""
    while True:
        time.sleep(REAPER_INTERVAL)
        now = _now()
        to_prune = []
        with _lock:
            for sid, info in list(_clients.items()):
                if now - info["last_seen"] > HEARTBEAT_TIMEOUT:
                    to_prune.append(sid)
        if to_prune:
            for sid in to_prune:
                remove_client(sid, reason="timeout", suppress_broadcast=True)
            broadcast_client_list(reason="timeout")


def periodic_broadcast_loop():
    """Push roster on a fixed cadence even if nothing changed."""
    while True:
        time.sleep(BROADCAST_INTERVAL)
        broadcast_client_list(reason="interval")


def handle_client(conn: socket.socket, addr):
    conn.settimeout(2.0)
    buffer = ""
    session_id = None
    joined = False

    try:
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue

                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        print(f"[WARN] Bad JSON from {addr}: {line[:120]}")
                        continue

                    mtype = msg.get("type", "")

                    if mtype == "join":
                        # Fresh session for each join
                        session_id = uuid.uuid4().hex
                        name = str(msg.get("name", "Player"))
                        p2p_port = int(msg.get("p2p_port", 0))

                        with _lock:
                            _clients[session_id] = {
                                "conn": conn,
                                "name": name,
                                "ip": addr[0],
                                "p2p_port": p2p_port,
                                "last_seen": _now()
                            }

                        joined = True
                        _send_line(conn, {"type": "welcome", "session_id": session_id})
                        print(f"[JOIN] {name} ({session_id}) from {addr[0]}:{addr[1]} p2p={p2p_port}")
                        broadcast_client_list(reason="join")

                    elif mtype == "heartbeat":
                        with _lock:
                            if session_id and session_id in _clients:
                                _clients[session_id]["last_seen"] = _now()

                    elif mtype == "leave":
                        # Explicit leave: remove now and stop handling this socket
                        remove_client(session_id or f"{addr}", reason="leave", suppress_broadcast=False)
                        return

                    else:
                        # Any other message counts as activity
                        with _lock:
                            if session_id and session_id in _clients:
                                _clients[session_id]["last_seen"] = _now()

            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError, OSError):
                break

    finally:
        # On disconnect, prune if still registered
        if joined and session_id and session_id in _clients:
            remove_client(session_id, reason="disconnect", suppress_broadcast=False)
        else:
            try:
                conn.close()
            except Exception:
                pass


def start_server():
    print(f"[START] Lobby server on {HOST}:{PORT} "
          f"(HB_TIMEOUT={HEARTBEAT_TIMEOUT}s, PUSH_EVERY={BROADCAST_INTERVAL}s)")
    threading.Thread(target=reaper_loop, daemon=True).start()
    threading.Thread(target=periodic_broadcast_loop, daemon=True).start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen()

    try:
        while True:
            try:
                conn, addr = srv.accept()
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"[ACCEPT ERROR] {e}")
    finally:
        try:
            srv.close()
        except Exception:
            pass


if __name__ == "__main__":
    start_server()
