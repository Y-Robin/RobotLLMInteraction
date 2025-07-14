import socket

HOST = "192.168.25.2"  # IP deines PCs
PORT = 30003            # Port zum Lauschen

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"Server lauscht auf Port {PORT}...")
    
    conn, addr = server_socket.accept()
    with conn:
        print("Verbindung von", addr)
        data = conn.recv(1024)
        print("Empfangene Pose:", data.decode())