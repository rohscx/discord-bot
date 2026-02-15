import os
import logging
import discord
from discord.ext import commands
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)

# Read the bot token from an environment variable
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
if not TOKEN:
    logging.error("DISCORD_BOT_TOKEN environment variable not set.")
    exit(1)

# Read the text channel ID from an environment variable
text_channel_id_str = os.environ.get('TEXT_CHANNEL_ID')
if not text_channel_id_str:
    logging.error("TEXT_CHANNEL_ID environment variable not set.")
    exit(1)
try:
    text_channel_id = int(text_channel_id_str)
except ValueError:
    logging.error("TEXT_CHANNEL_ID environment variable must be an integer.")
    exit(1)

# Read the time threshold from an environment variable, default to 60 seconds
time_threshold_str = os.environ.get('TIME_THRESHOLD', '60')
try:
    TIME_THRESHOLD = int(time_threshold_str)
except ValueError:
    logging.error("TIME_THRESHOLD environment variable must be an integer.")
    exit(1)

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.presences = True  # Enable presence intent to access user's activities
intents.message_content = False  # Set to True only if necessary

bot = commands.Bot(command_prefix='!', intents=intents)

# Dictionary to track the last join time of members
member_join_times = {}

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("Bot is ready and listening for voice state updates.")

@bot.event
async def on_voice_state_update(member, before, after):
    logging.debug(f"{member.display_name} changed voice state.")
    logging.debug(f"Before channel: {before.channel}")
    logging.debug(f"After channel: {after.channel}")

    # Check if the member joined the "Lounge" voice channel
    if after.channel and after.channel.name == 'Lounge' and before.channel != after.channel:
        current_time = datetime.utcnow()
        member_id = member.id

        logging.debug(f"{member.display_name} has joined 'Lounge'.")

        # Check if the member has joined recently
        last_join_time = member_join_times.get(member_id)
        if last_join_time:
            time_diff = (current_time - last_join_time).total_seconds()
            logging.debug(f"Time since last join for {member.display_name}: {time_diff} seconds.")
            if time_diff < TIME_THRESHOLD:
                # Log the event instead of sending a message
                logging.info(f"{member.display_name} rejoined 'Lounge' within {TIME_THRESHOLD} seconds. Suppressing message.")
                # Include game/status in the log
                await log_member_activity(member)
                return

        # Update the last join time
        member_join_times[member_id] = current_time

        # Get all members currently in the "Lounge"
        members_in_channel = after.channel.members
        member_names = [m.display_name for m in members_in_channel]
        members_list = ', '.join(member_names)

        # Get the member's current activity (game)
        activity = None
        if member.activities:
            for act in member.activities:
                if isinstance(act, discord.Game):
                    activity = act.name
                    break
                elif isinstance(act, discord.Activity):
                    activity = act.name
                    break
                elif isinstance(act, discord.Streaming):
                    activity = f"Streaming {act.game}" if act.game else "Streaming"
                    break
                elif isinstance(act, discord.Spotify):
                    activity = f"Listening to {act.title} by {act.artist}"
                    break
        if activity:
            game_status = f"{activity}"
        else:
            game_status = "No activity"

        # Log the game/status
        logging.info(f"{member.display_name}'s activity: {game_status}")

        # Compose the notification message
        message = (
            f"@here\n"
            f"🔊 **{member.display_name}** has joined **{after.channel.name}**.\n"
            f"👥 Current members in the channel: {members_list}\n"
            f"🎮 Status: {game_status}"
        )

        # Get the text channel
        text_channel = bot.get_channel(text_channel_id)

        if text_channel:
            try:
                logging.info(f"Sending message to channel ID {text_channel_id}: {message}")
                await text_channel.send(message)
            except Exception as e:
                logging.error(f"Failed to send message: {e}")
        else:
            logging.warning(f"Text channel with ID {text_channel_id} not found.")
    else:
        logging.debug(f"{member.display_name} did not join 'Lounge'. Event ignored.")

async def log_member_activity(member):
    # Get the member's current activity (game)
    activity = None
    if member.activities:
        for act in member.activities:
            if isinstance(act, discord.Game):
                activity = act.name
                break
            elif isinstance(act, discord.Activity):
                activity = act.name
                break
            elif isinstance(act, discord.Streaming):
                activity = f"Streaming {act.game}" if act.game else "Streaming"
                break
            elif isinstance(act, discord.Spotify):
                activity = f"Listening to {act.title} by {act.artist}"
                break
    if activity:
        game_status = f"{activity}"
    else:
        game_status = "No activity"

    # Log the game/status
    logging.info(f"{member.display_name}'s activity: {game_status}")

# Run the bot
try:
    bot.run(TOKEN)
except Exception as e:
    logging.error(f"An error occurred: {e}")
