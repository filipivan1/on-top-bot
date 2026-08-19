import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database
from moderation import ModerationService, ModerationCog, AutoModCog, TemporaryActionCog
from web import create_app

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it in Render Environment Variables or .env.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

class ModerationBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.db = Database("moderation.sqlite3")
        self.mod = ModerationService(self)
        self.web_task = None

    async def setup_hook(self):
        await self.db.initialize()
        await self.add_cog(ModerationCog(self))
        await self.add_cog(AutoModCog(self))
        await self.add_cog(TemporaryActionCog(self))

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Slash commands synced to guild %s", guild_id)
        else:
            await self.tree.sync()
            logging.info("Global slash commands synced")

        self.web_task = asyncio.create_task(self.run_web())

    async def run_web(self):
        import uvicorn
        app = create_app(self)
        port = int(os.getenv("PORT", os.getenv("WEB_PORT", "10000")))
        host = os.getenv("WEB_HOST", "0.0.0.0")
        await uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info")).serve()

    async def close(self):
        if self.web_task:
            self.web_task.cancel()
        await self.db.close()
        await super().close()

bot = ModerationBot()

@bot.event
async def on_ready():
    logging.info("Logged in as %s (%s)", bot.user, bot.user.id)

bot.run(TOKEN)
