import asyncio
import os
import re
import tempfile
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD = discord.Object(id=int(os.environ["DISCORD_GUILD_ID"]))
API_KEY = os.environ["OPENROUTER_API_KEY"]
TEXT_MODEL = os.environ["OPENROUTER_TEXT_MODEL"]
SEARCH_MODEL = os.getenv("OPENROUTER_SEARCH_MODEL", "openai/gpt-4.1-nano")
TTS_MODEL = os.environ["OPENROUTER_TTS_MODEL"]
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
TTS_URL = "https://openrouter.ai/api/v1/audio/speech"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
round_lock = asyncio.Lock()
lessons: dict[int, tuple[str, str]] = {}


async def response_data(response: aiohttp.ClientResponse) -> dict:
    if response.status >= 400:
        raise RuntimeError(f"OpenRouter returned HTTP {response.status}.")
    return await response.json()

async def research(prompt):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    search_payload = {
        "model": SEARCH_MODEL,
        "max_tokens": 900,
        "max_tool_calls": 1,
        "tool_choice": "required",
        "tools": [{"type": "openrouter:web_search", "parameters": {
            "max_results": 5, "search_context_size": "low",
        }}],
        "messages": [{"role": "user", "content": (
            "Search the web for this learning request. Summarize 5 to 8 useful facts, "
            "explain uncertainty where needed, and cite each source with a markdown link. "
            f"Request: {prompt}"
        )}],
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as session:
        async with session.post(CHAT_URL, headers=headers, json=search_payload) as response:
            data = await response_data(response)

    notes = data["choices"][0]["message"]["content"]
    sources = re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", notes)
    return notes, sources


async def write_lesson(prompt, notes):
    payload = {
        "model": TEXT_MODEL,
        "max_tokens": 1800,
        "reasoning": {"enabled": False},
        "messages": [
            {"role": "system", "content": (
                "You are an accurate English voice tutor. Use only the research notes provided. "
                "Write clear spoken prose in English, 750 to 1,100 words for a roughly 5–10 minute round. "
                "Explain ideas step by step, distinguish established facts from uncertainty, "
                "and do not include markdown, URLs, or a bibliography."
            )},
            {"role": "user", "content": f"Request: {prompt}\n\nResearch notes:\n{notes}"},
        ],
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=240)) as session:
        async with session.post(CHAT_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json=payload) as response:
            data = await response_data(response)
    return data["choices"][0]["message"]["content"]


async def play_file(voice: discord.VoiceClient, path: Path) -> None:
    loop = asyncio.get_running_loop()
    done = loop.create_future()

    def finished(error):
        if error:
            loop.call_soon_threadsafe(done.set_exception, error)
        else:
            loop.call_soon_threadsafe(done.set_result, None)

    voice.play(discord.FFmpegPCMAudio(str(path)), after=finished)
    await done


async def tts(narration: str) -> bytes:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=900)) as session:
        async with session.post(TTS_URL,
                                headers={
                                    "Authorization": f"Bearer {API_KEY}"
                                },
                                json={
                                    "model": TTS_MODEL,
                                    "input": narration,
                                    "response_format": "mp3"
                                }) as response:
            response.raise_for_status()
            return await response.read()


async def speak(channel, voice, narration, title):
    audio = await tts(narration)
    with tempfile.TemporaryDirectory(prefix="nerv-audio-") as temp_dir:
        lesson_mp3 = Path(temp_dir) / "lesson.mp3"
        lesson_mp3.write_bytes(audio)
        await play_file(voice, lesson_mp3)
        await channel.send(embed=discord.Embed(
            title=f"🎧 {title[:240]}",
            description="Replay this round.",
            color=discord.Color.blurple(),
        ), file=discord.File(lesson_mp3), allowed_mentions=discord.AllowedMentions.none())


async def send_sources(channel, title, sources):
    links = []
    for index, (source_title, url) in enumerate(sources, 1):
        label = discord.utils.escape_markdown(" ".join(source_title.split())[:90]).replace("[", "").replace("]", "")
        link = url.replace("(", "%28").replace(")", "%29")
        links.append(f"**{index}.** [{label}]({link})")
    await channel.send(embed=discord.Embed(
        title=f"📚 {title[:240]}",
        description="\n".join(links),
        color=discord.Color.blurple(),
    ), allowed_mentions=discord.AllowedMentions.none())


async def send_round_finished(channel):
    await channel.send(embed=discord.Embed(
        title="✅ Round complete",
        description="Ask a follow-up with `/ask` whenever you're ready.",
        color=discord.Color.green(),
    ))


async def run_round(interaction: discord.Interaction, title: str, prompt: str) -> str:
    notes, sources = await research(prompt)
    narration = await write_lesson(prompt, notes)
    await send_sources(interaction.channel, title, sources)
    await speak(interaction.channel, interaction.guild.voice_client, narration, title)
    await send_round_finished(interaction.channel)
    return narration


@bot.tree.command(name="join", description="Join your voice channel", guild=GUILD)
async def join(interaction: discord.Interaction) -> None:
    if interaction.guild.voice_client is None:
        await interaction.user.voice.channel.connect()
    await interaction.response.send_message(embed=discord.Embed(
        title="🔊 Ready in voice",
        description="Use `/learn` to start a lesson.",
        color=discord.Color.green(),
    ), ephemeral=True)


@bot.tree.command(name="learn", description="Hear a researched spoken lesson", guild=GUILD)
@app_commands.describe(topic="What would you like to learn about?")
async def learn(interaction: discord.Interaction, topic: str) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.followup.send(embed=discord.Embed(
        title="📚 Lesson queued",
        description="I'll post the sources here and teach in voice.",
        color=discord.Color.blurple(),
    ), ephemeral=True)
    async with round_lock:
        narration = await run_round(interaction, topic, f"Teach me about: {topic}")
        lessons[interaction.guild_id] = (topic, narration)


@bot.tree.command(name="ask", description="Ask a researched follow-up about the current lesson", guild=GUILD)
@app_commands.describe(question="What would you like to ask?")
async def ask(interaction: discord.Interaction, question: str) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    await interaction.followup.send(embed=discord.Embed(
        title="💬 Follow-up queued",
        description="I'll research your question and answer in voice.",
        color=discord.Color.blurple(),
    ), ephemeral=True)
    async with round_lock:
        topic, previous = lessons[interaction.guild_id]
        prompt = f"Current lesson topic: {topic}\nPrevious answer: {previous[:12000]}\nQuestion: {question}"
        narration = await run_round(interaction, question, prompt)
        lessons[interaction.guild_id] = (topic, narration)


@bot.event
async def setup_hook() -> None:
    await bot.tree.sync(guild=GUILD)
    print("Discord commands synced for the configured server.")


bot.run(TOKEN)
