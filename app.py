import os
import threading
import subprocess
import telebot
from flask import Flask, request
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time

TOKEN = "8142769913:AAGKzD793hjAWaYcKrmYiUJD_P-sQGdxFHw"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Store user uploads and threads
USER_SESSIONS = {}
UPLOAD_DIR = "runtime"
LOG_DIR = "logs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# === Helper Functions ===
def run_script(user_id, filepath, requirements):
    log_file = os.path.join(LOG_DIR, f"{user_id}.log")
    with open(log_file, 'w') as log:
        if requirements:
            try:
                log.write("Installing modules...\n")
                subprocess.check_call(["pip", "install"] + requirements.split(), stdout=log, stderr=log)
            except Exception as e:
                log.write(f"Module install error: {e}\n")

        def target():
            try:
                log.write(f"Running script: {filepath}\n")
                subprocess.call(["python3", filepath], stdout=log, stderr=log)
            except Exception as e:
                log.write(f"Runtime error: {e}\n")

        t = threading.Thread(target=target)
        USER_SESSIONS[user_id] = {"thread": t, "file": filepath}
        t.start()

# === Bot Handlers ===
@bot.message_handler(commands=["start"])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Upload Python File", callback_data="upload"),
        InlineKeyboardButton("My Hosts", callback_data="myhosts"),
    )
    bot.send_message(message.chat.id, "Welcome to Python Hosting Bot!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "upload":
        bot.send_message(call.message.chat.id, "Send me your `.py` file.")
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, handle_file_upload)
    elif call.data == "myhosts":
        session = USER_SESSIONS.get(call.from_user.id)
        markup = InlineKeyboardMarkup()
        if session:
            markup.add(
                InlineKeyboardButton("Stop", callback_data="stop"),
                InlineKeyboardButton("Redeploy", callback_data="redeploy"),
                InlineKeyboardButton("Logs", callback_data="logs")
            )
            bot.send_message(call.message.chat.id, f"You're hosting: `{session['file']}`", parse_mode='Markdown', reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, "You are not hosting any script.")

    elif call.data == "stop":
        session = USER_SESSIONS.get(call.from_user.id)
        if session and session["thread"].is_alive():
            bot.send_message(call.message.chat.id, "Stopping is not supported via thread (needs process control). Consider redeploying.")
        else:
            bot.send_message(call.message.chat.id, "No active thread found.")

    elif call.data == "redeploy":
        session = USER_SESSIONS.get(call.from_user.id)
        if session:
            run_script(call.from_user.id, session['file'], session.get('reqs', ''))
            bot.send_message(call.message.chat.id, "Redeployed successfully.")

    elif call.data == "logs":
        log_path = os.path.join(LOG_DIR, f"{call.from_user.id}.log")
        if os.path.exists(log_path):
            with open(log_path, 'rb') as f:
                bot.send_document(call.message.chat.id, f)
        else:
            bot.send_message(call.message.chat.id, "No logs available.")

def handle_file_upload(message):
    if message.document and message.document.file_name.endswith(".py"):
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = os.path.join(UPLOAD_DIR, f"{message.from_user.id}_{message.document.file_name}")
        with open(filename, 'wb') as f:
            f.write(downloaded)

        bot.send_message(message.chat.id, "Any Python modules to install? (Space separated, or type `none`)")
        bot.register_next_step_handler(message, lambda msg: after_requirements(msg, filename))
    else:
        bot.send_message(message.chat.id, "Please upload a valid `.py` file.")

def after_requirements(message, filepath):
    reqs = message.text.strip()
    if reqs.lower() == "none":
        reqs = ""
    USER_SESSIONS[message.from_user.id] = {"file": filepath, "reqs": reqs}
    run_script(message.from_user.id, filepath, reqs)
    bot.send_message(message.chat.id, f"Started hosting `{os.path.basename(filepath)}`", parse_mode="Markdown")

# === Flask Webhook ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "OK", 200

@app.route("/")
def index():
    return "Python Hosting Bot is running!"

# === Main Runner ===
if __name__ == "__main__":
    import sys
    port = int(os.environ.get('PORT', 5000))
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"hostingbot-dccp.onrender.com/{TOKEN}")
    app.run(host="0.0.0.0", port=port)
