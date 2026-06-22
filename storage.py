import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "ranko.db")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ROLES_CACHE_FILE = os.path.join(BASE_DIR, "roles_cache.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "bot_name": "Ranko",
    "prefix": ";;",
    "guild_id": "",
    "welcome_enabled": True,
    "welcome_channel": "general",
    "welcome_text": "Добро пожаловать на сервер, {user}!",
    "welcome_role_id": "",
    "levels_enabled": True,
    "xp_per_message": 10,
    "level_multiplier": 100,
    "moderation_enabled": True,
    "log_channel": "logs",
    "bot_owner_ids": [],
    "commander_role_ids": [],
    "level_admin_role_ids": [],
    "role_rewards": [],
    "public_user_page_enabled": True,
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS levels (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                messages INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_activity (
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                last_joined_at TEXT,
                last_left_at TEXT,
                last_channel_id TEXT,
                last_channel_name TEXT,
                current_channel_id TEXT,
                current_channel_name TEXT,
                total_sessions INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        conn.commit()

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(DEFAULT_CONFIG, file, indent=2, ensure_ascii=False)

    current = load_config(skip_init=True)
    if not current:
        save_config(DEFAULT_CONFIG)


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def load_config(skip_init: bool = False) -> Dict[str, Any]:
    if not skip_init and not os.path.exists(DB_FILE):
        init_db()

    config = DEFAULT_CONFIG.copy()

    if os.path.exists(DB_FILE):
        with get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
        if rows:
            row_keys = {row["key"] for row in rows}
            for row in rows:
                config[row["key"]] = _parse_value(row["value"])
            if any(key not in row_keys for key in DEFAULT_CONFIG):
                save_config(config)
            return config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            file_config = json.load(file)
            config.update(file_config)
    except FileNotFoundError:
        pass

    if not skip_init:
        save_config(config)
    return config


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)

    with get_connection() as conn:
        for key, value in merged.items():
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        conn.commit()

    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(merged, file, indent=2, ensure_ascii=False)

    return merged


def load_roles_cache() -> Dict[str, Any]:
    try:
        with open(ROLES_CACHE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"guilds": []}


def save_roles_cache(guilds: List[Dict[str, Any]]) -> None:
    data = {"guilds": guilds}
    with open(ROLES_CACHE_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def get_cached_guild(guild_id: str) -> Optional[Dict[str, Any]]:
    for guild in load_roles_cache().get("guilds", []):
        if str(guild.get("id")) == str(guild_id):
            return guild
    return None


def add_xp(guild_id: int, user_id: int, username: str, xp_amount: int, multiplier: int) -> Dict[str, Any]:
    guild = str(guild_id)
    user = str(user_id)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild, user),
        ).fetchone()

        if row is None:
            xp = xp_amount
            level = 1
            messages = 1
            leveled_up = False
        else:
            xp = int(row["xp"]) + xp_amount
            level = int(row["level"])
            messages = int(row["messages"]) + 1
            leveled_up = False

        needed_xp = max(1, level * int(multiplier))
        if xp >= needed_xp:
            level += 1
            xp = 0
            leveled_up = True

        conn.execute(
            """
            INSERT OR REPLACE INTO levels
            (guild_id, user_id, username, xp, level, messages)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild, user, username, xp, level, messages),
        )
        conn.commit()

    return {
        "guild_id": guild,
        "user_id": user,
        "username": username,
        "xp": xp,
        "level": level,
        "messages": messages,
        "leveled_up": leveled_up,
    }


def set_user_level(guild_id: int | str, user_id: int | str, username: str, level: int, xp: Optional[int] = None) -> Dict[str, Any]:
    guild = str(guild_id)
    user = str(user_id)
    level = max(1, int(level))
    xp_value = 0 if xp is None else max(0, int(xp))

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild, user),
        ).fetchone()
        messages = int(row["messages"]) if row else 0
        if xp is None and row:
            xp_value = int(row["xp"])
        conn.execute(
            """
            INSERT OR REPLACE INTO levels
            (guild_id, user_id, username, xp, level, messages)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild, user, username, xp_value, level, messages),
        )
        conn.commit()

    return {"guild_id": guild, "user_id": user, "username": username, "xp": xp_value, "level": level, "messages": messages}


