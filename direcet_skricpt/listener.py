import socket

HOST = "192.168.25.2"  # IP-Adresse deines PCs (aus Sicht des Roboters)
PORT = 30003           # Port zum Lauschen

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"📡 Server lauscht dauerhaft auf Port {PORT}...")

    while True:
        conn, addr = server_socket.accept()
        with conn:
            print(f"🔗 Verbindung von {addr}")
            data = conn.recv(1024)
            if data:
                pose_str = data.decode()
                print("📦 Empfangene Pose:", pose_str)
            else:
                print("⚠️ Leere Nachricht erhalten")
