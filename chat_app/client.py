import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import json
import os
import socket
import threading


class ChatUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Chat Room v2.0")
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

        # AUTO SAVE CONTROL
        self.save_scheduled = False

        # CHANNEL DATA
        self.channels = {
            "General": [],
            "Random": [],
            "Gaming": []
        }

        self.current_channel = "General"

        self.load_channels()

        # MAIN FRAME
        self.main_frame = tk.Frame(self.window)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.top_frame = tk.Frame(self.main_frame)
        self.top_frame.pack(fill=tk.X, padx=5, pady=5)

        # LEFT PANEL
        self.left_frame = tk.Frame(self.top_frame, width=150)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        tk.Label(self.left_frame, text="Channels", font=("Arial", 12, "bold")).pack(
            anchor="w", padx=10, pady=(5, 0)
        )

        self.channel_list = tk.Listbox(self.left_frame, height=6)
        for ch in self.channels:
            self.channel_list.insert(tk.END, ch)

        self.channel_list.pack(fill=tk.Y, padx=10, pady=5)
        self.channel_list.bind("<<ListboxSelect>>", self.switch_channel)
        self.channel_list.selection_set(0)

        # RIGHT PANEL
        self.right_frame = tk.Frame(self.top_frame)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)

        # CONNECTION
        self.conn_frame = tk.Frame(self.right_frame)
        self.conn_frame.pack(fill=tk.X, pady=5)

        tk.Label(self.conn_frame, text="Host:").pack(side=tk.LEFT)

        tk.Entry(self.conn_frame, textvariable=self.host_ip, width=15).pack(side=tk.LEFT, padx=5)

        tk.Label(self.conn_frame, text="Port:").pack(side=tk.LEFT)

        tk.Entry(self.conn_frame, textvariable=self.port, width=7).pack(side=tk.LEFT, padx=5)

        self.connect_button = tk.Button(
            self.conn_frame,
            text="Connect",
            command=self.toggle_connection,
            width=12
        )
        self.connect_button.pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(self.conn_frame, text="Offline")
        self.status_label.pack(side=tk.LEFT, padx=10)

        # NAME
        self.name_frame = tk.Frame(self.right_frame)
        self.name_frame.pack(fill=tk.X, pady=5)

        tk.Label(self.name_frame, text="Name:").pack(side=tk.LEFT)

        self.name_entry = tk.Entry(self.name_frame)
        self.name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.name_entry.insert(0, "User")

        # MESSAGE
        tk.Label(self.right_frame, text="Message:").pack(anchor="w")

        self.message_entry = tk.Text(self.right_frame, height=3, font=("Arial", 11))
        self.message_entry.pack(fill=tk.X, pady=5)

        # BUTTONS
        self.button_frame = tk.Frame(self.right_frame)
        self.button_frame.pack(fill=tk.X, pady=5)

        tk.Button(
            self.button_frame,
            text="Send",
            command=self.send_message,
            width=12
        ).pack(side=tk.LEFT, padx=(0, 10))

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
        self.chat_label.pack(anchor="w", padx=10, pady=(10, 0))

        # CHAT AREA
        self.chat_area = scrolledtext.ScrolledText(
            self.main_frame,
            wrap=tk.WORD,
            state='disabled',
            font=("Arial", 11),
            height=15
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # BINDINGS
        self.message_entry.bind("<Return>", self.send_message)
        self.message_entry.bind("<Shift-Return>", self.new_line)

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.refresh_chat()
        self.window.mainloop()

    # ---------------- CONNECTION TOGGLE ----------------
    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        try:
            ip = self.host_ip.get()
            port = int(self.port.get())

            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, port))

            self.connected = True
            self.status_label.config(text=f"Connected: {ip}:{port}")
            self.connect_button.config(text="Disconnect")

            threading.Thread(target=self.receive_messages, daemon=True).start()

        except Exception as e:
            self.status_label.config(text="Connection failed")
            print(e)

    def disconnect(self):
        self.connected = False

        try:
            if self.client_socket:
                self.client_socket.close()
        except:
            pass

        self.client_socket = None
        self.status_label.config(text="Offline")
        self.connect_button.config(text="Connect")

    # ---------------- RECEIVE ----------------
    def receive_messages(self):
        buffer = ""

        while self.connected:
            try:
                data = self.client_socket.recv(1024).decode()
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
                    text = packet.get("message", "")

                    if msg_type == "system":
                        formatted = f"*** {text} ***"
                    else:
                        formatted = f"[{channel}] {name}: {text}"

                    if channel in self.channels:
                        self.channels[channel].append(formatted)
                        self.window.after(0, self.schedule_save)

                    if channel == self.current_channel:
                        self.window.after(
                            0,
                            lambda m=formatted: self.display_message(m)
                        )

            except:
                break

        self.window.after(0, self.disconnect)

    # ---------------- SAVE SYSTEM ----------------
    def schedule_save(self):
        if not self.save_scheduled:
            self.save_scheduled = True
            self.window.after(1000, self._do_save)

    def _do_save(self):
        self.save_channels()
        self.save_scheduled = False

    def get_path(self, channel):
        return os.path.join(self.DATA_DIR, f"{channel}.json")

    def save_channels(self):
        for channel, messages in self.channels.items():
            with open(self.get_path(channel), "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2, ensure_ascii=False)

    def load_channels(self):
        for channel in self.channels:
            path = self.get_path(channel)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.channels[channel] = json.load(f)
                except:
                    self.channels[channel] = []

    # ---------------- CHAT ----------------
    def switch_channel(self, event):
        sel = self.channel_list.curselection()
        if sel:
            self.current_channel = self.channel_list.get(sel[0])
            self.chat_label.config(text=f"Chat - {self.current_channel}")
            self.refresh_chat()

    def send_message(self, event=None):
        message = self.message_entry.get("1.0", tk.END).strip()
        name = self.name_entry.get().strip() or "User"

        if not message:
            return "break"

        timestamp = datetime.now().strftime("%H:%M")
        formatted = f"[{timestamp}] {name}: {message}"

        self.channels[self.current_channel].append(formatted)
        self.display_message(formatted)

        if self.connected and self.client_socket:
            try:
                packet = {
                    "name": name,
                    "channel": self.current_channel,
                    "message": message
                }
                self.client_socket.send((json.dumps(packet) + "\n").encode())
            except:
                self.disconnect()

        self.message_entry.delete("1.0", tk.END)
        return "break"

    def new_line(self, event=None):
        self.message_entry.insert(tk.INSERT, "\n")
        return "break"

    def display_message(self, message):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, message + "\n")
        self.chat_area.config(state='disabled')
        self.chat_area.yview(tk.END)

    def refresh_chat(self):
        self.chat_area.config(state='normal')
        self.chat_area.delete("1.0", tk.END)

        for msg in self.channels[self.current_channel]:
            self.chat_area.insert(tk.END, msg + "\n")

        self.chat_area.config(state='disabled')

    def clear_chat(self):
        self.channels[self.current_channel] = []
        self.refresh_chat()
        self.save_channels()

    def on_close(self):
        self.disconnect()
        self.save_channels()
        self.window.destroy()


if __name__ == "__main__":
    ChatUI()
