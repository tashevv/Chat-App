import socket
import threading

HOST = "127.0.0.1"
PORT = 5555

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))


# --- username handshake ---
msg = client.recv(1024).decode()
if msg == "USERNAME":
    username = input("Choose a username: ")
    client.send(username.encode())


def receive():
    while True:
        try:
            msg = client.recv(1024).decode()
            if not msg:
                break

            print(msg)

        except:
            print("[DISCONNECTED]")
            client.close()
            break


threading.Thread(target=receive, daemon=True).start()


# --- send loop (no prompt) ---
while True:
    try:
        msg = input()

        if msg.lower() == "/quit":
            break

        client.send(msg.encode())

    except:
        break

client.close()
print("[CONNECTION CLOSED]")