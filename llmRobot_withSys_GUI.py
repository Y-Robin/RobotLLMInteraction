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
import keyword
import tkinter as tk
from tkinter import ttk  # ttk für dunkle Scrollbars

# ─── Roboter-Module ────────────────────────────────────────────────────────────
from stopRobot import stop_robot
from gripper_control import gripper_open, gripper_close
from moveFun import send_pose_to_robot
from robot_teaching import teach_positions  # wie im Ursprungsskript
from bandFun import send_conveyor_to_robot
from infoLicht import read_licht_input

# ─── OpenAI ────────────────────────────────────────────────────────────────────
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ─── Konstanten / Dateien ─────────────────────────────────────────────────────
AUDIO_FILE            = "befehl.wav"
SAMPLERATE            = 16000
SYSTEM_PROMPT_FILE    = "DemoPrompts/demo2.txt"
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
USER_PROMPT_HISTORY = []

# GUI-State
root                 = None
status_label         = None
prompt_text_widget   = None
code_text_widget     = None
system_prompt_widget = None
input_entry          = None

spinner_running      = False
spinner_index        = 0
spinner_frames       = ["⏳", "◴", "◷", "◶", "◵"]

SYSTEM_PROMPT_BASE   = ""

# Flow-Diagramm
flow_canvas          = None
FLOW_NODES           = {}
CURRENT_PHASE        = "ready"

FLOW_DEFINITION = [
    {"phase": "ready",   "label": "READY",         "icon": "✅"},
    {"phase": "input",   "label": "SPRACHE",       "icon": "🎙"},
    {"phase": "stt",     "label": "Speech → Text", "icon": "🎧"},
    {"phase": "llm",     "label": "LLM",           "icon": "🤖"},
    {"phase": "code",    "label": "CODE",          "icon": "📜"},
    {"phase": "robot",   "label": "ROBOT",         "icon": "🦾"},
    {"phase": "stopped", "label": "STOP",          "icon": "⛔"},
]

# Aufnahme-State für Speech→Code
speech_recording         = False
speech_record_stop_event = threading.Event()
speech_button            = None

# ─── Farben / Theme ───────────────────────────────────────────────────────────
BG_MAIN   = "#101015"
BG_PANEL  = "#181820"
BG_TEXT   = "#1e1e26"
FG_TEXT   = "#f5f5f5"
FG_SUBTLE = "#bbbbbb"
ACCENT    = "#2979ff"
ERROR_COLOR = "#ff5252"
OK_COLOR    = "#66bb6a"
SCROLL_BG   = "#2a2a35"

BUTTON_STYLE = {
    "bg": "#262636",
    "fg": FG_TEXT,
    "activebackground": "#33334a",
    "activeforeground": FG_TEXT,
    "relief": "flat",
    "bd": 0,
    "highlightthickness": 0,
    "padx": 6,
    "pady": 6,
}

LABEL_FONT  = ("Segoe UI", 9, "bold")   # Beschreibende Texte fett
STATUS_FONT = ("Segoe UI", 9)
CODE_FONT   = ("Consolas", 10)

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

def _apply_system_prompt_styling():
    if system_prompt_widget is None:
        return
    system_prompt_widget.tag_config(
        "header",
        font=(CODE_FONT[0], CODE_FONT[1], "bold"),
        foreground="#FFD54F"
    )
    system_prompt_widget.tag_remove("header", "1.0", "end")
    headers = [
        "Prompt-Historie:",
        "Zusatzinfo:",
        "Letztes ausgeführtes Skript:",
        "Bekannte Variablen (MEMORY):",
    ]
    for h in headers:
        start_idx = "1.0"
        while True:
            idx = system_prompt_widget.search(h, start_idx, stopindex="end")
            if not idx:
                break
            end_idx = f"{idx}+{len(h)}c"
            system_prompt_widget.tag_add("header", idx, end_idx)
            start_idx = end_idx

