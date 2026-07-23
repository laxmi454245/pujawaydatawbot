import os
import telebot
import requests
import pandas as pd
import time
import json
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= CONFIGURATIONS =================
BOT_TOKEN = "8888346751:AAHBjv-VX3JIcBo68brML3opH1gw7hq6W-g"
ADMIN_ID = 8184803370
FIREBASE_PROJECT_ID = "ss22-a96d3"

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=50)

# User state tracker (Temp Memory)
user_states = {}
active_searches = {}

# ================= FIREBASE REST API HELPERS =================
BASE_DB_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

def get_user_data(user_id):
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            fields = response.json().get("fields", {})
            return {
                "user_id": fields.get("user_id", {}).get("stringValue"),
                "name": fields.get("name", {}).get("stringValue"),
                "username": fields.get("username", {}).get("stringValue"),
                "balance": float(fields.get("balance", {}).get("doubleValue" if "doubleValue" in fields.get("balance", {}) else "integerValue", 0))
            }
    except Exception as e:
        print(f"Error fetching user data: {e}")
    return None

def register_user(user_id, name, username):
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": name},
            "username": {"stringValue": username or "No_Username"},
            "balance": {"doubleValue": 12.0}
        }
    }
    requests.patch(url, json=payload)
    return {"user_id": str(user_id), "name": name, "username": username or "No_Username", "balance": 12.0}

def update_balance(user_id, new_balance):
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    current_data = get_user_data(user_id)
    if not current_data: return False
    
    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": current_data["name"]},
            "username": {"stringValue": current_data["username"]},
            "balance": {"doubleValue": float(new_balance)}
        }
    }
    requests.patch(url, json=payload)
    return True

def add_history_log(user_id, amount, reason, bp):
    url = f"{BASE_DB_URL}/bot_users/{user_id}/history"
    current_ms_time = int(time.time() * 1000)
    payload = {
        "fields": {
            "type": {"stringValue": "deduct"},
            "amount": {"doubleValue": float(amount)},
            "reason": {"stringValue": reason},
            "bp": {"stringValue": str(bp)},
            "time": {"integerValue": current_ms_time}
        }
    }
    requests.post(url, json=payload)

def save_search_history_to_firestore(user_id, name, base_ca, qty, excel_data_list):
    url = f"{BASE_DB_URL}/search_history"
    
    formatted_rows = []
    for row in excel_data_list:
        map_value = {}
        for k, v in row.items():
            map_value[k] = {"stringValue": str(v)}
        formatted_rows.append({"mapValue": {"fields": map_value}})

    current_ms_time = int(time.time() * 1000)
    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": name},
            "base_ca": {"stringValue": str(base_ca)},
            "quantity": {"integerValue": int(qty)},
            "timestamp": {"integerValue": current_ms_time},
            "excel_data": {
                "arrayValue": {
                    "values": formatted_rows
                }
            }
        }
    }
    requests.post(url, json=payload)

# ================= BACKGROUND FIREBASE RESEND LISTENER =================
def run_resend_checker_loop():
    while True:
        try:
            url = f"{BASE_DB_URL}/resend_requests"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                documents = response.json().get("documents", [])
                for doc in documents:
                    doc_id = doc.get("name", "").split("/")[-1]
                    fields = doc.get("fields", {})
                    status = fields.get("status", {}).get("stringValue", "pending")
                    
                    if status == "pending":
                        target_user_id = fields.get("user_id", {}).get("stringValue")
                        base_ca = fields.get("base_ca", {}).get("stringValue")
                        date_time = fields.get("date_time", {}).get("stringValue")
                        raw_excel_string = fields.get("excel_data", {}).get("stringValue")
                        
                        if target_user_id and raw_excel_string:
                            try:
                                parsed_data = json.loads(raw_excel_string)
                                df = pd.DataFrame(parsed_data)
                                
                                temp_file = f"Resend_Report_{target_user_id}.xlsx"
                                df.to_excel(temp_file, index=False)
                                
                                final_data = get_user_data(target_user_id)
                                final_bal = final_data.get("balance", 0.0) if final_data else 0.0
                                
                                caption_text = f"""🔁 **Re-Sent Report (Admin Action):**
📊 **Invoice / Report Summary:**
🕒 **Date time:** `{date_time}`
💬 **Chat id:** `{target_user_id}`
🔢 **Ca number:** `{base_ca}`

📈 Total Processed: `{len(df)}` items
💰 Current Balance: `₹{final_bal}`"""
                                
                                with open(temp_file, "rb") as file:
                                    bot.send_document(
                                        target_user_id, 
                                        file, 
                                        caption=caption_text,
                                        parse_mode="Markdown"
                                    )
                                    
                                if os.path.exists(temp_file):
                                    os.remove(temp_file)
                                    
                            except Exception as parse_err:
                                print(f"Resend Compilation Error: {parse_err}")
                                
                        delete_url = f"{BASE_DB_URL}/resend_requests/{doc_id}"
                        requests.delete(delete_url)
                        
        except Exception as loop_err:
            print(f"Resend loop runtime issue: {loop_err}")
        time.sleep(5)

