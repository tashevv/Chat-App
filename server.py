import socket
import threading
import json
import ssl
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import os

# Windows-only: set taskbar app ID for custom icon grouping
if os.name == "nt":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("chat.room.server.app")

HOST = "0.0.0.0"
PORT = 5555
MAX_CLIENTS = 50
RECV_BUFFER = 4096


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"[get_local_ip] {e}")
        return "127.0.0.1"


def timestamp():
    return datetime.now().strftime("%H:%M:%S")


# ---------------- SERVER STATE ----------------

class ServerState:
    """
    Owns all shared mutable state. Every access to clients goes
    through this class so locking is centralised and consistent.
    """

    def __init__(self):
        # clients: socket → {"name": str, "channel": str}
        self._clients: dict = {}
        self._lock = threading.Lock()

    # ---- read ----

    def snapshot(self) -> list:
        """Return a stable list of (socket, info) pairs for iteration."""
        with self._lock:
            return list(self._clients.items())

    def count(self) -> int:
        with self._lock:
            return len(self._clients)

    def get_info(self, client) -> dict | None:
        with self._lock:
            return self._clients.get(client)

    # ---- write ----

    def add(self, client, name: str, channel: str):
        with self._lock:
            self._clients[client] = {"name": name, "channel": channel}

    def update(self, client, name: str, channel: str):
        with self._lock:
            if client in self._clients:
                self._clients[client] = {"name": name, "channel": channel}

    def remove(self, client) -> dict | None:
        """
        Remove a client and return its info dict, or None if not found.
        Safe to call even if the client was already removed.
        """
        with self._lock:
            return self._clients.pop(client, None)


# ---------------- UI ----------------