def set_system_prompt_text(txt: str):
    if system_prompt_widget is None:
        return
    system_prompt_widget.config(state="normal")
    system_prompt_widget.delete("1.0", tk.END)
    system_prompt_widget.insert(tk.END, txt)
    _apply_system_prompt_styling()
    system_prompt_widget.config(state="normal")

def update_prompt_history_section():
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
    if system_prompt_widget is None:
        return
    txt = get_system_prompt_text()
    new_block = f"\n\nZusatzinfo: {extra_text.strip()}"
    pattern = r"(\n\nZusatzinfo:)(.*?)(?=\n\nLetztes ausgeführtes Skript:|\n\nBekannte Variablen \(MEMORY\):|\n\nPrompt-Historie:|\Z)"
    m = re.search(pattern, txt, flags=re.DOTALL)
    if m:
        new_txt = txt[:m.start()] + new_block + txt[m.end():]
    else:
        mem_pos = txt.find("\n\nBekannte Variablen (MEMORY):")
        if mem_pos == -1:
            new_txt = txt + new_block
        else:
            new_txt = txt[:mem_pos] + new_block + txt[mem_pos:]
    set_system_prompt_text(new_txt)

def update_last_script_section(code: str):
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
        mem_pos = txt.find("\n\nBekannte Variablen (MEMORY):")
        if mem_pos == -1:
            new_txt = txt + new_block
        else:
            new_txt = txt[:mem_pos] + new_block + txt[mem_pos:]
    set_system_prompt_text(new_txt)

def update_memory_section():
    if system_prompt_widget is None:
        return
    txt = get_system_prompt_text()
    mem_repr = repr(dict_without_functions(MEMORY))
    new_block = f"\n\nBekannte Variablen (MEMORY):\n{mem_repr}"
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

def record_audio_with_early_stop(fname, stop_evt: threading.Event, max_duration=5.0):
    write_log(f"Starte Audioaufnahme (max {max_duration} s, frühzeitiger Stop möglich)")
    recording = []
    stream = sd.InputStream(samplerate=SAMPLERATE, channels=1)
    start_time = time.time()
    with stream:
        while True:
            if stop_evt.is_set():
                write_log("Audioaufnahme: Stop-Event gesetzt, breche ab.")
                break
            if time.time() - start_time >= max_duration:
                write_log("Audioaufnahme: max Dauer erreicht.")
                break
            data, _ = stream.read(1024)
            recording.append(data.copy())
    if recording:
        audio = np.concatenate(recording, axis=0)
    else:
        audio = np.zeros((1, 1), dtype=np.float32)
    scipy.io.wavfile.write(fname, SAMPLERATE,
                           np.int16(audio.flatten() * 32767))

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
        model="gpt-4.1-2025-04-14",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt_text}
        ],
        temperature=0
    )
    return rsp.choices[0].message.content.strip()

# ─── Robot-Code-Handling (nah am Ursprung) ────────────────────────────────────
def stop_robot_and_code():
    global running_code_thread
    stop_event.set()
    try:
        stop_robot()
    except Exception as e:
        write_log(f"Fehler beim Stoppen des Roboters: {e}")
    if running_code_thread and running_code_thread.is_alive():
        write_log("⏹️ Beende laufenden Code-Thread …")
        running_code_thread.join(timeout=2)
        running_code_thread = None

def run_code(code, q, memory):
    lcl = {
        "MEMORY": memory,
        "stop_event": stop_event,
        "teach_positions": teach_positions,
        "stop_robot": stop_robot,
        "gripper_open": gripper_open,
        "gripper_close": gripper_close,
        "send_pose_to_robot": send_pose_to_robot,
        "send_conveyor_to_robot": send_conveyor_to_robot,
        "read_licht_input": read_licht_input,
    }
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

