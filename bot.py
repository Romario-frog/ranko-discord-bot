import os
import asyncio
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp
import ollama

from storage import (
    add_audit,
    add_user_level,
    add_xp,
    get_rank,
    get_top,
    load_config,
    save_config,
    save_roles_cache,
    record_voice_join,
    record_voice_leave,
    get_voice_activity,
    set_user_level,
    set_user_xp,
)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не найден. Переименуй .env.example в .env и вставь токен бота.")


def get_prefix(bot: commands.Bot, message: discord.Message):
    config = load_config()
    return config.get("prefix", ";;")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)
_synced_once = False


def _ids(values: Iterable) -> List[str]:
    return [str(v).strip() for v in values if str(v).strip()]


def member_has_any_role(member: discord.Member, role_ids: Iterable) -> bool:
    wanted = set(_ids(role_ids))
    if not wanted:
        return False
    return any(str(role.id) in wanted for role in member.roles)


def is_global_ranko_admin(member: discord.Member) -> bool:
    """Optional global access for the person who hosts Ranko."""
    config = load_config()
    owner_ids = set(_ids(config.get("bot_owner_ids", [])))
    return str(member.id) in owner_ids


def has_server_admin_power(member: discord.Member) -> bool:
    """Server-side admin logic, similar to public Discord bots."""
    if member.guild and member.guild.owner_id == member.id:
        return True

    perms = getattr(member, "guild_permissions", None)
    if not perms:
        return False

    return bool(perms.administrator or perms.manage_guild)


def can_use_mod_command(member: discord.Member) -> bool:
    config = load_config()
    return (
        is_global_ranko_admin(member)
        or has_server_admin_power(member)
        or member_has_any_role(member, config.get("commander_role_ids", []))
    )


def can_manage_levels(member: discord.Member) -> bool:
    config = load_config()
    return (
        is_global_ranko_admin(member)
        or has_server_admin_power(member)
        or member_has_any_role(member, config.get("level_admin_role_ids", []))
    )


async def send_log(guild: discord.Guild, text: str) -> None:
    config = load_config()
    channel_name = config.get("log_channel", "logs")
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if channel:
        await channel.send(text)


def guild_to_cache(guild: discord.Guild) -> dict:
    roles = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if role.name == "@everyone" or role.managed:
            continue
        roles.append({
            "id": str(role.id),
            "name": role.name,
            "position": role.position,
            "color": str(role.color),
        })

    channels = []
    for channel in sorted(guild.text_channels, key=lambda c: c.position):
        channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "position": channel.position,
        })

    return {
        "id": str(guild.id),
        "name": guild.name,
        "roles": roles,
        "channels": channels,
    }


def update_roles_cache() -> None:
    guilds = [guild_to_cache(guild) for guild in bot.guilds]
    save_roles_cache(guilds)

    # Если бот стоит только на одном сервере, Ranko сам подставит Guild ID для сайта.
    config = load_config()
    if not str(config.get("guild_id", "")).strip() and len(guilds) == 1:
        config["guild_id"] = guilds[0]["id"]
        save_config(config)


async def apply_role_rewards(member: discord.Member, level: int, exact_only: bool = True) -> List[str]:
    """Выдать роли за уровни. exact_only=True — только за достигнутый уровень."""
    config = load_config()
    rewards = config.get("role_rewards", []) or []
    given = []

    for reward in rewards:
        try:
            reward_level = int(reward.get("level", 0))
            role_id = int(reward.get("role_id", 0))
        except (TypeError, ValueError):
            continue

        if exact_only and level != reward_level:
            continue
        if not exact_only and level < reward_level:
            continue

        role = member.guild.get_role(role_id)
        if role and role not in member.roles:
            try:
                await member.add_roles(role, reason=f"Ranko role reward level {reward_level}")
                given.append(role.name)
            except discord.Forbidden:
                given.append(f"{role.name} (не выдалась: роль Ranko ниже этой роли)")
            except discord.HTTPException:
                given.append(f"{role.name} (ошибка Discord)")

    return given



MUSIC_YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "default_search": "auto",
}
MUSIC_FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
music_now_playing: dict[int, dict] = {}
music_queues: dict[int, list[dict]] = {}
music_messages: dict[int, discord.Message] = {}

ai_user_memory: dict[int, list[dict]] = {}

TTS_DIR = Path(__file__).resolve().parent / "generated_tts"
TTS_DEFAULT_VOICE = os.getenv("RANKO_TTS_VOICE", "ru-RU-DmitryNeural")
TTS_MAX_CHARS = int(os.getenv("RANKO_TTS_MAX_CHARS", "250"))
TTS_VOLUME = float(os.getenv("RANKO_TTS_VOLUME", "3.0"))
TTS_FFMPEG_OPTIONS = {"options": f"-vn -filter:a volume={TTS_VOLUME}"}



def clean_tts_text(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS].rstrip() + "..."
    return text


async def make_tts_file(text: str, guild_id: int, voice_name: str | None = None) -> Path:
    import edge_tts

    TTS_DIR.mkdir(exist_ok=True)
    safe_text = clean_tts_text(text)
    if not safe_text:
        raise ValueError("Пустой текст.")

    out = TTS_DIR / f"ranko_tts_{guild_id}_{uuid.uuid4().hex}.mp3"
    communicate = edge_tts.Communicate(safe_text, voice_name or TTS_DEFAULT_VOICE)
    await communicate.save(str(out))
    return out


async def speak_in_voice(ctx: commands.Context, text: str):
    voice = await get_existing_or_author_voice(ctx)
    if not voice:
        return

    if voice.is_playing() or voice.is_paused():
        await ctx.send("❌ Сейчас уже играет музыка/голос. Напиши `;;stop` или дождись окончания.")
        return

    msg = await ctx.send("🗣️ Готовлю голос...")
    try:
        audio_path = await make_tts_file(text, ctx.guild.id)
    except Exception as exc:
        await msg.edit(content=f"❌ Не смог создать голос: `{exc}`")
        return

    def after_tts(error):
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        if error:
            print(f"Ranko TTS error: {error}")

    try:
        source = discord.FFmpegPCMAudio(str(audio_path), **TTS_FFMPEG_OPTIONS)
        voice.play(source, after=after_tts)
    except Exception as exc:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        await msg.edit(content=f"❌ Не смог озвучить текст: `{exc}`")
        return

    await msg.edit(content=f"🗣️ Ranko говорит в **{voice.channel.name}**: **{clean_tts_text(text)}**")


