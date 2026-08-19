import asyncio
import os
import time
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

class ModerationService:
    def __init__(self, bot):
        self.bot = bot
        self.message_windows = defaultdict(deque)
        self.join_windows = defaultdict(deque)
        self.lockdowns = {}

    def can_act(self, actor, target):
        return actor.id != target.id and target.id != target.guild.owner_id and actor.top_role > target.top_role

    def _has_mod_role(self, member):
        return member.guild_permissions.administrator or any(
            r.name.lower() in {"mod","moderator","staff","admin"} for r in member.roles)

    async def log(self, guild, action, user=None, moderator=None, reason="", duration=None):
        await self.bot.db.add_action(guild.id, user.id if user else None,
                                     moderator.id if moderator else None, action, reason, duration)

    async def warn(self, guild, moderator, target, reason):
        wid = await self.bot.db.add_warning(guild.id, target.id,
                                            moderator.id if moderator else None, reason)
        await self.log(guild, "WARN", target, moderator, reason)
        return wid

    async def lockdown(self, guild, seconds):
        if self.lockdowns.get(guild.id):
            return
        self.lockdowns[guild.id] = True
        changed = []
        try:
            for channel in guild.text_channels:
                overwrite = channel.overwrites_for(guild.default_role)
                if overwrite.send_messages is not False:
                    overwrite.send_messages = False
                    try:
                        await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Anti-Raid lockdown")
                        changed.append(channel)
                    except discord.HTTPException:
                        pass
            await asyncio.sleep(seconds)
        finally:
            for channel in changed:
                try:
                    overwrite = channel.overwrites_for(guild.default_role)
                    overwrite.send_messages = None
                    await channel.set_permissions(guild.default_role, overwrite=overwrite, reason="Anti-Raid lockdown ended")
                except discord.HTTPException:
                    pass
            self.lockdowns.pop(guild.id, None)

class AutoModCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    def _has_mod_role(self, member):
        return member.guild_permissions.administrator or any(
            r.name.lower() in {"mod","moderator","staff","admin"} for r in member.roles)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        if self._has_mod_role(message.author):
            return
        cfg = await self.bot.db.get_config(message.guild.id)
        content = message.content.lower()
        words = [w.strip().lower() for w in cfg["banned_words"].split(",") if w.strip()]
        matched = next((w for w in words if w in content), None)
        if matched:
            try: await message.delete(reason="AutoMod: banned word")
            except discord.HTTPException: pass
            await self.bot.mod.warn(message.guild, self.bot.user, message.author, f"AutoMod banned-word match: {matched}")
            try:
                await message.author.timeout(timedelta(minutes=cfg["spam_timeout"]), reason="AutoMod: banned word")
            except discord.HTTPException: pass
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        window = self.bot.mod.message_windows[key]
        window.append(now)
        while window and now - window[0] > cfg["spam_window"]:
            window.popleft()
        if len(window) >= cfg["spam_count"]:
            window.clear()
            try:
                await message.author.timeout(timedelta(minutes=cfg["spam_timeout"]), reason="AutoMod: anti-spam")
            except discord.HTTPException: pass
            await self.bot.mod.log(message.guild, "ANTI-SPAM TIMEOUT", message.author,
                                   self.bot.user, f"{cfg['spam_count']} messages in {cfg['spam_window']} seconds",
                                   cfg["spam_timeout"])

class ModerationCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction, member: discord.Member, reason="No reason provided"):
        if not self.bot.mod.can_act(interaction.user, member):
            return await interaction.response.send_message("❌ You cannot moderate that member.", ephemeral=True)
        wid = await self.bot.mod.warn(interaction.guild, interaction.user, member, reason)
        await interaction.response.send_message(f"Warned **{member}**. Warning #{wid} (ID `{wid}`).")

    @app_commands.command(name="warnings", description="View a member's active warnings.")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction, member: discord.Member):
        rows = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"**{member}** has **{len(rows)}** active warning(s).", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member.")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction, member: discord.Member, reason="No reason provided"):
        if not self.bot.mod.can_act(interaction.user, member):
            return await interaction.response.send_message("❌ You cannot moderate that member.", ephemeral=True)
        try: await member.kick(reason=reason)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Kick failed: {e}", ephemeral=True)
        await self.bot.mod.log(interaction.guild,"KICK",member,interaction.user,reason)
        await interaction.response.send_message(f"Kicked **{member}**.")

    @app_commands.command(name="ban", description="Ban a member.")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction, member: discord.Member, reason="No reason provided"):
        if not self.bot.mod.can_act(interaction.user, member):
            return await interaction.response.send_message("❌ You cannot moderate that member.", ephemeral=True)
        try: await member.ban(reason=reason)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Ban failed: {e}", ephemeral=True)
        await self.bot.mod.log(interaction.guild,"BAN",member,interaction.user,reason)
        await interaction.response.send_message(f"Banned **{member}**.")

    @app_commands.command(name="timeout", description="Timeout a member.")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction, member: discord.Member,
                      minutes: app_commands.Range[int,1,40320]=10, reason="No reason provided"):
        if not self.bot.mod.can_act(interaction.user, member):
            return await interaction.response.send_message("❌ You cannot moderate that member.", ephemeral=True)
        try: await member.timeout(timedelta(minutes=minutes), reason=reason)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Timeout failed: {e}", ephemeral=True)
        await self.bot.mod.log(interaction.guild,"TIMEOUT",member,interaction.user,reason,minutes)
        await interaction.response.send_message(f"Timed out **{member}** for **{minutes} minutes**.")

    @app_commands.command(name="purge", description="Delete recent messages.")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction, amount: app_commands.Range[int,1,100]):
        await interaction.response.defer(ephemeral=True)
        try: deleted = await interaction.channel.purge(limit=amount)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ Purge failed: {e}", ephemeral=True)
        await self.bot.mod.log(interaction.guild,"PURGE",None,interaction.user,f"Deleted {len(deleted)} messages",len(deleted))
        await interaction.followup.send(f"Deleted **{len(deleted)}** messages.", ephemeral=True)

    @app_commands.command(name="setautomod", description="Configure AutoMod and anti-raid settings.")
    @app_commands.default_permissions(administrator=True)
    async def setautomod(self, interaction, banned_words="",
                          spam_count: app_commands.Range[int,2,30]=6,
                          spam_window: app_commands.Range[int,2,60]=8,
                          spam_timeout: app_commands.Range[int,1,40320]=10,
                          raid_joins: app_commands.Range[int,2,100]=8,
                          raid_window: app_commands.Range[int,5,300]=20,
                          lockdown_seconds: app_commands.Range[int,30,3600]=120):
        await self.bot.db.set_config(interaction.guild.id, banned_words=banned_words,
            spam_count=spam_count, spam_window=spam_window, spam_timeout=spam_timeout,
            raid_join_count=raid_joins, raid_window=raid_window, raid_lockdown=lockdown_seconds)
        await interaction.response.send_message("✅ AutoMod settings saved.", ephemeral=True)

    @app_commands.command(name="tempban", description="Temporarily ban a member.")
    @app_commands.default_permissions(ban_members=True)
    async def tempban(self, interaction, member: discord.Member,
                      minutes: app_commands.Range[int,1,40320]=10, reason="No reason provided"):
        if not self.bot.mod.can_act(interaction.user, member):
            return await interaction.response.send_message("❌ You cannot moderate that member.", ephemeral=True)
        try: await member.ban(reason=reason)
        except discord.HTTPException as e:
            return await interaction.response.send_message(f"❌ Temporary ban failed: {e}", ephemeral=True)
        await self.bot.mod.log(interaction.guild,"TEMPBAN",member,interaction.user,reason,minutes)
        await interaction.response.send_message(f"Temporarily banned **{member}** for **{minutes} minutes**.")
        async def unban_later():
            await asyncio.sleep(minutes*60)
            try: await interaction.guild.unban(discord.Object(id=member.id), reason="Temporary ban expired")
            except discord.HTTPException: pass
        asyncio.create_task(unban_later())

    @app_commands.command(name="appeal", description="Submit a moderation appeal.")
    async def appeal(self, interaction, reason: str):
        appeal_id = await self.bot.db.add_appeal(interaction.guild.id, interaction.user.id, reason)
        cfg = await self.bot.db.get_config(interaction.guild.id)
        url = cfg.get("appeal_url") or os.getenv("APPEAL_URL","")
        suffix = f" Web dashboard: {url}/appeal" if url else " Web dashboard: /appeal"
        await interaction.response.send_message(f"Appeal #{appeal_id} submitted.{suffix}", ephemeral=True)

class TemporaryActionCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        cfg = await self.bot.db.get_config(member.guild.id)
        window = self.bot.mod.join_windows[member.guild.id]
        now = discord.utils.utcnow().timestamp()
        window.append(now)
        while window and now-window[0] > cfg["raid_window"]:
            window.popleft()
        if len(window) >= cfg["raid_join_count"]:
            await self.bot.mod.lockdown(member.guild, cfg["raid_lockdown"])
            await self.bot.mod.log(member.guild,"ANTI-RAID LOCKDOWN",member,self.bot.user,
                                   f"{len(window)} joins in {cfg['raid_window']} seconds",cfg["raid_lockdown"])
