import socket
import time

ROBOT_IP = "192.168.25.3"
PC_IP = "192.168.25.2"

ROBOT_PORT_SEND = 30002       # Port zum UR-Controller (Programm-Port)
PC_INPUT_PORT = 30006         # Port auf dem PC für Rückmeldung vom Roboter


def send_urscript(script: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((ROBOT_IP, ROBOT_PORT_SEND))
        s.sendall(script.encode())
        s.recv(1024)


def read_licht_input(input_number=5, timeout_s=5):
    """
    Liest get_configurable_digital_input(input_number) auf dem Roboter.
    Rückgabe: True, False oder None bei Fehler.
    """

    # ---------- PC-Server für Rückmeldung ----------
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PC_IP, PC_INPUT_PORT))
    server.listen(1)
    server.settimeout(timeout_s)

    time.sleep(0.2)

    # ---------- Vollständiges URScript ----------
    ur_script = f"""
def read_input_cmd():
  sleep(0.05)
  val = get_configurable_digital_in({input_number})
  sleep(0.05)
  socket_open("{PC_IP}", {PC_INPUT_PORT}, "input_socket")
  sleep(0.05)
  if val:
    socket_send_string("1", "input_socket")
  else:
    socket_send_string("0", "input_socket")
  end
  sleep(0.05)
  socket_close("input_socket")
end
read_input_cmd()
"""

    try:
        # ---------- URScript an Roboter schicken ----------
        send_urscript(ur_script)

        # ---------- Antwort vom Roboter ----------
        conn, _ = server.accept()
        with conn:
            msg = conn.recv(1024).decode().strip()

        server.close()

        if msg == "1":
            return True
        elif msg == "0":
            return False
        else:
            return None

    except (socket.timeout, OSError):
        server.close()
        return None
