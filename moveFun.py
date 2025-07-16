import socket
import time
import random


def send_pose_to_robot(
        pose_target,
        robot_ip="192.168.25.3",
        robot_port=30002,         # Secondary bleibt
        acceleration=1.2,
        velocity=1.5,
        blend_radius=0.01,
        tol_mm=15,
        timeout_s=30,
        pc_ip="192.168.25.2"      # <– IP deines PCs (aus Robotensicht!)
):
    """
    1. Öffnet einen kleinen TCP-Server (zufälliger Port) auf dem PC.
    2. Schickt ein Secondary-Programm (Port 30002).
    3. UR-Script verbindet sich zurück, sendet 'done' / 'failed' / 'timeout'.
    4. Funktion gibt erst danach True / False zurück.
    """
    # ---------- Server-Socket auf PC öffnen ----------
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Zufälliger freier Port (>= 40000, um Konflikte zu vermeiden)
    while True:
        pc_port = random.randint(40000, 50000)
        try:
            srv.bind((pc_ip, pc_port))
            break
        except OSError:
            continue
    srv.listen(1)
    srv.settimeout(timeout_s + 5)

    # ---------- Secondary-UR-Script bauen ----------
    tol = tol_mm / 1000.0
    pose_str = "[" + ", ".join(map(str, pose_target)) + "]"

    ur_script = f"""
def move_to_pose_secondary():
  set_tcp(p[0,0,0,0,0,0])
  target = p{pose_str}
  qnear  = get_actual_joint_positions()

  if get_inverse_kin_has_solution(target, qnear):
    movej(get_inverse_kin(target, qnear),
          a={acceleration}, v={velocity}, r={blend_radius})

    tick = 0
    tol  = {tol}
    while True:
      current = get_actual_tcp_pose()
      if point_dist(current, target) < tol and is_steady():
        socket_open("{pc_ip}", {pc_port}, "pc")
        socket_send_string("done\\n", "pc")
        socket_close("pc")
        break
      end
      if tick*0.1 > {timeout_s}:
        socket_open("{pc_ip}", {pc_port}, "pc")
        socket_send_string("timeout\\n", "pc")
        socket_close("pc")
        break
      end
      sleep(0.1)
      tick = tick + 1
    end
  else:
    textmsg(">> IK solution NOT found! Aborting.")
    socket_open("{pc_ip}", {pc_port}, "pc")
    socket_send_string("failed\\n", "pc")
    socket_close("pc")
  end
end
move_to_pose_secondary()
"""

    # ---------- Secondary-Programm schicken ----------
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as cli:
        cli.connect((robot_ip, robot_port))
        cli.sendall(ur_script.encode())
        # Verbindung wird vom Controller sofort wieder geschlossen

    # ---------- Auf Rückmeldung warten ----------
    try:
        conn, _ = srv.accept()           # UR-Controller ruft zurück
        conn.settimeout(timeout_s + 2)
        msg = conn.recv(64).decode().strip()
        conn.close()
    except socket.timeout:
        srv.close()
        #print("PC-Seite: kein Feedback – Timeout.")
        return False
    finally:
        srv.close()

    if msg == "done":
        #print("Zielposition erreicht ✓")
        return True
    elif msg == "failed":
        #print("Inverse Kinematik ohne Lösung ✗")
        return False
    else:  # "timeout" oder unbekannt
        #print(f"Roboter meldet: {msg}")
        return False
