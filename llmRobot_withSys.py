import os
import ast
import datetime
from dotenv import load_dotenv
from openai import OpenAI
import sounddevice as sd
import numpy as np
import scipy.io.wavfile
import keyboard
import threading
import queue
import time
import re

# ─── Roboter‑Module ────────────────────────────────────────────────────────────
from stopRobot import stop_robot
from gripper_control import gripper_open, gripper_close
from moveFun import send_pose_to_robot
from robot_teaching import teach_positions

# ─── OpenAI ────────────────────────────────────────────────────────────────────
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─── Konstanten / Dateien ─────────────────────────────────────────────────────
AUDIO_FILE            = "befehl.wav"
SAMPLERATE            = 16000
SYSTEM_PROMPT_FILE    = "DemoPrompts/demo.txt"
LOGFILE               = "robot_assist.log"
CODE_SAVE_FOLDER      = "generated_codes"
FULL_PROMPT_FOLDER    = "full_prompts"

# ─── Laufzeit‑Variablen ───────────────────────────────────────────────────────
result_queue       = queue.Queue()
running_code_thread = None
stop_event         = threading.Event()
LAST_SCRIPT        = ""
EXTRA_PROMPT       = ""

# ──────────────────────────────────────────────────────────────────────────────
# Hilfsfunktion: entfernt Funktionsobjekte aus verschachtelten Dicts/Listen
def dict_without_functions(d):
    if isinstance(d, dict):
        return {k: dict_without_functions(v)
                for k, v in d.items()
                if not callable(v) and not str(v).startswith("<function ")}
    if isinstance(d, list):
        return [dict_without_functions(x) for x in d]
    return d

# ─── Ultra‑robuster MEMORY‑Extractor ──────────────────────────────────────────
def extract_memory_from_prompt_file(path: str) -> dict:
    """Lädt den MEMORY‑Block nach dem Label; ersetzt <function …> durch None."""
    if not os.path.exists(path):
        print(f"⚠️ Prompt‑Datei nicht gefunden: {path}")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()

    m = re.search(r"Bekannte Variablen \(MEMORY\):\s*({.*?})\s*(?:\[USER PROMPT\]|\Z)",
                  txt, flags=re.DOTALL)
    if not m:
        print("ℹ️ Kein MEMORY‑Block gefunden.")
        return {}

    mem_txt = m.group(1).strip()
    if not mem_txt or mem_txt == "{}":
        print("ℹ️ MEMORY‑Block leer.")
        return {}

    # 1) Funktions‑Objekte neutralisieren
    mem_txt = re.sub(r"<function[^>]*>", "None", mem_txt)

    try:
        mem = ast.literal_eval(mem_txt)
        if not isinstance(mem, dict):
            print("❗ MEMORY ist kein Dict.")
            return {}
        # 2) optional: 'main'‑Schlüssel entfernen
        mem.pop("main", None)
        print("✅ MEMORY erfolgreich geladen.")
        return mem
    except Exception as err:
        print("❌ Fehler beim Parsen von MEMORY:", err)
        print("Block, der nicht geparst werden konnte:\n", mem_txt)
        return {}

# ─── System‑Prompt & Zusatzinfo laden ────────────────────────────────────────
def extract_systemprompt_and_extra(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()

    m = re.search(
        r"\[SYSTEM PROMPT\]\s*(.*?)(?:\nZusatzinfo:([^\n]*)|Bekannte Variablen \(MEMORY\):"
        r"|Letztes ausgeführtes Skript:|\[USER PROMPT\]|\Z)",
        txt, re.DOTALL)
    if not m:
        print("⚠️ [SYSTEM PROMPT] Abschnitt fehlt.")
        return "", ""
    return m.group(1).strip(), (m.group(2) or "").strip()

try:
    SYSTEM_PROMPT_BASE, EXTRA_PROMPT = extract_systemprompt_and_extra(SYSTEM_PROMPT_FILE)
    MEMORY                           = extract_memory_from_prompt_file(SYSTEM_PROMPT_FILE)
except Exception as e:
    print("❌ Fehler beim Initialisieren:", e)
    SYSTEM_PROMPT_BASE, EXTRA_PROMPT, MEMORY = "", "", {}

# ─── Logging‑ & Speicher‑Funktionen ───────────────────────────────────────────
def write_log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOGFILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def save_code(code, suffix=""):
    os.makedirs(CODE_SAVE_FOLDER, exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn  = f"code_{ts}{suffix}.py"
    fp  = os.path.join(CODE_SAVE_FOLDER, fn)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(code)
    write_log(f"Code gespeichert: {fp}")
    return fp

def save_full_prompt(system_prompt, user_prompt, suffix=""):
    os.makedirs(FULL_PROMPT_FOLDER, exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn  = f"prompt_{ts}{suffix}.txt"
    fp  = os.path.join(FULL_PROMPT_FOLDER, fn)
    with open(fp, "w", encoding="utf-8") as f:
        f.write("[SYSTEM PROMPT]\n")
        f.write(system_prompt.strip() + "\n\n[USER PROMPT]\n")
        f.write(user_prompt.strip())
    write_log(f"Prompt gespeichert: {fp}")
    return fp

# ─── Prompt‑Builder ───────────────────────────────────────────────────────────
def build_system_prompt(memory, last_script="", extra_prompt=""):
    p = SYSTEM_PROMPT_BASE
    if extra_prompt or EXTRA_PROMPT:
        p += f"\n\nZusatzinfo: {(extra_prompt or EXTRA_PROMPT).strip()}"
    if last_script:
        p += f"\n\nLetztes ausgeführtes Skript:\n{last_script.strip()}"
    p += f"\n\nBekannte Variablen (MEMORY):\n{repr(dict_without_functions(memory))}"
    return p

# ─── Audio‑Aufnahme & Transkription ───────────────────────────────────────────
def record_audio_with_keypress(fname=AUDIO_FILE, stop_key="space"):
    print(f"Drücke '{stop_key}' zum Starten …")
    while not keyboard.is_pressed(stop_key):
        time.sleep(0.05)
    print(f"🎙️ Aufnahme läuft … (erneut '{stop_key}' zum Stoppen)")
    recording, stream = [], sd.InputStream(samplerate=SAMPLERATE, channels=1)
    stream.start()
    try:
        while True:
            rec, _ = stream.read(1024)
            recording.append(rec.copy())
            if keyboard.is_pressed(stop_key):
                while keyboard.is_pressed(stop_key):
                    time.sleep(0.05)
                break
    finally:
        stream.stop(); stream.close()
    scipy.io.wavfile.write(fname, SAMPLERATE,
                           np.int16(np.concatenate(recording) * 32767))

def transkribiere_audio(fname=AUDIO_FILE):
    with open(fname, "rb") as f:
        rsp = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
            language="de")
    return rsp.text

# ─── GPT‑Code‑Generator ───────────────────────────────────────────────────────
def generiere_code(prompt_text, memory, last_script="", extra_prompt=""):
    write_log(f"GPT‑Anfrage: {prompt_text}")
    sys_p = build_system_prompt(memory, last_script, extra_prompt)
    save_full_prompt(sys_p, prompt_text)
    rsp   = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "system", "content": sys_p},
                  {"role": "user",   "content": prompt_text}],
        temperature=0)
    return rsp.choices[0].message.content.strip()

