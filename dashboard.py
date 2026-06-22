import os
import secrets
from urllib.parse import urlencode
from functools import wraps
from typing import Callable, List, Dict, Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session
from storage import (
    add_user_level,
    get_all_levels,
    get_stats,
    load_config,
    load_roles_cache,
    get_cached_guild,
    save_config,
    set_user_level,
    set_user_xp,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "ranko_dev_secret")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
API_KEY = os.getenv("API_KEY", "ranko_api_key_123")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_API = "https://discord.com/api/v10"
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:5000/oauth/callback")
DISCORD_OAUTH_SCOPES = "identify guilds"



def is_panel_user() -> bool:
    return bool(session.get("admin") or session.get("discord_admin"))


def login_required(func: Callable):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_panel_user():
            return redirect("/")
        return func(*args, **kwargs)
    return wrapper


def api_required(func: Callable):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if key != API_KEY:
            return jsonify({"ok": False, "error": "invalid_api_key"}), 401
        return func(*args, **kwargs)
    return wrapper


def _split_ids(value: str) -> List[str]:
    return [x.strip() for x in value.replace("\n", ",").split(",") if x.strip()]


def _multi_select_ids(form, key: str) -> List[str]:
    return [str(x).strip() for x in form.getlist(key) if str(x).strip()]


def parse_role_rewards(form) -> List[Dict[str, str]]:
    levels = form.getlist("reward_level")
    role_ids = form.getlist("reward_role_id")
    rewards = []
    for level, role_id in zip(levels, role_ids):
        level = str(level).strip()
        role_id = str(role_id).strip()
        if not level or not role_id:
            continue
        try:
            level_int = max(1, int(level))
        except ValueError:
            continue
        rewards.append({"level": level_int, "role_id": role_id})
    rewards.sort(key=lambda item: int(item["level"]))
    return rewards


def normalize_config_from_form(form) -> dict:
    config = load_config()
    config["bot_name"] = form.get("bot_name", "Ranko").strip() or "Ranko"
    config["prefix"] = form.get("prefix", ";;").strip() or ";;"
    config["guild_id"] = form.get("guild_id", "").strip()
    config["welcome_channel"] = form.get("welcome_channel", "general").strip() or "general"
    config["welcome_text"] = form.get("welcome_text", "")
    config["welcome_role_id"] = form.get("welcome_role_id", "").strip()
    config["log_channel"] = form.get("log_channel", "logs").strip() or "logs"
    config["xp_per_message"] = max(1, int(form.get("xp_per_message", 10)))
    config["level_multiplier"] = max(10, int(form.get("level_multiplier", 100)))
    config["welcome_enabled"] = "welcome_enabled" in form
    config["levels_enabled"] = "levels_enabled" in form
    config["moderation_enabled"] = "moderation_enabled" in form
    config["bot_owner_ids"] = _split_ids(form.get("bot_owner_ids", ""))
    config["commander_role_ids"] = _multi_select_ids(form, "commander_role_ids")
    config["level_admin_role_ids"] = _multi_select_ids(form, "level_admin_role_ids")
    config["role_rewards"] = parse_role_rewards(form)
    # AI
    config["ai_model"] = form.get("ai_model", "qwen2.5:7b").strip() or "qwen2.5:7b"
    config["ai_enabled"] = "ai_enabled" in form
    guild_id = form.get("guild_id", "").strip()
    persona = form.get("ai_persona", "").strip()
    if guild_id and persona:
        config[f"ai_persona_{guild_id}"] = persona
    # TTS / Voice
    config["tts_voice"] = form.get("tts_voice", "ru-RU-DmitryNeural").strip() or "ru-RU-DmitryNeural"
    try:
        config["tts_volume"] = max(0.1, min(10.0, float(form.get("tts_volume", 3.0))))
    except (ValueError, TypeError):
        config["tts_volume"] = 3.0
    config["listen_enabled"] = "listen_enabled" in form
    return config


def discord_headers() -> Dict[str, str]:
    return {"Authorization": f"Bot {DISCORD_TOKEN}"}


