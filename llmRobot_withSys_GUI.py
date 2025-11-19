import os
import ast
import datetime
from dotenv import load_dotenv
from openai import OpenAI
import sounddevice as sd
import numpy as np
import scipy.io.wavfile
import threading
import queue
import time
import re

# ─── GUI ──────────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import scrolledtext

# ─── Roboter-Module ────────────────────────────────────────────────────────────
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
SYSTEM_PROMPT_FILE    = "DemoPrompts/JaNein.txt"
LOGFILE               = "robot_assist.log"
CODE_SAVE_FOLDER      = "generated_codes"
FULL_PROMPT_FOLDER    = "full_prompts"
SAVED_SYSTEM_PROMPT   = "saved_system_prompt_runtime.txt"

# ─── Laufzeit-Variablen ───────────────────────────────────────────────────────
result_queue        = queue.Queue()
running_code_thread = None
stop_event          = threading.Event()
LAST_SCRIPT         = ""
EXTRA_PROMPT        = ""
MEMORY              = {}
USER_PROMPT_HISTORY = []   # gesamte Historie der User-Prompts

# GUI-State
root                   = None
status_label           = None
prompt_text_widget     = None
code_text_widget       = None
system_prompt_widget   = None
input_entry            = None

spinner_running        = False
spinner_index          = 0
spinner_frames         = ["⏳", "◴", "◷", "◶", "◵"]

SYSTEM_PROMPT_BASE     = ""   # ursprünglich aus der Datei

# ──────────────────────────────────────────────────────────────────────────────
def dict_without_functions(d):
    if isinstance(d, dict):
        return {k: dict_without_functions(v)
                for k, v in d.items()
                if not callable(v) and not str(v).startswith("<function ")}
    if isinstance(d, list):
        return [dict_without_functions(x) for x in d]
    return d

# ─── MEMORY-Extractor ─────────────────────────────────────────────────────────
def extract_memory_from_prompt_file(path: str) -> dict:
    if not os.path.exists(path):
        print(f"⚠️ Prompt-Datei nicht gefunden: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"Bekannte Variablen \(MEMORY\):\s*({.*?})\s*(?:\[USER PROMPT\]|\Z)",
                  txt, flags=re.DOTALL)
    if not m:
        print("ℹ️ Kein MEMORY-Block gefunden.")
        return {}
    mem_txt = m.group(1).strip()
    if not mem_txt or mem_txt == "{}":
        print("ℹ️ MEMORY-Block leer.")
        return {}
    mem_txt = re.sub(r"<function[^>]*>", "None", mem_txt)
    try:
        mem = ast.literal_eval(mem_txt)
        if not isinstance(mem, dict):
            print("❗ MEMORY ist kein Dict.")
            return {}
        mem.pop("main", None)
        print("✅ MEMORY erfolgreich geladen.")
        return mem
    except Exception as err:
        print("❌ Fehler beim Parsen von MEMORY:", err)
        print("Block, der nicht geparst werden konnte:\n", mem_txt)
        return {}

# ─── SYSTEM PROMPT & EXTRA ───────────────────────────────────────────────────
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

# ─── Logging & Dateien ────────────────────────────────────────────────────────
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

def save_system_prompt_to_file(text):
    with open(SAVED_SYSTEM_PROMPT, "w", encoding="utf-8") as f:
        f.write(text)
    write_log(f"System Prompt in {SAVED_SYSTEM_PROMPT} gespeichert.")

# ─── System-Prompt-Section-Helfer ────────────────────────────────────────────
def get_system_prompt_text():
    if system_prompt_widget is None:
        return ""
    return system_prompt_widget.get("1.0", "end-1c")

def set_system_prompt_text(txt: str):
    if system_prompt_widget is None:
        return
    system_prompt_widget.delete("1.0", tk.END)
    system_prompt_widget.insert(tk.END, txt)

