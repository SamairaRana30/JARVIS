# Jarvis Setup Guide

## Prerequisites

### 1. Python 3.10+
Already installed. Verify: `python --version`

### 2. Wake Word Model
**The wake word model downloads automatically on first run. No manual download needed.**

On first launch `jarvis.py` calls `setup_models.py`, which checks for
`assets/models/hey_jarvis.onnx` and downloads it from GitHub if missing (~2 MB).
A progress bar is shown in the console.

If the download fails (no internet), Jarvis still starts — wake word detection
is disabled until the file is placed manually:
```
assets/models/hey_jarvis.onnx
```

Model source: `config.yaml → wake_word → model_url`

### 3. Install Ollama
Download from https://ollama.com/download and install.

Then pull the llama3 model:
```
ollama pull llama3
```

Verify Ollama is running:
```
ollama list
```

### 3. Add Ollama to Windows Startup
Open Task Scheduler → Create Basic Task:
- Name: Ollama Server
- Trigger: At log on
- Action: Start a program
- Program: `C:\Users\<you>\AppData\Local\Programs\Ollama\ollama.exe`
- Arguments: `serve`
- Check "Run whether user is logged on or not" → No (run only when logged on)

Or run the first-launch script and Jarvis will register it automatically.

### 4. Install Python Dependencies
```
cd C:\Users\samai\Desktop\Jarvis\Jarvis
pip install -r requirements.txt
```

### 5. Microphone Setup
Default: Jarvis auto-detects your default mic.

To use a specific mic, find its index:
```python
import sounddevice as sd
print(sd.query_devices())
```
Set `mic_device_index` in `config.yaml` to the correct index.

### 6. Personalise config.yaml
Edit `data/memory.json`:
- Change `"name"` to your name
- Change `"location"` to your city
- Change `"uni"` to your university
- Update `"projects"`, `"study_apps"`, `"quick_links"`

Edit `config.yaml`:
- Set `voice` to your preferred edge-tts voice
  (run `edge-tts --list-voices` to see options)
- Set `profile` to `study`, `work`, or `chill`

### 7. First Run

> **Important:** Run as Administrator to enable site blocking (Study Mode).
> Without admin rights, Jarvis works fully except it cannot edit the Windows
> hosts file to block distracting websites.

**Option A — Run as administrator (recommended):**
Right-click PowerShell → "Run as administrator", then:
```
cd C:\Users\samai\Desktop\Jarvis\Jarvis
python tray_icon.py
```

**Option B — Standard run (site blocking disabled):**
```
python tray_icon.py
```
Jarvis will warn you on startup and skip site blocking gracefully.
All other features (notes, tasks, reminders, calendar, Notion, weather, etc.) work fine.

**Option C — Always run as admin via Task Scheduler (permanent fix):**
1. Open Task Scheduler → Create Task (not Basic Task)
2. General tab → check **"Run with highest privileges"**
3. Triggers → New → At log on
4. Actions → New → Start a program:
   - Program: `C:\Users\samai\AppData\Local\Programs\Python\Python313\python.exe`
   - Arguments: `C:\Users\samai\Desktop\Jarvis\Jarvis\tray_icon.py`
5. Settings → uncheck "Stop the task if it runs longer than"
6. Click OK

This makes Jarvis start as administrator automatically on every login.

Jarvis will:
1. Log version and profile on startup
2. Register itself in Windows Task Scheduler for auto-start
3. Register Ollama in startup if not already present
4. Start the system tray icon
5. Begin listening for the wake word "Jarvis"

### 8. Wake Word
The model downloads automatically on first run.
Say **"Jarvis"** to activate.
Or press **Ctrl+Shift+J** to manually trigger / mute toggle.

### 9. Tray Icon Menu (right-click)
- Pause / Resume listening
- Switch profile (study / work / chill)
- Toggle dry-run mode
- Reload config
- Open logs folder
- Open conversations folder
- Restart Jarvis
- Quit

### 10. Running Tests
```
pytest tests/ -v
```

## Whisper Model Size Guide

Whisper is the speech-to-text engine. Configure it in `config.yaml → whisper`.

