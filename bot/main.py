from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from bot.database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger("community-bot")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "/tmp/community.db")
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0") or 0)
PLATFORMS = ("Java", "Bedrock", "Xbox", "PlayStation", "Mobile")


class CommunityBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.invites = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DATABASE_PATH)
        self.invite_cache: dict[int, dict[str, tuple[int, int | None]]] = {}

    async def setup_hook(self) -> None:
        await self.db.initialize()
        if TEST_GUILD_ID:
            guild = discord.Object(id=TEST_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                LOGGER.info("Synced commands to test guild %s", TEST_GUILD_ID)
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning("Could not sync commands to test guild %s: %s", TEST_GUILD_ID, exc)
        else:
            try:
                await self.tree.sync()
                LOGGER.info("Synced global commands")
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning("Could not sync global commands: %s", exc)

    async def cache_invites(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            LOGGER.warning("Missing Manage Guild permission for invite tracking in %s", guild.id)
            return
        self.invite_cache[guild.id] = {
            invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None)
            for invite in invites
        }


bot = CommunityBot()


def admin_only(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.administrator)


async def configured_channel(guild: discord.Guild, key: str) -> discord.TextChannel | None:
    config = await bot.db.get_config(guild.id)
    channel_id = config.get(key)
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel if isinstance(channel, discord.TextChannel) else None


async def send_log(guild: discord.Guild, title: str, description: str) -> None:
    channel = await configured_channel(guild, "log_channel_id")
    if channel:
        await channel.send(embed=discord.Embed(title=title, description=description, color=discord.Color.blurple()))


@bot.event
async def on_ready() -> None:
    for guild in bot.guilds:
        await bot.cache_invites(guild)
    LOGGER.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await bot.cache_invites(guild)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    old = bot.invite_cache.get(member.guild.id, {})
    inviter_id: int | None = None
    invite_code: str | None = None
    try:
        current = await member.guild.invites()
        for invite in current:
            previous_uses = old.get(invite.code, (0, None))[0]
            if (invite.uses or 0) > previous_uses:
                inviter_id = invite.inviter.id if invite.inviter else None
                invite_code = invite.code
                break
        bot.invite_cache[member.guild.id] = {
            invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None)
            for invite in current
        }
    except discord.Forbidden:
        pass

    await bot.db.record_join(member.guild.id, member.id, inviter_id, invite_code)
    welcome = await configured_channel(member.guild, "welcome_channel_id")
    if welcome:
        inviter_text = f" Invited by <@{inviter_id}>." if inviter_id else ""
        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}!",
            description=f"Welcome {member.mention}! Use `/verify` and `/platform` to unlock the server.{inviter_text}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await welcome.send(embed=embed)
    await send_log(member.guild, "Member joined", f"{member.mention} joined. Invite: `{invite_code or 'unknown'}`")


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    await bot.db.record_leave(member.guild.id, member.id)
    await send_log(member.guild, "Member left", f"{member} (`{member.id}`) left the server.")


@bot.tree.command(description="Create or configure the core community channels and verified role.")
@app_commands.check(admin_only)
async def setup(interaction: discord.Interaction) -> None:
    assert interaction.guild
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    verified = discord.utils.get(guild.roles, name="Verified") or await guild.create_role(
        name="Verified", reason="Community bot setup"
    )
    category = discord.utils.get(guild.categories, name="COMMUNITY BOT") or await guild.create_category("COMMUNITY BOT")

    async def channel(name: str) -> discord.TextChannel:
        existing = discord.utils.get(guild.text_channels, name=name)
        return existing or await guild.create_text_channel(name, category=category)

    welcome = await channel("welcome")
    suggestions = await channel("suggestions")
    applications = await channel("staff-applications")
    logs = await channel("bot-logs")
    await logs.set_permissions(guild.default_role, view_channel=False)

    await bot.db.set_config(
        guild.id,
        welcome_channel_id=welcome.id,
        log_channel_id=logs.id,
        suggestion_channel_id=suggestions.id,
        application_channel_id=applications.id,
        verified_role_id=verified.id,
    )
    await interaction.followup.send(
        "Setup complete. I created/configured the Verified role and the welcome, suggestions, applications, and bot-logs channels.",
        ephemeral=True,
    )


@setup.error
async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    message = "Only a server administrator can run `/setup`." if isinstance(error, app_commands.CheckFailure) else "Setup failed. Check my role permissions and try again."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(description="Verify yourself and receive the server's verified role.")
async def verify(interaction: discord.Interaction) -> None:
    assert interaction.guild and isinstance(interaction.user, discord.Member)
    config = await bot.db.get_config(interaction.guild.id)
    role = interaction.guild.get_role(config.get("verified_role_id") or 0)
    if not role:
        await interaction.response.send_message("The server owner must run `/setup` first.", ephemeral=True)
        return
    await interaction.user.add_roles(role, reason="Member verification")
    await interaction.response.send_message(f"You are verified and now have {role.mention}.", ephemeral=True)