def update_prompt_history_section():
    """Fügt / aktualisiert den 'Prompt-Historie:'-Block mit allen User-Prompts."""
    if system_prompt_widget is None or not USER_PROMPT_HISTORY:
        return

    txt = get_system_prompt_text()
    lines = [f"{i}. {p}" for i, p in enumerate(USER_PROMPT_HISTORY, 1)]
    hist_str = "\n".join(lines)
    new_block = f"\n\nPrompt-Historie:\n{hist_str}"

    pattern = r"(\n\nPrompt-Historie:\n)(.*?)(?=\n\nZusatzinfo:|\n\nLetztes ausgeführtes Skript:|\n\nBekannte Variablen \(MEMORY\):|\Z)"
    m = re.search(pattern, txt, flags=re.DOTALL)
    if m:
        new_txt = txt[:m.start()] + new_block + txt[m.end():]
    else:
        # vor Zusatzinfo / Letztes Skript / MEMORY einfügen, falls vorhanden
        insert_pos = len(txt)
        for marker in ["\n\nZusatzinfo:", "\n\nLetztes ausgeführtes Skript:", "\n\nBekannte Variablen (MEMORY):"]:
            pos = txt.find(marker)
            if pos != -1 and pos < insert_pos:
                insert_pos = pos
        if insert_pos == len(txt):
            new_txt = txt + new_block
        else:
            new_txt = txt[:insert_pos] + new_block + txt[insert_pos:]

    set_system_prompt_text(new_txt)

def update_zusatzinfo_section(extra_text: str):
    """Aktualisiert/fügt den 'Zusatzinfo:'-Block im Systemprompt-Text ein (immer VOR MEMORY)."""
    if system_prompt_widget is None:
        return
    txt = get_system_prompt_text()
    new_block = f"\n\nZusatzinfo: {extra_text.strip()}"

    pattern = r"(\n\nZusatzinfo:)(.*?)(?=\n\nLetztes ausgeführtes Skript:|\n\nBekannte Variablen \(MEMORY\):|\n\nPrompt-Historie:|\Z)"
    m = re.search(pattern, txt, flags=re.DOTALL)
    if m:
        new_txt = txt[:m.start()] + new_block + txt[m.end():]
    else:
        # Falls noch kein Zusatzinfo-Block: vor MEMORY einsortieren, sonst ans Ende
        mem_pos = txt.find("\n\nBekannte Variablen (MEMORY):")
        if mem_pos == -1:
            new_txt = txt + new_block
        else:
            new_txt = txt[:mem_pos] + new_block + txt[mem_pos:]
    set_system_prompt_text(new_txt)

def update_last_script_section(code: str):
    """Aktualisiert/fügt den 'Letztes ausgeführtes Skript:'-Block ein (immer VOR MEMORY)."""
    if system_prompt_widget is None:
        return
    txt = get_system_prompt_text()
    code_str = code.strip()
    new_block = f"\n\nLetztes ausgeführtes Skript:\n{code_str}"

    pattern = r"(\n\nLetztes ausgeführtes Skript:\n)(.*?)(?=\n\nBekannte Variablen \(MEMORY\):|\n\nZusatzinfo:|\n\nPrompt-Historie:|\Z)"
    m = re.search(pattern, txt, flags=re.DOTALL)
    if m:
        new_txt = txt[:m.start()] + new_block + txt[m.end():]
    else:
        # Falls noch kein Block: vor MEMORY einsortieren, sonst ans Ende
        mem_pos = txt.find("\n\nBekannte Variablen (MEMORY):")
        if mem_pos == -1:
            new_txt = txt + new_block
        else:
            new_txt = txt[:mem_pos] + new_block + txt[mem_pos:]
    set_system_prompt_text(new_txt)

