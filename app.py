import os
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# === Credentials & Config ===
BOT_TOKEN = "7893130831:AAFqjiwzUyXNQbNYuSt0rWT9Ex8J_S2qG9Y"
DEEPAI_KEY = "36e40954-0d98-4221-bcae-109ccfe95e2c"
ADMIN_ID = 6521162324  # Your Telegram ID
WEBHOOK_URL = "https://hostingbot-dcn4.onrender.com"

# === Flask app and Bot ===
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# === DeepAI API endpoints ===
deepai_urls = {
    "Text to Image": "https://api.deepai.org/api/text2img",
    "Upscale Image": "https://api.deepai.org/api/torch-srgan",
    "Colorize Image": "https://api.deepai.org/api/colorizer",
    "Cartoon Generator": "https://api.deepai.org/api/toonify",
    "NSFW Detection": "https://api.deepai.org/api/nsfw-detector",
    "Text Generator": "https://api.deepai.org/api/text-generator",
    "Style Transfer": "https://api.deepai.org/api/neural-style",
    "BigGAN Generator": "https://api.deepai.org/api/biggan",
    "Waifu Enhancer": "https://api.deepai.org/api/waifu2x",
    "Image Similarity": "https://api.deepai.org/api/image-similarity"
}

# === User State & Usage Limits ===
user_states = {}
usage_log = {}

# === Helper: Daily limit check ===
def check_user_limit(user_id):
    if user_id == ADMIN_ID:
        return True
    now = datetime.utcnow()
    data = usage_log.get(user_id, {"count": 0, "reset": now + timedelta(days=1)})
    if now > data["reset"]:
        data = {"count": 0, "reset": now + timedelta(days=1)}
    if data["count"] >= 10:
        return False
    data["count"] += 1
    usage_log[user_id] = data
    return True

# === Inline Keyboard ===
def main_menu():
    markup = InlineKeyboardMarkup()
    for label in deepai_urls:
        markup.add(InlineKeyboardButton(label, callback_data=label))
    return markup

# === Start Command ===
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Welcome to DeepAI Bot! Choose a feature:", reply_markup=main_menu())

# === Feature selection ===
@bot.callback_query_handler(func=lambda call: True)
def handle_buttons(call):
    user_id = call.from_user.id
    if not check_user_limit(user_id):
        bot.answer_callback_query(call.id, "Limit reached. Try again tomorrow.")
        return
    feature = call.data
    user_states[user_id] = feature

    if feature in ["Text to Image", "Text Generator", "BigGAN Generator"]:
        bot.send_message(user_id, f"Send the text for: {feature}")
    elif feature in ["Style Transfer", "Image Similarity"]:
        user_states[user_id] = {"feature": feature, "step": 1, "images": []}
        bot.send_message(user_id, f"Send image 1 of 2 for {feature}")
    else:
        bot.send_message(user_id, f"Send the image for: {feature}")

# === Handle messages ===
@bot.message_handler(content_types=['text', 'photo'])
def handle_input(message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return bot.reply_to(message, "Please choose a feature using /start")

    state = user_states[user_id]
    feature = state if isinstance(state, str) else state["feature"]

    # Text-based APIs
    if feature in ["Text to Image", "Text Generator", "BigGAN Generator"]:
        if message.content_type != 'text':
            return bot.reply_to(message, "Please send text input.")
        payload = {'text': message.text}
        response = requests.post(deepai_urls[feature], data=payload, headers={'api-key': DEEPAI_KEY})
        out = response.json()
        if 'output_url' in out:
            bot.send_photo(user_id, out['output_url'])
        else:
            bot.send_message(user_id, out.get('output', 'Failed.'))
        user_states.pop(user_id, None)
        return

    # 2-Image APIs
    elif feature in ["Style Transfer", "Image Similarity"]:
        if message.content_type != 'photo':
            return bot.reply_to(message, "Please send an image.")
        file_info = bot.get_file(message.photo[-1].file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        state["images"].append(image_url)
        if state["step"] == 1:
            state["step"] = 2
            bot.send_message(user_id, "Now send image 2")
        else:
            files = {'image1': requests.get(state["images"][0], stream=True).raw,
                     'image2': requests.get(state["images"][1], stream=True).raw}
            response = requests.post(deepai_urls[feature], files=files, headers={'api-key': DEEPAI_KEY})
            out = response.json()
            if 'output_url' in out:
                bot.send_photo(user_id, out['output_url'])
            else:
                bot.send_message(user_id, str(out))
            user_states.pop(user_id, None)
        return

    # Image-only APIs
    elif message.content_type == 'photo':
        file_info = bot.get_file(message.photo[-1].file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        file_data = requests.get(image_url, stream=True).raw
        response = requests.post(deepai_urls[feature], files={'image': file_data}, headers={'api-key': DEEPAI_KEY})
        out = response.json()
        if 'output_url' in out:
            bot.send_photo(user_id, out['output_url'])
        elif 'output' in out:
            bot.send_message(user_id, out['output'])
        else:
            bot.send_message(user_id, "Something went wrong.")
        user_states.pop(user_id, None)
        return
    else:
        bot.send_message(user_id, "Unsupported content.")

# === Flask route for webhook ===
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '', 200

# === Home route for Render health check ===
@app.route('/')
def home():
    return 'DeepAI Telegram Bot is running.'

# === Run & set webhook ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=port)