# ─── Robot‑Code‑Handling ──────────────────────────────────────────────────────
def stop_robot_and_code():
    global running_code_thread
    stop_event.set(); stop_robot()
    if running_code_thread and running_code_thread.is_alive():
        write_log("⏹️ Beende laufenden Code‑Thread …")
        running_code_thread.join(timeout=2)
        running_code_thread = None

def run_code(code, q, memory):
    lcl = {"MEMORY": memory, "stop_event": stop_event}
    try:
        exec(code, globals(), lcl)
        if callable(lcl.get("main")):
            lcl["main"](stop_event, memory)
        q.put(lcl)
    except Exception as e:
        q.put({"_error": str(e)})

def update_memory_from_locals(lcl, memory):
    memory.update(lcl.get("MEMORY", {}))
    for k, v in lcl.items():
        if k not in ("MEMORY", "stop_event") and not k.startswith("_"):
            memory[k] = v

# ─── Haupt‑Loop ───────────────────────────────────────────────────────────────
def main_loop():
    global running_code_thread, LAST_SCRIPT, EXTRA_PROMPT, MEMORY
    print("s=Sprache  t=Text  p=Zusatzinfo(Sprache)  u=Zusatzinfo(Text)  q=Quit")
    while True:
        # Ergebnis aus laufendem Code holen
        if running_code_thread and not running_code_thread.is_alive():
            try:
                lcl = result_queue.get_nowait()
                if "_error" in lcl:
                    print("❌ Fehler:", lcl["_error"]); write_log(str(lcl["_error"]))
                else:
                    update_memory_from_locals(lcl, MEMORY)
                    write_log(f"MEMORY: {MEMORY}")
            except queue.Empty:
                pass
            running_code_thread = None

        # Tasten‑Events
        if keyboard.is_pressed("s"):
            stop_robot_and_code()
            record_audio_with_keypress()
            txt = transkribiere_audio(); print("📝", txt)
            code = generiere_code(txt, MEMORY, LAST_SCRIPT, EXTRA_PROMPT)
            save_code(code, "_speech"); LAST_SCRIPT = code
            stop_event.clear()
            running_code_thread = threading.Thread(
                target=run_code, args=(code, result_queue, MEMORY.copy()))
            running_code_thread.start(); time.sleep(1)
        elif keyboard.is_pressed("t"):
            stop_robot_and_code()
            txt = input("Befehl: ").strip()
            if txt:
                code = generiere_code(txt, MEMORY, LAST_SCRIPT, EXTRA_PROMPT)
                save_code(code, "_text"); LAST_SCRIPT = code
                stop_event.clear()
                running_code_thread = threading.Thread(
                    target=run_code, args=(code, result_queue, MEMORY.copy()))
                running_code_thread.start()
            time.sleep(1)
        elif keyboard.is_pressed("p"):
            record_audio_with_keypress()
            extra = transkribiere_audio().strip()
            if extra:
                EXTRA_PROMPT += ("\n" if EXTRA_PROMPT else "") + extra
                print("🔖 Zusatzinfo:", EXTRA_PROMPT)
            time.sleep(1)
        elif keyboard.is_pressed("u"):
            extra = input("Zusatzinfo: ").strip()
            if extra:
                EXTRA_PROMPT += ("\n" if EXTRA_PROMPT else "") + extra
                print("🔖 Zusatzinfo:", EXTRA_PROMPT)
            time.sleep(1)
        elif keyboard.is_pressed("q"):
            stop_robot_and_code(); print("🏁 Ende"); break

        time.sleep(0.1)

# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main_loop()
