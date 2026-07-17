# Community Hub Discord Bot

A custom Discord bot for community migration, onboarding, invite tracking, suggestions, applications, staff workflows, and future Minecraft integration.

## MVP features

- Slash-command based setup
- Verification and configurable member role
- Platform role selection for Java, Bedrock, Xbox, PlayStation, and Mobile
- Welcome messages
- Invite tracking and invite leaderboard
- Suggestions and bug reports
- Staff/developer/builder applications
- Server information and Minecraft status placeholders
- Configurable logging channel
- SQLite persistence

## Requirements

- Python 3.11+
- A Discord application and bot token
- Bot permissions: Manage Roles, Manage Channels, View Audit Log, Send Messages, Embed Links, Read Message History, Use Application Commands
- Server Members Intent enabled in the Discord Developer Portal

## Setup

1. Create a Discord application in the Discord Developer Portal.
2. Add a bot to the application and copy its token.
3. Enable **Server Members Intent**.
4. Invite the bot with the `bot` and `applications.commands` scopes.
5. Copy `.env.example` to `.env` and fill in the values.
6. Install dependencies:

```bash
pip install -r requirements.txt
```

7. Start the bot:

```bash
python -m bot.main
```

8. In Discord, run `/setup` as an administrator.

## Environment variables

See `.env.example`. Do not commit a real bot token.

## Deployment

The bot can run on Railway, Render, Fly.io, a VPS, or another always-on Python host. Persistent hosting should attach storage for `data/community.db`.

## Roadmap

- Minecraft Java/Bedrock account linking
- Live server status and player count
- Rank synchronization
- Ticket and appeal workflow
- Moderation case history
- Web dashboard
- Store and supporter role integration
