# 🔊 Lounge Bot

A lightweight Discord bot that notifies your server when someone joins a voice channel — so nobody misses out when the squad is hanging out.

## What It Does

When a member joins the **Lounge** voice channel, the bot posts a notification to a designated text channel with:

- **Who joined** the voice channel
- **Who's already there** — see the full list of current members
- **What they're up to** — game activity, Spotify, streaming status

### Spam Prevention

If someone disconnects and rejoins within a configurable time window (default: 2 hours), the bot suppresses the notification to keep the text channel clean. No more notification spam from flaky connections.

## Quick Start

### Prerequisites

- Python 3.9+
- A [Discord Bot Token](https://discord.com/developers/applications) with the following **Privileged Gateway Intents** enabled:
  - Server Members Intent
  - Presence Intent

### 1. Clone the repo

```bash
git clone https://github.com/rohscx/discord-bot.git
cd discord-bot
```

### 2. Set up environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
DISCORD_BOT_TOKEN=your_bot_token_here
TEXT_CHANNEL_ID=your_text_channel_id_here
TIME_THRESHOLD=7200  # Spam suppression window in seconds (default: 2 hours)
```

> **How to get the Channel ID:** Enable Developer Mode in Discord (Settings → Advanced → Developer Mode), then right-click the text channel and select "Copy Channel ID".

### 3. Run it

**Option A: Python (venv)**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python lounge_bot.py
```

**Option B: Docker**

```bash
docker build -t lounge-bot .
docker run -d --env-file .env --name lounge-bot lounge-bot
```

**Option C: systemd (Linux server)**

A systemd service file and install script are provided in the `deploy/` directory for running the bot as a persistent background service:

```bash
bash deploy/install.sh
```

This will:
- Create a Python virtual environment (if needed)
- Install dependencies
- Install and enable the systemd service
- Start the bot

Manage the service with:

```bash
sudo systemctl status lounge-bot    # Check status
sudo systemctl restart lounge-bot   # Restart
sudo journalctl -u lounge-bot -f    # View live logs
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | ✅ | — | Your Discord bot token |
| `TEXT_CHANNEL_ID` | ✅ | — | Channel ID where notifications are posted |
| `TIME_THRESHOLD` | ❌ | `7200` | Seconds before a rejoin triggers a new notification |

## How It Works

```
Member joins "Lounge" voice channel
        │
        ▼
  Joined recently?  ──yes──▶  Suppress notification (log only)
        │
        no
        │
        ▼
  Post notification to text channel:
    • @here ping
    • Member name
    • Current channel members
    • Activity/game status
```

## Deployment Options

The bot needs a persistent connection to Discord's gateway, so it must run on something that stays on 24/7.

| Platform | Works? | Notes |
|----------|--------|-------|
| Linux server / EC2 | ✅ | Use the systemd service in `deploy/` |
| Synology NAS (Docker) | ✅ | See Docker instructions above |
| Docker Hub | ✅ | Build and push with `docker buildx` |
| AWS ECR + NAS | ✅ | Push to ECR, pull from NAS |
| Google Cloud Run | ❌ | Idles and kills WebSocket connections |
| AWS Lambda | ❌ | Same timeout/idle issues |

## Project Structure

```
├── lounge_bot.py        # Main bot logic
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container build
├── .env.example         # Environment template
├── deploy/
│   ├── lounge-bot.service   # systemd unit file
│   └── install.sh           # Automated install script
└── README.md
```

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push and open a PR

## License

See [LICENSE](LICENSE) for details.