def get_cached_guilds() -> List[Dict[str, Any]]:
    return load_roles_cache().get("guilds", [])


def get_cached_roles(guild_id: str) -> List[Dict[str, Any]]:
    guild = get_cached_guild(str(guild_id))
    return guild.get("roles", []) if guild else []


def get_cached_channels(guild_id: str) -> List[Dict[str, Any]]:
    guild = get_cached_guild(str(guild_id))
    return guild.get("channels", []) if guild else []


def get_guild_roles(guild_id: str) -> List[Dict[str, Any]]:
    cached = get_cached_roles(guild_id)
    if cached:
        return cached
    if not DISCORD_TOKEN or not guild_id:
        return []
    try:
        response = requests.get(f"{DISCORD_API}/guilds/{guild_id}/roles", headers=discord_headers(), timeout=8)
        if response.status_code != 200:
            return []
        roles = response.json()
        roles = [r for r in roles if not r.get("managed") and r.get("name") != "@everyone"]
        roles.sort(key=lambda r: int(r.get("position", 0)), reverse=True)
        return [{"id": str(r["id"]), "name": r["name"], "position": r.get("position", 0), "color": str(r.get("color", ""))} for r in roles]
    except requests.RequestException:
        return []


def get_guild_channels(guild_id: str) -> List[Dict[str, Any]]:
    cached = get_cached_channels(guild_id)
    if cached:
        return cached
    if not DISCORD_TOKEN or not guild_id:
        return []
    try:
        response = requests.get(f"{DISCORD_API}/guilds/{guild_id}/channels", headers=discord_headers(), timeout=8)
        if response.status_code != 200:
            return []
        channels = response.json()
        channels = [c for c in channels if c.get("type") == 0]
        channels.sort(key=lambda c: int(c.get("position", 0)))
        return [{"id": str(c["id"]), "name": c["name"], "position": c.get("position", 0)} for c in channels]
    except requests.RequestException:
        return []



def oauth_enabled() -> bool:
    return bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI)


def guild_has_manage_permission(guild: Dict[str, Any]) -> bool:
    permissions = int(guild.get("permissions", 0) or 0)
    is_owner = bool(guild.get("owner"))
    has_admin = bool(permissions & 0x8)
    has_manage_guild = bool(permissions & 0x20)
    return is_owner or has_admin or has_manage_guild


def split_manageable_guilds(user_guilds: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cached = {str(g.get("id")): g for g in get_cached_guilds()}
    available: List[Dict[str, Any]] = []
    installable: List[Dict[str, Any]] = []

    for guild in user_guilds:
        if not guild_has_manage_permission(guild):
            continue

        item = {
            "id": str(guild.get("id", "")),
            "name": guild.get("name", "Unknown server"),
            "icon": guild.get("icon"),
        }

        if item["id"] in cached:
            item["name"] = cached[item["id"]].get("name", item["name"])
            available.append(item)
        else:
            installable.append(item)

    return available, installable

    for guild in user_guilds:
        guild_id = str(guild.get("id", ""))
        permissions = int(guild.get("permissions", 0) or 0)
        is_owner = bool(guild.get("owner"))

        # Discord permissions: ADMINISTRATOR = 0x8, MANAGE_GUILD = 0x20
        has_admin = bool(permissions & 0x8)
        has_manage_guild = bool(permissions & 0x20)

        if guild_id in cached_ids and (is_owner or has_admin or has_manage_guild):
            session["discord_guild_id"] = guild_id
            return True

    return False

@app.route("/", methods=["GET", "POST"])
def login():
    if is_panel_user():
        return redirect("/dashboard")

    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/dashboard")
        return render_template("login.html", error="Неверный пароль", oauth_enabled=oauth_enabled())

    return render_template("login.html", error=None, oauth_enabled=oauth_enabled())


@app.route("/oauth/login")
def oauth_login():
    if not oauth_enabled():
        return render_template(
            "login.html",
            error="Discord OAuth не настроен. Заполни DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET и DISCORD_REDIRECT_URI в .env.",
            oauth_enabled=False,
        )

    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": DISCORD_OAUTH_SCOPES,
        "state": state,
        "prompt": "none",
    }
    return redirect("https://discord.com/oauth2/authorize?" + urlencode(params))


