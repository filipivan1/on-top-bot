# Render-ready ModBot

Upload these files to the root of your GitHub bot repository.

Render:
- Language: Python 3
- Build Command: pip install -r requirements.txt
- Start Command: python bot.py
- Environment: DISCORD_TOKEN = your bot token
- Optional GUILD_ID = your test server ID

The web server uses Render's PORT automatically and binds to 0.0.0.0.

Note: SQLite is local storage and is not persistent on a free ephemeral deployment. Temporary bans are also in-memory and do not survive a restart. Move to a persistent database before treating this as production.