# ─── Flow-Diagramm ───────────────────────────────────────────────────────────
def redraw_flow_diagram(event=None):
    global FLOW_NODES
    if flow_canvas is None:
        return
    flow_canvas.delete("all")
    width = flow_canvas.winfo_width()
    if width < 1:
        width = 800
    height = flow_canvas.winfo_height()
    if height < 80:
        height = 110
    y = height // 2
    box_h = 60
    count = len(FLOW_DEFINITION)
    margin = 40
    available = max(250, width - 2 * margin)
    box_w = min(150, max(100, available / (count * 1.2)))
    if count > 1:
        gap = max(20, (available - count * box_w) / (count - 1))
    else:
        gap = 0
    FLOW_NODES = {}
    for i, node in enumerate(FLOW_DEFINITION):
        x1 = margin + i * (box_w + gap)
        x2 = x1 + box_w
        y1 = y - box_h // 2
        y2 = y + box_h // 2
        rect = flow_canvas.create_rectangle(
            x1, y1, x2, y2,
            fill="#252536",
            outline="#44445a",
            width=2,
            tags=("node", node["phase"])
        )
        icon = flow_canvas.create_text(
            (x1 + x2) // 2, y1 + 15,
            text=node["icon"],
            fill=FG_TEXT,
            font=("Segoe UI Emoji", 16, "bold")
        )
        label = flow_canvas.create_text(
            (x1 + x2) // 2, y1 + 35,
            text=node["label"],
            fill=FG_TEXT,
            font=("Segoe UI", 9, "bold")
        )
        FLOW_NODES[node["phase"]] = {
            "rect": rect,
            "icon": icon,
            "label": label,
            "x_center": (x1 + x2) // 2
        }
    for i in range(count - 1):
        p1 = FLOW_DEFINITION[i]["phase"]
        p2 = FLOW_DEFINITION[i + 1]["phase"]
        n1 = FLOW_NODES[p1]
        n2 = FLOW_NODES[p2]
        x1 = n1["x_center"] + box_w / 2 - 20
        x2 = n2["x_center"] - box_w / 2 + 20
        flow_canvas.create_line(
            x1, y, x2, y,
            fill="#77778a",
            width=2,
            arrow=tk.LAST
        )
    update_flow_phase(CURRENT_PHASE)

def build_flow_diagram(parent):
    global flow_canvas
    flow_canvas = tk.Canvas(parent, height=110, bg="#171721", highlightthickness=0, bd=0)
    flow_canvas.grid(row=0, column=0, columnspan=4, sticky="we", padx=8, pady=8)
    flow_canvas.bind("<Configure>", redraw_flow_diagram)
    redraw_flow_diagram()

def update_flow_phase(phase: str):
    global CURRENT_PHASE
    CURRENT_PHASE = phase
    if flow_canvas is None:
        return
    for ph, node in FLOW_NODES.items():
        rect_id = node["rect"]
        if ph == phase:
            if ph in ("stopped", "error"):
                fill = "#b71c1c"
                outline = ERROR_COLOR
            elif ph == "ready":
                fill = "#1b5e20"
                outline = OK_COLOR
            else:
                fill = "#0d47a1"
                outline = ACCENT
        else:
            fill = "#252536"
            outline = "#44445a"
        flow_canvas.itemconfig(rect_id, fill=fill, outline=outline)

# ─── GUI-Helfer ───────────────────────────────────────────────────────────────
def set_status(text, busy=False, phase=None):
    global spinner_running
    if status_label is not None:
        status_label.config(text=text)
    spinner_running = busy
    if phase is not None:
        update_flow_phase(phase)

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