@app.route("/oauth/callback")
def oauth_callback():
    if not oauth_enabled():
        return redirect("/")

    if request.args.get("state") != session.get("oauth_state"):
        return render_template("login.html", error="OAuth state не совпал. Попробуй снова.", oauth_enabled=oauth_enabled())

    code = request.args.get("code")
    if not code:
        return render_template("login.html", error="Discord не вернул code.", oauth_enabled=oauth_enabled())

    token_response = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )

    if token_response.status_code != 200:
        return render_template("login.html", error="Не удалось получить OAuth token от Discord.", oauth_enabled=oauth_enabled())

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return render_template("login.html", error="Discord OAuth token пустой.", oauth_enabled=oauth_enabled())

    user_headers = {"Authorization": f"Bearer {access_token}"}
    user_response = requests.get(f"{DISCORD_API}/users/@me", headers=user_headers, timeout=10)
    guilds_response = requests.get(f"{DISCORD_API}/users/@me/guilds", headers=user_headers, timeout=10)

    if user_response.status_code != 200 or guilds_response.status_code != 200:
        return render_template("login.html", error="Не удалось прочитать Discord профиль/серверы.", oauth_enabled=oauth_enabled())

    user = user_response.json()
    guilds = guilds_response.json()

    available_guilds, installable_guilds = split_manageable_guilds(guilds)

    session["discord_user"] = {
        "id": str(user.get("id", "")),
        "username": user.get("global_name") or user.get("username") or "Discord user",
        "avatar": user.get("avatar"),
    }
    session["available_guilds"] = available_guilds
    session["installable_guilds"] = installable_guilds

    if not available_guilds:
        return render_template(
            "server_select.html",
            available_guilds=[],
            installable_guilds=installable_guilds,
        )

    if len(available_guilds) == 1:
        guild_id = str(available_guilds[0]["id"])
        config = load_config()
        config["guild_id"] = guild_id
        save_config(config)
        session["discord_admin"] = True
        session["discord_guild_id"] = guild_id
        return redirect("/dashboard")

    return redirect("/select-server")




@app.route("/select-server")
def select_server_page():
    if not session.get("discord_user"):
        return redirect("/")
    return render_template(
        "server_select.html",
        available_guilds=session.get("available_guilds", []),
        installable_guilds=session.get("installable_guilds", []),
    )


@app.route("/select-server/<guild_id>")
def select_server(guild_id: str):
    available = session.get("available_guilds", [])
    if not any(str(g.get("id")) == str(guild_id) for g in available):
        return redirect("/select-server")

    config = load_config()
    config["guild_id"] = str(guild_id)
    save_config(config)

    session["discord_admin"] = True
    session["discord_guild_id"] = str(guild_id)
    return redirect("/dashboard")


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        config = normalize_config_from_form(request.form)
        save_config(config)
        return redirect("/dashboard?saved=1")

    config = load_config()
    cached_guilds = get_cached_guilds()
    if not str(config.get("guild_id", "")).strip() and len(cached_guilds) == 1:
        config["guild_id"] = str(cached_guilds[0]["id"])
        save_config(config)

    roles = get_guild_roles(str(config.get("guild_id", "")))
    channels = get_guild_channels(str(config.get("guild_id", "")))
    return render_template(
        "index.html",
        config=config,
        roles=roles,
        channels=channels,
        cached_guilds=cached_guilds,
        stats=get_stats(),
        saved=request.args.get("saved") == "1",
        discord_connected=bool(DISCORD_TOKEN),
    )


@app.route("/levels")
@login_required
def levels_page():
    return render_template("levels.html", levels=get_all_levels(100), stats=get_stats(), config=load_config())


