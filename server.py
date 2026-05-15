import socket
import threading
import json
import ssl
import tkinter as tk
from datetime import datetime
import ctypes

HOST = "0.0.0.0"
PORT = 5555

# ---------------- SSL ----------------
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

server = context.wrap_socket(server, server_side=True)


# ---------------- SERVER STATE ----------------
clients = []  # (client, channel, name)

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# ---------------- UI ----------------
class Server:

    def __init__(self):
        # IMPORTANT: set BEFORE Tk()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("chat.room.server.app")

        self.window = tk.Tk()
        self.window.title("Chat Server Dashboard")
        self.window.iconbitmap("icon.ico")
        self.window.geometry("700x500")

        # ---------------- NETWORK INFO PANEL ----------------
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
            text=f"Local IP (LAN): {local_ip} Port: {PORT}",
            font=("Arial", 10)
        ).pack()

        # CLIENT LIST
        self.client_box = tk.Listbox(self.window, height=10)
        self.client_box.pack(fill=tk.X, padx=10, pady=5)

        # LOG AREA
        self.log = tk.Text(self.window, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    def log_msg(self, msg):
        self.log.config(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def update_clients(self):
        self.client_box.delete(0, tk.END)
        for c, ch, name in clients:
            self.client_box.insert(tk.END, f"{name} ({ch})")

    def safe_log(self, msg):
        self.window.after(0, lambda: self.log_msg(msg))

    def safe_update_clients(self):
        self.window.after(0, self.update_clients)

    def run(self):
        self.window.mainloop()


ui = Server()


# ---------------- CORE LOGIC ----------------
def broadcast(packet, sender=None):
    target_channel = packet.get("channel", "General")

    for client, channel, name in clients:
        if client != sender and channel == target_channel:
            try:
                client.send((json.dumps(packet) + "\n").encode())
            except:
                remove_client(client)


def remove_client(client):
    global clients

    for c, ch, name in clients:
        if c == client:
            clients.remove((c, ch, name))

            ui.safe_log(f"[DISCONNECTED] {name}")
            ui.safe_update_clients()

            broadcast({
                "type": "system",
                "event": "leave",
                "name": name,
                "channel": ch,
                "message": f"{name} left the chat"
            })

            break


def handle_client(client):
    buffer = ""
    name = "User"
    channel = "General"

    clients.append((client, channel, name))

    ui.safe_log("[NEW CLIENT CONNECTED]")
    ui.safe_update_clients()

    broadcast({
        "type": "system",
        "event": "join",
        "name": name,
        "channel": channel,
        "message": f"{name} joined the chat"
    }, sender=client)

    while True:
        try:
            data = client.recv(1024).decode()
            if not data:
                break

            buffer += data

            while "\n" in buffer:
                msg, buffer = buffer.split("\n", 1)

                try:
                    packet = json.loads(msg)
                except:
                    continue

                msg_type = packet.get("type", "message")
                name = packet.get("name", "User")
                channel = packet.get("channel", "General")

                # update client info
                for i, (c, ch, n) in enumerate(clients):
                    if c == client:
                        clients[i] = (client, channel, name)

                ui.safe_update_clients()

                # JOIN
                if msg_type == "join":
                    ui.safe_log(f"[CHANNEL SWITCH] {name} -> {channel}")
                    continue

                # MESSAGE
                text = packet.get("message", "")
                ui.safe_log(f"[{channel}] {name}: {text}")

                broadcast({
                    "type": "message",
                    "name": name,
                    "channel": channel,
                    "message": text
                }, sender=client)

        except:
            break

    remove_client(client)
    client.close()


# ---------------- ACCEPT LOOP ----------------
def accept_loop():
    while True:
        client, addr = server.accept()
        print(f"[CONNECTED] {addr}")

        ui.safe_log(f"[CONNECTED] {addr}")

        thread = threading.Thread(
            target=handle_client,
            args=(client,),
            daemon=True
        )
        thread.start()


# ---------------- START ----------------
threading.Thread(target=accept_loop, daemon=True).start()
ui.run()