class ServerUI:

    def __init__(self, window: tk.Tk, state: ServerState):
        self.window = window
        self.state = state

        self.window.title("Chat Server")
        self.window.geometry("700x450")
        self.window.minsize(700, 450)

        if os.name == "nt" and os.path.exists("icon.ico"):
            self.window.iconbitmap("icon.ico")

        # NETWORK INFO
        network_frame = tk.Frame(self.window)
        network_frame.pack(pady=5)

        local_ip = get_local_ip()

        tk.Label(
            network_frame,
            text="Connection Info:",
            font=("Arial", 11, "bold")
        ).pack()

        tk.Label(
            network_frame,
            text=f"Local IP (LAN): {local_ip}    Port: {PORT}",
            font=("Arial", 10)
        ).pack()

        # CLIENT LIST FRAME
        client_frame = tk.Frame(self.window)
        client_frame.pack(fill=tk.X, padx=10, pady=(5, 0))

        tk.Label(
            client_frame,
            text="Connected Clients:",
            font=("Arial", 10, "bold")
        ).pack(anchor="w")

        list_frame = tk.Frame(client_frame)
        list_frame.pack(fill=tk.X)

        self.client_box = tk.Listbox(list_frame, height=8)
        self.client_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # KICK BUTTON
        self.kick_button = tk.Button(
            list_frame,
            text="Kick",
            width=8,
            command=self._kick_selected
        )
        self.kick_button.pack(side=tk.LEFT, padx=(5, 0), anchor="n")

        # LOG AREA
        tk.Label(
            self.window,
            text="Server Log:",
            font=("Arial", 10, "bold")
        ).pack(anchor="w", padx=10)

        self.log = scrolledtext.ScrolledText(
            self.window,
            state="disabled",
            font=("Courier", 10)
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Map listbox index → socket for kick support
        self._index_to_socket: list = []

    # ---- logging ----

    def log_msg(self, msg: str):
        """Append a timestamped line to the log. Must be called from main thread."""
        self.log.config(state="normal")
        self.log.insert(tk.END, f"[{timestamp()}] {msg}\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def safe_log(self, msg: str):
        """Thread-safe log: schedules log_msg on the main thread."""
        self.window.after(0, lambda: self.log_msg(msg))

    # ---- client list ----

    def update_clients(self):
        """Rebuild the client listbox. Must be called from main thread."""
        self.client_box.delete(0, tk.END)
        self._index_to_socket = []

        for sock, info in self.state.snapshot():
            self.client_box.insert(
                tk.END,
                f"{info['name']}  ({info['channel']})"
            )
            self._index_to_socket.append(sock)

    def safe_update_clients(self):
        self.window.after(0, self.update_clients)

    # ---- kick ----

    def _kick_selected(self):
        sel = self.client_box.curselection()
        if not sel:
            return

        idx = sel[0]
        if idx >= len(self._index_to_socket):
            return

        sock = self._index_to_socket[idx]
        info = self.state.get_info(sock)
        name = info["name"] if info else "Unknown"

        self.log_msg(f"[KICK] Kicking {name}")

        # Closing the socket causes handle_client's recv() to raise,
        # which triggers the normal remove_client / cleanup path.
        try:
            sock.close()
        except Exception as e:
            print(f"[kick] {e}")


# ---------------- CHAT SERVER ----------------

class ChatServer:

    def __init__(self):
        self.state = ServerState()
        self.running = False
        self.server_socket = None

        # Build SSL context — fail early with a clear message
        try:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(
                certfile="cert.pem",
                keyfile="key.pem"
            )
        except (FileNotFoundError, ssl.SSLError) as e:
            raise RuntimeError(
                f"SSL setup failed: {e}\n"
                "Make sure cert.pem and key.pem exist in the working directory."
            ) from e

        # Build server socket
        try:
            raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            raw.bind((HOST, PORT))
            raw.listen()
            self.server_socket = self.ssl_context.wrap_socket(raw, server_side=True)
        except OSError as e:
            raise RuntimeError(f"Could not bind to {HOST}:{PORT} — {e}") from e

        # Build UI
        self.window = tk.Tk()
        self.ui = ServerUI(self.window, self.state)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- BROADCAST ----------------

    def broadcast(self, packet: dict, sender=None):
        """Send packet to all clients in the same channel, except sender."""
        target_channel = packet.get("channel", "General")
        data = (json.dumps(packet) + "\n").encode()

        for sock, info in self.state.snapshot():
            if sock == sender:
                continue
            if info["channel"] != target_channel:
                continue
            try:
                sock.send(data)
            except Exception as e:
                print(f"[broadcast] Failed to send to {info['name']}: {e}")
                self.remove_client(sock)

    # ---------------- REMOVE CLIENT ----------------

    def remove_client(self, client):
        info = self.state.remove(client)
        if info is None:
            return  # Already removed by another thread — nothing to do

        name = info["name"]
        channel = info["channel"]

        self.ui.safe_log(f"[DISCONNECTED] {name}")
        self.ui.safe_update_clients()

        self.broadcast({
            "type": "system",
            "event": "leave",
            "name": name,
            "channel": channel,
            "message": f"{name} left the chat"
        })

    # ---------------- HANDLE CLIENT ----------------

    def handle_client(self, client, addr):
        buffer = ""
        name = "User"
        channel = "General"
        joined = False  # True after the connect packet is processed

        # Check capacity before registering
        if self.state.count() >= MAX_CLIENTS:
            self.ui.safe_log(f"[REJECTED] {addr} — server full ({MAX_CLIENTS} clients)")
            try:
                client.close()
            except Exception:
                pass
            return

        self.state.add(client, name, channel)
        self.ui.safe_log(f"[CONNECTED] {addr}")
        self.ui.safe_update_clients()

        while self.running:
            try:
                data = client.recv(RECV_BUFFER).decode()
                if not data:
                    break

                buffer += data

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    try:
                        packet = json.loads(line)
                    except json.JSONDecodeError as e:
                        print(f"[handle_client] Bad JSON from {addr}: {e}")
                        continue

                    msg_type = packet.get("type", "message")
                    name = packet.get("name", "User")
                    channel = packet.get("channel", "General")

                    # Sanitize inputs
                    name = name[:32].replace('"', "'").replace("\n", " ") or "User"
                    channel = channel if channel in ("General", "Random", "Gaming") else "General"

                    self.state.update(client, name, channel)
                    self.ui.safe_update_clients()

                    # CONNECT — initial handshake; announce join after real name known
                    if msg_type == "connect":
                        joined = True
                        self.ui.safe_log(f"[JOIN] {name} -> #{channel}")
                        self.broadcast({
                            "type": "system",
                            "event": "join",
                            "name": name,
                            "channel": channel,
                            "message": f"{name} joined the chat"
                        }, sender=client)
                        continue

                    # JOIN — channel switch
                    if msg_type == "join":
                        self.ui.safe_log(f"[SWITCH] {name} -> #{channel}")
                        continue

                    # MESSAGE
                    text = packet.get("message", "").strip()
                    if not text:
                        continue

                    # Truncate oversized messages server-side as well
                    text = text[:2000]

                    self.ui.safe_log(f"[#{channel}] {name}: {text}")

                    self.broadcast({
                        "type": "message",
                        "name": name,
                        "channel": channel,
                        "message": text
                    }, sender=client)

            except Exception as e:
                print(f"[handle_client] {addr}: {e}")
                break

        self.remove_client(client)
        try:
            client.close()
        except Exception:
            pass

    # ---------------- ACCEPT LOOP ----------------

    def accept_loop(self):
        self.ui.safe_log(f"[LISTENING] {HOST}:{PORT}")

        while self.running:
            try:
                client, addr = self.server_socket.accept()
            except Exception as e:
                if self.running:
                    print(f"[accept_loop] {e}")
                break

            threading.Thread(
                target=self.handle_client,
                args=(client, addr),
                daemon=True
            ).start()

    # ---------------- SHUTDOWN ----------------

    def on_close(self):
        """Graceful shutdown: stop accepting, close all client sockets, destroy UI."""
        self.running = False
        self.ui.safe_log("[SHUTDOWN] Server closing...")

        # Close the server socket so accept_loop unblocks
        try:
            self.server_socket.close()
        except Exception as e:
            print(f"[on_close] server socket: {e}")

        # Close all client connections
        for sock, info in self.state.snapshot():
            try:
                sock.close()
            except Exception as e:
                print(f"[on_close] client {info['name']}: {e}")

        self.window.destroy()

    # ---------------- START ----------------

    def start(self):
        self.running = True
        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.window.mainloop()


# ---------------- ENTRY POINT ----------------

if __name__ == "__main__":
    try:
        server = ChatServer()
        server.start()
    except RuntimeError as e:
        print(f"[FATAL] {e}")