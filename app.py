import os
import telebot
from flask import Flask, request
import yt_dlp

API_TOKEN = "8142769913:AAGKzD793hjAWaYcKrmYiUJD_P-sQGdxFHw"
WEBHOOK_URL = "https://hostingbot-dccp.onrender.com"

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Welcome! Use /search <song or video name> to find YouTube videos.")

@bot.message_handler(commands=['search'])
def search(message):
    query = message.text[8:].strip()
    if not query:
        bot.reply_to(message, "Please provide search keywords, e.g. /search coldplay viva la vida")
        return

    ydl_opts = {'quiet': True, 'skip_download': True, 'format': 'bestaudio/best'}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch5:{query}", download=False)['entries']
    except Exception as e:
        bot.reply_to(message, f"Error searching YouTube: {e}")
        return

    response = "Top 5 results:\n\n"
    for i, video in enumerate(results):
        title = video['title'][:50]
        url = f"https://youtu.be/{video['id']}"
        duration = video.get('duration', 0)
        minutes = duration // 60
        seconds = duration % 60
        response += f"{i+1}. {title} [{minutes}:{seconds:02d}]\n{url}\n\n"

    bot.reply_to(message, response)

@app.route('/' + API_TOKEN, methods=['POST'])
def webhook():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

@app.route('/')
def index():
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{API_TOKEN}")
    return "Webhook set", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