resend_thread = threading.Thread(target=run_resend_checker_loop, daemon=True)
resend_thread.start()

# ================= TELEGRAM ADMIN COMMANDS =================
@bot.message_handler(commands=['admin'])
def admin_help(message):
    if message.from_user.id != ADMIN_ID: return
    help_text = """
👑 **Admin Control Panel**

🔹 **Balance Add:** `/add [User_ID] [Amount]`
🔹 **Balance Deduct:** `/deduct [User_ID] [Amount]`
🔹 **User Info:** `/info [User_ID]`
"""
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_balance(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        target_id = parts[1]
        amount = float(parts[2])
        
        data = get_user_data(target_id)
        if not data:
            bot.reply_to(message, "❌ User database me nahi mila.")
            return
            
        new_bal = data["balance"] + amount
        update_balance(target_id, new_bal)
        
        bot.reply_to(message, f"✅ User {target_id} me ₹{amount} add ho gaye.\nNaya Balance: ₹{new_bal}")
        try:
            bot.send_message(target_id, f"💰 Admin ne aapke wallet me ₹{amount} add kiye hain!\n**Naya Balance:** ₹{new_bal}", parse_mode="Markdown")
        except: pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['deduct'])
def deduct_balance(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        target_id = parts[1]
        amount = float(parts[2])
        
        data = get_user_data(target_id)
        if not data:
            bot.reply_to(message, "❌ User database me nahi mila.")
            return
            
        new_bal = max(0.0, data["balance"] - amount)
        update_balance(target_id, new_bal)
        
        bot.reply_to(message, f"📉 User {target_id} se ₹{amount} kaat liye gaye.\nNaya Balance: ₹{new_bal}")
        try:
            bot.send_message(target_id, f"📉 Aapke wallet se ₹{amount} deduct kiye gaye hain.\n**Naya Balance:** ₹{new_bal}", parse_mode="Markdown")
        except: pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['info'])