| Model | Speed | Accuracy | RAM | Best for |
|-------|-------|----------|-----|---------|
| `tiny` | Fastest | Low | ~200 MB | Quick commands, low-power laptops |
| `base` | Fast | Good | ~300 MB | **Recommended** — best balance on most laptops |
| `small` | Moderate | Better | ~500 MB | More accurate, still usable on mid-range CPUs |
| `medium` | Slow | Very good | ~1.5 GB | Needs a decent CPU (i7 / Ryzen 7+) |
| `large` | Very slow | Best | ~3 GB | GPU recommended (`device: cuda`) |

**Recommended settings by hardware:**

```yaml
# Most laptops (default)
whisper:
  model_size: "base"
  device: "cpu"
  compute_type: "int8"

# Good CPU (i7 / Ryzen 7)
whisper:
  model_size: "small"
  device: "cpu"
  compute_type: "int8"

# Dedicated GPU (NVIDIA)
whisper:
  model_size: "large"
  device: "cuda"
  compute_type: "float16"
```

Models download automatically on first transcription via HuggingFace.

---

## Timezone

Set your timezone in `config.yaml` so all times (deadlines, reminders, transcripts, notes, briefings) are correct for your location.

```yaml
timezone: "Europe/Berlin"
```

Common examples:

| City | Timezone |
|------|---------|
| Berlin / Paris | `Europe/Berlin` |
| London | `Europe/London` |
| New York | `America/New_York` |
| Los Angeles | `America/Los_Angeles` |
| Dubai | `Asia/Dubai` |
| Karachi | `Asia/Karachi` |
| Mumbai | `Asia/Kolkata` |
| Singapore | `Asia/Singapore` |
| Tokyo | `Asia/Tokyo` |

Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

---

## Custom Sounds

Jarvis plays audio feedback at key moments (wake word, task saved, error, alarm, Pomodoro end).

All sound files live in `assets/sounds/`. The mapping is in `config.yaml → sounds`.

Chime sounds (`wake.mp3`, `done.mp3`, `error.mp3`, `alarm.mp3`) are **auto-generated** on first run as simple tones — no download needed.

For background study sounds, replace the placeholders with real audio:
- `lofi.mp3` / `rain.mp3` / `white_noise.mp3` — currently silent placeholders
- Download free music from [pixabay.com](https://pixabay.com) (no account needed, CC0 licensed)
- Or search YouTube for "lofi study music no copyright download"
- Any MP3 or WAV file works — just drop it in `assets/sounds/` with the same filename

To use your own sounds:
1. Drop `.mp3` or `.wav` files into `assets/sounds/`
2. Update the matching key in `config.yaml`:
   ```yaml
   sounds:
     wake_chime:  "assets/sounds/wake.mp3"
     error_chime: "assets/sounds/error.mp3"
     done_chime:  "assets/sounds/done.mp3"
     alarm:       "assets/sounds/alarm.mp3"
     volume:      0.7   # 0.0 to 1.0
   ```
3. Restart Jarvis — no other changes needed.

Free sounds: [freesound.org](https://freesound.org)

If a sound file is missing, Jarvis logs a warning and continues silently — it won't crash.

---

## Testing Before First Run

Before running Jarvis for real, verify everything works:

```
cd C:\Users\samai\Desktop\Jarvis\Jarvis
pytest tests/ -v
```

Or double-click `run_integration_test.bat`.

All tests should pass. If any fail, check the error output and fix before starting Jarvis.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Llama is offline" | Run `ollama serve` or check Task Scheduler |
| "I can't find your microphone" | Set `mic_device_index` in config.yaml |
| Wake word not triggering | Lower `wake_word_sensitivity` (e.g. 0.3) |
| TTS silent | Check system volume; edge-tts needs internet for first use, Piper is fully offline |
| JSON corrupt error | Jarvis auto-restores from `.bak` in backups/ |

## File Locations
- Config: `config.yaml`
- Personal data: `data/`
- Notes: `notes/`
- Memory: `memory/`
- Logs: `logs/jarvis.log`
- Conversations: `logs/conversations/`
- Backups: `backups/`
