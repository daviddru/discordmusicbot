import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
import asyncio
from collections import deque

from keep_alive import keep_alive

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1393926471701237830
SONG_QUEUES = {}

keep_alive()

intents = discord.Intents.default()
intents.message_content = True


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        # Register all commands BEFORE syncing
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} command(s) to guild {GUILD_ID}")


bot = MyBot()


async def search_ytdlp_async(query, ydl_options):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _extract(query, ydl_options))


def _extract(query, ydl_options):
    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        return ydl.extract_info(query, download=False)


@bot.tree.command(name="hello", description="Say hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello, {interaction.user.mention}!")


@bot.tree.command(name="play", description="Play a song or add it to the queue.")
@app_commands.describe(song_query="Search query")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()

    member = interaction.guild.get_member(interaction.user.id)
    voice_state = member.voice if member else None
    if not voice_state or not voice_state.channel:
        await interaction.followup.send("You must be in a voice channel.")
        return
    voice_channel = voice_state.channel

    if voice_channel is None:
        await interaction.followup.send("You must be in a voice channel.")
        return
    
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_channel != voice_client.channel:
        await voice_client.move_to(voice_channel)

    ydl_options = {
        "format": "bestaudio[abr<=96]/bestaudio",
        "noplaylist": True,
        "youtube_include_dash_manifest": False,
    }

    query = f"ytsearch1:{song_query}"
    results = await search_ytdlp_async(query, ydl_options)
    tracks = results.get("entries", [])

    if tracks is None:
        await interaction.followup.send("No results found.")
        return
    
    first_track = tracks[0]
    audio_url = first_track["url"]
    title = first_track.get("title", "Untitled")

    guild_id = str(interaction.guild_id)
    if SONG_QUEUES.get(guild_id) is None:
        SONG_QUEUES[guild_id] = deque()

    SONG_QUEUES[guild_id].append((audio_url, title))

    if voice_client.is_playing() or voice_client.is_paused():
        await interaction.followup.send(f"Added to queue: **{title}**")
    else:
        await play_next_song(voice_client, guild_id, interaction.channel)
        await interaction.followup.send(f"Added to queue: **{title}**")


@bot.tree.command(name="skip", description="Skips to the next song")
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await interaction.response.send_message("Skipped the current song.")
    else:
        await interaction.response.send_message("Not playing anything to skip.")


@bot.tree.command(name="pause", description="Pauses the current song.")
async def pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        return await interaction.response.send_message("Not connected to a voice channel!")
    
    if not voice_client.is_playing():
        return await interaction.response.send_message("Nothing to pause.")
    
    voice_client.pause()
    await interaction.response.send_message("Paused.")


@bot.tree.command(name="resume", description="Resumes playback.")
async def resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        return await interaction.response.send_message("Not connected to a voice channel!")
    
    if not voice_client.is_paused():
        return await interaction.response.send_message("Nothing to resume.")
    
    voice_client.resume()
    await interaction.response.send_message("Resumed.")


@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
async def stop(interaction: discord.Interaction):
    await interaction.response.defer()
    voice_client = interaction.guild.voice_client

    if not voice_client or not voice_client.is_connected():
        await interaction.followup.send("Not connected to a voice channel.")
        return
    
    # Clear the queue
    guild_id_str = str(interaction.guild_id)
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()

    # Stop the playback
    if voice_client.is_playing() or voice_client.is_paused():
        voice_client.stop()

    await interaction.followup.send("Stopped playback and disconnected!")

    # Disconnect from the channel
    await voice_client.disconnect()


@bot.tree.command(name="queue", description="Show the current song queue.")
async def queue(interaction: discord.Interaction):
    guild_id_str = str(interaction.guild_id)

    queue = SONG_QUEUES.get(guild_id_str)

    if not queue or len(queue) == 0:
        await interaction.response.send_message("📭 The queue is currently empty.")
        return

    # Format the queue list
    message = "**🎶 Current Queue:**\n"
    for idx, (_, title) in enumerate(queue, start=1):
        message += f"{idx}. {title}\n"

    await interaction.response.send_message(message)


@bot.tree.command(name="clear", description="Clears the current song queue.")
async def queue(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client

    if not voice_client or not voice_client.is_connected():
        await interaction.followup.send("Not connected to a voice channel.")
        return


    guild_id_str = str(interaction.guild_id)
    if guild_id_str in SONG_QUEUES:
        SONG_QUEUES[guild_id_str].clear()
        await interaction.response.send_message("Queue cleared.")
    else:
        await interaction.response.send_message("Queue already empty.")


async def play_next_song(voice_client, guild_id, channel):
    if SONG_QUEUES[guild_id]:
        audio_url, title = SONG_QUEUES[guild_id].popleft()

        ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -c:a libopus -b:a 96k",
        }

        source = discord.FFmpegOpusAudio(audio_url, **ffmpeg_options, executable="bin\\ffmpeg\\ffmpeg.exe")
        
        def after_playing(error):
            if error:
                print(f"Error playing audio: {error}")
            asyncio.run_coroutine_threadsafe(play_next_song(voice_client, guild_id, channel), bot.loop)

        voice_client.play(source, after=after_playing)
        asyncio.create_task(channel.send(f"Now playing: **{title}**"))

    else:
        await voice_client.disconnect()
        SONG_QUEUES[guild_id] = deque()



@bot.event
async def on_ready():
    print(f"🤖 {bot.user} is online!")


bot.run(TOKEN)