def update_memory_section():
    """Aktualisiert/fügt den 'Bekannte Variablen (MEMORY):'-Block ein (immer als letzter Block)."""
    if system_prompt_widget is None:
        return
    txt = get_system_prompt_text()
    mem_repr = repr(dict_without_functions(MEMORY))
    new_block = f"\n\nBekannte Variablen (MEMORY):\n{mem_repr}"

    # Nur den Inhalt des MEMORY-Blocks ersetzen, Rest davor/danach bleibt
    pattern = r"(\n\nBekannte Variablen \(MEMORY\):\n)(.*?)(\Z)"
    m = re.search(pattern, txt, flags=re.DOTALL)
    if m:
        new_txt = txt[:m.start(1)] + new_block + txt[m.end(3):]
    else:
        new_txt = txt + new_block
    set_system_prompt_text(new_txt)

# ─── Audio & Transkription ────────────────────────────────────────────────────
def record_audio_fixed_duration(fname=AUDIO_FILE, duration=5.0):
    write_log(f"Starte Audioaufnahme ({duration} s)")
    recording = sd.rec(int(duration * SAMPLERATE), samplerate=SAMPLERATE, channels=1)
    sd.wait()
    scipy.io.wavfile.write(fname, SAMPLERATE,
                           np.int16(recording.flatten() * 32767))

def transkribiere_audio(fname=AUDIO_FILE):
    with open(fname, "rb") as f:
        rsp = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
            language="de")
    return rsp.text

# ─── GPT-Code-Generator ───────────────────────────────────────────────────────
def generiere_code(system_prompt: str, prompt_text: str):
    write_log(f"GPT-Anfrage: {prompt_text}")
    save_full_prompt(system_prompt, prompt_text, suffix="")
    rsp   = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt_text}
        ],
        temperature=0
    )
    return rsp.choices[0].message.content.strip()

# ─── Guarded Robot-Calls ─────────────────────────────────────────────────────
def guarded(func, name=None):
    fname = name or func.__name__
    def wrapper(*args, **kwargs):
        if stop_event.is_set():
            msg = f"Ausführung durch Benutzer gestoppt (bei Aufruf von {fname})."
            write_log(msg)
            raise RuntimeError(msg)
        return func(*args, **kwargs)
    return wrapper

# ─── Robot-Code-Handling ──────────────────────────────────────────────────────
def stop_robot_and_code():
    global running_code_thread
    stop_event.set()
    try:
        stop_robot()
    except Exception as e:
        write_log(f"Fehler beim Stoppen des Roboters: {e}")

    if running_code_thread and running_code_thread.is_alive():
        write_log("⏹️ Stop angefordert, warte auf Code-Thread …")
        running_code_thread.join(timeout=2)

        if running_code_thread.is_alive():
            write_log("⚠️ Code-Thread läuft nach Stop noch weiter (kann nicht hart beendet werden).")
        else:
            write_log("✅ Code-Thread beendet.")
            running_code_thread = None

def run_code(code, q, memory):
    import time as _time  # lokaler Alias

    # Kooperatives Sleep: bricht ab, wenn stop_event gesetzt ist
    def safe_sleep(seconds):
        step = 0.1
        elapsed = 0.0
        while elapsed < seconds:
            if stop_event.is_set():
                write_log("safe_sleep: stop_event gesetzt, breche Sleep ab.")
                break
            to_sleep = min(step, seconds - elapsed)
            _time.sleep(to_sleep)
            elapsed += to_sleep

    # Lokale Umgebung für exec
    lcl = {
        "MEMORY": memory,
        "stop_event": stop_event,
        "stop_robot": guarded(stop_robot, "stop_robot"),
        "gripper_open": guarded(gripper_open, "gripper_open"),
        "gripper_close": guarded(gripper_close, "gripper_close"),
        "send_pose_to_robot": guarded(send_pose_to_robot, "send_pose_to_robot"),
        "teach_positions": guarded(teach_positions, "teach_positions"),
        "time": __import__("time"),
    }

    # time.sleep im lokalen time-Modul patchen
    lcl["time"].sleep = safe_sleep

    try:
        exec(code, globals(), lcl)
        if callable(lcl.get("main")):
            lcl["main"](stop_event, memory)
        q.put({"type": "code_result", "locals": lcl})
    except Exception as e:
        q.put({"type": "error", "message": str(e)})

