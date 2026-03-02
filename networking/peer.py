# connect_four/networking/peer.py
# Robust P2P connection helper for game play.
# - Newline-delimited JSON over TCP
# - Safe shutdown sequencing (stop send/recv, shutdown, close, join)
# - Guarded send() when not connected/running

import socket
import threading
import json
import queue
from typing import Callable, Optional

MESSAGE_DELIMITER = "\n"


class PeerConnection:
    """
    Thin wrapper around a TCP socket for P2P messaging.
    Host flow:
        PeerConnection(is_host=True, ip="", port=port, on_message=cb)
        -> internally listens and accepts 1 connection, then starts I/O threads.

    Guest flow:
        PeerConnection(is_host=False, ip=host_ip, port=host_port, on_message=cb)
        -> connects immediately, then starts I/O threads.
    """

    def __init__(self, is_host: bool, ip: str, port: int, on_message: Optional[Callable[[dict], None]]):
        self.sock: Optional[socket.socket] = None
        self.send_queue: "queue.Queue[Optional[dict]]" = queue.Queue()
        self.on_message: Optional[Callable[[dict], None]] = on_message

        self.running = threading.Event()
        self.running.set()
        self._closed = threading.Event()

        self.recv_thread: Optional[threading.Thread] = None
        self.send_thread: Optional[threading.Thread] = None

        if is_host:
            threading.Thread(target=self._start_host, args=(port,), daemon=True).start()
        else:
            self._connect_to_peer(ip, port)
            self._start_threads()

    # --- lifecycle ----------------------------------------------------------

    def _start_host(self, port: int):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Allow quick reuse when players rehost a new game
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("", port))
            listener.listen(1)
            print(f"[HOST] Waiting for peer to connect on port {port}...")
            self.sock, addr = listener.accept()
            print(f"[HOST] Connection established with {addr}")
            self._start_threads()
        except Exception as e:
            print(f"[HOST ERROR] {e}")
            self.running.clear()
        finally:
            try:
                listener.close()
            except Exception:
                pass

    def _connect_to_peer(self, ip: str, port: int):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((ip, port))
            print(f"[GUEST] Connected to host at {ip}:{port}")
        except Exception as e:
            print(f"[GUEST ERROR] {e}")
            self.running.clear()
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            raise

    def wait_until_connected(self, timeout: float = 5.0) -> bool:
        import time
        start = time.time()
        while self.sock is None and (time.time() - start < timeout):
            time.sleep(0.05)
        return self.sock is not None

    def _start_threads(self):
        if not self.sock:
            return
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True, name="PeerRecv")
        self.send_thread = threading.Thread(target=self._send_loop, daemon=True, name="PeerSend")
        self.recv_thread.start()
        self.send_thread.start()

    # --- I/O loops ----------------------------------------------------------

    def _recv_loop(self):
        buffer = ""
        try:
            while self.running.is_set():
                try:
                    data = self.sock.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", errors="ignore")
                    while MESSAGE_DELIMITER in buffer:
                        line, buffer = buffer.split(MESSAGE_DELIMITER, 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                            if self.on_message:
                                self.on_message(msg)
                        except json.JSONDecodeError:
                            print(f"[WARN] Invalid JSON: {line[:120]}")
                except (ConnectionResetError, BrokenPipeError, OSError):
                    break
        except Exception as e:
            print(f"[RECV ERROR] {e}")
        finally:
            self.running.clear()
            self._closed.set()

    def _send_loop(self):
        try:
            while self.running.is_set():
                msg = self.send_queue.get()
                if msg is None:
                    break
                if not self.sock:
                    break
                try:
                    raw = json.dumps(msg) + MESSAGE_DELIMITER
                    self.sock.sendall(raw.encode("utf-8"))
                except (ConnectionResetError, BrokenPipeError, OSError):
                    break
                except Exception as e:
                    print(f"[SEND ERROR] {e}")
                    break
        finally:
            self.running.clear()
            self._closed.set()

    # --- API ----------------------------------------------------------------

    def set_on_message(self, cb: Optional[Callable[[dict], None]]):
        self.on_message = cb

    def send(self, msg: dict) -> bool:
        """Queue a message for sending. Returns False if not running."""
        if not self.running.is_set():
            return False
        self.send_queue.put(msg)
        return True

    def is_connected(self) -> bool:
        return self.running.is_set() and self.sock is not None

    def close(self):
        """Orderly shutdown: stop loops, signal send thread, shutdown socket, join threads, close."""
        if not self.running.is_set() and self._closed.is_set():
            return
        self.running.clear()
        # Unblock sender
        self.send_queue.put(None)
        # Half-close to wake recv
        try:
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
        except Exception:
            pass

        # Join threads briefly (best-effort)
        for t in (self.recv_thread, self.send_thread):
            if t and t.is_alive():
                try:
                    t.join(timeout=0.3)
                except Exception:
                    pass

        # Close socket
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        finally:
            self.sock = None
            self._closed.set()