# ─── Syntax Highlighting ──────────────────────────────────────────────────────
def highlight_code():
    if code_text_widget is None:
        return
    code_text_widget.config(state="normal")
    text = code_text_widget.get("1.0", "end-1c")
    code_text_widget.tag_config("keyword", foreground="#82AAFF")
    code_text_widget.tag_config("string",  foreground="#C3E88D")
    code_text_widget.tag_config("comment", foreground="#676E95")
    code_text_widget.tag_config("builtin", foreground="#FFCB6B")
    for tag in ("keyword", "string", "comment", "builtin"):
        code_text_widget.tag_remove(tag, "1.0", "end")
    kw_pattern = r"\b(" + "|".join(keyword.kwlist) + r")\b"
    for m in re.finditer(kw_pattern, text):
        start = f"1.0+{m.start()}c"
        end   = f"1.0+{m.end()}c"
        code_text_widget.tag_add("keyword", start, end)
    builtins = ["print", "range", "len", "int", "float", "str",
                "list", "dict", "set", "tuple"]
    bt_pattern = r"\b(" + "|".join(builtins) + r")\b"
    for m in re.finditer(bt_pattern, text):
        start = f"1.0+{m.start()}c"
        end   = f"1.0+{m.end()}c"
        code_text_widget.tag_add("builtin", start, end)
    str_pattern = r"(\".*?\"|\'.*?\')"
    for m in re.finditer(str_pattern, text, re.DOTALL):
        start = f"1.0+{m.start()}c"
        end   = f"1.0+{m.end()}c"
        code_text_widget.tag_add("string", start, end)
    for m in re.finditer(r"#.*", text):
        start = f"1.0+{m.start()}c"
        end   = f"1.0+{m.end()}c"
        code_text_widget.tag_add("comment", start, end)
    code_text_widget.config(state="disabled")

# ─── System Prompt speichern ──────────────────────────────────────────────────
def on_button_save_system_prompt():
    txt = get_system_prompt_text()
    save_system_prompt_to_file(txt)
    set_status("💾 System Prompt gespeichert (wird ab jetzt so verwendet).", busy=False)

# ─── Worker-Funktionen ────────────────────────────────────────────────────────
def start_gpt_flow(prompt_text, suffix_for_save="_text"):
    global LAST_SCRIPT, USER_PROMPT_HISTORY, running_code_thread
    if not prompt_text:
        return
    if running_code_thread is not None and running_code_thread.is_alive():
        set_status("⚠️ Es läuft noch ein Code-Thread – zuerst Stop drücken.", busy=False, phase="stopped")
        return
    USER_PROMPT_HISTORY.append(prompt_text)
    update_prompt_history_section()
    system_prompt = get_system_prompt_text()
    set_status("Sende an GPT und generiere Code …", busy=True, phase="llm")
    def worker():
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
    set_status("Text-Eingabe …", busy=True, phase="input")
    start_gpt_flow(txt, "_text")

def on_button_speech():
    global speech_recording
    if not speech_recording:
        speech_recording = True
        speech_record_stop_event.clear()
        set_status("🎙️ Aufnahme läuft … (erneut klicken zum Stoppen, max. 5 s)", busy=True, phase="input")
        if speech_button is not None:
            speech_button.config(text="Aufnahme stoppen")
        def worker():
            try:
                record_audio_with_early_stop(AUDIO_FILE, speech_record_stop_event, max_duration=5.0)
                result_queue.put({"type": "after_record"})
                txt = transkribiere_audio().strip()
                result_queue.put({"type": "speech_record_done"})
                if not txt or txt == "[]":
                    result_queue.put({"type": "info", "message": "Keine Sprache erkannt."})
                    result_queue.put({"type": "phase", "phase": "ready"})
                    return
                result_queue.put({"type": "speech_transcript", "text": txt})
                result_queue.put({"type": "phase", "phase": "stt"})
                result_queue.put({"type": "start_gpt", "prompt": txt, "suffix": "_speech"})
            except Exception as e:
                result_queue.put({"type": "error", "message": str(e)})
                result_queue.put({"type": "speech_record_done"})
        threading.Thread(target=worker, daemon=True).start()
    else:
        speech_record_stop_event.set()
        set_status("⏹️ Aufnahme wird beendet …", busy=True, phase="stt")

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
    set_status("🎙️ Aufnahme Zusatzinfo (5 s)…", busy=True, phase="input")
    def worker():
        try:
            record_audio_fixed_duration()
            txt = transkribiere_audio().strip()
            if not txt or txt == "[]":
                result_queue.put({"type": "info", "message": "Keine Zusatzinfo erkannt."})
                result_queue.put({"type": "phase", "phase": "ready"})
                return
            result_queue.put({"type": "extra_speech", "text": txt})
        except Exception as e:
            result_queue.put({"type": "error", "message": str(e)})
    threading.Thread(target=worker, daemon=True).start()