def update_memory_from_locals(lcl, memory):
    memory.update(lcl.get("MEMORY", {}))
    for k, v in lcl.items():
        if k not in ("MEMORY", "stop_event") and not k.startswith("_"):
            memory[k] = v

# ─── GUI-Helfer ───────────────────────────────────────────────────────────────
def set_status(text, busy=False):
    global spinner_running
    if status_label is not None:
        status_label.config(text=text)
    spinner_running = busy

def animate_spinner():
    global spinner_index
    if status_label is not None:
        if spinner_running:
            spinner_index = (spinner_index + 1) % len(spinner_frames)
            prefix = spinner_frames[spinner_index]
            current = status_label.cget("text")
            parts = current.split(" ", 1)
            rest = parts[1] if len(parts) > 1 else ""
            status_label.config(text=f"{prefix} {rest}")
    if root is not None:
        root.after(150, animate_spinner)

def update_text_widget(widget, text, readonly=False):
    if readonly:
        widget.config(state="normal")
    widget.delete("1.0", tk.END)
    widget.insert(tk.END, text)
    if readonly:
        widget.config(state="disabled")

# ─── System Prompt speichern ──────────────────────────────────────────────────
def on_button_save_system_prompt():
    txt = get_system_prompt_text()
    save_system_prompt_to_file(txt)
    set_status("💾 System Prompt gespeichert (wird ab jetzt so verwendet).", busy=False)

# ─── Worker-Funktionen für Buttons ───────────────────────────────────────────
def start_gpt_flow(prompt_text, suffix_for_save="_text"):
    global LAST_SCRIPT, USER_PROMPT_HISTORY, running_code_thread
    if not prompt_text:
        return

    # Wenn noch ein Code-Thread läuft: keine neue Ausführung starten
    if running_code_thread is not None and running_code_thread.is_alive():
        set_status("⚠️ Es läuft noch ein Code-Thread – zuerst Stop drücken.", busy=False)
        return

    # Historie erweitern und im System-Prompt updaten
    USER_PROMPT_HISTORY.append(prompt_text)
    update_prompt_history_section()

    # Snapshot des System-Prompts NACH dem Update
    system_prompt = get_system_prompt_text()

    set_status("⏳ Sende an GPT und führe Code aus …", busy=True)

    def worker():
        global LAST_SCRIPT
        try:
            code = generiere_code(system_prompt, prompt_text)
            result_queue.put({
                "type": "code_generated",
                "prompt": prompt_text,
                "code": code,
                "suffix": suffix_for_save
            })
        except Exception as e:
            result_queue.put({"type": "error", "message": str(e)})

    threading.Thread(target=worker, daemon=True).start()

def on_button_text():
    txt = input_entry.get().strip()
    if not txt and prompt_text_widget is not None:
        txt = prompt_text_widget.get("1.0", "end-1c").strip()
    if not txt:
        return
    start_gpt_flow(txt, "_text")

def on_button_speech():
    set_status("🎙️ Aufnahme (5 s)…", busy=True)
    def worker():
        try:
            record_audio_fixed_duration()
            txt = transkribiere_audio().strip()
            if not txt or txt == "[]":
                result_queue.put({"type": "info", "message": "Keine Sprache erkannt."})
                return
            result_queue.put({"type": "speech_transcript", "text": txt})
            start_gpt_flow(txt, "_speech")
        except Exception as e:
            result_queue.put({"type": "error", "message": str(e)})
    threading.Thread(target=worker, daemon=True).start()

def on_button_extra_text():
    global EXTRA_PROMPT
    extra = input_entry.get().strip()
    if extra:
        EXTRA_PROMPT += ("\n" if EXTRA_PROMPT else "") + extra
        write_log(f"Neue Zusatzinfo (Text): {extra}")
        set_status("💾 Zusatzinfo (Text) gespeichert.", busy=False)
        input_entry.delete(0, tk.END)
        update_zusatzinfo_section(EXTRA_PROMPT)

