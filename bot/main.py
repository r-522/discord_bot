import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Optional

import aiohttp
import discord
from aiohttp import web

from detector import TermDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("it-term-bot")

WORKERS_BASE_URL = os.getenv("WORKERS_BASE_URL", "")
WORKER_BEARER_TOKEN = os.getenv("WORKER_BEARER_TOKEN", "")
DICT_RELOAD_SECONDS = int(os.getenv("DICT_RELOAD_SECONDS", "3600"))
USER_COOLDOWN_SECONDS = int(os.getenv("USER_COOLDOWN_SECONDS", "30"))
CHANNEL_COOLDOWN_SECONDS = int(os.getenv("CHANNEL_COOLDOWN_SECONDS", "10"))
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True

client = discord.Client(intents=intents)
detector = TermDetector()
user_last: Dict[int, float] = {}
channel_last: Dict[int, float] = {}
queue: deque[discord.Message] = deque()
processing = False


async def fetch_terms(session: aiohttp.ClientSession) -> None:
    try:
        async with session.get(
            f"{WORKERS_BASE_URL}/terms",
            headers={"Authorization": f"Bearer {WORKER_BEARER_TOKEN}"},
            timeout=10,
        ) as res:
            res.raise_for_status()
            data = await res.json()
            detector.reload_terms(data.get("terms", []))
            logger.info("辞書ロード完了: %s件", len(data.get("terms", [])))
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        logger.error("辞書ロード失敗: %s", e)


async def periodic_reload() -> None:
    async with aiohttp.ClientSession() as session:
        while True:
            await fetch_terms(session)
            await asyncio.sleep(DICT_RELOAD_SECONDS)


async def resolve_conversation_id(message: discord.Message) -> str:
    try:
        current = message
        while current.reference and current.reference.message_id:
            ref = current.reference.cached_message
            if ref is None:
                break
            current = ref
        return str(current.id)
    except (AttributeError, RuntimeError):
        return str(message.id)


async def call_ask_api(session: aiohttp.ClientSession, query: str, conversation_id: str) -> Optional[str]:
    payload = {"query": query, "conversationId": conversation_id}
    for _ in range(3):
        try:
            async with session.post(
                f"{WORKERS_BASE_URL}/ask",
                json=payload,
                headers={"Authorization": f"Bearer {WORKER_BEARER_TOKEN}"},
                timeout=10,
            ) as res:
                if res.status >= 500:
                    await asyncio.sleep(0.5)
                    continue
                data = await res.json()
                return data.get("answer")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.error("/ask失敗: %s", e)
            await asyncio.sleep(0.5)
    return None


async def process_queue() -> None:
    global processing
    if processing:
        return
    processing = True
    async with aiohttp.ClientSession() as session:
        while queue:
            message = queue.popleft()
            now = time.time()
            if now - user_last.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
                continue
            if now - channel_last.get(message.channel.id, 0) < CHANNEL_COOLDOWN_SECONDS:
                continue

            result = detector.detect(message.content)
            if not result.terms:
                continue

            term = result.terms[0]
            conversation_id = await resolve_conversation_id(message)
            answer = await call_ask_api(session, term, conversation_id)
            if not answer:
                continue
            text = answer[:2000]
            try:
                await message.reply(text)
                user_last[message.author.id] = now
                channel_last[message.channel.id] = now
                logger.info("反応: term=%s channel=%s ts=%s", term, message.channel.id, int(now))
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.error("返信失敗: %s", e)
            await asyncio.sleep(0.1)
    processing = False


@client.event
async def on_ready() -> None:
    logger.info("ログイン完了: %s", client.user)
    client.loop.create_task(periodic_reload())


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    queue.append(message)
    await process_queue()


async def healthz(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def run_health_server() -> None:
    app = web.Application()
    app.router.add_get('/healthz', healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    await site.start()


async def main() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKENが未設定です")
    await run_health_server()
    await client.start(token)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (RuntimeError, KeyboardInterrupt, OSError) as e:
        logger.error("終了: %s", e)
