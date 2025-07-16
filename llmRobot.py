import os
from dotenv import load_dotenv
from openai import OpenAI
import sounddevice as sd
import numpy as np
import scipy.io.wavfile
import keyboard
import threading
import queue
import time

# Roboter-Module importieren!
from stopRobot import stop_robot
from gripper_control import gripper_open, gripper_close
from moveFun import send_pose_to_robot
from robot_teaching import teach_positions

# OpenAI API-Key laden
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AUDIO_FILE = "befehl.wav"
SAMPLERATE = 16000

MEMORY = {}
result_queue = queue.Queue()
running_code_thread = None
stop_event = threading.Event()
LAST_SCRIPT = ""  # Hier speichern wir das letzte ausgeführte Skript
EXTRA_PROMPT = ""  # Hier stehen die Zusatzinfos aus 'p'

def build_system_prompt(memory, last_script="", extra_prompt=""):
    return (
        "Du bist ein Assistenzsystem, das Sprachbefehle in ausführbaren Python-Code für die Steuerung eines Roboters umwandelt.\n\n"
        "Regeln:\n"
        "- Only the code without anything else no commends no ``` python no nothing. Only imports and code!!\n"
        "- Antworte ausschließlich mit ausführbarem Python-Code, ohne Kommentare oder Erklärungen. und ohne ```python. Nur der Code!!!s\n"
        "- Benutze nur die bereitgestellten Funktionen: send_pose_to_robot(), gripper_open(), gripper_close(), teach_positions(), stop_robot(), usw.\n"
        "- Wenn du im Code eine neue Positionen erzeugst, schreibe diese am Ende explizit in das Python-Dictionary MEMORY, z.B. MEMORY['meine_variable'] = meine_variable.\n"
        "- Verwende Variablen aus MEMORY für Folgeanweisungen, z.B. fahre zu MEMORY['positionen'][0]. Position 1/A verweist auf MEMORY['positionen'][0], Position 2/B verweist auf MEMORY['positionen'][1]\n"
        "- Prüfe in jeder Schleife oder langen Aktion regelmäßig, ob stop_event.is_set() == True ist. Falls ja, stoppe sofort mit stop_robot() und return.\n"
        "- Wenn eine Variable wie 'positionen' schon existiert, nutze diese weiter.\n"
        "- Liefere immer def main(stop_event, MEMORY): ... und KEINEN Code außerhalb dieser Funktion\n"
        "\nBeispiel (One-Shot mit korrektem Abbruch):\n"
        "def main(stop_event, MEMORY):\n"
        "   from gripper_control import gripper_open, gripper_close\n"
        "   from robot_teaching import teach_positions\n"
        "   from moveFun import send_pose_to_robot\n"
        "   import time\n"
        "   from stopRobot import stop_robot\n"
        "   positionen = teach_positions(num_positions=2)\n"
        "   for pose in positionen:\n"
        "       if stop_event.is_set():\n"
        "           stop_robot()\n"
        "           return\n"
        "       send_pose_to_robot(pose, acceleration=0.8, velocity=1.2)\n"
        "   if stop_event.is_set():\n"
        "       stop_robot()\n"
        "       return\n"
        "   gripper_open()\n"
        "   if stop_event.is_set():\n"
        "       stop_robot()\n"
        "       return\n"
        "   gripper_close()\n"
        "   stop_robot()\n"
        "   MEMORY['positionen'] = positionen\n\n"
        "Bspeiel Positionen (1 und 2):\n"
        "positionen = [\n"
        "   [0.1, -0.5, 0.35, 3.14, -0.1, 0.02],\n"
        "   [0.12, -0.51, 0.34, 3.13, -0.11, 0.021]\n"
        "]"
        + (f"\n\nZusatzinfo: {extra_prompt.strip()}" if extra_prompt else "")
        + (f"\n\nLetztes ausgeführtes Skript:\n{last_script.strip()}" if last_script else "")
        + f"\n\nBekannte Variablen (MEMORY):\n{repr(memory)}"
    )

def record_audio_with_keypress(filename=AUDIO_FILE, stop_key="space"):
    print(f"Drücke '{stop_key}' zum Starten der Aufnahme...")
    while True:
        if keyboard.is_pressed(stop_key):
            print(f"🎙️ Aufnahme läuft... (erneut '{stop_key}' drücken zum Stoppen)")
            while keyboard.is_pressed(stop_key):
                time.sleep(0.05)
            break
        time.sleep(0.05)

    recording = []
    stream = sd.InputStream(samplerate=SAMPLERATE, channels=1)
    stream.start()
    try:
        while True:
            data, _ = stream.read(1024)
            recording.append(data.copy())
            if keyboard.is_pressed(stop_key):
                print("🛑 Aufnahme gestoppt.")
                while keyboard.is_pressed(stop_key):
                    time.sleep(0.05)
                break
    finally:
        stream.stop()
        stream.close()
    audio_np = np.concatenate(recording, axis=0)
    scipy.io.wavfile.write(filename, SAMPLERATE, np.int16(audio_np * 32767))
    print("✅ Aufnahme gespeichert.")

