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
    response = requests.get(url)
    if response.status_code == 200:
        fields = response.json().get("fields", {})
        return {
            "user_id": fields.get("user_id", {}).get("stringValue"),
            "name": fields.get("name", {}).get("stringValue"),
            "username": fields.get("username", {}).get("stringValue"),
            "balance": float(fields.get("balance", {}).get("doubleValue" if "doubleValue" in fields.get("balance", {}) else "integerValue", 0))
        }
    return None

def register_user(user_id, name, username):
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": name},
            "username": {"stringValue": username or "No_Username"},
            "balance": {"doubleValue": 5.0}
        }
    }
    requests.patch(url, json=payload)
    return {"user_id": str(user_id), "name": name, "username": username or "No_Username", "balance": 5.0}

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
            "bp": {"stringValue": bp},
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
            response = requests.get(url)
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
    welcome_msg = "🎁 Aapko ₹5 Free Welcome Bonus credit kar diya gaya hai!\n\n" if welcome else ""
    dashboard = f"""
{welcome_msg}👋 **Hello, {data.get('name')}!**

💰 **Wallet Balance:** ₹{data.get('balance')}
📋 **Rate:** ₹10 per Consumer Search

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
        
    if data.get("balance", 0.0) < 10.0:
        bot.reply_to(message, f"❌ Aapka balance insufficient hai (₹{data.get('balance')}). Search ke liye kam se kam ₹10 hone chahiye.")
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
    bot.reply_to(message, "📊 Is CA number ke aage aapko **kitni quantity** (serial sequence) autofill karni hai? (E.g. 5, 10, 50):")

@bot.message_handler(func=lambda msg: msg.text == "🔴 Cancel Search" and msg.from_user.id in active_searches)
def cancel_ongoing_search(message):
    user_id = message.from_user.id
    active_searches[user_id] = False
    bot.reply_to(message, "⏳ Request received. Bulk search ko beech me cancel kiya ja raha hai, please wait...")


# ================= HIGH-SPEED PARALLEL SEARCH WITH MILESTONE PROGRESS =================
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

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "waiting_qty")
def process_autofill_and_search(message):
    user_id = message.from_user.id
    qty_text = message.text.strip()
    
    if not qty_text.isdigit() or int(qty_text) < 1:
        bot.reply_to(message, "❌ Valid integer quantity dalein (Minimum 1):")
        return
        
    qty = int(qty_text)
    state = user_states.get(user_id)
    base_ca = state["base_ca"]
    
    ca_list = [str(base_ca + i) for i in range(qty)]
    user_states.pop(user_id, None)
    
    user_data = get_user_data(user_id)
    current_balance = user_data.get("balance", 0.0)
    max_possible_searches = int(current_balance // 10.0)
    
    if max_possible_searches == 0:
        bot.reply_to(message, "❌ Aapke wallet me minimum 1 search (₹10) ke liye bhi balance nahi hai.")
        return
        
    if qty > max_possible_searches:
        bot.send_message(message.chat.id, f"⚠️ Aapne {qty} requests ki hain, par aapke balance (₹{current_balance}) ke mutabik sirf **{max_possible_searches}** records process ho payenge.")
        ca_list = ca_list[:max_possible_searches]
    
    cancel_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_markup.add("🔴 Cancel Search")
    
    # Initial status
    status_msg = bot.send_message(
        message.chat.id, 
        f"⚡ High-speed server initiating...\n📥 Progress: [░░░░░░░░░░] 0% (0/{len(ca_list)})", 
        reply_markup=cancel_markup
    )
    
    active_searches[user_id] = True
    bulk_results = []
    deducted_total = 0
    cancelled_by_user = False

    # ULTRA-SPEED: Ek sath 10 requests parallel chalengi!
    num_workers = min(len(ca_list), 10) 
    raw_api_responses = {}
    
    def make_progress_bar(percent):
        slices = int(percent // 10)
        filled = "█" * slices
        empty = "░" * (10 - slices)
        return f"[{filled}{empty}]"

    completed_count = 0
    
    # Jis milestone edits par report trigger hoga
    milestones = [5, 20, 50, 75, 95, 100]
    triggered_milestones = set()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        if not active_searches.get(user_id, True):
            cancelled_by_user = True
        else:
            futures = {executor.submit(fetch_single_ca_data, ca): ca for ca in ca_list}
            
            for future in as_completed(futures):
                if not active_searches.get(user_id, True):
                    cancelled_by_user = True
                    break
                
                ca_num, api_data = future.result()
                raw_api_responses[ca_num] = api_data
                completed_count += 1
                
                # Percentage calculation
                percent = int((completed_count / len(ca_list)) * 100)
                
                # Milestone check: find if percent crossed any milestones not yet triggered
                for m in milestones:
                    if percent >= m and m not in triggered_milestones:
                        triggered_milestones.add(m)
                        p_bar = make_progress_bar(percent)
                        try:
                            bot.edit_message_text(
                                chat_id=message.chat.id,
                                message_id=status_msg.message_id,
                                text=f"⚡ Processing data parallelly...\n📥 Progress: {p_bar} {percent}% ({completed_count}/{len(ca_list)})"
                            )
                        except Exception:
                            pass
                        break

    if cancelled_by_user:
        active_searches.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Bulk search cancel kar di gayi.")
        return

    # Succeeded responses compile karna aur balance deduct karna
    for ca in ca_list:
        fresh_data = get_user_data(user_id)
        fresh_bal = fresh_data.get("balance", 0.0) if fresh_data else 0.0
        
        if fresh_bal < 10.0:
            bot.send_message(message.chat.id, "❌ Wallet balance limit reached! Kuch data process nahi ho paya.")
            break
            
        new_balance = fresh_bal - 10.0
        update_balance(user_id, new_balance)
        deducted_total += 10
        add_history_log(user_id, 10.0, "Bot Bulk Search", ca)
        
        d = raw_api_responses.get(ca, {})
        
        row = {
            "Name": d.get("Name", "Not Found"),
            "Mobile_No": d.get("Mobile_No", "Not Found"),
            "Email": d.get("Email", "Not Found"),
            "Contract_Account": d.get("Contract_Account", ca),
            "Partner": d.get("Partner", "null"),
            "Legacy_CRN": d.get("Legacy_CRN", "0"),
            "Plot_No": d.get("Plot_No", ""),
            "Flat_No": d.get("Flat_No", ""),
            "Floor": d.get("Floor", ""),
            "Wing": d.get("Wing", ""),
            "Bldg_Name": d.get("Bldg_Name", ""),
            "Colony": d.get("Colony", ""),
            "Road_name": d.get("Road_name", ""),
            "Land_Mark": d.get("Land_Mark", ""),
            "Location": d.get("Location", ""),
            "City": d.get("City", ""),
            "Postal_code": d.get("Postal_code", ""),
            "Tel_No": d.get("Tel_No", ""),
            "Drs": d.get("Drs", ""),
            "Amount": d.get("Amount", ""),
            "Due_Date": d.get("Due_Date", ""),
            "Bill_Date": d.get("Bill_Date", ""),
            "Dispatch_Date": d.get("Dispatch_Date", ""),
            "Meter_No": d.get("Meter_No", "null"),
            "VIP": d.get("VIP", ""),
            "Modify_date": d.get("Modify_date", ""),
            "Create_date": d.get("Create_date", ""),
            "Bill_mon": d.get("Bill_mon", ""),
            "Opening": d.get("Opening", ""),
            "Closing": d.get("Closing", ""),
            "Bill_no": d.get("Bill_no", ""),
            "Sr_no": d.get("Sr_no", ""),
            "Conn_Obj": d.get("Conn_Obj", ""),
            "BP_CreateDt": d.get("BP_CreateDt", ""),
            "Bill