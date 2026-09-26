import asyncio
import base64
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands

PREFIX = os.getenv("BOT_PREFIX", ".")
DEFAULT_PRESET = os.getenv("DEFAULT_PRESET", "Medium")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "5"))
OBF_TIMEOUT = int(os.getenv("OBFUSCATE_TIMEOUT", "120"))
PORT = int(os.getenv("PORT", "10000"))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip().strip("/")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_DIR = os.getenv("GITHUB_DIR", "obfuscated").strip("/")

ALLOWED_PRESETS = {"Minify", "Weak", "Vmify", "Medium", "Strong"}
PROM_DIR = Path(__file__).resolve().parent / "prometheus"
CLI = PROM_DIR / "cli.lua"
PROM_CONFIG = PROM_DIR / "src" / "config.lua"
TMP_ROOT = Path(tempfile.gettempdir()) / "discord-prometheus-bot"
TMP_ROOT.mkdir(parents=True, exist_ok=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def clean_name(name: str) -> str:
    name = Path(name).name
    stem = Path(name).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "script"
    return stem[:80]


def parse_args(args: list[str]):
    mode = "file"
    preset = DEFAULT_PRESET
    remaining = []
    for arg in args:
        low = arg.lower()
        if low == "load":
            mode = "load"
        elif arg.capitalize() in ALLOWED_PRESETS:
            preset = arg.capitalize()
        else:
            remaining.append(arg)
    return mode, preset, remaining


def run_prometheus(src: Path, out: Path, preset: str):
    cmd = [
        "luajit",
        str(CLI),
        "--preset", preset,
        "--LuaU",
        "--nocolors",
        "--out", str(out),
        str(src),
    ]
    return asyncio.run(_run_process(cmd))


async def _run_process(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(PROM_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=OBF_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Prometheus timed out after {OBF_TIMEOUT} seconds.")
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (err or out).strip()
        if len(detail) > 2500:
            detail = detail[-2500:]
        raise RuntimeError(f"Prometheus exited with code {proc.returncode}.\n```text\n{detail}\n```")
    return out, err


async def github_publish(content: bytes, filename: str):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO must be configured for `load` mode.")

    if "/" not in GITHUB_REPO:
        raise RuntimeError("GITHUB_REPO must be in the form `owner/repository`.")

    owner, repo = GITHUB_REPO.split("/", 1)
    path = f"{GITHUB_DIR}/{filename}" if GITHUB_DIR else filename
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    encoded = base64.b64encode(content).decode("ascii")
    payload = {
        "message": f"Add obfuscated script {filename}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "discord-prometheus-bot",
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(api_url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                try:
                    data = await resp.json()
                    message = data.get("message", body)
                except Exception:
                    message = body
                raise RuntimeError(f"GitHub upload failed ({resp.status}): {message}")

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{GITHUB_BRANCH}/{path}"
    return raw_url


async def get_attachment(message: discord.Message):
    if not message.attachments:
        return None
    attachment = message.attachments[0]
    if attachment.size > MAX_FILE_MB * 1024 * 1024:
        raise RuntimeError(f"File is too large. Maximum size is {MAX_FILE_MB} MB.")
    if not attachment.filename.lower().endswith(".lua"):
        raise RuntimeError("Please attach a `.lua` file.")
    return attachment


async def process_message(message: discord.Message, args: list[str]):
    mode, preset, extra = parse_args(args)
    if extra and not message.attachments:
        await message.reply("Attach the `.lua` file to the command. Example: `.obfuscate load Medium`.")
        return
    if len(message.attachments) > 1:
        await message.reply("Please attach only one `.lua` file per command.")
        return

    attachment = await get_attachment(message)
    if attachment is None:
        await message.reply(
            f"Attach a `.lua` file. Examples:\n"
            f"`{PREFIX}obfuscate`\n"
            f"`{PREFIX}obfuscate load`\n"
            f"`{PREFIX}obfuscate Strong`\n"
            f"`{PREFIX}obfuscate load Strong`"
        )
        return

    job_id = uuid.uuid4().hex[:12]
    work = TMP_ROOT / job_id
    work.mkdir(parents=True, exist_ok=True)
    source = work / f"{clean_name(attachment.filename)}.lua"
    output = work / f"{clean_name(attachment.filename)}.obfuscated.lua"

    try:
        await attachment.save(source)
        await message.channel.typing()
        status = await message.reply(f"Obfuscating `{attachment.filename}` with **{preset}**…")

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, run_prometheus, source, output, preset)
        except Exception as exc:
            await status.edit(content=f"❌ Obfuscation failed:\n{exc}")
            return

        if not output.exists() or output.stat().st_size == 0:
            await status.edit(content="❌ Prometheus completed but produced an empty output file.")
            return

        if mode == "load":
            data = output.read_bytes()
            unique = f"{clean_name(attachment.filename)}-{uuid.uuid4().hex[:10]}.lua"
            try:
                raw_url = await github_publish(data, unique)
            except Exception as exc:
                await status.edit(content=f"❌ Obfuscated successfully, but GitHub publishing failed:\n{exc}")
                await message.channel.send(file=discord.File(output, filename=output.name))
                return

            loadstring = f'loadstring(game:HttpGet("{raw_url}"))()'
            await status.edit(content="✅ Obfuscated and published to GitHub.")
            await message.reply(
                f"```lua\n{loadstring}\n```\n"
                f"Preset: **{preset}**\n"
                f"GitHub file: `{unique}`"
            )
        else:
            await status.edit(content="✅ Obfuscation complete.")
            await message.reply(file=discord.File(output, filename=output.name))
    finally:
        shutil.rmtree(work, ignore_errors=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id={bot.user.id})")
    print(f"Prefix: {PREFIX} | Default preset: {DEFAULT_PRESET}")


@bot.command(name="obfuscate", aliases=["obf"])
async def obfuscate(ctx: commands.Context, *args: str):
    await process_message(ctx.message, list(args))


@bot.command(name="obfuscator", aliases=["obfhelp"])
async def obfuscator_help(ctx: commands.Context):
    await ctx.reply(
        f"**Prometheus Obfuscator**\n\n"
        f"Attach one `.lua` file and use:\n"
        f"`{PREFIX}obfuscate` → obfuscate and return the file\n"
        f"`{PREFIX}obfuscate load` → obfuscate, publish to GitHub, return a loadstring\n"
        f"`{PREFIX}obfuscate Strong` → use the Strong preset\n"
        f"`{PREFIX}obfuscate load Strong` → publish Strong output\n\n"
        f"Presets: Minify, Weak, Vmify, Medium, Strong\n"
        f"Default: {DEFAULT_PRESET}"
    )


async def health(request):
    return web.json_response({"ok": True, "discord_ready": bot.is_ready()})


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Health server listening on 0.0.0.0:{PORT}")
    return runner


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not configured.")
    if DEFAULT_PRESET not in ALLOWED_PRESETS:
        raise RuntimeError(f"DEFAULT_PRESET must be one of: {', '.join(sorted(ALLOWED_PRESETS))}")
    if not CLI.exists():
        raise RuntimeError("Prometheus cli.lua was not found in ./prometheus")
    if not PROM_CONFIG.exists():
        raise RuntimeError("Prometheus installation is incomplete: ./prometheus/src/config.lua is missing. Re-upload the complete prometheus/ directory from the project ZIP.")
    runner = await start_health_server()
    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
