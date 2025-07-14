import socket
import keyboard
import time

robot_ip = "192.168.25.3"
robot_port_send = 30002
robot_port_receive = 30003  # Port, an dem der Roboter TCP-Pose zurücksendet
local_ip = "192.168.25.2"   # IP deines PCs (aus Sicht des Roboters)

poses = []

def start_freedrive():
    ur_script = """
def start_freedrive():
  textmsg("Freedrive an")
  freedrive_mode()
end
start_freedrive()
"""
    send_urscript(ur_script)

def stop_freedrive():
    ur_script = """
def stop_freedrive():
  end_freedrive_mode()
  textmsg("Freedrive aus")
end
stop_freedrive()
"""
    send_urscript(ur_script)

def get_current_pose():
    ur_script = f"""
def send_pose():
  end_freedrive_mode()
  socket_open("{local_ip}", {robot_port_receive})
  pose = get_actual_tcp_pose()
  socket_send_string(to_str(pose))
  socket_close()
end
send_pose()
"""
    send_urscript(ur_script)

def send_urscript(script):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((robot_ip, robot_port_send))
        s.sendall(script.encode())

def wait_for_pose():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((local_ip, robot_port_receive))
        server.listen(1)
        conn, _ = server.accept()
        with conn:
            data = conn.recv(1024)
            pose_str = data.decode()
            print(f"Empfangene Pose: {pose_str}")
            return pose_str

def main():
    print("Starte Freedrive-Teachen für 3 Positionen (XY-Ebene)")
    for i in range(3):
        print(f"\n➡️  Position {i+1}: Führe den Roboter in XY. Drücke [Leertaste], wenn du fertig bist.")
        start_freedrive()

        # Warten auf Leertaste
        while True:
            if keyboard.is_pressed('space'):
                print("🔹 Leertaste erkannt – Pose wird gespeichert...")
                break
            time.sleep(0.05)

        get_current_pose()
        pose = wait_for_pose()
        poses.append(pose)

        time.sleep(0.5)  # etwas Pufferzeit
        start_freedrive()  # wieder aktivieren für nächste Runde

    stop_freedrive()
    print("\n✅ Alle 3 Positionen gespeichert:")
    for i, p in enumerate(poses):
        print(f"Position {i+1}: {p}")

if __name__ == "__main__":
    main()