def on_button_stop():
    stop_robot_and_code()
    phase = "ready"
    if running_code_thread is not None and running_code_thread.is_alive():
        phase = "stopped"
    set_status("⏹️ Code/Roboter gestoppt.", busy=False, phase=phase)

def on_button_quit():
    stop_robot_and_code()
    if root is not None:
        root.destroy()

# ─── Queue-Verarbeitung ───────────────────────────────────────────────────────
def process_queue():
    global running_code_thread, LAST_SCRIPT, EXTRA_PROMPT, MEMORY, speech_recording
    try:
        while True:
            item = result_queue.get_nowait()
            t = item.get("type")
            if t == "error":
                msg = item["message"]
                if "durch Benutzer gestoppt" in msg:
                    set_status("⏹️ Vom Benutzer gestoppt.", busy=False, phase="ready")
                else:
                    set_status(f"❌ Fehler: {msg}", busy=False, phase="stopped")
                write_log(f"Fehler: {msg}")
            elif t == "info":
                set_status(f"ℹ️ {item['message']}", busy=False)
                write_log(item['message'])
            elif t == "phase":
                update_flow_phase(item["phase"])
            elif t == "after_record":
                set_status("Wandle Sprache in Text um …", busy=True, phase="stt")
            elif t == "speech_record_done":
                speech_recording = False
                if speech_button is not None:
                    speech_button.config(text="Sprache → Code")
            elif t == "speech_transcript":
                txt = item["text"]
                update_text_widget(prompt_text_widget, f"[Sprache]\n{txt}", readonly=False)
            elif t == "extra_speech":
                extra = item["text"]
                EXTRA_PROMPT += ("\n" if EXTRA_PROMPT else "") + extra
                write_log(f"Neue Zusatzinfo (Sprache): {extra}")
                set_status("💾 Zusatzinfo (Sprache) gespeichert.", busy=False)
                update_zusatzinfo_section(EXTRA_PROMPT)
            elif t == "start_gpt":
                prompt = item["prompt"]
                suffix = item.get("suffix", "_text")
                start_gpt_flow(prompt, suffix)
            elif t == "code_generated":
                prompt = item["prompt"]
                code   = item["code"]
                suffix = item.get("suffix", "")
                LAST_SCRIPT = code
                save_code(code, suffix)
                update_text_widget(prompt_text_widget, prompt, readonly=False)
                update_text_widget(code_text_widget, code, readonly=True)
                highlight_code()
                update_last_script_section(code)
                set_status("▶️ Führe generierten Code aus …", busy=True, phase="code")
                stop_event.clear()
                running_code_thread = threading.Thread(
                    target=run_code,
                    args=(code, result_queue, MEMORY.copy()),
                    daemon=True
                )
                running_code_thread.start()
                update_flow_phase("robot")
            elif t == "code_result":
                lcl = item["locals"]
                if "_error" in lcl:
                    set_status(f"❌ Fehler im Code: {lcl['_error']}", busy=False, phase="stopped")
                    write_log(f"Codefehler: {lcl['_error']}")
                else:
                    update_memory_from_locals(lcl, MEMORY)
                    write_log(f"MEMORY aktualisiert: {MEMORY}")
                    set_status("✅ Code fertig.", busy=False, phase="ready")
                    update_memory_section()
            result_queue.task_done()
    except queue.Empty:
        pass
    if root is not None:
        root.after(100, process_queue)

