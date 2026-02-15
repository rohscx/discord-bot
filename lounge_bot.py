import os
import logging
from logging.handlers import RotatingFileHandler
import discord
from discord.ext import commands
from datetime import datetime, timezone

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
    exit(1)

text_channel_id_str = os.environ.get('TEXT_CHANNEL_ID')
if not text_channel_id_str:
    logger.error("TEXT_CHANNEL_ID environment variable not set.")
    exit(1)
try:
    text_channel_id = int(text_channel_id_str)
except ValueError:
    logger.error("TEXT_CHANNEL_ID environment variable must be an integer.")
    exit(1)

time_threshold_str = os.environ.get('TIME_THRESHOLD', '7200')
try:
    TIME_THRESHOLD = int(time_threshold_str)
except ValueError:
    logger.error("TIME_THRESHOLD environment variable must be an integer.")
    exit(1)

VOICE_CHANNEL_NAME = os.environ.get('VOICE_CHANNEL_NAME', 'Lounge')

# --- Bot Setup ---
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.presences = True
intents.message_content = False

bot = commands.Bot(command_prefix='!', intents=intents)

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


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Monitoring voice channel: '{VOICE_CHANNEL_NAME}'")
    logger.info(f"Notifications channel ID: {text_channel_id}")
    logger.info(f"Spam threshold: {TIME_THRESHOLD}s")
    logger.info("Bot is ready and listening for voice state updates.")


@bot.event
async def on_resumed():
    """Handle gateway reconnects — clear stale join times to prevent phantom notifications."""
    logger.warning("Gateway session resumed. Clearing stale join time cache.")
    member_join_times.clear()


@bot.event
async def on_disconnect():
    """Log disconnections for debugging."""
    logger.warning("Bot disconnected from Discord gateway.")


@bot.event
async def on_voice_state_update(member, before, after):
    joined_target = (
        after.channel is not None
        and after.channel.name == VOICE_CHANNEL_NAME
        and (before.channel is None or before.channel.id != after.channel.id)
    )

    left_target = (
        before.channel is not None
        and before.channel.name == VOICE_CHANNEL_NAME
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

    # Update the last join time
    member_join_times[member_id] = current_time

    # Build the notification
    member_names = [m.display_name for m in actual_members]
    members_list = ', '.join(member_names)
    activity = get_member_activity(member)

    logger.info(f"JOIN: {member.display_name} → '{VOICE_CHANNEL_NAME}' | Members: {members_list} | Activity: {activity}")

    message = (
        f"@here\n"
        f"🔊 **{member.display_name}** has joined **{after.channel.name}**.\n"
        f"👥 Current members in the channel: {members_list}\n"
        f"🎮 Status: {activity}"
    )

    text_channel = bot.get_channel(text_channel_id)
    if text_channel:
        try:
            await text_channel.send(message)
            logger.info(f"NOTIFY: Sent join notification for {member.display_name}")
        except Exception as e:
            logger.error(f"NOTIFY FAILED: Could not send message — {e}")
    else:
        logger.warning(f"Text channel {text_channel_id} not found. Is the bot in the right server?")


# --- Run ---
try:
    bot.run(TOKEN, log_handler=None)  # log_handler=None prevents discord.py from overriding our logging
except Exception as e:
    logger.error(f"Fatal error: {e}")
