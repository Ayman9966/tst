# 💰 Expense Manager Bot

A professional Telegram bot for tracking income and expenses with minimal typing.

## Features

- **Live Master Message** — Balance + last 5 transactions always visible
- **Auto-Confirm** — No confirmation step, instant save
- **Clean Chat** — User messages auto-deleted, only master message remains
- **Delete Records** — Tap any transaction to remove it
- **Export Data** — CSV export of all transactions

## Deploy to Render

### 1. Fork this repo to your GitHub

### 2. Create a Bot
- Message [@BotFather](https://t.me/BotFather) on Telegram
- Send `/newbot` and follow instructions
- Copy your **Bot Token**

### 3. Deploy on Render
1. Go to [render.com](https://render.com) → **New Web Service**
2. Connect your GitHub repo
3. Set **Environment Variables**:
   - `BOT_TOKEN` = your token from BotFather
   - `RENDER_EXTERNAL_URL` = your Render service URL (e.g., `https://your-bot.onrender.com`)
4. **Build Command**: `pip install -r requirements.txt`
5. **Start Command**: `python bot.py`
6. Deploy!

### 4. Set Webhook (auto on startup, or manual)
The bot auto-sets the webhook on startup. If not, visit:
```
https://your-bot.onrender.com/set_webhook
```

### 5. Test
Open Telegram, find your bot, send `/start`

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `RENDER_EXTERNAL_URL` | Yes | Your Render service URL |
| `PORT` | No | Port (default: 10000) |

## Local Development

```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token"
export RENDER_EXTERNAL_URL="http://localhost:10000"
python bot.py
```

Then visit `http://localhost:10000/set_webhook` to set the webhook locally.