def on_button_extra_speech():
    global EXTRA_PROMPT
    set_status("🎙️ Aufnahme Zusatzinfo (5 s)…", busy=True)
    def worker():
        try:
            record_audio_fixed_duration()
            extra = transkribiere_audio().strip()
            if not extra or extra == "[]":
                result_queue.put({"type": "info", "message": "Keine Zusatzinfo erkannt."})
                return
            result_queue.put({"type": "extra_speech", "text": extra})
        except Exception as e:
            result_queue.put({"type": "error", "message": str(e)})
    threading.Thread(target=worker, daemon=True).start()

def on_button_stop():
    stop_robot_and_code()
    set_status("⏹️ Code/Roboter gestoppt.", busy=False)

def on_button_quit():
    stop_robot_and_code()
    if root is not None:
        root.destroy()

# ─── Queue-Verarbeitung ───────────────────────────────────────────────────────
def process_queue():
    global running_code_thread, LAST_SCRIPT, EXTRA_PROMPT, MEMORY
    try:
        while True:
            item = result_queue.get_nowait()
            t = item.get("type")

            if t == "error":
                set_status(f"❌ Fehler: {item['message']}", busy=False)
                write_log(f"Fehler: {item['message']}")

            elif t == "info":
                set_status(f"ℹ️ {item['message']}", busy=False)
                write_log(item['message'])

            elif t == "speech_transcript":
                txt = item["text"]
                update_text_widget(prompt_text_widget, f"[Sprache]\n{txt}", readonly=False)

            elif t == "extra_speech":
                extra = item["text"]
                EXTRA_PROMPT += ("\n" if EXTRA_PROMPT else "") + extra
                write_log(f"Neue Zusatzinfo (Sprache): {extra}")
                set_status("💾 Zusatzinfo (Sprache) gespeichert.", busy=False)
                update_zusatzinfo_section(EXTRA_PROMPT)

            elif t == "code_generated":
                prompt = item["prompt"]
                code   = item["code"]
                suffix = item.get("suffix", "")
                LAST_SCRIPT = code
                save_code(code, suffix)
                update_text_widget(prompt_text_widget, prompt, readonly=False)
                update_text_widget(code_text_widget, code, readonly=True)
                update_last_script_section(code)
                set_status("▶️ Führe generierten Code aus …", busy=True)

                stop_event.clear()
                running_code_thread = threading.Thread(
                    target=run_code,
                    args=(code, result_queue, MEMORY.copy()),
                    daemon=True
                )
                running_code_thread.start()

            elif t == "code_result":
                lcl = item["locals"]
                if "_error" in lcl:
                    set_status(f"❌ Fehler im Code: {lcl['_error']}", busy=False)
                    write_log(f"Codefehler: {lcl['_error']}")
                else:
                    update_memory_from_locals(lcl, MEMORY)
                    write_log(f"MEMORY aktualisiert: {MEMORY}")
                    set_status("✅ Code fertig.", busy=False)
                    update_memory_section()

            result_queue.task_done()
    except queue.Empty:
        pass

    if root is not None:
        root.after(100, process_queue)