@bot.tree.command(description="Choose your main Minecraft platform and receive its role.")
@app_commands.describe(platform="Your primary Minecraft platform")
@app_commands.choices(platform=[app_commands.Choice(name=name, value=name) for name in PLATFORMS])
async def platform(interaction: discord.Interaction, platform: app_commands.Choice[str]) -> None:
    assert interaction.guild and isinstance(interaction.user, discord.Member)
    role = discord.utils.get(interaction.guild.roles, name=platform.value)
    if role is None:
        try:
            role = await interaction.guild.create_role(name=platform.value, reason="Platform role")
        except discord.Forbidden:
            await interaction.response.send_message("I cannot create roles. Ask an admin to move my bot role higher.", ephemeral=True)
            return
    other_roles = [r for r in interaction.user.roles if r.name in PLATFORMS and r != role]
    if other_roles:
        await interaction.user.remove_roles(*other_roles, reason="Platform selection changed")
    await interaction.user.add_roles(role, reason="Platform selection")
    await interaction.response.send_message(f"Your platform is now **{platform.value}**.", ephemeral=True)


async def create_public_submission(
    interaction: discord.Interaction,
    kind: str,
    title: str,
    details: str,
    channel_key: str,
) -> None:
    assert interaction.guild
    channel = await configured_channel(interaction.guild, channel_key)
    if not channel:
        await interaction.response.send_message("The server owner must run `/setup` first.", ephemeral=True)
        return
    submission_id = await bot.db.create_submission(interaction.guild.id, interaction.user.id, kind, title, details)
    embed = discord.Embed(title=f"#{submission_id} — {title}", description=details, color=discord.Color.blurple())
    embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
    embed.add_field(name="Type", value=kind.replace("_", " ").title())
    embed.add_field(name="Status", value="Under Review")
    message = await channel.send(embed=embed)
    if kind in {"suggestion", "bug_report"}:
        await message.add_reaction("👍")
        await message.add_reaction("👎")
    await interaction.response.send_message(f"Submitted as **#{submission_id}** in {channel.mention}.", ephemeral=True)


@bot.tree.command(description="Submit a community suggestion for voting and staff review.")
@app_commands.describe(title="Short suggestion title", details="Explain your suggestion")
async def suggest(interaction: discord.Interaction, title: str, details: str) -> None:
    await create_public_submission(interaction, "suggestion", title, details, "suggestion_channel_id")


@bot.tree.command(description="Report a bug to the development team.")
@app_commands.describe(title="Short bug title", details="What happened and how to reproduce it")
async def bug_report(interaction: discord.Interaction, title: str, details: str) -> None:
    await create_public_submission(interaction, "bug_report", title, details, "suggestion_channel_id")


@bot.tree.command(description="Apply for a community team position.")
@app_commands.describe(position="Position requested", experience="Relevant experience", reason="Why you want the role")
@app_commands.choices(position=[
    app_commands.Choice(name="Moderator", value="moderator"),
    app_commands.Choice(name="Developer", value="developer"),
    app_commands.Choice(name="Builder", value="builder"),
    app_commands.Choice(name="Content Creator", value="content_creator"),
])
async def apply(
    interaction: discord.Interaction,
    position: app_commands.Choice[str],
    experience: str,
    reason: str,
) -> None:
    details = f"**Experience**\n{experience}\n\n**Reason**\n{reason}"
    await create_public_submission(interaction, f"{position.value}_application", f"{position.name} application", details, "application_channel_id")


@bot.tree.command(description="Show the top members bringing active people into the server.")
async def invite_leaderboard(interaction: discord.Interaction) -> None:
    assert interaction.guild
    rows = await bot.db.invite_leaderboard(interaction.guild.id)
    if not rows:
        await interaction.response.send_message("No tracked invites yet.", ephemeral=True)
        return
    lines = [f"**{index}.** <@{user_id}> — **{count}** active joins" for index, (user_id, count) in enumerate(rows, 1)]
    await interaction.response.send_message(embed=discord.Embed(title="Invite Leaderboard", description="\n".join(lines)))


@bot.tree.command(description="Show community and Minecraft connection information.")
async def server_info(interaction: discord.Interaction) -> None:
    assert interaction.guild
    embed = discord.Embed(title=interaction.guild.name, color=discord.Color.blurple())
    embed.add_field(name="Members", value=str(interaction.guild.member_count or 0))
    embed.add_field(name="Minecraft", value="Integration is prepared but not configured yet.", inline=False)
    embed.add_field(name="Getting Started", value="Use `/verify`, then `/platform`.", inline=False)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(description="Check the future Minecraft server integration status.")
async def server_status(interaction: discord.Interaction) -> None:
    host = os.getenv("MINECRAFT_HOST", "").strip()
    if not host:
        await interaction.response.send_message("Minecraft server status is not configured yet. Set `MINECRAFT_HOST` when the server is ready.")
        return
    await interaction.response.send_message(f"Minecraft host configured as `{host}`. Live player polling will be added in Phase 2.")


@bot.tree.command(description="Post a branded announcement as the bot.")
@app_commands.check(admin_only)
@app_commands.describe(channel="Channel to post in", title="Announcement title", message="Announcement content")
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
) -> None:
    embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
    embed.set_footer(text=f"Posted by {interaction.user}")
    await channel.send(embed=embed)
    await interaction.response.send_message(f"Announcement posted in {channel.mention}.", ephemeral=True)


@bot.tree.error
async def global_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    LOGGER.exception("Command error", exc_info=error)
    message = "You do not have permission to use that command." if isinstance(error, app_commands.CheckFailure) else "Something went wrong while running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/health", lambda request: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    LOGGER.info("Health server listening on port %s", port)
    return runner


async def main() -> None:
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add the bot token.")
    health_runner = None
    try:
        async with bot:
            health_runner = await start_health_server()
            await bot.start(TOKEN)
    finally:
        if health_runner is not None:
            await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
