import socket

robot_ip = "192.168.25.3"  # IP deines Roboters
robot_port = 30002         # URScript-Port

# Zwei Ziel-TCP-Punkte
pose_a = [0.430477, -0.154308, 0.276892,  0.4654, 3.060047, -0.087519]
pose_b = [0.442668,  0.11412,  0.270919, -0.254055, 3.086944, -0.038854]

# Auswahl
wahl = input("Welche Position anfahren? (A/B): ").strip().upper()
pose_target = pose_a if wahl == "A" else pose_b
pose_str = "[" + ", ".join([str(x) for x in pose_target]) + "]"

# Dynamikparameter
acceleration = 1.2
velocity = 1.5
blend_radius = 0.01

# URScript: schnelle direkte Bewegung mit movej
ur_script = f"""
def move_to_pose_direct():
  set_tcp(p[0,0,0,0,0,0])  # TCP neutral

  target_pose = p{pose_str}
  qnear = get_actual_joint_positions()

  if get_inverse_kin_has_solution(target_pose, qnear):
    q = get_inverse_kin(target_pose, qnear)
    movej(q, a={acceleration}, v={velocity}, r={blend_radius})
    textmsg("Zielpose erreicht.")
  else:
    textmsg("IK fehlgeschlagen.")
  end
end
move_to_pose_direct()
"""

# Senden an den Roboter
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((robot_ip, robot_port))
    s.sendall(ur_script.encode())
    print(f"URScript gesendet für Position {wahl}")
    print(ur_script)
