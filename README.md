<div align="center">

# 🌸 Ranko — Discord Bot

**A self-hosted Discord bot with AI chat, music streaming, leveling, TTS, and a web dashboard.**  
Powered by [Ollama](https://ollama.com) · Built with [discord.py](https://discordpy.readthedocs.io) · Managed via Flask

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![Ollama](https://img.shields.io/badge/AI-Ollama-black?logo=ollama)](https://ollama.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

## ✨ Features

| Category | What Ranko can do |
|---|---|
| 🤖 **AI Chat** | Local LLM via Ollama with per-user memory, server personas, and voice responses |
| 🎵 **Music** | YouTube/URL streaming with queue, skip, pause, and interactive embed controls |
| 🗣️ **TTS** | Edge TTS voice synthesis — Ranko reads text aloud in your voice channel |
| 📈 **Leveling** | XP per message, level-up announcements, role rewards, and a leaderboard |
| 🛡️ **Moderation** | Kick, ban, clear, channel lock/unlock with audit logging |
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
git clone https://github.com/Romario-frog/ranko-discord-bot
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
RANKO_TTS_MAX_CHARS=250
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

## 🕹️ Commands

Ranko supports both the classic prefix `;;` and modern slash commands `/`.

### 🤖 AI

| Prefix | Slash | Description |
|---|---|---|
| `;;ai <prompt>` | `/ai <prompt>` | Ask the local AI. Responds in text and voice if you're in a VC |
| `;;persona [text]` | `/persona [text]` | View or set the server's AI system prompt *(Admin only)* |
| `;;forget` | `/forget` | Clear your personal AI memory buffer |
| `;;aimodel [name]` | — | Switch the active Ollama model globally |

### 🎵 Music

| Prefix | Slash | Description |
|---|---|---|
| `;;play <query/url>` | `/play <query/url>` | Stream a track by search or URL |
| `;;queue` | `/queue` | Show the current playback queue |
| `;;skip` | `/skip` | Skip to the next track |
| `;;pause` | `/pause` | Pause playback |
| `;;resume` | `/resume` | Resume a paused track |
| `;;stop` | `/stop` | Stop playback and clear the queue |
| `;;nowplaying` | `/nowplaying` | Show what's currently playing |
| `;;sayvc <text>` | `/sayvc <text>` | Speak text aloud via TTS in your voice channel |

### 📊 Leveling & Profiles

| Prefix | Slash | Description |
|---|---|---|
| `;;rank [@user]` | `/rank [@user]` | View a user's level, XP, and message count |
| `;;top` | `/top` | Show the server-wide XP leaderboard |
| `;;profile [@user]` | `/profile [@user]` | View a detailed profile card with banner |
| `;;setlevel <@user> <lvl>` | `/setlevel ...` | Manually set a user's level *(Level Admin only)* |

### 🛡️ Moderation

| Prefix | Slash | Description |
|---|---|---|
| `;;clear [amount]` | `/clear [amount]` | Delete up to 100 messages |
| `;;kick <@user> [reason]` | `/kick <@user>` | Remove a member from the server |
| `;;ban <@user> [reason]` | `/ban <@user>` | Ban a user from the server |
| `;;lock` | — | Lock all public channels (revoke send permissions) |
| `;;unlock` | — | Restore send permissions in locked channels |

### 🔧 Utility

| Prefix | Slash | Description |
|---|---|---|
| `;;serverinfo` | `/serverinfo` | Display server information |
| `;;avatar [@user]` | `/avatar [@user]` | Show a user's avatar |
| `;;botinfo` | `/botinfo` | Show Ranko's status and info |
| `;;lastvoice [@user]` | `/lastvoice [@user]` | Check when a user last joined a voice channel |
| `;;poll <question>` | — | Create a quick 👍/👎 poll |
| `;;coin` | — | Flip a coin |
| `;;roll [sides]` | — | Roll a dice (default: 6 sides) |

---

## 🖥️ Web Dashboard

The dashboard (`dashboard.py`) gives server admins a browser-based panel to control Ranko without using commands.

**Login options:**
- **Discord OAuth** — log in with your Discord account (requires `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET`)
- **Password** — use `ADMIN_PASSWORD` as a fallback

**What you can configure:**
- Bot prefix, AI model, and server persona
- XP settings: XP per message, level multiplier, level-up channel
- Role rewards at specific levels
- Commander roles, mod roles, and level admin roles
- Welcome roles for new members
- Log channel for audit events
- Per-user XP and level overrides

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
| `RANKO_TTS_MAX_CHARS` | `250` | Max characters per TTS request |

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `discord.py` | Discord bot framework |
| `Flask` | Web dashboard server |
| `ollama` | Local AI inference |
| `yt-dlp` | Audio extraction for music streaming |
| `edge-tts` | Text-to-speech synthesis |
| `python-dotenv` | Environment variable loading |
| `PyNaCl` | Voice channel encryption |

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.
