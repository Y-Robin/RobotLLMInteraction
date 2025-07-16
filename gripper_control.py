import socket
import time

def run_urp_program(program_name: str, robot_ip: str = "192.168.25.3", dashboard_port: int = 29999):
    """
    Lädt und startet ein .urp-Programm über die Dashboard-API des UR-Roboters.

    :param program_name: Dateiname des Programms (z. B. 'gripper_open.urp')
    :param robot_ip: IP-Adresse des Roboters
    :param dashboard_port: Standardport der Dashboard-Schnittstelle
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect((robot_ip, dashboard_port))

            # Programm laden
            s.sendall(f'load {program_name}\n'.encode())
            response_load = s.recv(1024).decode().strip()
            print(f"[Dashboard] Load response: {response_load}")

            # Programm starten
            s.sendall(b'play\n')
            response_play = s.recv(1024).decode().strip()
            print(f"[Dashboard] Play response: {response_play}")
            time.sleep(2)

    except Exception as e:
        print(f"[Error] Failed to run program '{program_name}': {e}")

def gripper_open():
    run_urp_program("gripper_open.urp")

def gripper_close():
    run_urp_program("gripper_close.urp")