# ─── GUI ──────────────────────────────────────────────────────────────────────
def build_gui():
    global root, status_label, prompt_text_widget, code_text_widget, system_prompt_widget, input_entry

    root = tk.Tk()
    root.title("Robot LLM Interface")

    status_label = tk.Label(root, text="Bereit.", anchor="w")
    status_label.grid(row=0, column=0, columnspan=4, sticky="we", padx=5, pady=5)

    btn_width = 22
    btn_speech   = tk.Button(root, text="Sprache → Code",       command=on_button_speech,       width=btn_width)
    btn_text     = tk.Button(root, text="Text → Code",          command=on_button_text,         width=btn_width)
    btn_extra_s  = tk.Button(root, text="Zusatzinfo (Sprache)", command=on_button_extra_speech, width=btn_width)
    btn_extra_t  = tk.Button(root, text="Zusatzinfo (Text)",    command=on_button_extra_text,   width=btn_width)

    btn_speech.grid(  row=1, column=0, padx=5, pady=5, sticky="we")
    btn_text.grid(    row=1, column=1, padx=5, pady=5, sticky="we")
    btn_extra_s.grid( row=1, column=2, padx=5, pady=5, sticky="we")
    btn_extra_t.grid( row=1, column=3, padx=5, pady=5, sticky="we")

    tk.Label(root, text="Eingabe (für Befehle oder Zusatzinfo):").grid(
        row=2, column=0, columnspan=4, padx=5, pady=2, sticky="w"
    )
    input_entry = tk.Entry(root)
    input_entry.grid(row=3, column=0, columnspan=4, padx=5, pady=2, sticky="we")

    btn_stop  = tk.Button(root, text="Stop Code/Roboter",  command=on_button_stop)
    btn_quit  = tk.Button(root, text="Quit",               command=on_button_quit)
    btn_stop.grid( row=4, column=0, padx=5, pady=5, sticky="we")
    btn_quit.grid( row=4, column=3, padx=5, pady=5, sticky="we")

    tk.Label(root, text="Letzter Prompt:").grid(row=5, column=0, padx=5, pady=2, sticky="w")
    tk.Label(root, text="Generierter Code:").grid(row=5, column=1, padx=5, pady=2, sticky="w")
    tk.Label(root, text="Aktueller System Prompt:").grid(row=5, column=2, padx=5, pady=2, sticky="w")

    btn_save_sys = tk.Button(root, text="System Prompt speichern", command=on_button_save_system_prompt)
    btn_save_sys.grid(row=5, column=3, padx=5, pady=2, sticky="e")

    prompt_text_widget   = scrolledtext.ScrolledText(root, width=30, height=15, wrap="none")
    code_text_widget     = scrolledtext.ScrolledText(root, width=50, height=15, wrap="none")
    system_prompt_widget = scrolledtext.ScrolledText(root, width=50, height=15, wrap="none")

    prompt_text_widget.grid(  row=6, column=0, padx=5, pady=5, sticky="nsew")
    code_text_widget.grid(    row=6, column=1, padx=5, pady=5, sticky="nsew")
    system_prompt_widget.grid(row=6, column=2, columnspan=2, padx=5, pady=5, sticky="nsew")

    prompt_scroll_x = tk.Scrollbar(root, orient="horizontal", command=prompt_text_widget.xview)
    code_scroll_x   = tk.Scrollbar(root, orient="horizontal", command=code_text_widget.xview)
    sys_scroll_x    = tk.Scrollbar(root, orient="horizontal", command=system_prompt_widget.xview)

    prompt_text_widget.configure(xscrollcommand=prompt_scroll_x.set)
    code_text_widget.configure(xscrollcommand=code_scroll_x.set)
    system_prompt_widget.configure(xscrollcommand=sys_scroll_x.set)

    prompt_scroll_x.grid(row=7, column=0, padx=5, pady=(0,5), sticky="we")
    code_scroll_x.grid(  row=7, column=1, padx=5, pady=(0,5), sticky="we")
    sys_scroll_x.grid(   row=7, column=2, columnspan=2, padx=5, pady=(0,5), sticky="we")

    code_text_widget.config(state="disabled")

    # Initialer Systemprompt: BASE + ggf. Zusatzinfo + MEMORY
    initial_txt = SYSTEM_PROMPT_BASE
    if EXTRA_PROMPT:
        initial_txt += f"\n\nZusatzinfo: {EXTRA_PROMPT.strip()}"
    if MEMORY:
        initial_txt += f"\n\nBekannte Variablen (MEMORY):\n{repr(dict_without_functions(MEMORY))}"
    system_prompt_widget.insert(tk.END, initial_txt)

    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=2)
    root.grid_columnconfigure(2, weight=2)
    root.grid_columnconfigure(3, weight=0)
    root.grid_rowconfigure(6, weight=1)

    root.after(100, process_queue)
    root.after(150, animate_spinner)

    return root

# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = build_gui()
    root.mainloop()