def add_user_level(guild_id: int | str, user_id: int | str, username: str, amount: int) -> Dict[str, Any]:
    current = get_rank(int(guild_id), int(user_id)) if str(guild_id).isdigit() and str(user_id).isdigit() else None
    current_level = int(current["level"]) if current else 1
    return set_user_level(guild_id, user_id, username, current_level + int(amount))


def set_user_xp(guild_id: int | str, user_id: int | str, username: str, xp: int) -> Dict[str, Any]:
    current = get_rank(int(guild_id), int(user_id)) if str(guild_id).isdigit() and str(user_id).isdigit() else None
    level = int(current["level"]) if current else 1
    return set_user_level(guild_id, user_id, username, level, xp=max(0, int(xp)))


def get_rank(guild_id: int, user_id: int) -> Dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return dict(row) if row else None


def get_top(guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM levels
            WHERE guild_id = ?
            ORDER BY level DESC, xp DESC, messages DESC
            LIMIT ?
            """,
            (str(guild_id), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_levels(limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM levels
            ORDER BY level DESC, xp DESC, messages DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_stats() -> Dict[str, Any]:
    with get_connection() as conn:
        users = conn.execute("SELECT COUNT(*) AS count FROM levels").fetchone()["count"]
        messages = conn.execute("SELECT COALESCE(SUM(messages), 0) AS total FROM levels").fetchone()["total"]
        avg_level = conn.execute("SELECT COALESCE(AVG(level), 0) AS avg FROM levels").fetchone()["avg"]
    return {"tracked_users": users, "tracked_messages": messages, "average_level": round(float(avg_level), 2)}


def add_audit(action: str, details: str) -> None:
    with get_connection() as conn:
        conn.execute("INSERT INTO audit_log (action, details) VALUES (?, ?)", (action, details))
        conn.commit()


def record_voice_join(
    guild_id: int | str,
    user_id: int | str,
    username: str,
    channel_id: int | str,
    channel_name: str,
    joined_at: str,
) -> None:
    guild = str(guild_id)
    user = str(user_id)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT total_sessions FROM voice_activity WHERE guild_id = ? AND user_id = ?",
            (guild, user),
        ).fetchone()
        total = int(row["total_sessions"]) + 1 if row else 1

        conn.execute(
            """
            INSERT OR REPLACE INTO voice_activity
            (guild_id, user_id, username, last_joined_at, last_left_at, last_channel_id, last_channel_name,
             current_channel_id, current_channel_name, total_sessions)
            VALUES (?, ?, ?, ?, COALESCE((SELECT last_left_at FROM voice_activity WHERE guild_id = ? AND user_id = ?), NULL),
                    ?, ?, ?, ?, ?)
            """,
            (
                guild,
                user,
                username,
                joined_at,
                guild,
                user,
                str(channel_id),
                channel_name,
                str(channel_id),
                channel_name,
                total,
            ),
        )
        conn.commit()


def record_voice_leave(
    guild_id: int | str,
    user_id: int | str,
    username: str,
    left_at: str,
) -> None:
    guild = str(guild_id)
    user = str(user_id)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM voice_activity WHERE guild_id = ? AND user_id = ?",
            (guild, user),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT OR REPLACE INTO voice_activity
                (guild_id, user_id, username, last_left_at, current_channel_id, current_channel_name, total_sessions)
                VALUES (?, ?, ?, ?, NULL, NULL, 0)
                """,
                (guild, user, username, left_at),
            )
        else:
            conn.execute(
                """
                UPDATE voice_activity
                SET username = ?, last_left_at = ?, current_channel_id = NULL, current_channel_name = NULL
                WHERE guild_id = ? AND user_id = ?
                """,
                (username, left_at, guild, user),
            )
        conn.commit()


def get_voice_activity(guild_id: int | str, user_id: int | str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM voice_activity WHERE guild_id = ? AND user_id = ?",
            (str(guild_id), str(user_id)),
        ).fetchone()
    return dict(row) if row else None



init_db()
