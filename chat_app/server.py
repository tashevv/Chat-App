import socket
import threading

HOST = "0.0.0.0"
PORT = 5555

clients = []
usernames = {}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

print(f"[SERVER STARTED] Listening on port {PORT}")


def broadcast(message, sender=None):
    for client in clients:
        if client != sender:
            try:
                client.send(message.encode())
            except:
                remove_client(client)


def remove_client(client):
    if client in clients:
        clients.remove(client)

    username = usernames.get(client, "Unknown")

    print(f"[DISCONNECTED] {username}")

    broadcast(f"[SERVER] {username} left the chat.")

    if client in usernames:
        del usernames[client]

    try:
        client.close()
    except:
        pass


def handle_client(client):
    username = usernames[client]

    broadcast(f"[SERVER] {username} joined the chat.")
    print(f"[JOINED] {username}")

    while True:
        try:
            message = client.recv(1024).decode()

            if not message:
                break

            formatted = f"[{username}] {message}"

            print(formatted)
            broadcast(formatted, client)

        except:
            break

    remove_client(client)


while True:
    client, address = server.accept()
    print(f"[NEW CONNECTION] {address}")

    # Username handshake
    client.send("USERNAME".encode())
    username = client.recv(1024).decode().strip()

    clients.append(client)
    usernames[client] = username

    print(f"[USERNAME SET] {username}")

    thread = threading.Thread(target=handle_client, args=(client,))
    thread.start()

    print(f"[ACTIVE CONNECTIONS] {threading.active_count() - 1}")