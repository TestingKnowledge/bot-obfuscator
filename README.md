# Prometheus Discord Obfuscator

Discord bot that runs the bundled Prometheus 0.2.8 obfuscator against an attached Lua/Luau file.

## Commands

Attach one `.lua` file to the Discord message.

```text
.obfuscate
.obfuscate Medium
.obfuscate Strong
.obfuscate load
.obfuscate load Strong
```

`.obfuscate` returns the obfuscated Lua file.

`.obfuscate load` obfuscates the file, publishes it to the configured GitHub repository, and returns:

```lua
loadstring(game:HttpGet("https://raw.githubusercontent.com/OWNER/REPO/main/obfuscated/FILE.lua"))()
```

Available presets: `Minify`, `Weak`, `Vmify`, `Medium`, `Strong`.

## 1. Create the Discord bot

Create an application in the Discord Developer Portal, add a bot, and copy its token.

Enable the **Message Content Intent** under the bot's privileged gateway intents.

Invite the bot with the permissions needed to read messages, read message history, send messages, and attach files.

## 2. Create the GitHub repository

For `load` mode, the repository should be **public**, because the generated raw URL is fetched without GitHub authentication.

Create a fine-grained GitHub token with access to the target repository and **Contents: Read and write** permission.

Do not put the token in source code.

## 3. Local test

Install Docker, then:

```bash
docker build -t prometheus-discord-obfuscator .
```

Run it with environment variables:

```bash
docker run --rm -p 10000:10000 \
  -e DISCORD_TOKEN="YOUR_DISCORD_TOKEN" \
  -e GITHUB_TOKEN="YOUR_GITHUB_TOKEN" \
  -e GITHUB_REPO="OWNER/REPO" \
  prometheus-discord-obfuscator
```

Health check:

```text
http://localhost:10000/health
```

## 4. Deploy to Render

Push this folder to GitHub, then create a Render service from the repository. Render can use the included `render.yaml` and `Dockerfile`.

Set the secret environment variables in Render:

- `DISCORD_TOKEN`
- `GITHUB_TOKEN`
- `GITHUB_REPO`

The other variables already have defaults in `render.yaml`.

Render supplies `PORT` automatically.

## 5. UptimeRobot

After Render gives the service a public URL, create an HTTP monitor for:

```text
https://YOUR-RENDER-SERVICE.onrender.com/health
```

A successful response is JSON similar to:

```json
{"ok":true,"discord_ready":true}
```

The health endpoint only verifies that the web process is running and whether the Discord client is ready; it does not replace Discord's gateway connection.

## Prometheus attribution

This project bundles Prometheus 0.2.8. Prometheus's license requires attribution for a hosted wrapper/service. Keep the included `prometheus/LICENSE` file and this attribution:

> Based on Prometheus by Elias Oelschner, https://github.com/prometheus-lua/Prometheus

Prometheus 0.2.8 reports that LuaU support is not finished, so test the resulting scripts before relying on them.
