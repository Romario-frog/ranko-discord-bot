<div align="center">

# 🌸 Ranko — Discord Bot

**A self-hosted Discord bot with AI chat, music streaming, leveling, voice recognition, TTS, and a web dashboard.**  
Powered by [Ollama](https://ollama.com) · Built with [discord.py](https://discordpy.readthedocs.io) · Managed via Flask

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![Ollama](https://img.shields.io/badge/AI-Ollama-black?logo=ollama)](https://ollama.com)
[![Whisper](https://img.shields.io/badge/STT-faster--whisper-orange)](https://github.com/SYSTRAN/faster-whisper)

</div>

---

## ✨ Features

| Category | What Ranko can do |
|---|---|
| 🤖 **AI Chat** | Local LLM via Ollama with per-user memory, server personas, and voice responses |
| 🎙️ **Voice Recognition** | Listens to you in a VC, transcribes with Whisper, and replies via AI + TTS |
| 🗣️ **TTS** | Edge TTS voice synthesis — Ranko reads text aloud in your voice channel (no character limit) |
| 🎵 **Music** | YouTube/URL streaming with queue, skip, pause, and interactive embed controls |
| 📈 **Leveling** | XP per message, level-up announcements, role rewards, and a leaderboard |
| 🛡️ **Moderation** | Kick, ban, clear, slowmode, channel lock/unlock with audit logging |
| 🖥️ **Web Dashboard** | Flask panel to configure every setting — login via Discord OAuth or password |
| 🎨 **Profile Cards** | Rank cards with custom banner backgrounds and XP stats |
| 🔔 **Voice Tracking** | Logs when members join and leave voice channels |

---

## 🛠️ Installation

### Prerequisites

- **Python 3.10+**
- **FFmpeg** installed and available on your system `PATH`
- **Ollama** running locally — download from [ollama.com](https://ollama.com)

### 1. Clone & Install

```bash
git clone https://github.com/Romario-frog/ranko-discord-bot.git
cd ranko-discord-bot
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```env
# Discord
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CLIENT_ID=your_discord_application_client_id
DISCORD_CLIENT_SECRET=your_discord_application_client_secret
DISCORD_REDIRECT_URI=http://127.0.0.1:5000/oauth/callback

# Web Dashboard
FLASK_SECRET_KEY=some_long_random_secret_string
ADMIN_PASSWORD=your_dashboard_password
API_KEY=your_internal_api_key

# TTS (optional — these are the defaults)
RANKO_TTS_VOICE=ru-RU-DmitryNeural
RANKO_TTS_VOLUME=3.0
```

> **Tip:** Generate a secure secret key with `python -c "import secrets; print(secrets.token_hex(32))"`.

### 3. Pull the AI Model

Make sure Ollama is running, then pull the default model:

```bash
ollama pull qwen2.5:7b
```

---

## 🚀 Running Ranko

Start both processes in separate terminals:

```bash
# Terminal 1 — Discord bot
python bot.py

# Terminal 2 — Web dashboard
python dashboard.py
```

The dashboard will be available at **http://127.0.0.1:5000** by default.

---

## 🕹️ Full Command Reference

Ranko supports both the classic prefix `;;` and modern slash commands `/`.

---

### 🤖 AI

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;ai <prompt>` | `/ai` | — | Ask the local AI. Responds in text and voice if you're in a VC |
| `;;persona [text]` | `/persona` | — | View or set the server's AI system prompt *(Admin only)* |
| `;;forget` | `/forget` | — | Clear your personal AI memory buffer |
| `;;aimodel [name]` | — | — | Switch the active Ollama model globally *(Admin only)* |

---

### 🎙️ Voice Recognition

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;listen [seconds]` | `/listen` | `;;слушай` | Ranko records you for N seconds (default 5, max 30), transcribes with Whisper, then answers via AI + TTS |

> On first use, Whisper will automatically download the `small` model (~500 MB).

---

### 🗣️ TTS

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;sayvc <text>` | `/sayvc` | `;;tts`, `;;speak` | Speak text aloud via TTS in your voice channel |
| `;;say <text>` | — | — | Make Ranko send a plain text message *(Admin only)* |
| `;;embed <text>` | — | — | Make Ranko send a formatted embed message *(Admin only)* |

---

### 🎵 Music

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;play <query/url>` | `/play` | — | Stream a track by search or URL |
| `;;queue` | `/queue` | `;;q` | Show the current playback queue |
| `;;skip` | `/skip` | — | Skip to the next track |
| `;;pause` | `/pause` | — | Pause playback |
| `;;resume` | `/resume` | — | Resume a paused track |
| `;;stop` | `/stop` | — | Stop playback and clear the queue |
| `;;nowplaying` | `/nowplaying` | `;;np` | Show what's currently playing |
| `;;join` | `/join` | — | Join your voice channel |
| `;;jointo <channel>` | `/jointo` | `;;moveto`, `;;movevoice` | Move Ranko to a specific voice channel |
| `;;leave` | `/leave` | — | Leave the voice channel |

---

### 📊 Leveling & Profiles

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;rank [@user]` | `/rank` | — | View a user's level, XP, and message count |
| `;;top` | `/top` | — | Show the server-wide XP leaderboard |
| `;;profile [@user]` | `/profile` | — | View a detailed profile card with banner |
| `;;setlevel <@user> <lvl>` | `/setlevel` | — | Set a user's level *(Level Admin only)* |
| `;;addlevel <@user> <n>` | `/addlevel` | — | Add N levels to a user *(Level Admin only)* |
| `;;setxp <@user> <xp>` | `/setxp` | — | Set a user's XP directly *(Level Admin only)* |

---

### 🛡️ Moderation

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;clear [amount]` | `/clear` | — | Delete up to 100 messages (default 5) |
| `;;kick <@user> [reason]` | `/kick` | — | Remove a member from the server *(Commander only)* |
| `;;ban <@user> [reason]` | `/ban` | — | Ban a user from the server *(Commander only)* |
| `;;lock` | — | — | Lock all public channels (revoke send permissions) |
| `;;unlock` | — | — | Restore send permissions in locked channels |
| `;;slowmode [seconds]` | — | — | Set slowmode delay in the current channel |

---

### 🔧 Utility

| Command | Slash | Aliases | Description |
|---|---|---|---|
| `;;serverinfo` | `/serverinfo` | — | Display server information |
| `;;avatar [@user]` | `/avatar` | — | Show a user's avatar |
| `;;botinfo` | `/botinfo` | — | Show Ranko's status and info |
| `;;lastvoice [@user]` | `/lastvoice` | `;;voiceinfo` | Check when a user last joined a voice channel |
| `;;roles` | — | — | List all roles on the server |
| `;;myroles [@user]` | — | — | Show roles of a user |
| `;;poll <question>` | — | — | Create a quick 👍/👎 poll |
| `;;coin` | — | — | Flip a coin |
| `;;roll [sides]` | — | — | Roll a dice (default: 6 sides) |
| `;;ping` | `/ping` | — | Check Ranko's latency |
| `;;commands` | `/commands` | `;;help` | Show the command list |

---

## 🖥️ Web Dashboard

The dashboard (`dashboard.py`) gives server admins a browser-based panel to control Ranko without using commands.

**Login options:**
- **Discord OAuth** — log in with your Discord account
- **Password** — use `ADMIN_PASSWORD` as a fallback

**Pages:**
- **Dashboard** — main settings: prefix, server, welcome, XP, moderation, role rewards
- **Levels** — full leaderboard with inline level/XP editor
- **AI & Voice** (`/ai-settings`) — Ollama model, server persona, TTS voice, Whisper toggle
- **Commands** — full command reference with all categories
- **API Docs** — built-in REST API documentation

**What you can configure:**
- Bot prefix, AI model, and server persona prompt
- XP settings: XP per message, level multiplier, level-up channel
- Role rewards at specific levels
- Commander roles, mod roles, and level admin roles
- Welcome roles and welcome message for new members
- Log channel for audit events
- Per-user XP and level overrides
- TTS voice (Edge TTS), volume multiplier
- Toggle AI, leveling, moderation, voice recognition modules

---

## 🗂️ Project Structure

```
ranko-discord-bot/
├── bot.py              # Main Discord bot — all commands and event handlers
├── dashboard.py        # Flask web dashboard
├── storage.py          # JSON-based data layer (config, XP, levels, cache)
├── banner_utils.py     # Profile card and banner image generation
├── requirements.txt
├── assets/
│   └── banners/        # Background images for profile cards
├── static/             # Dashboard CSS, JS, and image assets
├── templates/          # Jinja2 HTML templates for the dashboard
└── generated_tts/      # Temporary TTS audio files (auto-cleaned)
```

---

## ⚙️ Configuration Reference

Key settings managed via the dashboard or `config.json`:

| Setting | Default | Description |
|---|---|---|
| `prefix` | `;;` | Command prefix |
| `ai_model` | `qwen2.5:7b` | Active Ollama model |
| `xp_per_message` | `10` | XP awarded per message |
| `level_multiplier` | `100` | XP required per level (`level × multiplier`) |
| `RANKO_TTS_VOICE` | `ru-RU-DmitryNeural` | Edge TTS voice name |
| `RANKO_TTS_VOLUME` | `3.0` | TTS output volume multiplier |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `discord.py` | Discord bot framework |
| `Flask` | Web dashboard server |
| `ollama` | Local AI inference |
| `yt-dlp` | Audio extraction for music streaming |
| `edge-tts` | Text-to-speech synthesis |
| `faster-whisper` | Local speech-to-text (voice recognition) |
| `python-dotenv` | Environment variable loading |
| `PyNaCl` | Voice channel encryption |
