import socket

robot_ip = "192.168.25.3"  # IP deines Roboters
robot_port = 30002         # URScript-Port

# 🔹 Ziel-TCP-Pose (zuvor mit get_actual_tcp_pose() erfasst)
pose_target = [0.430477, -0.154308, 0.276892, 0.4654, 3.060047, -0.087519]
pose_target = [0.442668, 0.11412, 0.270919, -0.254055, 3.086944, -0.038854]
pose_str = "[" + ", ".join([str(x) for x in pose_target]) + "]"

# 🔹 Sichere Zwischenposition (angepasst an UR3: Arm nach oben gefaltet)
safe_q = [0.0, -1.57, 1.57, 0.0, 1.57, 0.0]

# Dynamikparameter
acceleration = 1.2
velocity = 1.0
blend_radius = 0.0

# 🔹 URScript: vollständig auf Roboter ausführbar
ur_script = f"""
def safe_move_to_pose():
  set_tcp(p[0,0,0,0,0,0])  # TCP auf neutral setzen, damit Pose stimmt

  # 1. In sichere Zwischenposition fahren
  movej({safe_q}, a={acceleration}, v={velocity})
  sync()

  # 2. Zielpose setzen und Gelenkwinkel berechnen
  target_pose = p{pose_str}
  qnear = get_actual_joint_positions()
  if get_inverse_kin_has_solution(target_pose, qnear):
    q = get_inverse_kin(target_pose, qnear)
    movej(q, a={acceleration}, v={velocity}, r={blend_radius})
    textmsg("Zielpose erreicht.")
  else:
    textmsg("Fehler: Keine IK-Lösung für Zielpose.")
  end
end
safe_move_to_pose()
"""

# 🔹 Senden des Skripts an den Roboter
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((robot_ip, robot_port))
    s.sendall(ur_script.encode())
    print("URScript gesendet:")
    print(ur_script)