def user_info(message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = message.text.split()[1]
        data = get_user_data(target_id)
        if not data:
            bot.reply_to(message, "❌ User records nahi mile.")
            return
        info = f"""
👤 **User Details:**
ID: `{data.get('user_id')}`
Name: {data.get('name')}
Username: @{data.get('username')}
💰 Balance: ₹{data.get('balance')}
"""
        bot.reply_to(message, info, parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ Kripya ID sahi se dalein: `/info [User_ID]`")

# ================= USER REGISTRATION & FLOW =================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    data = get_user_data(user_id)
    if not data:
        if not username:
            bot.reply_to(message, "👋 Welcome! Aapka Telegram Username set nahi hai. Kripya register karne ke liye apna **Pura Naam** likh kar bhejiye:")
            user_states[user_id] = {"step": "waiting_name"}
        else:
            data = register_user(user_id, first_name, username)
            send_dashboard(message, data, welcome=True)
    else:
        send_dashboard(message, data)

def send_dashboard(message, data, welcome=False):
    welcome_msg = "🎁 Aapko ₹12 Free Welcome Bonus credit kar diya gaya hai!\n\n" if welcome else ""
    dashboard = f"""
{welcome_msg}👋 **Hello, {data.get('name')}!**

💰 **Wallet Balance:** ₹{data.get('balance')}
📋 **Rate:** ₹12 per Valid Consumer Search

🔎 Bulk search start karne ke liye niche diya gaya button dabayein ya direct `/search` type karein.
"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔎 Start Bulk Search", "💰 Check Balance")
    bot.send_message(message.chat.id, dashboard, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "💰 Check Balance")
def check_balance_btn(message):
    data = get_user_data(message.from_user.id)
    if data:
        bot.reply_to(message, f"💰 Aapka current wallet balance hai: **₹{data.get('balance')}**", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "🔎 Start Bulk Search" or msg.text == "/search")
def ask_ca_number(message):
    user_id = message.from_user.id
    data = get_user_data(user_id)
    if not data:
        bot.reply_to(message, "⚠️ Pehle `/start` karke register karein.")
        return
        
    if data.get("balance", 0.0) < 12.0:
        bot.reply_to(message, f"❌ Aapka balance insufficient hai (₹{data.get('balance')}). Search ke liye kam se kam ₹12 hone chahiye.")
        return
        
    bot.send_message(message.chat.id, "🔢 Kripya pehla **CA / BP Number** enter karein:")
    user_states[user_id] = {"step": "waiting_ca"}

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "waiting_name")
def register_without_username(message):
    user_id = message.from_user.id
    name = message.text.strip()
    if len(name) < 3:
        bot.reply_to(message, "❌ Name bohot chota hai, please sahi naam enter karein:")
        return
    data = register_user(user_id, name, "No_Username")
    user_states.pop(user_id, None)
    send_dashboard(message, data, welcome=True)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "waiting_ca")
def get_ca_and_ask_qty(message):
    user_id = message.from_user.id
    ca_no = message.text.strip()
    
    if not ca_no.isdigit():
        bot.reply_to(message, "❌ Invalid CA number! Sirf numbers enter karein:")
        return
    
    if len(ca_no) > 12:
        bot.reply_to(message, "❌ Request Failed! CA / BP Number 12 digit se zyada bada nahi ho sakta. Kripya dobara koshish karein:")
        return
        
    user_states[user_id] = {
        "step": "waiting_qty",
        "base_ca": int(ca_no)
    }
    bot.reply_to(message, "📊 Aapko **kitne valid (Mobile_New wale) records** chahiye? (E.g. 5, 10, 50):")

@bot.message_handler(func=lambda msg: msg.text == "🔴 Cancel Search" and msg.from_user.id in active_searches)
def cancel_ongoing_search(message):
    user_id = message.from_user.id
    active_searches[user_id] = False
    bot.reply_to(message, "⏳ Request received. Bulk search ko beech me cancel kiya ja raha hai, please wait...")

# ================= SINGLE FETCH FUNCTION =================
def fetch_single_ca_data(ca):
    """Single API hit function for parallel threading"""
    try:
        api_url = f"https://billguru.kzthubbjdo.workers.dev/?ca_no={ca}"
        response = requests.get(api_url, timeout=8)
        if response.status_code == 200:
            raw_res = response.json()
            return ca, raw_res.get("data", {})
    except Exception as e:
        print(f"Error fetching CA {ca}: {e}")
    return ca, {}

# ================= CONTINUOUS PARALLEL SEARCH UNTIL TARGET REACHED =================
@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "waiting_qty")
def process_autofill_and_search(message):
    user_id = message.from_user.id
    qty_text = message.text.strip()
    
    if not qty_text.isdigit() or int(qty_text) < 1:
        bot.reply_to(message, "❌ Valid integer quantity dalein (Minimum 1):")
        return
        
    required_valid_qty = int(qty_text)
    state = user_states.get(user_id)
    base_ca = state["base_ca"]
    user_states.pop(user_id, None)
    
    cancel_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_markup.add("🔴 Cancel Search")
    
    status_msg = bot.send_message(
        message.chat.id, 
        f"⚡ Searching for Valid Records...\n✅ Valid: 0/{required_valid_qty} | ❌ Invalid: 0", 
        reply_markup=cancel_markup
    )
    
    active_searches[user_id] = True
    bulk_results = []
    deducted_total = 0
    invalid_count = 0
    current_ca_offset = 0
    cancelled_by_user = False
    last_update_time = time.time()

    # Dynamic loop running until target required_valid_qty is achieved
    while len(bulk_results) < required_valid_qty:
        if not active_searches.get(user_id, True):
            cancelled_by_user = True
            break
            
        # Check wallet before next batch
        user_data = get_user_data(user_id)
        current_bal = user_data.get("balance", 0.0) if user_data else 0.0
        if current_bal < 12.0:
            bot.send_message(message.chat.id, "⚠️ Wallet balance limit reached! Search complete process nahi ho payi.")
            break

        # Generate a small parallel chunk (10 requests at a time)
        batch_size = min(10, (required_valid_qty - len(bulk_results)) * 2)
        ca_batch = [str(base_ca + current_ca_offset + i) for i in range(batch_size)]
        current_ca_offset += batch_size

        batch_responses = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_single_ca_data, ca): ca for ca in ca_batch}
            for future in as_completed(futures):
                ca_num, api_data = future.result()
                batch_responses[ca_num] = api_data

        # Process batch results
        for ca in ca_batch:
            if not active_searches.get(user_id, True):
                cancelled_by_user = True
                break
                
            d = batch_responses.get(ca, {})
            mobile_new = d.get("Mobile_New")

            # VALIDITY CHECK: Mobile_New must be non-empty string
            if mobile_new and str(mobile_new).strip() != "" and str(mobile_new).strip().lower() != "null":
                # Re-verify Wallet & Deduct only for valid records
                user_data = get_user_data(user_id)
                current_bal = user_data.get("balance", 0.0) if user_data else 0.0
                if current_bal < 12.0:
                    bot.send_message(message.chat.id, "⚠️ Wallet balance finished during processing.")
                    break

                new_bal = current_bal - 12.0
                update_balance(user_id, new_bal)
                deducted_total += 12
                add_history_log(user_id, 12.0, "Bulk Search Valid Record", ca)

                # Exactly same layout & dynamic JSON structure as HTML Code
                row = {
                    "Name": d.get("Name", "Not Found"),                      # Col A
                    "Mobile_New": mobile_new,                                # Col B
                    "Email": d.get("Email", "Not Found"),                    # Col C
                    "Contract_Account": d.get("Contract_Account", ca),       # Col D
                    "Partner": d.get("Partner", "")                          # Col E
                }
                
                # Auto-fill remaining API fields dynamically in sequence
                for key, val in d.items():
                    if key not in row:
                        row[key] = val if val is not None else ""

                bulk_results.append(row)

                if len(bulk_results) >= required_valid_qty:
                    break
            else:
                invalid_count += 1

        # Smooth UI progress updates (throttled to avoid Telegram Rate Limits)
        if time.time() - last_update_time > 1.5:
            try:
                bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id,
                    text=f"⚡ Searching for Valid Records...\n✅ Valid: {len(bulk_results)}/{required_valid_qty} | ❌ Invalid: {invalid_count}",
                    reply_markup=cancel_markup
                )
                last_update_time = time.time()
            except Exception:
                pass

    active_searches.pop(user_id, None)

    dashboard_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    dashboard_markup.add("🔎 Start Bulk Search", "💰 Check Balance")

    if cancelled_by_user and len(bulk_results) == 0:
        bot.send_message(message.chat.id, "❌ Bulk search cancel kar di gayi.", reply_markup=dashboard_markup)
        return

    if len(bulk_results) == 0:
        bot.send_message(message.chat.id, "❌ Koi valid record (Mobile_New) nahi mila.", reply_markup=dashboard_markup)
        return

    try:
        user_data = get_user_data(user_id)
        user_display_name = user_data.get("name", "Unknown") if user_data else "Unknown"
        save_search_history_to_firestore(user_id, user_display_name, base_ca, len(bulk_results), bulk_results)
    except Exception as db_err:
        print(f"Firestore save error: {db_err}")

    # Export to Excel
    df = pd.DataFrame(bulk_results)
    file_name = f"Bulk_Bill_{user_id}_{int(time.time())}.xlsx"
    df.to_excel(file_name, index=False)

    final_data = get_user_data(user_id)
    final_bal = final_data.get("balance", 0.0) if final_data else 0.0
    ist_datetime = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

    caption_text = f"""✅ **Bulk Search Completed!**

📊 **Invoice / Report Summary:**
🕒 **Date time:** `{ist_datetime}`
💬 **Chat id:** `{user_id}`
🔢 **Base CA number:** `{base_ca}`

✅ **Valid Records:** `{len(bulk_results)}`
❌ **Invalid Records Skipped:** `{invalid_count}`
📉 **Wallet Deducted:** `₹{deducted_total}` (₹12/valid)
💰 **Remaining Balance:** `₹{final_bal}`"""

    with open(file_name, "rb") as file:
        bot.send_document(
            message.chat.id,
            file,
            caption=caption_text,
            parse_mode="Markdown",
            reply_markup=dashboard_markup
        )

    if os.path.exists(file_name):
        os.remove(file_name)

# ================= BOT RUNNER =================
if __name__ == "__main__":
    print("🤖 BABA MNGL Multi-threaded Bot running with Valid Record Logic...")
    bot.infinity_polling()