async def speak_in_voice_interaction(interaction: discord.Interaction, text: str):
    voice = await get_existing_or_author_voice_interaction(interaction)
    if not voice:
        return

    if voice.is_playing() or voice.is_paused():
        await interaction.followup.send("❌ Сейчас уже играет музыка/голос. Используй `/stop` или дождись окончания.", ephemeral=True)
        return

    try:
        audio_path = await make_tts_file(text, interaction.guild.id)
    except Exception as exc:
        await interaction.followup.send(f"❌ Не смог создать голос: `{exc}`", ephemeral=True)
        return

    def after_tts(error):
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        if error:
            print(f"Ranko TTS error: {error}")

    try:
        source = discord.FFmpegPCMAudio(str(audio_path), **TTS_FFMPEG_OPTIONS)
        voice.play(source, after=after_tts)
    except Exception as exc:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        await interaction.followup.send(f"❌ Не смог озвучить текст: `{exc}`", ephemeral=True)
        return

    await interaction.followup.send(f"🗣️ Ranko говорит в **{voice.channel.name}**: **{clean_tts_text(text)}**")


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "??:??"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def queue_for(guild_id: int) -> list[dict]:
    return music_queues.setdefault(int(guild_id), [])


def make_music_embed(guild_id: int, title: str = "🎵 Ranko Music") -> discord.Embed:
    current = music_now_playing.get(int(guild_id))
    queue = queue_for(int(guild_id))

    embed = discord.Embed(title=title, color=discord.Color.blurple())

    if current:
        duration = format_duration(current.get("duration"))
        requested_by = current.get("requested_by_mention", "неизвестно")
        desc = f"**{current.get('title', 'Unknown track')}**\n⏱️ `{duration}` · 👤 {requested_by}"
        if current.get("webpage_url"):
            desc += f"\n🔗 {current.get('webpage_url')}"
        embed.description = desc
    else:
        embed.description = "Сейчас ничего не играет."

    if queue:
        lines = []
        for idx, item in enumerate(queue[:10], start=1):
            lines.append(f"`{idx}.` {item.get('title', 'Unknown track')} · `{format_duration(item.get('duration'))}`")
        extra = "" if len(queue) <= 10 else f"\n…и ещё **{len(queue) - 10}**"
        embed.add_field(name=f"📜 Очередь ({len(queue)})", value="\n".join(lines) + extra, inline=False)
    else:
        embed.add_field(name="📜 Очередь", value="Пусто", inline=False)

    embed.set_footer(text="Кнопки: ⏸️ пауза · ▶️ продолжить · ⏭️ скип · ⏹️ стоп · 📜 очередь")
    return embed


