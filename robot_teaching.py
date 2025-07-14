import socket
import time

ROBOT_IP = "192.168.25.3"
PC_IP = "192.168.25.2"
ROBOT_PORT_SEND = 30002
ROBOT_PORT_RECEIVE = 30003
PC_TRIGGER_PORT = 30004

def send_urscript(script):
    print("▶️ Send_urscript")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ROBOT_IP, ROBOT_PORT_SEND))
        s.sendall(script.encode())
        s.recv(1024)

def teach_positions(num_positions):
    poses = []

    # Starte zuerst Trigger- & Pose-Sockets
    print("🔌 Öffne Server-Sockets...")
    trigger_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    pose_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    trigger_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    pose_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    trigger_server.bind((PC_IP, PC_TRIGGER_PORT))
    pose_server.bind((PC_IP, ROBOT_PORT_RECEIVE))
    trigger_server.listen(1)
    pose_server.listen(1)

    print("✅ Server-Sockets offen. Starte Roboter-Skript in 2 Sekunden...")
    time.sleep(2)  # Sicherheitspuffer

    # Roboter-Skript wie oben
    ur_script = f"""
def teach_loop():
  textmsg("Freedrive aktiviert")
  freedrive_mode()
  sleep(0.5)

  socket_open("{PC_IP}", {PC_TRIGGER_PORT}, "trigger_socket")
  textmsg("Trigger-Socket offen")

  socket_open("{PC_IP}", {ROBOT_PORT_RECEIVE}, "pose_socket")
  textmsg("Pose-Socket offen")

  count = 0
  while count < {num_positions}:
    textmsg("Warte auf Signal...")
    signal = socket_read_byte_list(1, "trigger_socket")
    if signal[0] == 1:
      pose = get_actual_tcp_pose()
      textmsg("Pose gesendet")
      socket_send_string(to_str(pose), "pose_socket")
      count = count + 1
    end          # ← schließt das IF
    sync()
  end            # ← schließt die WHILE

  end_freedrive_mode()
  socket_close("pose_socket")
  socket_close("trigger_socket")
  textmsg("Freedrive beendet")
end
teach_loop()
"""


    send_urscript(ur_script)

    # Jetzt auf Verbindungen warten
    trigger_conn, _ = trigger_server.accept()
    pose_conn, _ = pose_server.accept()
    print("🤝 Roboter hat sich verbunden.")

    with trigger_conn, pose_conn:
        for i in range(num_positions):
            input(f"📍 Position {i+1}: Bewege Roboter, dann [Enter] drücken...")
            trigger_conn.send(bytes([1]))  # Triggersignal senden

            print("⏳ Warte auf Pose vom Roboter...")
            data = pose_conn.recv(1024)
            pose_str = data.decode().strip()
            print("📦 Pose empfangen:", pose_str)
            try:
                pose_str_clean = pose_str.strip().removeprefix("p").strip("[]")
                pose = [float(x) for x in pose_str_clean.split(",")]
                poses.append(pose)
            except Exception as e:
                print("⚠️ Fehler beim Parsen:", e)

    trigger_server.close()
    pose_server.close()

    print("✅ Alle Posen empfangen.")
    return poses
