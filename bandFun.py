import socket
import time

ROBOT_IP = "192.168.25.3"
PC_IP = "192.168.25.2"

ROBOT_PORT_SEND = 30002       # Port zum UR-Controller (Programm-Port)
PC_CONVEYOR_PORT = 30005      # Port auf dem PC für Rückmeldung vom Roboter


def send_urscript(script: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ROBOT_IP, ROBOT_PORT_SEND))
        s.sendall(script.encode())
        # Warten, bis der Roboter den Empfang quittiert (wie im teach_positions-Skript)
        s.recv(1024)


def send_conveyor_to_robot(band, direction, timeout_s=5):
    """
    band: 1 oder 2
    direction: -1 = rückwärts, 0 = stopp, 1 = vorwärts
    Rückgabe: True, wenn "done" vom Roboter kam, sonst False
    """

    # ---------- PC-Server für Rückmeldung ----------
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PC_IP, PC_CONVEYOR_PORT))
    server.listen(1)
    server.settimeout(timeout_s)

    # leichter Puffer, damit der Server sicher bereit ist
    time.sleep(0.2)

    # ---------- IO-Mapping ----------
    if band == 1:
        std_do = 6
        config_do = 0
        analog_out = 0
    elif band == 2:
        std_do = 7
        config_do = 4
        analog_out = 1
    else:
        server.close()
        raise ValueError("Ungültiges Band (1 oder 2)!")

    # ---------- Aktion je nach Richtung ----------
    if direction == 1:
        # Vorwärts
        action_block = f"""  sleep(0.05)
  set_standard_analog_out({analog_out}, 0.0)
  sleep(0.05)
  set_standard_digital_out({std_do}, False)
  sleep(0.05)
  set_standard_digital_out({std_do}, True)
  sleep(0.05)
  set_configurable_digital_out({config_do}, True)
  sleep(0.05)
  set_standard_analog_out({analog_out}, 0.3)
  sleep(0.05)
  textmsg("Band {band}: VORWAERTS")"""
    elif direction == -1:
        # Rückwärts
        action_block = f"""  sleep(0.05)
  set_standard_analog_out({analog_out}, 0.0)
  sleep(0.05)
  set_standard_digital_out({std_do}, False)
  sleep(0.05)
  set_standard_digital_out({std_do}, True)
  sleep(0.05)
  set_configurable_digital_out({config_do}, False)
  sleep(0.05)
  set_standard_analog_out({analog_out}, 0.3)
  sleep(0.05)
  textmsg("Band {band}: RUECKWAERTS")"""
    elif direction == 0:
        # Stopp
        action_block = f"""  sleep(0.05)
  set_standard_digital_out({std_do}, False)
  sleep(0.05)
  set_standard_analog_out({analog_out}, 0.0)
  sleep(0.05)
  textmsg("Band {band}: STOPP")"""
    else:
        server.close()
        raise ValueError("direction muss -1, 0 oder 1 sein!")

    # ---------- Vollständiges URScript ----------
    ur_script = f"""
def conveyor_cmd():
{action_block}
  sleep(0.1)
  socket_open("{PC_IP}", {PC_CONVEYOR_PORT}, "conv_socket")
  sleep(0.05)
  socket_send_string("done", "conv_socket")
  sleep(0.05)
  socket_close("conv_socket")
end
conveyor_cmd()
"""

    try:
        # ---------- URScript an Roboter schicken ----------
        send_urscript(ur_script)

        # ---------- Auf Rückmeldung warten ----------
        conn, _ = server.accept()
        with conn:
            msg = conn.recv(1024).decode().strip()

        server.close()
        return msg == "done"

    except (socket.timeout, OSError):
        server.close()
        return False