# ─── Scrollbar-Helfer: dunkel & nur anzeigen, wenn nötig ─────────────────────
def attach_dark_scrollbars(text_widget, frame):
    """
    Fügt vertikale/horizontale Scrollbars hinzu, die:
      - dunkles ttk-Design haben
      - automatisch ausgeblendet werden, wenn kein Scrollen nötig ist
    Erwartet Layout:
      row=0,col=0 -> Text
      row=0,col=1 -> V-Scroll
      row=1,col=0 -> H-Scroll
    """
    vscroll = ttk.Scrollbar(
        frame, orient="vertical",
        command=text_widget.yview,
        style="Dark.Vertical.TScrollbar"
    )
    hscroll = ttk.Scrollbar(
        frame, orient="horizontal",
        command=text_widget.xview,
        style="Dark.Horizontal.TScrollbar"
    )

    def _on_yscroll(first, last):
        vscroll.set(first, last)
        # first=0,last=1 -> alles sichtbar, kein Scroll nötig
        if float(first) <= 0.0 and float(last) >= 1.0:
            vscroll.grid_remove()
        else:
            vscroll.grid(row=0, column=1, sticky="ns")

    def _on_xscroll(first, last):
        hscroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            hscroll.grid_remove()
        else:
            hscroll.grid(row=1, column=0, sticky="we")

    text_widget.configure(yscrollcommand=_on_yscroll,
                          xscrollcommand=_on_xscroll)

    # Initial verstecken
    vscroll.grid_remove()
    hscroll.grid_remove()

    return vscroll, hscroll

