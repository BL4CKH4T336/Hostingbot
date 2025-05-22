import os
import subprocess
import logging
import threading
import time
import json
from datetime import datetime
from flask import Flask, request, abort
import telebot
from telebot import types
import psutil

# Initialize
TOKEN = '8142769913:AAGKzD793hjAWaYcKrmYiUJD_P-sQGdxFHW'
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Configuration
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {'.py'}
LOG_DIR = 'logs'
TEMP_DIR = 'temp_files'
HOSTS_FILE = 'hosted_files.json'

# Setup directories and files
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
if not os.path.exists(HOSTS_FILE):
    with open(HOSTS_FILE, 'w') as f:
        json.dump({}, f)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'bot.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Helper functions
def load_hosted_files():
    with open(HOSTS_FILE, 'r') as f:
        return json.load(f)

def save_hosted_files(data):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(data, f)

def generate_log_filename(user_id):
    return f"user_{user_id}_{int(time.time())}.log"

def install_requirements(requirements, user_id):
    log_file = os.path.join(LOG_DIR, generate_log_filename(user_id))
    try:
        with open(log_file, 'a') as f:
            process = subprocess.Popen(
                ['pip', 'install'] + requirements.split(),
                stdout=f, stderr=f
            )
            process.wait()
        return True
    except Exception as e:
        logger.error(f"Error installing requirements: {e}")
        return False

def execute_python_file(file_path, user_id):
    log_file = os.path.join(LOG_DIR, generate_log_filename(user_id))
    process = subprocess.Popen(
        ['python', file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Store process info
    hosted = load_hosted_files()
    hosted[str(user_id)] = hosted.get(str(user_id), {})
    hosted[str(user_id)][file_path] = {
        'pid': process.pid,
        'start_time': datetime.now().isoformat(),
        'log_file': log_file,
        'status': 'running'
    }
    save_hosted_files(hosted)
    
    # Start thread to monitor process
    def monitor_process(proc, file_path, user_id):
        proc.wait()
        hosted = load_hosted_files()
        if str(user_id) in hosted and file_path in hosted[str(user_id)]:
            hosted[str(user_id)][file_path]['status'] = 'completed'
            hosted[str(user_id)][file_path]['end_time'] = datetime.now().isoformat()
            save_hosted_files(hosted)
    
    threading.Thread(target=monitor_process, args=(process, file_path, user_id)).start()
    return process

def stop_process(pid):
    try:
        process = psutil.Process(pid)
        for proc in process.children(recursive=True):
            proc.kill()
        process.kill()
        return True
    except psutil.NoSuchProcess:
        return False

def get_system_stats():
    cpu = psutil.cpu_percent()
    memory = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    return f"CPU: {cpu}% | Memory: {memory}% | Disk: {disk}%"

# Keyboard generators
def create_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        '📤 Host Python File',
        '📝 My Hosted Files',
        '📊 System Stats',
        '🛠️ Manage Hosts',
        'ℹ️ Help'
    ]
    keyboard.add(*[types.KeyboardButton(btn) for btn in buttons])
    return keyboard

def create_host_management_keyboard(user_id):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    hosted = load_hosted_files().get(str(user_id), {})
    
    for file_path, details in hosted.items():
        btn_text = f"{'▶️' if details['status'] == 'stopped' else '⏸️'} {os.path.basename(file_path)}"
        callback_data = f"restart_{file_path}" if details['status'] == 'stopped' else f"stop_{file_path}"
        keyboard.add(types.InlineKeyboardButton(
            text=btn_text,
            callback_data=callback_data
        ))
    
    keyboard.add(
        types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_hosts"),
        types.InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
    )
    return keyboard

def create_file_action_keyboard(file_path):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("📄 View Logs", callback_data=f"view_log_{file_path}"),
        types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{file_path}")
    )
    keyboard.row(
        types.InlineKeyboardButton("⏹️ Stop", callback_data=f"stop_{file_path}"),
        types.InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{file_path}")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_files"))
    return keyboard

# Bot handlers
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    abort(403)

