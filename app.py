import os
import subprocess
import logging
import tempfile
import threading
import time
from flask import Flask, request, abort
import telebot
from telebot import types
import traceback

# Initialize bot and Flask app
TOKEN = '8142769913:AAGKzD793hjAWaYcKrmYiUJD_P-sQGdxFHw'
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Configuration
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_EXTENSIONS = {'.py'}
LOG_DIR = 'logs'
TEMP_DIR = 'temp_files'

# Create necessary directories
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'bot.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# User sessions to store state
user_sessions = {}

# Helper functions
def is_allowed_file(filename):
    return any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS)

def generate_log_file_name(user_id):
    return f"user_{user_id}_{int(time.time())}.log"

def install_requirements(requirements, user_id):
    log_file = os.path.join(LOG_DIR, generate_log_file_name(user_id))
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

def execute_python_code(file_path, user_id):
    log_file = os.path.join(LOG_DIR, generate_log_file_name(user_id))
    try:
        with open(log_file, 'a') as f:
            process = subprocess.Popen(
                ['python', file_path],
                stdout=f, stderr=f
            )
            process.wait()
        return True
    except Exception as e:
        logger.error(f"Error executing Python file: {e}")
        return False

def get_user_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'state': None,
            'file_path': None,
            'requirements': None,
            'log_files': []
        }
    return user_sessions[user_id]

def create_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton('🏠 Main Menu'))
    keyboard.add(types.KeyboardButton('📤 Upload Python File'))
    keyboard.add(types.KeyboardButton('📝 View Logs'))
    keyboard.add(types.KeyboardButton('ℹ️ Help'))
    return keyboard

def create_logs_keyboard(user_id):
    session = get_user_session(user_id)
    keyboard = types.InlineKeyboardMarkup()
    for log_file in session.get('log_files', []):
        keyboard.add(types.InlineKeyboardButton(
            text=os.path.basename(log_file),
            callback_data=f"view_log_{log_file}"
        ))
    keyboard.add(types.InlineKeyboardButton(
        text="🔙 Back",
        callback_data="back_to_main"
    ))
    return keyboard

# Bot handlers
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    session = get_user_session(message.from_user.id)
    session['state'] = None
    
    welcome_text = """
🤖 *Welcome to Python Hosting Bot* 🤖

With this bot you can:
- Upload and run Python files
- Install required modules
- View execution logs
- Manage your scripts

*Available commands:*
/start - Show this message
/upload - Upload a Python file
/logs - View your execution logs
/help - Show help information

Use the buttons below to navigate easily!
    """
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == '🏠 Main Menu')
def main_menu(message):
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == '📤 Upload Python File')
def upload_python_file(message):
    session = get_user_session(message.from_user.id)
    session['state'] = 'awaiting_python_file'
    
    bot.send_message(
        message.chat.id,
        "⬆️ *Please upload your Python file* (.py)\n\n"
        "Max size: 5MB",
        parse_mode='Markdown',
        reply_markup=types.ReplyKeyboardRemove()
    )