# ─── GUI ──────────────────────────────────────────────────────────────────────
def build_gui():
    global root, status_label, prompt_text_widget, code_text_widget, system_prompt_widget, input_entry, speech_button

    root = tk.Tk()
    root.title("Robot LLM Interface")
    root.configure(bg=BG_MAIN)
    root.minsize(1200, 700)

    # Dark ttk-Styles für Scrollbars
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "Dark.Vertical.TScrollbar",
        background=SCROLL_BG,
        troughcolor=BG_TEXT,
        bordercolor=BG_MAIN,
        arrowcolor=FG_TEXT,
        width=12
    )
    style.configure(
        "Dark.Horizontal.TScrollbar",
        background=SCROLL_BG,
        troughcolor=BG_TEXT,
        bordercolor=BG_MAIN,
        arrowcolor=FG_TEXT,
        width=12
    )

    build_flow_diagram(root)

    status_label = tk.Label(root, text="Bereit.", anchor="w",
                            bg=BG_MAIN, fg=FG_SUBTLE, font=STATUS_FONT)
    status_label.grid(row=1, column=0, columnspan=4, sticky="we", padx=8, pady=(0,8))

    btn_width = 22
    speech_button = tk.Button(root, text="Sprache → Code", command=on_button_speech,
                              width=btn_width, **BUTTON_STYLE)
    btn_text     = tk.Button(root, text="Text → Code", command=on_button_text,
                             width=btn_width, **BUTTON_STYLE)
    btn_extra_s  = tk.Button(root, text="Zusatzinfo (Sprache)", command=on_button_extra_speech,
                             width=btn_width, **BUTTON_STYLE)
    btn_extra_t  = tk.Button(root, text="Zusatzinfo (Text)", command=on_button_extra_text,
                             width=btn_width, **BUTTON_STYLE)

    speech_button.grid(row=2, column=0, padx=8, pady=4, sticky="we")
    btn_text.grid(      row=2, column=1, padx=8, pady=4, sticky="we")
    btn_extra_s.grid(   row=2, column=2, padx=8, pady=4, sticky="we")
    btn_extra_t.grid(   row=2, column=3, padx=8, pady=4, sticky="we")

    lbl_in = tk.Label(root, text="Eingabe (für Befehle oder Zusatzinfo):",
                      bg=BG_MAIN, fg=FG_TEXT, font=LABEL_FONT)
    lbl_in.grid(row=3, column=0, columnspan=4, padx=8, pady=2, sticky="w")

    # Größeres Eingabefeld (Font + ipady)
    input_entry = tk.Entry(
        root,
        bg=BG_TEXT,
        fg=FG_TEXT,
        insertbackground=FG_TEXT,
        relief="solid",
        bd=1,
        font=("Segoe UI", 10)
    )
    input_entry.grid(row=4, column=0, columnspan=4, padx=8, pady=4, sticky="we", ipady=4)

    btn_stop  = tk.Button(root, text="Stop Code/Roboter", command=on_button_stop,
                          **BUTTON_STYLE)
    btn_quit  = tk.Button(root, text="Quit", command=on_button_quit,
                          **BUTTON_STYLE)
    btn_stop.grid( row=5, column=0, padx=8, pady=4, sticky="we")
    btn_quit.grid( row=5, column=3, padx=8, pady=4, sticky="we")

    tk.Label(root, text="Letzter Prompt:", bg=BG_MAIN, fg=FG_TEXT, font=LABEL_FONT).grid(
        row=6, column=0, padx=8, pady=2, sticky="w"
    )
    tk.Label(root, text="Generierter Code:", bg=BG_MAIN, fg=FG_TEXT, font=LABEL_FONT).grid(
        row=6, column=1, padx=8, pady=2, sticky="w"
    )
    tk.Label(root, text="Aktueller System Prompt:", bg=BG_MAIN, fg=FG_TEXT, font=LABEL_FONT).grid(
        row=6, column=2, padx=8, pady=2, sticky="w"
    )

    btn_save_sys = tk.Button(root, text="System Prompt speichern",
                             command=on_button_save_system_prompt, **BUTTON_STYLE)
    btn_save_sys.grid(row=6, column=3, padx=8, pady=2, sticky="e")

    # Prompt-Panel
    prompt_frame = tk.Frame(root, bg=BG_MAIN, bd=0)
    prompt_frame.grid(row=7, column=0, padx=8, pady=6, sticky="nsew")
    prompt_text_widget = tk.Text(
        prompt_frame, wrap="none",
        bg=BG_TEXT, fg=FG_TEXT, insertbackground=FG_TEXT,
        relief="solid", bd=2, font=CODE_FONT
    )
    prompt_text_widget.grid(row=0, column=0, sticky="nsew")
    attach_dark_scrollbars(prompt_text_widget, prompt_frame)
    prompt_frame.grid_rowconfigure(0, weight=1)
    prompt_frame.grid_columnconfigure(0, weight=1)

    # Code-Panel
    code_frame = tk.Frame(root, bg=BG_MAIN, bd=0)
    code_frame.grid(row=7, column=1, padx=8, pady=6, sticky="nsew")
    code_text_widget = tk.Text(
        code_frame, wrap="none",
        bg=BG_TEXT, fg=FG_TEXT, insertbackground=FG_TEXT,
        relief="solid", bd=2, font=CODE_FONT
    )
    code_text_widget.grid(row=0, column=0, sticky="nsew")
    attach_dark_scrollbars(code_text_widget, code_frame)
    code_frame.grid_rowconfigure(0, weight=1)
    code_frame.grid_columnconfigure(0, weight=1)

    # System-Prompt-Panel
    sys_frame = tk.Frame(root, bg=BG_MAIN, bd=0)
    sys_frame.grid(row=7, column=2, columnspan=2, padx=8, pady=6, sticky="nsew")
    system_prompt_widget = tk.Text(
        sys_frame, wrap="none",
        bg=BG_TEXT, fg=FG_TEXT, insertbackground=FG_TEXT,
        relief="solid", bd=2, font=CODE_FONT
    )
    system_prompt_widget.grid(row=0, column=0, sticky="nsew")
    attach_dark_scrollbars(system_prompt_widget, sys_frame)
    sys_frame.grid_rowconfigure(0, weight=1)
    sys_frame.grid_columnconfigure(0, weight=1)

    code_text_widget.config(state="disabled")
    system_prompt_widget.config(state="normal")

    # Initialer Systemprompt
    initial_txt = SYSTEM_PROMPT_BASE
    if EXTRA_PROMPT:
        initial_txt += f"\n\nZusatzinfo: {EXTRA_PROMPT.strip()}"
    if MEMORY:
        initial_txt += f"\n\nBekannte Variablen (MEMORY):\n{repr(dict_without_functions(MEMORY))}"
    system_prompt_widget.insert(tk.END, initial_txt)
    _apply_system_prompt_styling()

    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=2)
    root.grid_columnconfigure(2, weight=2)
    root.grid_columnconfigure(3, weight=1)
    root.grid_rowconfigure(7, weight=1)

    root.after(100, process_queue)
    root.after(150, animate_spinner)
    update_flow_phase("ready")

    return root

# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = build_gui()
    root.mainloop()