class MusicControlView(discord.ui.View):
    def __init__(self, timeout: float | None = 900):
        super().__init__(timeout=timeout)

    async def _voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_connected():
            await interaction.response.send_message("❌ Ranko сейчас не в голосовом канале.", ephemeral=True)
            return None
        return voice

    @discord.ui.button(emoji="⏸️", label="Pause", style=discord.ButtonStyle.secondary)
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self._voice(interaction)
        if not voice:
            return
        if voice.is_playing():
            voice.pause()
            await interaction.response.send_message("⏸️ Пауза.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Сейчас музыка не играет.", ephemeral=True)

    @discord.ui.button(emoji="▶️", label="Resume", style=discord.ButtonStyle.success)
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self._voice(interaction)
        if not voice:
            return
        if voice.is_paused():
            voice.resume()
            await interaction.response.send_message("▶️ Продолжаю.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Музыка не на паузе.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", label="Skip", style=discord.ButtonStyle.primary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self._voice(interaction)
        if not voice:
            return
        if voice.is_playing() or voice.is_paused():
            voice.stop()
            await interaction.response.send_message("⏭️ Скипаю трек.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Сейчас ничего не играет.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice = await self._voice(interaction)
        if not voice:
            return
        queue_for(interaction.guild.id).clear()
        music_now_playing.pop(interaction.guild.id, None)
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await update_music_message(interaction.guild.id)
        await interaction.response.send_message("⏹️ Музыка остановлена, очередь очищена.", ephemeral=True)

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=make_music_embed(interaction.guild.id, "📜 Очередь Ranko"), ephemeral=True)


async def update_music_message(guild_id: int):
    message = music_messages.get(int(guild_id))
    if not message:
        return
    try:
        await message.edit(embed=make_music_embed(int(guild_id)), view=MusicControlView())
    except Exception:
        pass


async def play_next_track(guild: discord.Guild, text_channel: discord.TextChannel | None = None):
    voice = guild.voice_client
    if not voice or not voice.is_connected():
        music_now_playing.pop(guild.id, None)
        return

    queue = queue_for(guild.id)
    if not queue:
        music_now_playing.pop(guild.id, None)
        await update_music_message(guild.id)
        return

    track = queue.pop(0)
    music_now_playing[guild.id] = track

    def after_play(error):
        if error:
            print(f"Ranko music player error: {error}")
        future = asyncio.run_coroutine_threadsafe(play_next_track(guild, text_channel), bot.loop)
        try:
            future.result()
        except Exception as exc:
            print(f"Ranko music next track error: {exc}")

    try:
        source = discord.FFmpegPCMAudio(track["url"], **MUSIC_FFMPEG_OPTIONS)
        voice.play(source, after=after_play)
    except Exception as exc:
        if text_channel:
            await text_channel.send(f"❌ Не смог запустить трек: `{exc}`")
        await play_next_track(guild, text_channel)
        return

    if text_channel:
        embed = make_music_embed(guild.id)
        view = MusicControlView()
        old_message = music_messages.get(guild.id)
        try:
            if old_message:
                await old_message.edit(embed=embed, view=view)
            else:
                music_messages[guild.id] = await text_channel.send(embed=embed, view=view)
        except Exception:
            music_messages[guild.id] = await text_channel.send(embed=embed, view=view)


async def add_track_to_queue(ctx: commands.Context, query: str):
    voice = await get_existing_or_author_voice(ctx)
    if not voice:
        return

    msg = await ctx.send("🔎 Ищу аудио...")
    try:
        info = await extract_audio_info(query)
    except Exception as exc:
        await msg.edit(content=f"❌ Не смог получить аудио: `{exc}`")
        return

    if not info.get("url"):
        await msg.edit(content="❌ Не нашёл прямой аудиопоток.")
        return

    info["requested_by_id"] = str(ctx.author.id)
    info["requested_by_mention"] = ctx.author.mention

    queue_for(ctx.guild.id).append(info)

    if voice.is_playing() or voice.is_paused() or music_now_playing.get(ctx.guild.id):
        await msg.edit(content=f"➕ Добавил в очередь: **{info.get('title', 'Unknown track')}**")
        await update_music_message(ctx.guild.id)
    else:
        await msg.edit(content=f"▶️ Запускаю: **{info.get('title', 'Unknown track')}**")
        await play_next_track(ctx.guild, ctx.channel)


async def add_track_to_queue_interaction(interaction: discord.Interaction, query: str):
    voice = await get_existing_or_author_voice_interaction(interaction)
    if not voice:
        return

    try:
        info = await extract_audio_info(query)
    except Exception as exc:
        await interaction.followup.send(f"❌ Не смог получить аудио: `{exc}`")
        return

    if not info.get("url"):
        await interaction.followup.send("❌ Не нашёл прямой аудиопоток.")
        return

    info["requested_by_id"] = str(interaction.user.id)
    info["requested_by_mention"] = interaction.user.mention

    queue_for(interaction.guild.id).append(info)

    if voice.is_playing() or voice.is_paused() or music_now_playing.get(interaction.guild.id):
        await interaction.followup.send(f"➕ Добавил в очередь: **{info.get('title', 'Unknown track')}**")
        await update_music_message(interaction.guild.id)
    else:
        await interaction.followup.send(f"▶️ Запускаю: **{info.get('title', 'Unknown track')}**")
        await play_next_track(interaction.guild, interaction.channel)



async def get_existing_or_author_voice(ctx: commands.Context) -> discord.VoiceClient | None:
    """Если Ranko уже сидит в каком-то голосовом канале — оставляем его там.
    Если Ranko нигде не сидит — заходим в голосовой канал автора команды.
    """
    voice = ctx.guild.voice_client if ctx.guild else None
    if voice and voice.is_connected():
        return voice
    return await ensure_voice(ctx)


async def get_existing_or_author_voice_interaction(interaction: discord.Interaction) -> discord.VoiceClient | None:
    """Slash-версия: если Ranko уже в голосовом — оставляем его там."""
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice and voice.is_connected():
        return voice
    return await ensure_voice_interaction(interaction)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_dt(value: Optional[str]) -> str:
    if not value:
        return "нет данных"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        return value


async def extract_audio_info(query: str) -> dict:
    loop = asyncio.get_running_loop()

    def _extract():
        with yt_dlp.YoutubeDL(MUSIC_YTDL_OPTIONS) as ytdl:
            info = ytdl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return {
                "title": info.get("title", "Unknown track"),
                "url": info.get("url"),
                "webpage_url": info.get("webpage_url", query),
                "duration": info.get("duration"),
            }

    return await loop.run_in_executor(None, _extract)



def find_voice_channel(guild: discord.Guild, query: str) -> discord.VoiceChannel | None:
    query = (query or "").strip()
    if not query:
        return None

    # Mention format: <#123456789>
    match = re.search(r"\d{15,25}", query)
    if match:
        channel = guild.get_channel(int(match.group(0)))
        if isinstance(channel, discord.VoiceChannel):
            return channel

    lowered = query.lower()
    for channel in guild.voice_channels:
        if channel.name.lower() == lowered:
            return channel

    for channel in guild.voice_channels:
        if lowered in channel.name.lower():
            return channel

    return None


async def connect_to_voice_channel(ctx: commands.Context, channel: discord.VoiceChannel) -> discord.VoiceClient | None:
    permissions = channel.permissions_for(ctx.guild.me)
    if not permissions.view_channel or not permissions.connect:
        await ctx.send(f"❌ У Ranko нет прав зайти в **{channel.name}**. Нужны View Channel и Connect.")
        return None
    if not permissions.speak:
        await ctx.send(f"❌ У Ranko нет права Speak в **{channel.name}**.")
        return None

    voice = ctx.guild.voice_client
    try:
        if voice and voice.is_connected():
            await voice.move_to(channel)
        else:
            voice = await channel.connect()
    except discord.Forbidden:
        await ctx.send(f"❌ Discord не разрешил зайти в **{channel.name}**. Проверь права канала.")
        return None
    except Exception as exc:
        await ctx.send(f"❌ Не смог зайти в **{channel.name}**: `{exc}`")
        return None

    return voice


async def connect_to_voice_channel_interaction(interaction: discord.Interaction, channel: discord.VoiceChannel) -> discord.VoiceClient | None:
    permissions = channel.permissions_for(interaction.guild.me)
    if not permissions.view_channel or not permissions.connect:
        await interaction.followup.send(f"❌ У Ranko нет прав зайти в **{channel.name}**. Нужны View Channel и Connect.", ephemeral=True)
        return None
    if not permissions.speak:
        await interaction.followup.send(f"❌ У Ranko нет права Speak в **{channel.name}**.", ephemeral=True)
        return None

    voice = interaction.guild.voice_client
    try:
        if voice and voice.is_connected():
            await voice.move_to(channel)
        else:
            voice = await channel.connect()
    except discord.Forbidden:
        await interaction.followup.send(f"❌ Discord не разрешил зайти в **{channel.name}**. Проверь права канала.", ephemeral=True)
        return None
    except Exception as exc:
        await interaction.followup.send(f"❌ Не смог зайти в **{channel.name}**: `{exc}`", ephemeral=True)
        return None

    return voice


async def ensure_voice(ctx: commands.Context) -> discord.VoiceClient | None:
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ Сначала зайди в голосовой канал.")
        return None

    channel = ctx.author.voice.channel
    voice = ctx.guild.voice_client

    if voice and voice.is_connected():
        if voice.channel != channel:
            await voice.move_to(channel)
    else:
        voice = await channel.connect()

    return voice



async def ensure_voice_interaction(interaction: discord.Interaction) -> discord.VoiceClient | None:
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
        await interaction.followup.send("❌ Сначала зайди в голосовой канал.", ephemeral=True)
        return None

    channel = member.voice.channel
    voice = interaction.guild.voice_client

    if voice and voice.is_connected():
        if voice.channel != channel:
            await voice.move_to(channel)
    else:
        voice = await channel.connect()

    return voice


def commands_embed(prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="🤖 Ranko команды",
        description="Пиши `/`, чтобы Discord показал slash-подсказки Ranko. Prefix-команды тоже работают через `" + prefix + "`.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name=f"{prefix}ping / /ping", value="Проверка работы", inline=False)
    embed.add_field(name=f"{prefix}rank [@user] / /rank", value="Показать уровень", inline=False)
    embed.add_field(name=f"{prefix}top / /top", value="Топ пользователей", inline=False)
    embed.add_field(name=f"{prefix}userinfo [@user]", value="Информация о пользователе", inline=False)
    embed.add_field(name=f"{prefix}serverinfo / {prefix}botinfo", value="Информация о сервере и Ranko", inline=False)
    embed.add_field(name=f"{prefix}clear 10 / {prefix}kick / {prefix}ban", value="Модерация. Доступ: серверный админ или роль-командер", inline=False)
    embed.add_field(name=f"{prefix}setlevel / {prefix}addlevel / {prefix}setxp", value="Уровни. Доступ: серверный админ или level-manager роль", inline=False)
    embed.add_field(name=f"{prefix}join / /join", value="Зайти в твой голосовой канал", inline=False)
    embed.add_field(name=f"{prefix}play <url or search> / /play", value="Играть музыку по ссылке или поиску. Используй только разрешённый контент.", inline=False)
    embed.add_field(name=f"{prefix}pause / {prefix}resume / {prefix}skip / {prefix}stop", value="Управление музыкой", inline=False)
    embed.add_field(name=f"{prefix}nowplaying / {prefix}np", value="Что сейчас играет", inline=False)
    embed.add_field(name=f"{prefix}lastvoice @user / /lastvoice", value="Когда пользователь последний раз заходил в голосовой канал", inline=False)
    return embed


@bot.event
async def on_ready():
    global _synced_once
    config = load_config()
    print(f"{config.get('bot_name', 'Ranko')} запущен как {bot.user}")
    update_roles_cache()
    print("Кэш ролей/каналов обновлён для сайта")

    if not _synced_once:
        try:
            synced = await bot.tree.sync()
            print(f"Slash-команды синхронизированы: {len(synced)}")
            _synced_once = True
        except Exception as exc:
            print(f"Не удалось синхронизировать slash-команды: {exc}")




@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot or not member.guild:
        return

    if before.channel is None and after.channel is not None:
        record_voice_join(
            member.guild.id,
            member.id,
            str(member),
            after.channel.id,
            after.channel.name,
            utc_now_iso(),
        )
        return

    if before.channel is not None and after.channel is None:
        record_voice_leave(
            member.guild.id,
            member.id,
            str(member),
            utc_now_iso(),
        )
        return

    if before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
        record_voice_join(
            member.guild.id,
            member.id,
            str(member),
            after.channel.id,
            after.channel.name,
            utc_now_iso(),
        )


@bot.event
async def on_member_join(member: discord.Member):
    config = load_config()

    welcome_role_id = str(config.get("welcome_role_id", "")).strip()
    if welcome_role_id:
        role = member.guild.get_role(int(welcome_role_id)) if welcome_role_id.isdigit() else None
        if role:
            try:
                await member.add_roles(role, reason="Ranko welcome role")
            except discord.Forbidden:
                await send_log(member.guild, f"⚠️ Не смог выдать welcome-роль {role.name}: роль Ranko ниже неё.")
            except discord.HTTPException:
                await send_log(member.guild, f"⚠️ Discord ошибка при выдаче welcome-роли {role.name}.")

    if not config.get("welcome_enabled", True):
        return

    channel = discord.utils.get(member.guild.text_channels, name=config.get("welcome_channel", "general"))
    if not channel:
        return

    text = config.get("welcome_text", "Добро пожаловать, {user}!").replace("{user}", member.mention)
    embed = discord.Embed(
        title="👋 Ranko приветствует участника",
        description=text,
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await channel.send(embed=embed)


@bot.event
async def on_guild_join(guild: discord.Guild):
    update_roles_cache()


@bot.event
async def on_guild_role_create(role: discord.Role):
    update_roles_cache()


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    update_roles_cache()


@bot.event
async def on_guild_role_delete(role: discord.Role):
    update_roles_cache()


@bot.event
async def on_guild_channel_create(channel):
    update_roles_cache()


@bot.event
async def on_guild_channel_update(before, after):
    update_roles_cache()


@bot.event
async def on_guild_channel_delete(channel):
    update_roles_cache()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    config = load_config()
    prefix = config.get("prefix", ";;")

    if message.content.strip() == prefix:
        await message.channel.send(embed=commands_embed(prefix))
        return

    if config.get("levels_enabled", True):
        result = add_xp(
            guild_id=message.guild.id,
            user_id=message.author.id,
            username=str(message.author),
            xp_amount=int(config.get("xp_per_message", 10)),
            multiplier=int(config.get("level_multiplier", 100)),
        )

        if result["leveled_up"]:
            new_level = int(result["level"])
            given_roles = await apply_role_rewards(message.author, new_level, exact_only=True)
            extra = ""
            if given_roles:
                extra = "\n🎁 Выданы роли: " + ", ".join(given_roles)
            await message.channel.send(
                f"🎉 {message.author.mention} получил **{new_level} уровень** в Ranko!{extra}"
            )

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    prefix = load_config().get("prefix", ";;")
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❓ Такой команды нет. Напиши **{prefix}help** или просто **{prefix}**, чтобы увидеть список команд. Ещё можно писать `/` для slash-подсказок.")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Не хватает аргументов. Напиши **{prefix}help** для примеров.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"⚠️ Не понял пользователя/число. Пример: **{prefix}setlevel @user 10**")
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    if isinstance(error, commands.CommandInvokeError):
        original = error.original
        text = str(original).lower()
        if "ffmpeg" in text:
            await ctx.send("❌ FFmpeg не найден. Установи FFmpeg и перезапусти терминал/бота.")
            return
        if "davey" in text:
            await ctx.send("❌ Для голосовых каналов нужна библиотека davey. Выполни: `python -m pip install -U davey`.")
            return
        if "nacl" in text or "pynacl" in text:
            await ctx.send("❌ Для голосовых каналов нужна библиотека PyNaCl. Выполни: `python -m pip install -U PyNaCl`.")
            return
        await ctx.send(f"❌ Ошибка команды: `{original}`")
        return
    print(f"Unhandled command error: {error}")


@bot.command(name="help")
async def help_command(ctx: commands.Context):
    await ctx.send(embed=commands_embed(load_config().get("prefix", ";;")))


@bot.command(name="commands")
async def commands_command(ctx: commands.Context):
    await help_command(ctx)


@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send("🏓 Ranko работает")


@bot.command()
async def rank(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    row = get_rank(ctx.guild.id, member.id)

    if not row:
        await ctx.send(f"{member.mention} ещё не имеет опыта.")
        return

    embed = discord.Embed(title=f"📊 Ranko ранг — {member.display_name}", color=discord.Color.blue())
    embed.add_field(name="Уровень", value=str(row["level"]), inline=True)
    embed.add_field(name="XP", value=str(row["xp"]), inline=True)
    embed.add_field(name="Сообщений", value=str(row["messages"]), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def top(ctx: commands.Context):
    rows = get_top(ctx.guild.id, 10)
    if not rows:
        await ctx.send("Топ пока пустой.")
        return

    lines = []
    for index, row in enumerate(rows, start=1):
        lines.append(f"**{index}.** {row['username']} — lvl {row['level']}, XP {row['xp']}")

    embed = discord.Embed(title="🏆 Ranko топ сервера", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command()
async def userinfo(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title="👤 Информация о пользователе", color=discord.Color.purple())
    embed.add_field(name="Имя", value=member.display_name, inline=True)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Аккаунт создан", value=member.created_at.strftime("%d.%m.%Y"), inline=False)
    if member.joined_at:
        embed.add_field(name="Зашёл на сервер", value=member.joined_at.strftime("%d.%m.%Y"), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def clear(ctx: commands.Context, amount: int = 5):
    if not load_config().get("moderation_enabled", True):
        await ctx.send("❌ Модерация выключена в Ranko Dashboard.")
        return
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ Clear доступен только серверному админу или роли-командеру.")
        return
    amount = max(1, min(amount, 100))
    await ctx.channel.purge(limit=amount + 1)
    add_audit("clear", f"{ctx.author} удалил {amount} сообщений в {ctx.channel}")
    await ctx.send(f"🧹 Ranko удалил сообщений: {amount}", delete_after=3)


@bot.command()
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "Причина не указана"):
    if not load_config().get("moderation_enabled", True):
        await ctx.send("❌ Модерация выключена в Ranko Dashboard.")
        return
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ Kick доступен только серверному админу или роли-командеру.")
        return
    await member.kick(reason=reason)
    add_audit("kick", f"{ctx.author} кикнул {member}. Причина: {reason}")
    await ctx.send(f"👢 Ranko кикнул {member.mention}. Причина: {reason}")
    await send_log(ctx.guild, f"👢 {ctx.author.mention} кикнул {member.mention}. Причина: {reason}")


@bot.command()
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "Причина не указана"):
    if not load_config().get("moderation_enabled", True):
        await ctx.send("❌ Модерация выключена в Ranko Dashboard.")
        return
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ Ban доступен только серверному админу или роли-командеру.")
        return
    await member.ban(reason=reason)
    add_audit("ban", f"{ctx.author} забанил {member}. Причина: {reason}")
    await ctx.send(f"🔨 Ranko забанил {member.mention}. Причина: {reason}")
    await send_log(ctx.guild, f"🔨 {ctx.author.mention} забанил {member.mention}. Причина: {reason}")


@bot.command()
async def setlevel(ctx: commands.Context, member: discord.Member, level: int):
    if not can_manage_levels(ctx.author):
        await ctx.send("❌ Менять уровни может только серверный админ или level-admin роль.")
        return
    row = set_user_level(ctx.guild.id, member.id, str(member), level)
    given_roles = await apply_role_rewards(member, int(row["level"]), exact_only=False)
    extra = "\n🎁 Выданы роли: " + ", ".join(given_roles) if given_roles else ""
    await ctx.send(f"✅ Для {member.mention} установлен уровень **{row['level']}**.{extra}")


@bot.command()
async def addlevel(ctx: commands.Context, member: discord.Member, amount: int):
    if not can_manage_levels(ctx.author):
        await ctx.send("❌ Менять уровни может только серверный админ или level-admin роль.")
        return
    row = add_user_level(ctx.guild.id, member.id, str(member), amount)
    given_roles = await apply_role_rewards(member, int(row["level"]), exact_only=False)
    extra = "\n🎁 Выданы роли: " + ", ".join(given_roles) if given_roles else ""
    await ctx.send(f"✅ {member.mention}: теперь уровень **{row['level']}**.{extra}")


@bot.command()
async def setxp(ctx: commands.Context, member: discord.Member, xp: int):
    if not can_manage_levels(ctx.author):
        await ctx.send("❌ Менять XP может только серверный админ или level-admin роль.")
        return
    row = set_user_xp(ctx.guild.id, member.id, str(member), xp)
    await ctx.send(f"✅ Для {member.mention} установлено XP: **{row['xp']}**.")


# Slash-команды — они дают нормальные подсказки в Discord, когда пишешь `/`.
@bot.tree.command(name="commands", description="Показать команды Ranko")
async def slash_commands(interaction: discord.Interaction):
    await interaction.response.send_message(embed=commands_embed(load_config().get("prefix", ";;")), ephemeral=True)


@bot.tree.command(name="ping", description="Проверить работу Ranko")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Ranko работает")


@bot.tree.command(name="rank", description="Показать уровень пользователя")
@app_commands.describe(member="Пользователь, чей ранг нужно показать")
async def slash_rank(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    row = get_rank(interaction.guild.id, member.id)
    if not row:
        await interaction.response.send_message(f"{member.mention} ещё не имеет опыта.")
        return
    embed = discord.Embed(title=f"📊 Ranko ранг — {member.display_name}", color=discord.Color.blue())
    embed.add_field(name="Уровень", value=str(row["level"]), inline=True)
    embed.add_field(name="XP", value=str(row["xp"]), inline=True)
    embed.add_field(name="Сообщений", value=str(row["messages"]), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="top", description="Показать топ пользователей по уровню")
async def slash_top(interaction: discord.Interaction):
    rows = get_top(interaction.guild.id, 10)
    if not rows:
        await interaction.response.send_message("Топ пока пустой.")
        return
    lines = [f"**{i}.** {row['username']} — lvl {row['level']}, XP {row['xp']}" for i, row in enumerate(rows, start=1)]
    embed = discord.Embed(title="🏆 Ranko топ сервера", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setlevel", description="Установить уровень пользователю")
@app_commands.describe(member="Пользователь", level="Новый уровень")
async def slash_setlevel(interaction: discord.Interaction, member: discord.Member, level: int):
    if not can_manage_levels(interaction.user):
        await interaction.response.send_message("❌ Менять уровни может только серверный админ или level-admin роль.", ephemeral=True)
        return
    row = set_user_level(interaction.guild.id, member.id, str(member), level)
    given_roles = await apply_role_rewards(member, int(row["level"]), exact_only=False)
    extra = "\n🎁 Выданы роли: " + ", ".join(given_roles) if given_roles else ""
    await interaction.response.send_message(f"✅ Для {member.mention} установлен уровень **{row['level']}**.{extra}")


@bot.tree.command(name="kick", description="Кикнуть пользователя. Доступ: серверный админ или командер-роль")
@app_commands.describe(member="Пользователь", reason="Причина")
async def slash_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не указана"):
    if not load_config().get("moderation_enabled", True):
        await interaction.response.send_message("❌ Модерация выключена в Ranko Dashboard.", ephemeral=True)
        return
    if not can_use_mod_command(interaction.user):
        await interaction.response.send_message("❌ Kick доступен только серверному админу или роли-командеру.", ephemeral=True)
        return
    await member.kick(reason=reason)
    add_audit("kick", f"{interaction.user} кикнул {member}. Причина: {reason}")
    await interaction.response.send_message(f"👢 Ranko кикнул {member.mention}. Причина: {reason}")


@bot.tree.command(name="clear", description="Очистить сообщения. Доступ: серверный админ или командер-роль")
@app_commands.describe(amount="Сколько сообщений удалить, максимум 100")
async def slash_clear(interaction: discord.Interaction, amount: int = 5):
    if not load_config().get("moderation_enabled", True):
        await interaction.response.send_message("❌ Модерация выключена в Ranko Dashboard.", ephemeral=True)
        return
    if not can_use_mod_command(interaction.user):
        await interaction.response.send_message("❌ Clear доступен только серверному админу или роли-командеру.", ephemeral=True)
        return
    amount = max(1, min(amount, 100))
    await interaction.channel.purge(limit=amount)
    add_audit("clear", f"{interaction.user} удалил {amount} сообщений в {interaction.channel}")
    await interaction.response.send_message(f"🧹 Ranko удалил сообщений: {amount}", ephemeral=True)


@bot.tree.command(name="addlevel", description="Добавить уровни пользователю")
@app_commands.describe(member="Пользователь", amount="Сколько уровней добавить")
async def slash_addlevel(interaction: discord.Interaction, member: discord.Member, amount: int):
    if not can_manage_levels(interaction.user):
        await interaction.response.send_message("❌ Менять уровни может только серверный админ или level-admin роль.", ephemeral=True)
        return
    row = add_user_level(interaction.guild.id, member.id, str(member), amount)
    given_roles = await apply_role_rewards(member, int(row["level"]), exact_only=False)
    extra = "\n🎁 Выданы роли: " + ", ".join(given_roles) if given_roles else ""
    await interaction.response.send_message(f"✅ {member.mention}: теперь уровень **{row['level']}**.{extra}")


@bot.tree.command(name="setxp", description="Установить XP пользователю")
@app_commands.describe(member="Пользователь", xp="Новое значение XP")
async def slash_setxp(interaction: discord.Interaction, member: discord.Member, xp: int):
    if not can_manage_levels(interaction.user):
        await interaction.response.send_message("❌ Менять XP может только серверный админ или level-admin роль.", ephemeral=True)
        return
    row = set_user_xp(interaction.guild.id, member.id, str(member), xp)
    await interaction.response.send_message(f"✅ Для {member.mention} установлено XP: **{row['xp']}**.")


@bot.tree.command(name="ban", description="Забанить пользователя. Доступ: серверный админ или командер-роль")
@app_commands.describe(member="Пользователь", reason="Причина")
async def slash_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не указана"):
    if not load_config().get("moderation_enabled", True):
        await interaction.response.send_message("❌ Модерация выключена в Ranko Dashboard.", ephemeral=True)
        return
    if not can_use_mod_command(interaction.user):
        await interaction.response.send_message("❌ Ban доступен только серверному админу или роли-командеру.", ephemeral=True)
        return
    await member.ban(reason=reason)
    add_audit("ban", f"{interaction.user} забанил {member}. Причина: {reason}")
    await interaction.response.send_message(f"🔨 Ranko забанил {member.mention}. Причина: {reason}")


@bot.tree.command(name="join", description="Зайти в твой или выбранный голосовой канал")
@app_commands.describe(channel="Голосовой канал, необязательно")
async def slash_join(interaction: discord.Interaction, channel: discord.VoiceChannel | None = None):
    await interaction.response.defer(ephemeral=True)
    if channel:
        voice = await connect_to_voice_channel_interaction(interaction, channel)
    else:
        voice = await ensure_voice_interaction(interaction)

    if voice:
        await interaction.followup.send(f"✅ Ranko зашёл в голосовой канал **{voice.channel.name}**.", ephemeral=True)


@bot.tree.command(name="jointo", description="Переместить Ranko в выбранный голосовой канал")
@app_commands.describe(channel="Голосовой канал")
async def slash_jointo(interaction: discord.Interaction, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    voice = await connect_to_voice_channel_interaction(interaction, channel)
    if voice:
        await interaction.followup.send(f"✅ Ranko теперь в голосовом канале **{voice.channel.name}**.", ephemeral=True)


@bot.tree.command(name="leave", description="Выйти из голосового канала")
async def slash_leave(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if not voice or not voice.is_connected():
        await interaction.response.send_message("❌ Ranko сейчас не в голосовом канале.", ephemeral=True)
        return
    await voice.disconnect()
    music_now_playing.pop(interaction.guild.id, None)
    queue_for(interaction.guild.id).clear()
    music_messages.pop(interaction.guild.id, None)
    await interaction.response.send_message("👋 Ranko вышел из голосового канала.", ephemeral=True)


@bot.tree.command(name="play", description="Добавить трек в очередь по ссылке или поиску")
@app_commands.describe(query="Ссылка или поисковый запрос")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    await add_track_to_queue_interaction(interaction, query)


@bot.tree.command(name="queue", description="Показать очередь музыки")
async def slash_queue(interaction: discord.Interaction):
    await interaction.response.send_message(embed=make_music_embed(interaction.guild.id, "📜 Очередь Ranko"), view=MusicControlView(), ephemeral=True)


@bot.tree.command(name="skip", description="Пропустить текущий трек")
async def slash_skip(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and (voice.is_playing() or voice.is_paused()):
        voice.stop()
        await interaction.response.send_message("⏭️ Скипаю трек.")
    else:
        await interaction.response.send_message("❌ Сейчас ничего не играет.", ephemeral=True)


@bot.tree.command(name="pause", description="Поставить музыку на паузу")
async def slash_pause(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_playing():
        voice.pause()
        await interaction.response.send_message("⏸️ Пауза.")
    else:
        await interaction.response.send_message("❌ Сейчас ничего не играет.", ephemeral=True)


@bot.tree.command(name="resume", description="Продолжить музыку")
async def slash_resume(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_paused():
        voice.resume()
        await interaction.response.send_message("▶️ Продолжаю.")
    else:
        await interaction.response.send_message("❌ Музыка не на паузе.", ephemeral=True)


@bot.tree.command(name="stop", description="Остановить музыку")
async def slash_stop(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and (voice.is_playing() or voice.is_paused()):
        queue_for(interaction.guild.id).clear()
        music_now_playing.pop(interaction.guild.id, None)
        voice.stop()
        await update_music_message(interaction.guild.id)
        await interaction.response.send_message("⏹️ Остановил музыку и очистил очередь.")
    else:
        await interaction.response.send_message("❌ Сейчас ничего не играет.", ephemeral=True)


@bot.tree.command(name="nowplaying", description="Показать, что сейчас играет")
async def slash_nowplaying(interaction: discord.Interaction):
    await interaction.response.send_message(embed=make_music_embed(interaction.guild.id, "🎵 Сейчас играет"), view=MusicControlView(), ephemeral=True)


@bot.tree.command(name="sayvc", description="Озвучить текст в голосовом канале")
@app_commands.describe(text="Текст, который Ranko должен проговорить")
async def slash_sayvc(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    await speak_in_voice_interaction(interaction, text)


@bot.tree.command(name="lastvoice", description="Когда пользователь последний раз заходил в голосовой канал")
@app_commands.describe(member="Пользователь")
async def slash_lastvoice(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    data = get_voice_activity(interaction.guild.id, member.id)
    if not data:
        await interaction.response.send_message(
            f"ℹ️ По {member.mention} пока нет данных о голосовых каналах. Ranko считает только с момента запуска этой версии.",
            ephemeral=True,
        )
        return
    current = data.get("current_channel_name")
    embed = discord.Embed(title=f"🎙️ Голосовая активность — {member.display_name}", color=discord.Color.blurple())
    embed.add_field(name="Сейчас в голосовом", value=f"✅ {current}" if current else "❌ нет", inline=False)
    embed.add_field(name="Последний вход", value=format_dt(data.get("last_joined_at")), inline=True)
    embed.add_field(name="Последний выход", value=format_dt(data.get("last_left_at")), inline=True)
    embed.add_field(name="Последний канал", value=data.get("last_channel_name") or "нет данных", inline=False)
    embed.add_field(name="Всего входов", value=str(data.get("total_sessions", 0)), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="serverinfo", description="Информация о сервере")
async def slash_serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📌 Информация о сервере {guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Участников", value=str(guild.member_count), inline=True)
    embed.add_field(name="Ролей", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Каналов", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Владелец сервера", value=guild.owner.mention if guild.owner else "Не найден", inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Показать аватар пользователя")
@app_commands.describe(member="Пользователь")
async def slash_avatar(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"🖼️ Аватар {member.display_name}", color=discord.Color.blurple())
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="profile", description="Профиль пользователя Ranko")
@app_commands.describe(member="Пользователь")
async def slash_profile(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    data = get_rank(interaction.guild.id, member.id) or {"level": 1, "xp": 0, "messages": 0}
    embed = discord.Embed(
        title=f"👤 Профиль {member.display_name}",
        description=f"**Level:** {data.get('level', 1)}\n**XP:** {data.get('xp', 0)}\n**Messages:** {data.get('messages', 0)}",
        color=discord.Color.green(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="botinfo", description="Информация о Ranko")
async def slash_botinfo(interaction: discord.Interaction):
    config = load_config()
    embed = discord.Embed(
        title="🤖 Ranko",
        description="Бот для уровней, ролей, welcome-сообщений, модерации, музыки и панели управления.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Префикс", value=config.get("prefix", ";;"), inline=True)
    embed.add_field(name="Команды", value="Напиши `/commands` или `;;commands`", inline=True)
    await interaction.response.send_message(embed=embed)


# ===== Ranko v8 extra commands =====

@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("❌ Эта команда работает только на сервере.")
        return
    embed = discord.Embed(title=f"📌 Информация о сервере {guild.name}", color=discord.Color.blurple())
    embed.add_field(name="Участников", value=str(guild.member_count), inline=True)
    embed.add_field(name="Ролей", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Каналов", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Владелец", value=guild.owner.mention if guild.owner else "Не найден", inline=False)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await ctx.send(embed=embed)


@bot.command(name="avatar")
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"🖼️ Аватар {member.display_name}", color=discord.Color.blurple())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="profile")
async def profile(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_rank(ctx.guild.id, member.id) if ctx.guild else None
    data = data or {"level": 1, "xp": 0, "messages": 0}
    embed = discord.Embed(
        title=f"👤 Профиль {member.display_name}",
        description=f"**Level:** {data.get('level', 1)}\n**XP:** {data.get('xp', 0)}\n**Messages:** {data.get('messages', 0)}",
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="say")
async def say(ctx, *, text: str):
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(text)


@bot.command(name="embed")
async def make_embed(ctx, title: str, *, text: str):
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    embed = discord.Embed(title=title, description=text, color=discord.Color.blurple())
    await ctx.send(embed=embed)


@bot.command(name="slowmode")
async def slowmode(ctx, seconds: int = 0):
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    seconds = max(0, min(seconds, 21600))
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"✅ Slowmode установлен: **{seconds} сек.**")


@bot.command(name="lock")
async def lock(ctx):
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔒 Канал закрыт для сообщений.")


@bot.command(name="unlock")
async def unlock(ctx):
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или разрешённая роль Ranko.")
        return
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("🔓 Канал открыт.")


@bot.command(name="poll")
async def poll(ctx, *, question: str):
    embed = discord.Embed(title="📊 Опрос", description=question, color=discord.Color.gold())
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")


@bot.command(name="coin")
async def coin(ctx):
    import random
    await ctx.send("🪙 Выпало: **" + random.choice(["орёл", "решка"]) + "**")


@bot.command(name="roll")
async def roll(ctx, sides: int = 6):
    import random
    sides = max(2, min(sides, 1000))
    await ctx.send(f"🎲 Выпало: **{random.randint(1, sides)}** из {sides}")


@bot.command(name="roles")
async def roles_list(ctx):
    roles = [r.name for r in ctx.guild.roles if r.name != "@everyone"]
    text = "\n".join(f"• {name}" for name in roles[:40])
    await ctx.send(f"📌 **Роли сервера:**\n{text}" if text else "Ролей нет.")


@bot.command(name="myroles")
async def myroles(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = [r.name for r in member.roles if r.name != "@everyone"]
    await ctx.send(f"🎭 Роли {member.mention}: " + (", ".join(roles) if roles else "нет ролей"))


@bot.command(name="botinfo")
async def botinfo(ctx):
    config = load_config()
    embed = discord.Embed(
        title="🤖 Ranko",
        description="Бот для уровней, ролей, welcome-сообщений, модерации и панели управления.",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Префикс", value=config.get("prefix", ";;"), inline=True)
    embed.add_field(name="Команды", value="Напиши `/commands` или `;;commands`", inline=True)
    await ctx.send(embed=embed)




# ===== Ranko v12 music + voice activity commands =====

@bot.command(name="join")
async def join_voice(ctx: commands.Context, *, channel_name: str = None):
    if channel_name:
        channel = find_voice_channel(ctx.guild, channel_name)
        if not channel:
            await ctx.send(f"❌ Не нашёл голосовой канал: **{channel_name}**")
            return
        voice = await connect_to_voice_channel(ctx, channel)
    else:
        voice = await ensure_voice(ctx)

    if voice:
        await ctx.send(f"✅ Ranko зашёл в голосовой канал **{voice.channel.name}**.")


@bot.command(name="jointo", aliases=["moveto", "movevoice"])
async def join_to_voice(ctx: commands.Context, *, channel_name: str):
    channel = find_voice_channel(ctx.guild, channel_name)
    if not channel:
        await ctx.send(f"❌ Не нашёл голосовой канал: **{channel_name}**")
        return

    voice = await connect_to_voice_channel(ctx, channel)
    if voice:
        await ctx.send(f"✅ Ranko теперь в голосовом канале **{voice.channel.name}**.")


@bot.command(name="leave")
async def leave_voice(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if not voice or not voice.is_connected():
        await ctx.send("❌ Ranko сейчас не в голосовом канале.")
        return
    await voice.disconnect()
    music_now_playing.pop(ctx.guild.id, None)
    queue_for(ctx.guild.id).clear()
    music_messages.pop(ctx.guild.id, None)
    await ctx.send("👋 Ranko вышел из голосового канала.")


@bot.command(name="play")
async def play_music(ctx: commands.Context, *, query: str):
    await add_track_to_queue(ctx, query)


@bot.command(name="queue", aliases=["q"])
async def show_queue(ctx: commands.Context):
    await ctx.send(embed=make_music_embed(ctx.guild.id, "📜 Очередь Ranko"), view=MusicControlView())


@bot.command(name="skip")
async def skip_music(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and (voice.is_playing() or voice.is_paused()):
        voice.stop()
        await ctx.send("⏭️ Скипаю трек.")
    else:
        await ctx.send("❌ Сейчас ничего не играет.")


@bot.command(name="pause")
async def pause_music(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and voice.is_playing():
        voice.pause()
        await ctx.send("⏸️ Пауза.")
    else:
        await ctx.send("❌ Сейчас ничего не играет.")


@bot.command(name="resume")
async def resume_music(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and voice.is_paused():
        voice.resume()
        await ctx.send("▶️ Продолжаю.")
    else:
        await ctx.send("❌ Музыка не на паузе.")


@bot.command(name="stop")
async def stop_music(ctx: commands.Context):
    voice = ctx.guild.voice_client
    if voice and (voice.is_playing() or voice.is_paused()):
        queue_for(ctx.guild.id).clear()
        music_now_playing.pop(ctx.guild.id, None)
        voice.stop()
        await update_music_message(ctx.guild.id)
        await ctx.send("⏹️ Остановил музыку и очистил очередь.")
    else:
        await ctx.send("❌ Сейчас ничего не играет.")


@bot.command(name="nowplaying", aliases=["np"])
async def now_playing(ctx: commands.Context):
    await ctx.send(embed=make_music_embed(ctx.guild.id, "🎵 Сейчас играет"), view=MusicControlView())


@bot.command(name="sayvc", aliases=["tts", "speak"])
async def say_voice(ctx: commands.Context, *, text: str):
    await speak_in_voice(ctx, text)


@bot.command(name="lastvoice", aliases=["voiceinfo"])
async def last_voice(ctx: commands.Context, member: discord.Member = None):
    member = member or ctx.author
    data = get_voice_activity(ctx.guild.id, member.id)

    if not data:
        await ctx.send(f"ℹ️ По {member.mention} пока нет данных о голосовых каналах. Ranko считает только с момента, когда эта версия была запущена.")
        return

    current = data.get("current_channel_name")
    embed = discord.Embed(
        title=f"🎙️ Голосовая активность — {member.display_name}",
        color=discord.Color.blurple(),
    )
    if current:
        embed.add_field(name="Сейчас в голосовом", value=f"✅ {current}", inline=False)
    else:
        embed.add_field(name="Сейчас в голосовом", value="❌ нет", inline=False)

    embed.add_field(name="Последний вход", value=format_dt(data.get("last_joined_at")), inline=True)
    embed.add_field(name="Последний выход", value=format_dt(data.get("last_left_at")), inline=True)
    embed.add_field(name="Последний канал", value=data.get("last_channel_name") or "нет данных", inline=False)
    embed.add_field(name="Всего входов", value=str(data.get("total_sessions", 0)), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name="ai")
async def ai_command(ctx: commands.Context, *, prompt: str):
    """Задать вопрос ИИ. Ответ дублируется текстом и голосом (если вы в ГС)"""
    config = load_config()
    model_name = config.get("ai_model", "qwen3:8b")
    system_prompt = config.get(f"ai_persona_{ctx.guild.id}", "Ты — полезный голосовой ассистент Ranko.")

    if ctx.author.id not in ai_user_memory:
        ai_user_memory[ctx.author.id] = []

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(ai_user_memory[ctx.author.id][-10:])
    messages.append({"role": "user", "content": prompt})

    msg = await ctx.send("🤖 *Ranko думает...*")

    try:
        async_client = ollama.AsyncClient()
        response = await async_client.chat(model=model_name, messages=messages)
        reply = response["message"]["content"]
        
        ai_user_memory[ctx.author.id].append({"role": "user", "content": prompt})
        ai_user_memory[ctx.author.id].append({"role": "assistant", "content": reply})

        await msg.edit(content=f"🤖 **Ответ:** {reply}")

        if ctx.author.voice and ctx.author.voice.channel:
            await speak_in_voice(ctx, reply)

    except Exception as exc:
        await msg.edit(content=f"❌ Ошибка Ollama: `{exc}`")


@bot.command(name="persona")
async def persona_command(ctx: commands.Context, *, text: str = None):
    """Настройка характера/промпта ИИ для текущего сервера"""
    if not can_use_mod_command(ctx.author):
        await ctx.send("❌ У тебя нет доступа. Нужны права сервера или роль-командер.")
        return

    config = load_config()
    if not text:
        current = config.get(f"ai_persona_{ctx.guild.id}", "Ты — полезный голосовой ассистент Ranko.")
        await ctx.send(f"📜 **Текущий системный промпт сервера:**\n```text\n{current}\n```")
        return

    config[f"ai_persona_{ctx.guild.id}"] = text
    save_config(config)
    await ctx.send("✅ Системный промпт ИИ для этого сервера успешно обновлен!")


@bot.command(name="forget")
async def forget_command(ctx: commands.Context):
    """Очистить память твоего текущего диалога с ИИ"""
    if ctx.author.id in ai_user_memory:
        ai_user_memory[ctx.author.id].clear()
    await ctx.send(f"🧹 {ctx.author.mention}, память нашего с тобой диалога успешно очищена.")


@bot.command(name="aimodel")
async def aimodel_command(ctx: commands.Context, name: str = None):
    """Смена модели Ollama (Глобально)"""
    if not is_global_ranko_admin(ctx.author) and not has_server_admin_power(ctx.author):
        await ctx.send("❌ Настройку модели может менять только администратор.")
        return

    config = load_config()
    if not name:
        current = config.get("ai_model", "qwen3:8b")
        await ctx.send(f"🤖 Текущая используемая модель: `{current}`")
        return

    config["ai_model"] = name
    save_config(config)
    await ctx.send(f"✅ Модель успешно изменена на `{name}`. Убедись, что она скачана через `ollama pull {name}`.")


# ====================================================================
# ===== OLLAMA AI SYSTEM (SLASH COMMANDS) =====
# ====================================================================

@bot.tree.command(name="ai", description="Задать вопрос локальному ИИ Ranko")
@app_commands.describe(prompt="Твой вопрос или реплика для ИИ")
async def slash_ai(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    
    config = load_config()
    model_name = config.get("ai_model", "qwen3:8b")
    system_prompt = config.get(f"ai_persona_{interaction.guild.id}", "Ты — полезный голосовой ассистент Ranko.")

    user_id = interaction.user.id
    if user_id not in ai_user_memory:
        ai_user_memory[user_id] = []

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(ai_user_memory[user_id][-10:])
    messages.append({"role": "user", "content": prompt})

    try:
        async_client = ollama.AsyncClient()
        response = await async_client.chat(model=model_name, messages=messages)
        reply = response["message"]["content"]
        
        ai_user_memory[user_id].append({"role": "user", "content": prompt})
        ai_user_memory[user_id].append({"role": "assistant", "content": reply})

        await interaction.followup.send(f"🤖 **Ответ для {interaction.user.mention}:** {reply}")

        member = interaction.user
        if isinstance(member, discord.Member) and member.voice and member.voice.channel:
            await speak_in_voice_interaction(interaction, reply)

    except Exception as exc:
        await interaction.followup.send(f"❌ Ошибка Ollama: `{exc}`")


@bot.tree.command(name="forget", description="Очистить твою историю общения с ИИ")
async def slash_forget(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in ai_user_memory:
        ai_user_memory[user_id].clear()
    await interaction.response.send_message("🧹 Память твоего диалога с ИИ успешно очищена.", ephemeral=True)


@bot.tree.command(name="persona", description="Настроить системный промпт ИИ для этого сервера")
@app_commands.describe(text="Инструкции для ИИ (например: 'Отвечай как пират')")
async def slash_persona(interaction: discord.Interaction, text: Optional[str] = None):
    if not can_use_mod_command(interaction.user):
        await interaction.response.send_message("❌ У тебя нет доступа.", ephemeral=True)
        return

    config = load_config()
    if not text:
        current = config.get(f"ai_persona_{interaction.guild.id}", "Ты — полезный голосовой ассистент Ranko.")
        await interaction.response.send_message(f"📜 **Текущий системный промпт:** `{current}`", ephemeral=True)
        return

    config[f"ai_persona_{interaction.guild.id}"] = text
    save_config(config)
    await interaction.response.send_message("✅ Системный промпт ИИ успешно изменен!", ephemeral=True)

bot.run(TOKEN)
