import socket
import threading
import json
import ssl

HOST = "0.0.0.0"
PORT = 5555

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

server = context.wrap_socket(server, server_side=True)

print(f"[SERVER STARTED] Listening on port {PORT}")

clients = []  # (client, channel, name)


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

            print(f"[DISCONNECTED] {name}")

            # Notify all clients
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

    print("[NEW CLIENT CONNECTED]")

    # Notify all clients of join
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

                name = packet.get("name", "User")
                channel = packet.get("channel", "General")
                text = packet.get("message", "")

                # update client info
                for i, (c, ch, n) in enumerate(clients):
                    if c == client:
                        clients[i] = (client, channel, name)

                final_packet = {
                    "type": "message",
                    "name": name,
                    "channel": channel,
                    "message": text
                }

                print(f"[{channel}] {name}: {text}")

                broadcast(final_packet, sender=client)

        except:
            break

    remove_client(client)
    client.close()


while True:
    client, addr = server.accept()
    print(f"[CONNECTED] {addr}")

    thread = threading.Thread(target=handle_client, args=(client,))
    thread.start()