@app.route('/')
def index():
    bot.remove_webhook()
    webhook_url = f'https://{os.environ.get("RENDER_EXTERNAL_HOSTNAME")}/{TOKEN}'
    bot.set_webhook(url=webhook_url)
    return "Python Hosting Bot is running!", 200

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_msg = """
🤖 *Python Hosting Bot* 🚀

*Features:*
- Host and run Python files
- Install required packages
- Manage running processes
- View execution logs
- Monitor system resources

Use the buttons below to navigate:
"""
    bot.send_message(
        message.chat.id,
        welcome_msg,
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == '📤 Host Python File')
def request_python_file(message):
    bot.send_message(
        message.chat.id,
        "⬆️ Please upload your Python file (.py)\nMax size: 5MB",
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(func=lambda msg: msg.text == '📝 My Hosted Files')
def show_hosted_files(message):
    hosted = load_hosted_files().get(str(message.from_user.id), {})
    if not hosted:
        bot.send_message(
            message.chat.id,
            "You don't have any hosted files yet.",
            reply_markup=create_main_keyboard()
        )
        return
    
    response = "📁 *Your Hosted Files*\n\n"
    for file_path, details in hosted.items():
        status_icon = "🟢" if details['status'] == 'running' else "🔴"
        response += f"{status_icon} *{os.path.basename(file_path)}* - {details['status']}\n"
    
    bot.send_message(
        message.chat.id,
        response,
        parse_mode='Markdown',
        reply_markup=create_host_management_keyboard(message.from_user.id)
    )

@bot.message_handler(func=lambda msg: msg.text == '📊 System Stats')
def show_system_stats(message):
    stats = get_system_stats()
    bot.send_message(
        message.chat.id,
        f"⚙️ *System Statistics*\n\n{stats}",
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(func=lambda msg: msg.text == '🛠️ Manage Hosts')
def manage_hosts(message):
    show_hosted_files(message)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not message.document.file_name.endswith('.py'):
        bot.send_message(
            message.chat.id,
            "❌ Only Python files (.py) are allowed.",
            reply_markup=create_main_keyboard()
        )
        return
    
    if message.document.file_size > MAX_FILE_SIZE:
        bot.send_message(
            message.chat.id,
            f"❌ File too large (max {MAX_FILE_SIZE/1024/1024}MB allowed).",
            reply_markup=create_main_keyboard()
        )
        return
    
    try:
        # Download file
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save file
        file_path = os.path.join(TEMP_DIR, f"user_{message.from_user.id}_{message.document.file_name}")
        with open(file_path, 'wb') as f:
            f.write(downloaded_file)
        
        # Ask for requirements
        msg = bot.send_message(
            message.chat.id,
            "📦 Any packages to install? (space separated)\nSend /skip if none",
            reply_markup=types.ForceReply()
        )
        bot.register_next_step_handler(msg, lambda m: handle_requirements(m, file_path))
    
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Error processing your file. Please try again.",
            reply_markup=create_main_keyboard()
        )

def handle_requirements(message, file_path):
    requirements = message.text if message.text != '/skip' else None
    
    # Create confirmation keyboard
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Start Hosting", callback_data=f"host_{file_path}_{requirements}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_hosting")
    )
    
    bot.send_message(
        message.chat.id,
        f"⚙️ *Hosting Setup*\n\n"
        f"📄 File: `{os.path.basename(file_path)}`\n"
        f"📦 Packages: `{requirements if requirements else 'None'}`\n\n"
        "Ready to start hosting?",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('host_'))
def start_hosting(call):
    _, file_path, requirements = call.data.split('_', 2)
    user_id = call.from_user.id
    
    # Install requirements if any
    if requirements:
        bot.edit_message_text(
            "Installing requirements...",
            call.message.chat.id,
            call.message.message_id
        )
        if not install_requirements(requirements, user_id):
            bot.send_message(
                call.message.chat.id,
                "❌ Failed to install requirements. Check logs for details.",
                reply_markup=create_main_keyboard()
            )
            return
    
    # Execute file
    bot.edit_message_text(
        "Starting your Python file...",
        call.message.chat.id,
        call.message.message_id
    )
    process = execute_python_file(file_path, user_id)
    
    bot.edit_message_text(
        f"✅ *Hosting Started*\n\n`{os.path.basename(file_path)}` is now running!",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    show_hosted_files(call.message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_'))
def stop_hosting(call):
    file_path = call.data.split('_', 1)[1]
    hosted = load_hosted_files()
    user_id = str(call.from_user.id)
    
    if user_id in hosted and file_path in hosted[user_id]:
        pid = hosted[user_id][file_path]['pid']
        if stop_process(pid):
            hosted[user_id][file_path]['status'] = 'stopped'
            save_hosted_files(hosted)
            bot.answer_callback_query(call.id, "Process stopped")
            show_hosted_files(call.message)
        else:
            bot.answer_callback_query(call.id, "Failed to stop process")
    else:
        bot.answer_callback_query(call.id, "File not found")

@bot.callback_query_handler(func=lambda call: call.data.startswith('restart_'))
def restart_hosting(call):
    file_path = call.data.split('_', 1)[1]
    hosted = load_hosted_files()
    user_id = str(call.from_user.id)
    
    if user_id in hosted and file_path in hosted[user_id]:
        # Stop existing process if running
        if hosted[user_id][file_path]['status'] == 'running':
            pid = hosted[user_id][file_path]['pid']
            stop_process(pid)
        
        # Start new process
        process = execute_python_file(file_path, call.from_user.id)
        bot.answer_callback_query(call.id, "Process restarted")
        show_hosted_files(call.message)
    else:
        bot.answer_callback_query(call.id, "File not found")

@bot.callback_query_handler(func=lambda call: call.data.startswith('view_log_'))
def view_logs(call):
    file_path = call.data.split('_', 1)[1]
    hosted = load_hosted_files()
    user_id = str(call.from_user.id)
    
    if user_id in hosted and file_path in hosted[user_id]:
        log_file = hosted[user_id][file_path]['log_file']
        try:
            with open(log_file, 'r') as f:
                content = f.read(4000)  # Limit to 4000 chars
            
            if len(content) >= 4000:
                content += "\n\n... (truncated, full log available as file)"
                bot.send_document(
                    call.message.chat.id,
                    open(log_file, 'rb'),
                    caption=f"Log for {os.path.basename(file_path)}"
                )
            
            bot.send_message(
                call.message.chat.id,
                f"📄 *Log for {os.path.basename(file_path)}*\n\n```\n{content}\n```",
                parse_mode='Markdown'
            )
        except Exception as e:
            bot.answer_callback_query(call.id, "Error reading log file")
    else:
        bot.answer_callback_query(call.id, "Log not found")

@bot.callback_query_handler(func=lambda call: call.data == 'refresh_hosts')
def refresh_hosts(call):
    show_hosted_files(call.message)

@bot.callback_query_handler(func=lambda call: call.data in ['back_to_main', 'cancel_hosting'])
def back_to_main(call):
    bot.edit_message_text(
        "🏠 Main Menu",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=create_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_files')
def back_to_files(call):
    show_hosted_files(call.message)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
