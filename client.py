import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import json
import os
import socket
import threading
import ssl

# Windows-only: set taskbar app ID for custom icon grouping
if os.name == "nt":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("chat.room.app")

# UI SPACING CONSTANTS
PAD_X = 3
PAD_Y = 3
SECTION_PAD = 3

# Limits
MAX_NAME_LENGTH = 32
MAX_MESSAGE_LENGTH = 2000
RECV_BUFFER = 4096


class Client:

    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Chat Client")

        # Only load icon on Windows where .ico is natively supported
        if os.name == "nt" and os.path.exists("icon.ico"):
            self.window.iconbitmap("icon.ico")

        self.window.geometry("700x450")
        self.window.minsize(700, 450)

        # SAFE DATA FOLDER
        self.DATA_DIR = "data"
        os.makedirs(self.DATA_DIR, exist_ok=True)

        # NETWORK STATE
        self.host_ip = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="5555")
        self.connected = False
        self.client_socket = None

        # Thread lock — protects self.channels from concurrent access
        # between the main thread and the receive thread.
        self.lock = threading.Lock()

        # AUTO SAVE CONTROL
        self.save_scheduled = False
        self._pending_after_id = None  # track scheduled after() calls

        # CHANNEL DATA
        self.channels = {
            "General": [],
            "Random": [],
            "Gaming": []
        }

        self.current_channel = "General"

        self.load_channels()

        # BUILD UI
        self.build_ui()

        self.refresh_chat()
        self.window.mainloop()

    # ---------------- UI ----------------

    def build_ui(self):

        # MAIN FRAME
        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.top_frame = tk.Frame(self.main_frame)
        self.top_frame.pack(fill=tk.X, padx=PAD_X, pady=PAD_Y)

        # LEFT PANEL
        self.left_frame = tk.Frame(self.top_frame, width=150)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=PAD_X)

        tk.Label(
            self.left_frame,
            text="Channels",
            font=("Arial", 12, "bold")
        ).pack(anchor="w", padx=SECTION_PAD, pady=(5, 0))

        self.channel_list = tk.Listbox(self.left_frame, height=6)

        for ch in self.channels:
            self.channel_list.insert(tk.END, ch)

        self.channel_list.pack(
            fill=tk.Y,
            padx=SECTION_PAD,
            pady=PAD_Y
        )

        self.channel_list.bind(
            "<<ListboxSelect>>",
            self.switch_channel
        )

        # Defer selection so the widget is fully rendered first
        self.window.after(0, lambda: self.channel_list.selection_set(0))

        # RIGHT PANEL
        self.right_frame = tk.Frame(self.top_frame)

        self.right_frame.pack(
            side=tk.RIGHT,
            fill=tk.BOTH,
            expand=True,
            padx=PAD_X
        )

        # CONNECTION FRAME
        self.conn_frame = tk.Frame(self.right_frame)
        self.conn_frame.pack(fill=tk.X, pady=PAD_Y)

        tk.Label(self.conn_frame, text="Host:").pack(side=tk.LEFT)

        tk.Entry(
            self.conn_frame,
            textvariable=self.host_ip,
            width=15
        ).pack(side=tk.LEFT, padx=PAD_X)

        tk.Label(self.conn_frame, text="Port:").pack(side=tk.LEFT)

        tk.Entry(
            self.conn_frame,
            textvariable=self.port,
            width=7
        ).pack(side=tk.LEFT, padx=PAD_X)

        self.connect_button = tk.Button(
            self.conn_frame,
            text="Connect",
            command=self.toggle_connection,
            width=12
        )

        self.connect_button.pack(side=tk.LEFT, padx=PAD_X)

        self.status_label = tk.Label(
            self.conn_frame,
            text="Offline"
        )

        self.status_label.pack(side=tk.LEFT, padx=SECTION_PAD)

        # NAME FRAME
        self.name_frame = tk.Frame(self.right_frame)
        self.name_frame.pack(fill=tk.X, pady=PAD_Y)

        tk.Label(self.name_frame, text="Name:").pack(side=tk.LEFT)

        self.name_entry = tk.Entry(self.name_frame)
        # Enforce max name length at the widget level
        vcmd = self.window.register(
            lambda s: len(s) <= MAX_NAME_LENGTH
        )
        self.name_entry.config(validate="key", validatecommand=(vcmd, "%P"))

        self.name_entry.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
            padx=SECTION_PAD
        )

        self.name_entry.insert(0, "User")

        # MESSAGE LABEL
        tk.Label(
            self.right_frame,
            text="Message:"
        ).pack(anchor="w")

        # MESSAGE BOX
        self.message_entry = tk.Text(
            self.right_frame,
            height=3,
            font=("Arial", 11)
        )

        self.message_entry.pack(
            fill=tk.X,
            pady=PAD_Y
        )

        # BUTTON FRAME
        self.button_frame = tk.Frame(self.right_frame)
        self.button_frame.pack(fill=tk.X, pady=PAD_Y)

        self.send_button = tk.Button(
            self.button_frame,
            text="Send",
            command=self.send_message,
            width=12
        )
        self.send_button.pack(side=tk.LEFT, padx=(0, PAD_X))

        tk.Button(
            self.button_frame,
            text="Clear Chat",
            command=self.clear_chat,
            width=12
        ).pack(side=tk.LEFT)

        # CHAT LABEL
        self.chat_label = tk.Label(
            self.main_frame,
            text=f"Chat - {self.current_channel}",
            font=("Arial", 12, "bold")
        )

        self.chat_label.pack(
            anchor="w",
            padx=SECTION_PAD,
            pady=(10, 0)
        )

        # CHAT AREA
        self.chat_area = scrolledtext.ScrolledText(
            self.main_frame,
            wrap=tk.WORD,
            state='disabled',
            font=("Arial", 11),
            height=15
        )

        self.chat_area.pack(
            fill=tk.BOTH,
            expand=True,
            padx=SECTION_PAD,
            pady=SECTION_PAD
        )

        # BINDINGS
        self.message_entry.bind("<Return>", self.send_message)
        self.message_entry.bind("<Shift-Return>", self.new_line)

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- HELPERS ----------------

    def _get_name(self):
        """Return a sanitized, non-empty display name."""
        name = self.name_entry.get().strip()
        # Strip characters that would break JSON or newline framing
        name = name.replace('"', "'").replace("\n", " ")
        return name or "User"

    def _validate_port(self):
        """
        Parse and validate the port field.
        Returns the integer port on success, or None on failure
        (also updates status_label with an error message).
        """
        try:
            port = int(self.port.get())
            if not (1 <= port <= 65535):
                raise ValueError("Out of range")
            return port
        except ValueError:
            self.status_label.config(text="Invalid port (1–65535)")
            return None

    # ---------------- CONNECTION TOGGLE ----------------

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        ip = self.host_ip.get().strip()
        port = self._validate_port()

        if not ip:
            self.status_label.config(text="Enter a host IP")
            return

        if port is None:
            return

        try:
            # NOTE: cert verification is intentionally disabled here to allow
            # self-signed certificates on local/LAN servers. Do NOT use in
            # production without enabling hostname and cert verification.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.client_socket = context.wrap_socket(
                raw_socket,
                server_hostname=ip
            )

            self.client_socket.connect((ip, port))
            self.connected = True

        except Exception as e:
            self.status_label.config(text="Connection failed")
            print(f"[connect] {e}")
            return

        # Send initial handshake
        try:
            packet = {
                "type": "connect",
                "name": self._get_name(),
                "channel": self.current_channel
            }
            self._send_packet(packet)

        except Exception as e:
            print(f"[connect handshake] {e}")
            self.disconnect()
            return

        self.status_label.config(text=f"Connected: {ip}:{port}")
        self.connect_button.config(text="Disconnect")

        threading.Thread(
            target=self.receive_messages,
            daemon=True
        ).start()

    def disconnect(self):
        self.connected = False

        try:
            if self.client_socket:
                self.client_socket.close()
        except Exception as e:
            print(f"[disconnect] {e}")

        self.client_socket = None
        self.status_label.config(text="Offline")
        self.connect_button.config(text="Connect")

    # ---------------- SEND PACKET ----------------

    def _send_packet(self, packet: dict):
        """
        Serialize and send a JSON packet over the socket.
        Raises on failure — callers must handle.
        """
        data = (json.dumps(packet) + "\n").encode()
        self.client_socket.send(data)

    # ---------------- RECEIVE ----------------

    def receive_messages(self):
        buffer = ""

        while self.connected:
            try:
                data = self.client_socket.recv(RECV_BUFFER).decode()

                if not data:
                    break

                buffer += data

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)

                    try:
                        packet = json.loads(line)
                    except json.JSONDecodeError as e:
                        print(f"[receive] Bad JSON: {e}")
                        continue

                    msg_type = packet.get("type", "message")
                    name = packet.get("name", "User")
                    channel = packet.get("channel", "General")
                    text = packet.get("message", "")
                    sender = packet.get("sender_id", None)

                    # Skip messages the server echoed back from this client
                    # (if server includes a sender_id). Remove the `sender`
                    # check if your server does not echo back at all.
                    my_id = getattr(self, "my_id", None)
                    if sender is not None and sender == my_id:
                        continue

                    timestamp = datetime.now().strftime("%H:%M")

                    if msg_type == "system":
                        formatted = f"[{timestamp}] *** {text} ***"
                    else:
                        formatted = f"[{timestamp}] {name}: {text}"

                    if channel in self.channels:
                        with self.lock:
                            self.channels[channel].append(formatted)

                        self.window.after(0, self.schedule_save)

                    if channel == self.current_channel:
                        self.window.after(
                            0,
                            lambda m=formatted: self.display_message(m)
                        )

            except Exception as e:
                print(f"[receive_messages] {e}")
                break

        self.window.after(0, self.disconnect)

    # ---------------- SAVE SYSTEM ----------------

    def schedule_save(self):
        if not self.save_scheduled:
            self.save_scheduled = True
            self._pending_after_id = self.window.after(1000, self._do_save)

    def _do_save(self):
        self._pending_after_id = None
        self.save_channels()
        self.save_scheduled = False

    def _cancel_pending_save(self):
        """Cancel any scheduled (but not yet fired) auto-save."""
        if self._pending_after_id is not None:
            self.window.after_cancel(self._pending_after_id)
            self._pending_after_id = None
            self.save_scheduled = False

    def get_path(self, channel):
        return os.path.join(self.DATA_DIR, f"{channel}.json")

    def save_channels(self):
        with self.lock:
            snapshot = {ch: list(msgs) for ch, msgs in self.channels.items()}

        for channel, messages in snapshot.items():
            try:
                with open(self.get_path(channel), "w", encoding="utf-8") as f:
                    json.dump(messages, f, indent=2, ensure_ascii=False)
            except OSError as e:
                print(f"[save_channels] Could not save '{channel}': {e}")

    def load_channels(self):
        for channel in self.channels:
            path = self.get_path(channel)

            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.channels[channel] = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    print(f"[load_channels] Could not load '{channel}': {e}")
                    self.channels[channel] = []

    # ---------------- CHAT ----------------

    def switch_channel(self, event):
        sel = self.channel_list.curselection()

        if not sel:
            return

        self.current_channel = self.channel_list.get(sel[0])
        self.chat_label.config(text=f"Chat - {self.current_channel}")
        self.refresh_chat()

        if self.connected and self.client_socket:
            try:
                packet = {
                    "type": "join",
                    "channel": self.current_channel,
                    "name": self._get_name()
                }
                self._send_packet(packet)
            except Exception as e:
                print(f"[switch_channel] {e}")
                self.disconnect()

    def send_message(self, event=None):
        message = self.message_entry.get("1.0", tk.END).strip()
        name = self._get_name()

        if not message:
            return "break"

        # Silently truncate oversized messages
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH]

        timestamp = datetime.now().strftime("%H:%M")
        formatted = f"[{timestamp}] {name}: {message}"

        # Append locally and display immediately (optimistic update)
        with self.lock:
            self.channels[self.current_channel].append(formatted)

        self.display_message(formatted)
        self.schedule_save()

        if self.connected and self.client_socket:
            try:
                packet = {
                    "name": name,
                    "channel": self.current_channel,
                    "message": message
                }
                self._send_packet(packet)

            except Exception as e:
                print(f"[send_message] {e}")
                self.disconnect()

        self.message_entry.delete("1.0", tk.END)
        return "break"

    def new_line(self, event=None):
        self.message_entry.insert(tk.INSERT, "\n")
        return "break"

    def display_message(self, message):
        self.chat_area.config(state="normal")
        self.chat_area.insert(tk.END, message + "\n")
        self.chat_area.config(state="disabled")
        self.chat_area.yview(tk.END)

    def refresh_chat(self):
        self.chat_area.config(state="normal")
        self.chat_area.delete("1.0", tk.END)

        with self.lock:
            messages = list(self.channels[self.current_channel])

        for msg in messages:
            self.chat_area.insert(tk.END, msg + "\n")

        self.chat_area.config(state="disabled")
        self.chat_area.yview(tk.END)

    def clear_chat(self):
        with self.lock:
            self.channels[self.current_channel] = []

        self.refresh_chat()
        self.save_channels()

    def on_close(self):
        # Cancel any pending auto-save timer before destroying the window
        self._cancel_pending_save()
        self.disconnect()
        # Always do a final synchronous save so nothing is lost
        self.save_channels()
        self.window.destroy()


if __name__ == "__main__":
    Client()