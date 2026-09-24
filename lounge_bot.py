import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import boto3
from botocore.config import Config
import discord
from discord.ext import commands, tasks
from presence_snapshot import write_snapshot
from datetime import datetime, timezone, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from game_history import DynamoGameHistory, context_status_line

# --- Logging Setup ---
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger('lounge_bot')
logger.setLevel(logging.DEBUG)

# Console handler (INFO level — captured by journald when running as systemd service)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_fmt = logging.Formatter('%(asctime)s [%(levelname)-8s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_handler.setFormatter(console_fmt)
logger.addHandler(console_handler)

# File handler (DEBUG level — full detail for troubleshooting)
file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, 'lounge-bot.log'),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_fmt = logging.Formatter('%(asctime)s [%(levelname)-8s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(file_fmt)
logger.addHandler(file_handler)

# --- Configuration ---
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
if not TOKEN:
    logger.error("DISCORD_BOT_TOKEN environment variable not set.")
    sys.exit(1)

text_channel_id_str = os.environ.get('TEXT_CHANNEL_ID')
if not text_channel_id_str:
    logger.error("TEXT_CHANNEL_ID environment variable not set.")
    sys.exit(1)
try:
    text_channel_id = int(text_channel_id_str)
except ValueError:
    logger.error("TEXT_CHANNEL_ID environment variable must be an integer.")
    sys.exit(1)

time_threshold_str = os.environ.get('TIME_THRESHOLD', '7200')
try:
    TIME_THRESHOLD = int(time_threshold_str)
except ValueError:
    logger.error("TIME_THRESHOLD environment variable must be an integer.")
    sys.exit(1)

VOICE_CHANNEL_NAME = os.environ.get('VOICE_CHANNEL_NAME', 'Lounge')

voice_channel_id_str = os.environ.get('VOICE_CHANNEL_ID')
if voice_channel_id_str:
    try:
        voice_channel_id = int(voice_channel_id_str)
    except ValueError:
        logger.error("VOICE_CHANNEL_ID environment variable must be an integer.")
        sys.exit(1)
else:
    voice_channel_id = None

# --- Game History Configuration ---
GAME_HISTORY_ENABLED = os.environ.get('GAME_HISTORY_ENABLED', 'true').lower() in ('true', '1', 'yes')
GAME_HISTORY_TABLE = os.environ.get('GAME_HISTORY_TABLE', 'openclaw-discord-bot-state')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

excluded_ids_str = os.environ.get('GAME_TRACKING_EXCLUDED_MEMBER_IDS', '')
try:
    GAME_TRACKING_EXCLUDED_MEMBER_IDS = {
        int(value.strip()) for value in excluded_ids_str.split(',') if value.strip()
    }
except ValueError:
    logger.error("GAME_TRACKING_EXCLUDED_MEMBER_IDS must be a comma-separated list of integers.")
    sys.exit(1)

game_history = None
if GAME_HISTORY_ENABLED:
    try:
        dynamodb = boto3.resource(
            'dynamodb',
            region_name=AWS_REGION,
            config=Config(retries={'mode': 'standard', 'max_attempts': 5}),
        )
        game_history = DynamoGameHistory(
            dynamodb.Table(GAME_HISTORY_TABLE),
            excluded_member_ids=GAME_TRACKING_EXCLUDED_MEMBER_IDS,
        )
    except Exception as exc:
        logger.warning("Game history initialization failed; using live activity only: %s", exc)

# --- Office Hours Configuration ---
# When enabled, notifications sent outside the configured window will omit
# the @here ping so nobody gets buzzed at 2 AM. The notification still posts
# for context — just silently.
OFFICE_HOURS_ENABLED = os.environ.get('OFFICE_HOURS_ENABLED', 'false').lower() in ('true', '1', 'yes')
OFFICE_HOURS_START_STR = os.environ.get('OFFICE_HOURS_START', '06:00')
OFFICE_HOURS_END_STR = os.environ.get('OFFICE_HOURS_END', '22:30')
OFFICE_HOURS_TZ_STR = os.environ.get('OFFICE_HOURS_TZ', 'US/Eastern')

# Parse office hours config
OFFICE_HOURS_START = None
OFFICE_HOURS_END = None
OFFICE_HOURS_TZ = None

if OFFICE_HOURS_ENABLED:
    try:
        h, m = OFFICE_HOURS_START_STR.split(':')
        OFFICE_HOURS_START = dt_time(int(h), int(m))
        h, m = OFFICE_HOURS_END_STR.split(':')
        OFFICE_HOURS_END = dt_time(int(h), int(m))
        OFFICE_HOURS_TZ = ZoneInfo(OFFICE_HOURS_TZ_STR)
        logger.info(
            f"Office hours enabled: {OFFICE_HOURS_START_STR} – {OFFICE_HOURS_END_STR} "
            f"({OFFICE_HOURS_TZ_STR}). Notifications outside this window will omit @here."
        )
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid office hours configuration: {e}. Disabling office hours.")
        OFFICE_HOURS_ENABLED = False


def is_within_office_hours():
    """Check if the current time falls within the configured office hours window.

    Handles normal ranges (e.g., 06:00–22:30) and overnight ranges (e.g., 22:00–06:00).
    Returns True if office hours are disabled (all hours are 'active').
    """
    if not OFFICE_HOURS_ENABLED:
        return True

    now = datetime.now(OFFICE_HOURS_TZ).time()

    if OFFICE_HOURS_START <= OFFICE_HOURS_END:
        # Normal range: e.g., 06:00 – 22:30
        return OFFICE_HOURS_START <= now <= OFFICE_HOURS_END
    else:
        # Overnight range: e.g., 22:00 – 06:00 (active late night through early morning)
        return now >= OFFICE_HOURS_START or now <= OFFICE_HOURS_END


# --- Bot Setup ---
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.presences = True
intents.message_content = False

bot = commands.Bot(command_prefix='!', intents=intents)

# Opt-in private snapshot: one explicitly selected member in one guild.
PRESENCE_SNAPSHOT_PATH = os.environ.get("PRESENCE_SNAPSHOT_PATH", "")
PRESENCE_MEMBER_ID = int(os.environ.get("PRESENCE_MEMBER_ID", "0"))
PRESENCE_GUILD_ID = int(os.environ.get("PRESENCE_GUILD_ID", "0"))


@tasks.loop(seconds=30)
async def publish_presence_snapshot():
    if not PRESENCE_SNAPSHOT_PATH or not PRESENCE_MEMBER_ID or not PRESENCE_GUILD_ID:
        return
    try:
        guild = bot.get_guild(PRESENCE_GUILD_ID)
        await asyncio.to_thread(
            write_snapshot, PRESENCE_SNAPSHOT_PATH, guild, PRESENCE_MEMBER_ID,
            bot.is_ready(), PRESENCE_MEMBER_ID in GAME_TRACKING_EXCLUDED_MEMBER_IDS,
        )
    except Exception:
        logger.exception("Private presence snapshot write failed")


# Dictionary to track the last join time of members
member_join_times = {}


def get_member_activity(member):
    """Extract the primary activity/game status from a member."""
    if member.activities:
        for act in member.activities:
            if isinstance(act, discord.Game):
                return act.name
            elif isinstance(act, discord.Streaming):
                return f"Streaming {act.game}" if act.game else "Streaming"
            elif isinstance(act, discord.Spotify):
                return f"Listening to {act.title} by {act.artist}"
            elif isinstance(act, discord.Activity):
                return act.name
    return "No activity"


def get_member_game(member):
    """Extract only trackable game activity; ignore Spotify and custom statuses."""
    if member.activities:
        for act in member.activities:
            if isinstance(act, discord.Game):
                return act.name
            if isinstance(act, discord.Streaming) and act.game:
                return act.game
    return None


async def reconcile_game_history():
    """Reconcile persisted state against Discord presence without bursting DynamoDB."""
    if not game_history:
        return
    logger.info("GAME HISTORY: Starting presence reconciliation across %d guild(s).", len(bot.guilds))
    reconciled = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot or game_history.is_excluded(member.id):
                continue
            try:
                await asyncio.to_thread(
                    game_history.record_transition,
                    guild.id,
                    member.id,
                    get_member_game(member),
                )
                reconciled += 1
            except Exception as exc:
                logger.warning(
                    "GAME HISTORY: Reconciliation failed for member %s: %s",
                    member.id,
                    exc,
                )
            await asyncio.sleep(0.25)
    logger.info("GAME HISTORY: Reconciled %d member presence record(s).", reconciled)


@bot.event
async def on_ready():
    if PRESENCE_SNAPSHOT_PATH and not publish_presence_snapshot.is_running():
        publish_presence_snapshot.start()
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    if voice_channel_id:
        logger.info(f"Monitoring voice channel ID: {voice_channel_id}")
    else:
        logger.info(f"Monitoring voice channel by name: '{VOICE_CHANNEL_NAME}'")
    logger.info(f"Notifications channel ID: {text_channel_id}")
    logger.info(f"Spam threshold: {TIME_THRESHOLD}s")
    if OFFICE_HOURS_ENABLED:
        logger.info(f"Office hours: {OFFICE_HOURS_START_STR} – {OFFICE_HOURS_END_STR} ({OFFICE_HOURS_TZ_STR})")
    else:
        logger.info("Office hours: disabled (notifications ping @here at all times)")
    if game_history:
        logger.info(
            "Game history: DynamoDB table %s in %s (%d member opt-out(s))",
            GAME_HISTORY_TABLE,
            AWS_REGION,
            len(GAME_TRACKING_EXCLUDED_MEMBER_IDS),
        )
        global _reconcile_task
        if _reconcile_task is None or _reconcile_task.done():
            _reconcile_task = asyncio.create_task(reconcile_game_history())
    else:
        logger.info("Game history: disabled")
    logger.info("Bot is ready and listening for voice state updates.")


_resume_grace_until = None  # suppress notifications briefly after resume
_reconcile_task = None

@bot.event
async def on_resumed():
    """Handle gateway reconnects — keep cooldown cache intact, rely on membership check for stale events."""
    global _resume_grace_until
    logger.warning("Gateway session resumed. Cooldown cache preserved (%d entries).", len(member_join_times))
    _resume_grace_until = datetime.now(timezone.utc) + timedelta(seconds=10)
    logger.info("Resume grace period: suppressing join notifications for 10s.")


@bot.event
async def on_disconnect():
    """Log disconnections for debugging."""
    logger.warning("Bot disconnected from Discord gateway.")


@bot.event
async def on_presence_update(before, after):
    """Persist observed game sessions only when the trackable game changes."""
    if not game_history or after.bot or game_history.is_excluded(after.id):
        return
    previous_game = get_member_game(before)
    current_game = get_member_game(after)
    if previous_game == current_game:
        return
    try:
        await asyncio.to_thread(
            game_history.record_transition,
            after.guild.id,
            after.id,
            current_game,
        )
        logger.info(
            "GAME TRANSITION: %s | %s → %s",
            after.display_name,
            previous_game or "none",
            current_game or "none",
        )
    except Exception as exc:
        logger.warning("GAME HISTORY: Transition write failed for %s: %s", after.id, exc)


def _is_target_channel(channel):
    """Check if a channel matches the configured target (by ID if set, otherwise by name)."""
    if channel is None:
        return False
    if voice_channel_id:
        return channel.id == voice_channel_id
    return channel.name == VOICE_CHANNEL_NAME


@bot.event
async def on_voice_state_update(member, before, after):
    joined_target = (
        _is_target_channel(after.channel)
        and (before.channel is None or before.channel.id != after.channel.id)
    )

    left_target = (
        _is_target_channel(before.channel)
        and (after.channel is None or after.channel.id != before.channel.id)
    )

    # --- Handle leave events (log only) ---
    if left_target:
        dest = after.channel.name if after.channel else "disconnected"
        logger.info(f"LEAVE: {member.display_name} left '{VOICE_CHANNEL_NAME}' → {dest}")
        return

    # --- Handle join events ---
    if not joined_target:
        logger.debug(f"IGNORE: {member.display_name} voice state change (not a '{VOICE_CHANNEL_NAME}' join)")
        return

    logger.debug(f"JOIN EVENT: {member.display_name} → '{VOICE_CHANNEL_NAME}'")

    # Validate the member is actually in the channel right now.
    # This catches stale/replayed events after gateway reconnects.
    actual_members = after.channel.members
    if member not in actual_members:
        logger.warning(
            f"STALE EVENT: {member.display_name} triggered join for '{VOICE_CHANNEL_NAME}' "
            f"but is not in the channel member list. Suppressing notification."
        )
        return

    # Resume grace period — suppress phantom joins after gateway reconnect
    if _resume_grace_until and datetime.now(timezone.utc) < _resume_grace_until:
        logger.info(
            f"RESUME-SUPPRESSED: {member.display_name} join during post-resume grace period. Skipping."
        )
        return

    # Spam suppression — check if they joined recently
    current_time = datetime.now(timezone.utc)
    member_id = member.id
    last_join_time = member_join_times.get(member_id)

    if last_join_time:
        time_diff = (current_time - last_join_time).total_seconds()
        if time_diff < TIME_THRESHOLD:
            activity = get_member_activity(member)
            logger.info(
                f"SUPPRESSED: {member.display_name} rejoined '{VOICE_CHANNEL_NAME}' "
                f"after {time_diff:.0f}s (threshold: {TIME_THRESHOLD}s). Activity: {activity}"
            )
            return

    # Update the last join time and prune expired entries
    member_join_times[member_id] = current_time
    stale_ids = [k for k, v in member_join_times.items()
                 if (current_time - v).total_seconds() > TIME_THRESHOLD]
    for stale_id in stale_ids:
        del member_join_times[stale_id]
    if stale_ids:
        logger.debug(f"PRUNE: Removed {len(stale_ids)} expired cooldown entries.")

    # Build the notification
    member_names = [m.display_name for m in actual_members]
    members_list = ', '.join(member_names)
    activity = get_member_activity(member)
    current_game = get_member_game(member)

    headline = f"🔊 **{member.display_name}** has joined **{after.channel.name}**."
    context = {"kind": "generic", "game": None}
    if game_history:
        try:
            headline, context = await asyncio.to_thread(
                game_history.announcement,
                member.guild.id,
                member.id,
                member.display_name,
                after.channel.name,
                current_game,
            )
        except Exception as exc:
            logger.warning(
                "GAME HISTORY: Announcement lookup failed for %s; using live fallback: %s",
                member.id,
                exc,
            )

    # Determine if we should ping @here based on office hours
    within_hours = is_within_office_hours()

    if within_hours:
        ping = "@here\n"
        logger.info(f"JOIN: {member.display_name} → '{VOICE_CHANNEL_NAME}' | Members: {members_list} | Activity: {activity}")
    else:
        ping = ""
        local_time = datetime.now(OFFICE_HOURS_TZ).strftime('%I:%M %p %Z') if OFFICE_HOURS_TZ else "unknown"
        logger.info(
            f"JOIN (OFF-HOURS): {member.display_name} → '{VOICE_CHANNEL_NAME}' | "
            f"Members: {members_list} | Activity: {activity} | "
            f"Local time: {local_time} — @here suppressed"
        )

    message = (
        f"{ping}"
        f"{headline}\n"
        f"👥 Current members in the channel: {members_list}\n"
        f"{context_status_line(context, activity)}"
    )

    text_channel = bot.get_channel(text_channel_id)
    if text_channel:
        try:
            await text_channel.send(message)
            notify_type = "NOTIFY" if within_hours else "NOTIFY (QUIET)"
            logger.info(f"{notify_type}: Sent join notification for {member.display_name}")
        except Exception as e:
            logger.error(f"NOTIFY FAILED: Could not send message — {e}")
    else:
        logger.warning(f"Text channel {text_channel_id} not found. Is the bot in the right server?")


# --- Run ---
try:
    bot.run(TOKEN, log_handler=None)  # log_handler=None prevents discord.py from overriding our logging
except Exception as e:
    logger.error(f"Fatal error: {e}")