@bot.message_handler(func=lambda message: message.text == '📝 View Logs')
def view_logs(message):
    session = get_user_session(message.from_user.id)
    if not session.get('log_files'):
        bot.send_message(
            message.chat.id,
            "📭 *No logs available*\n\n"
            "You haven't executed any files yet.",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return
    
    bot.send_message(
        message.chat.id,
        "📜 *Your Log Files*\n\n"
        "Select a log file to view:",
        parse_mode='Markdown',
        reply_markup=create_logs_keyboard(message.from_user.id)
    )

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Help')
def show_help(message):
    send_welcome(message)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    session = get_user_session(message.from_user.id)
    
    if session.get('state') != 'awaiting_python_file':
        bot.send_message(
            message.chat.id,
            "⚠️ *Invalid operation*\n\n"
            "Please use the menu to upload a file.",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return
    
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    
    if not is_allowed_file(file_name):
        bot.send_message(
            message.chat.id,
            "❌ *Invalid file type*\n\n"
            "Only Python files (.py) are allowed.",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        session['state'] = None
        return
    
    if message.document.file_size > MAX_FILE_SIZE:
        bot.send_message(
            message.chat.id,
            f"❌ *File too large*\n\n"
            f"Max size: {MAX_FILE_SIZE/1024/1024}MB",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        session['state'] = None
        return
    
    try:
        # Download the file
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save to temporary file
        file_path = os.path.join(TEMP_DIR, f"user_{message.from_user.id}_{file_name}")
        with open(file_path, 'wb') as f:
            f.write(downloaded_file)
        
        session['file_path'] = file_path
        session['state'] = 'awaiting_requirements'
        
        bot.send_message(
            message.chat.id,
            "✅ *File uploaded successfully!*\n\n"
            "📝 *Do you need to install any Python modules?*\n\n"
            "If yes, please send the module names separated by spaces (e.g., `requests numpy`)\n"
            "If no, send /skip",
            parse_mode='Markdown',
            reply_markup=types.ForceReply(selective=True)
        )
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        bot.send_message(
            message.chat.id,
            "❌ *Error uploading file*\n\n"
            "Please try again.",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        session['state'] = None

@bot.message_handler(func=lambda message: get_user_session(message.from_user.id).get('state') == 'awaiting_requirements')
def handle_requirements(message):
    session = get_user_session(message.from_user.id)
    
    if message.text.strip().lower() == '/skip':
        session['requirements'] = None
    else:
        session['requirements'] = message.text.strip()
    
    # Prepare execution
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text="▶️ Execute Now",
        callback_data="execute_now"
    ))
    keyboard.add(types.InlineKeyboardButton(
        text="❌ Cancel",
        callback_data="cancel_execution"
    ))
    
    bot.send_message(
        message.chat.id,
        "⚙️ *Execution Setup*\n\n"
        f"📄 *File:* `{os.path.basename(session['file_path'])}`\n"
        f"📦 *Modules to install:* `{session['requirements'] or 'None'}`\n\n"
        "Ready to execute?",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    session['state'] = None

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    user_id = call.from_user.id
    session = get_user_session(user_id)
    
    if call.data == 'execute_now':
        bot.answer_callback_query(call.id, "Starting execution...")
        
        # Create a new log file for this execution
        log_file = os.path.join(LOG_DIR, generate_log_file_name(user_id))
        session['log_files'].append(log_file)
        
        # Edit the message to show execution started
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🔄 *Execution Started*\n\n"
            "Your Python file is being executed. "
            "This may take some time depending on your code.\n\n"
            "You'll be notified when it's done.",
            parse_mode='Markdown'
        )
        
        # Execute in a separate thread to avoid blocking
        def execute_in_thread():
            try:
                # Install requirements if any
                if session.get('requirements'):
                    install_success = install_requirements(session['requirements'], user_id)
                    if not install_success:
                        bot.send_message(
                            call.message.chat.id,
                            "❌ *Error installing requirements*\n\n"
                            "Check the logs for details.",
                            parse_mode='Markdown',
                            reply_markup=create_main_keyboard()
                        )
                        return
                
                # Execute the Python file
                exec_success = execute_python_code(session['file_path'], user_id)
                
                # Send completion message
                if exec_success:
                    bot.send_message(
                        call.message.chat.id,
                        "✅ *Execution Completed*\n\n"
                        "Your Python file has been executed successfully!\n\n"
                        "You can now view the logs if you want to see the output.",
                        parse_mode='Markdown',
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.send_message(
                        call.message.chat.id,
                        "⚠️ *Execution Completed with Errors*\n\n"
                        "Your Python file was executed but encountered some errors.\n\n"
                        "Check the logs for details.",
                        parse_mode='Markdown',
                        reply_markup=create_main_keyboard()
                    )
                
                # Clean up the file
                try:
                    os.remove(session['file_path'])
                    session['file_path'] = None
                except:
                    pass
                
            except Exception as e:
                logger.error(f"Error during execution: {e}")
                bot.send_message(
                    call.message.chat.id,
                    "❌ *Critical Error During Execution*\n\n"
                    "Please try again later.",
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
        
        thread = threading.Thread(target=execute_in_thread)
        thread.start()
    
    elif call.data == 'cancel_execution':
        bot.answer_callback_query(call.id, "Execution cancelled")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ *Execution Cancelled*\n\n"
            "Your file was not executed.",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        try:
            if session.get('file_path') and os.path.exists(session['file_path']):
                os.remove(session['file_path'])
        except:
            pass
        session['file_path'] = None
        session['requirements'] = None
    
    elif call.data.startswith('view_log_'):
        log_file = call.data.split('_', 2)[2]
        try:
            with open(log_file, 'r') as f:
                content = f.read()
            
            if len(content) > 4000:  # Telegram message limit
                # Send as document if too large
                bot.send_document(
                    call.message.chat.id,
                    open(log_file, 'rb'),
                    caption=f"📄 Log file: {os.path.basename(log_file)}"
                )
            else:
                # Send as message
                bot.send_message(
                    call.message.chat.id,
                    f"📄 *Log file: {os.path.basename(log_file)}*\n\n"
                    f"```\n{content}\n```",
                    parse_mode='Markdown'
                )
            
            bot.answer_callback_query(call.id)
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            bot.answer_callback_query(
                call.id,
                "Error reading log file",
                show_alert=True
            )
    
    elif call.data == 'back_to_main':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="🏠 *Main Menu*",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )

# Flask routes for webhook
@app.route('/' + TOKEN, methods=['POST'])
def get_message():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        abort(403)

@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url='https://your-render-app-name.onrender.com/' + TOKEN)
    return "Bot is running!", 200

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
