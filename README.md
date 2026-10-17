# Nerv Voice Tutor

A local Discord bot that researches a topic, posts its source links, and reads an English lesson aloud in your voice channel. `/learn` targets roughly 5–10 minutes; `/ask` researches a follow-up using the latest lesson context.

## Requirements

- Python 3.14 or newer and [uv](https://docs.astral.sh/uv/)
- FFmpeg available on `PATH`
- A Discord application installed in one server with the `bot` and `applications.commands` scopes, and **Send Messages**, **Embed Links**, **Attach Files**, **Connect**, and **Speak** permissions
- An OpenRouter API key with enough credit for model usage and web search

## Setup

1. Copy `.env.example` to `.env` and fill in the Discord bot token, server ID, OpenRouter API key, and model IDs. `OPENROUTER_SEARCH_MODEL` defaults to `openai/gpt-4.1-nano`; it performs the web search, then `OPENROUTER_TEXT_MODEL` writes the lesson. The initial speech model is `fish-audio/s2.1-pro-free:free`; the bot omits `voice` so the model's default voice is used.
2. Install dependencies and start the bot:

   ```sh
   uv sync
   uv run python bot.py
   ```

The bot registers `/join`, `/learn`, and `/ask` directly in `DISCORD_GUILD_ID` when it starts. Keep the bot running locally while using it.

## Use

Join your voice channel and run `/join` to connect the bot. Then run `/learn topic`. When the round ends, run `/ask question` for a researched follow-up. The source links appear in a compact embed, and a replayable MP3 is attached in the channel where each command was invoked. The bot keeps the latest lesson in memory until it exits.

OpenRouter web search is billed per search in addition to model tokens. Each round makes one search request with up to five results, one narration request, and one speech request for the full lesson. Every round requests 750–1,100 words. The temporary MP3 is deleted after the round.

## Check the setup

Run `uv run python -m py_compile bot.py`, then start the bot and confirm it logs in and syncs. In Discord, confirm all three slash commands appear, then run `/join` from voice before trying `/learn`. A real lesson and speech playback consume OpenRouter credit.