def transkribiere_audio(filename=AUDIO_FILE):
    print("📝 Transkribiere mit GPT-4o Transcribe...")
    with open(filename, "rb") as f:
        response = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",  # ← neues Modell!
            file=f,
            language="de"  # Optional: Deutsch explizit setzen
        )
    return response.text

def generiere_code(prompt_text, memory, last_script="", extra_prompt=""):
    print(f"🧠 Sende an GPT: {prompt_text}")
    system_prompt = build_system_prompt(memory, last_script, extra_prompt)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text},
        ],
        temperature=0,
    )
    code = response.choices[0].message.content
    return code.strip()

def stop_robot_and_code():
    global running_code_thread
    stop_event.set()
    stop_robot()
    if running_code_thread and running_code_thread.is_alive():
        print("⏹️ Beende laufenden Code-Thread...")
        running_code_thread.join(timeout=2)
        running_code_thread = None

def run_code(code, result_queue, memory):
    local_vars = {"MEMORY": memory, "stop_event": stop_event}
    try:
        exec(code, globals(), local_vars)  # main(...) wird jetzt definiert
        # WICHTIG: main() explizit aufrufen!
        if "main" in local_vars and callable(local_vars["main"]):
            local_vars["main"](stop_event, memory)
        result_queue.put(local_vars)
    except Exception as e:
        result_queue.put({'_error': str(e)})

def update_memory_from_locals(local_vars, memory):
    # Erst die (vielleicht neuen oder veränderten) Speicherinhalte in MEMORY übernehmen
    if "MEMORY" in local_vars:
        memory.update(local_vars["MEMORY"])
    # Zusätzlich neue einzelne Variablen in den Speicher übernehmen
    for k, v in local_vars.items():
        if not k.startswith("_") and k not in ("MEMORY", "stop_event"):
            memory[k] = v

def main_loop():
    global running_code_thread, LAST_SCRIPT, EXTRA_PROMPT
    print("Drücke 's' für Spracheingabe (Start/Stop mit SPACE), 'p' für Zusatzinfos, 'q' zum Beenden.")
    while True:
        # Wenn Thread fertig ist, speichere Rückgabe in MEMORY!
        if running_code_thread and not running_code_thread.is_alive():
            try:
                local_vars = result_queue.get_nowait()
                if "_error" in local_vars:
                    print("❌ Fehler beim Ausführen:", local_vars["_error"])
                else:
                    update_memory_from_locals(local_vars, MEMORY)
                    print("✅ MEMORY wurde aktualisiert:", MEMORY)
            except queue.Empty:
                pass
            running_code_thread = None  # Thread ist fertig

        if keyboard.is_pressed("s"):
            print("\n[🎤 Sprachaufnahme]")
            stop_robot_and_code()  # Aktive Bewegung und Thread beenden!
            record_audio_with_keypress()
            text = transkribiere_audio()
            print(f"📜 Transkribierter Text: {text}")
            code = generiere_code(text, MEMORY, LAST_SCRIPT, EXTRA_PROMPT)
            print("▶️ Führe Code aus:")
            print(code)
            LAST_SCRIPT = code  # Merke das letzte Skript für Prompt!
            stop_event.clear()
            running_code_thread = threading.Thread(target=run_code, args=(code, result_queue, MEMORY.copy()))
            running_code_thread.start()
            # Warte, damit Taste nicht mehrfach erkannt wird
            time.sleep(1.2)
            print("Drücke 's' für Spracheingabe (Start/Stop mit SPACE), 'p' für Zusatzinfos, 'q' zum Beenden.")

        elif keyboard.is_pressed("p"):
            print("\n[🎤 Zusatzinfo aufnehmen] (Start/Stop mit SPACE)")
            record_audio_with_keypress()
            extra_text = transkribiere_audio()
            if extra_text.strip():
                # Füge den neuen Text an, mit Zeilenumbruch falls nötig
                if EXTRA_PROMPT:
                    EXTRA_PROMPT += "\n"
                EXTRA_PROMPT += extra_text.strip()
                print(f"🔖 Zusatzinfo aktualisiert:\n{EXTRA_PROMPT}")
            else:
                print("❗ Keine Zusatzinfo erkannt.")
            time.sleep(1.2)
            print("Drücke 's' für Spracheingabe (Start/Stop mit SPACE), 'p' für Zusatzinfos, 'q' zum Beenden.")

        elif keyboard.is_pressed("q"):
            print("🏁 Beende...")
            stop_robot_and_code()
            break

        time.sleep(0.1)

if __name__ == "__main__":
    main_loop()