@app.route("/levels/update", methods=["POST"])
@login_required
def levels_update():
    action = request.form.get("action", "setlevel")
    guild_id = request.form.get("guild_id", "").strip()
    user_id = request.form.get("user_id", "").strip()
    username = request.form.get("username", "User")
    value = int(request.form.get("value", 1))

    if not guild_id or not user_id:
        return redirect("/levels?error=missing")

    if action == "setxp":
        set_user_xp(guild_id, user_id, username, value)
    elif action == "addlevel":
        add_user_level(guild_id, user_id, username, value)
    else:
        set_user_level(guild_id, user_id, username, value)

    return redirect("/levels?saved=1")


@app.route("/commands")
@login_required
def commands_page():
    return render_template("commands.html", config=load_config())


@app.route("/api-docs")
@login_required
def api_docs():
    return render_template("api_docs.html")


@app.route("/user-login")
def user_login():
    session["user_demo"] = True
    return redirect("/user")


@app.route("/user")
def user_page():
    config = load_config()
    return render_template("user.html", config=config, stats=get_stats(), levels=get_all_levels(10))


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")



@app.route("/dashboard/autosave", methods=["POST"])
@login_required
def dashboard_autosave():
    config = normalize_config_from_form(request.form)
    save_config(config)
    return jsonify({"ok": True, "message": "saved"})


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "name": "Ranko API"})


@app.route("/api/config", methods=["GET"])
@api_required
def api_get_config():
    return jsonify({"ok": True, "config": load_config()})


@app.route("/api/config", methods=["PUT", "POST"])
@api_required
def api_update_config():
    data = request.get_json(silent=True) or {}
    config = load_config()

    allowed = {
        "bot_name",
        "prefix",
        "guild_id",
        "welcome_enabled",
        "welcome_channel",
        "welcome_text",
        "welcome_role_id",
        "levels_enabled",
        "xp_per_message",
        "level_multiplier",
        "moderation_enabled",
        "log_channel",
        "bot_owner_ids",
        "commander_role_ids",
        "level_admin_role_ids",
        "role_rewards",
        "ai_model",
        "ai_enabled",
        "listen_enabled",
        "tts_voice",
        "tts_volume",
    }

    for key, value in data.items():
        if key in allowed:
            config[key] = value

    config = save_config(config)
    return jsonify({"ok": True, "config": config})


@app.route("/api/levels")
@api_required
def api_levels():
    limit = request.args.get("limit", 100, type=int)
    limit = max(1, min(limit, 500))
    return jsonify({"ok": True, "levels": get_all_levels(limit)})


@app.route("/api/stats")
@api_required
def api_stats():
    return jsonify({"ok": True, "stats": get_stats()})


@app.route("/api/levels/reset", methods=["POST"])
@api_required
def api_reset_level():
    data = request.get_json(silent=True) or {}
    guild_id = str(data.get("guild_id", "")).strip()
    user_id = str(data.get("user_id", "")).strip()
    if not guild_id or not user_id:
        return jsonify({"ok": False, "error": "guild_id and user_id required"}), 400
    set_user_level(guild_id, user_id, data.get("username", "User"), 0)
    set_user_xp(guild_id, user_id, data.get("username", "User"), 0)
    return jsonify({"ok": True})


@app.route("/api/ai-config", methods=["GET"])
@api_required
def api_ai_config():
    config = load_config()
    return jsonify({
        "ok": True,
        "ai_model": config.get("ai_model", "qwen2.5:7b"),
        "ai_enabled": config.get("ai_enabled", True),
        "listen_enabled": config.get("listen_enabled", True),
        "tts_voice": config.get("tts_voice", "ru-RU-DmitryNeural"),
        "tts_volume": config.get("tts_volume", 3.0),
    })


@app.route("/ai-settings")
@login_required
def ai_settings_page():
    config = load_config()
    guild_id = str(config.get("guild_id", ""))
    persona_key = f"ai_persona_{guild_id}" if guild_id else None
    persona = config.get(persona_key, "Ты — полезный голосовой ассистент Ranko.") if persona_key else ""
    return render_template("ai_settings.html", config=config, persona=persona, stats=get_stats())


@app.route("/ai-settings", methods=["POST"])
@login_required
def ai_settings_save():
    config = normalize_config_from_form(request.form)
    save_config(config)
    return redirect("/ai-settings?saved=1")


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
