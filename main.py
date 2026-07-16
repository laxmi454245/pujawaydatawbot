import os
import telebot
import requests
import pandas as pd

# ================= CONFIGURATIONS =================
BOT_TOKEN = "8888346751:AAHBjv-VX3JIcBo68brML3opH1gw7hq6W-g"          # <-- Yahan apna Telegram Bot Token dalein
ADMIN_ID = 8184803370                           # <-- Yahan apni numeric Telegram ID dalein (e.g. 987654321)
FIREBASE_PROJECT_ID = "ss22-a96d3"             # <-- Aapka Firebase Project ID

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=50)

# User state tracker (Temp Memory for steps)
user_states = {}

# ================= FIREBASE REST API HELPERS =================
# Bina kisi service-account JSON file ke direct database handle karne ke liye REST API
BASE_DB_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

def get_user_data(user_id):
    """Firestore se user profile aur balance check karne ke liye"""
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
    """Naye user ko automatic register aur ₹5 Welcome Bonus dene ke liye"""
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": name},
            "username": {"stringValue": username or "No_Username"},
            "balance": {"doubleValue": 5.0}  # ₹5 welcome bonus
        }
    }
    requests.patch(url, json=payload)
    return {"user_id": str(user_id), "name": name, "username": username or "No_Username", "balance": 5.0}

def update_balance(user_id, new_balance):
    """Database me balance safe update karne ke liye"""
    url = f"{BASE_DB_URL}/bot_users/{user_id}"
    current_data = get_user_data(user_id)
    if not current_data:
        return False
    
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
    """Har user ki dynamic transaction history log karne ke liye"""
    url = f"{BASE_DB_URL}/bot_users/{user_id}/history"
    payload = {
        "fields": {
            "type": {"stringValue": "deduct"},
            "amount": {"doubleValue": float(amount)},
            "reason": {"stringValue": reason},
            "bp": {"stringValue": bp},
            "time": {"integerValue": int(requests.get("https://showcase.api.linx.twenty-six-distribution.com/time").json().get("unixtime", 0)*1000)}
        }
    }
    requests.post(url, json=payload)

def save_search_history_to_firestore(user_id, name, base_ca, qty, excel_data_list):
    """Admin Panel me list dikhane aur backup download karne ke liye data save karna"""
    url = f"{BASE_DB_URL}/search_history"
    
    # Python dictionary (Excel Rows) ko Firestore format (REST API) me map karna
    formatted_rows = []
    for row in excel_data_list:
        map_value = {}
        for k, v in row.items():
            map_value[k] = {"stringValue": str(v)}
        formatted_rows.append({"mapValue": {"fields": map_value}})

    payload = {
        "fields": {
            "user_id": {"stringValue": str(user_id)},
            "name": {"stringValue": name},
            "base_ca": {"stringValue": str(base_ca)},
            "quantity": {"integerValue": int(qty)},
            "timestamp": {"integerValue": int(requests.get("https://showcase.api.linx.twenty-six-distribution.com/time").json().get("unixtime", 0)*1000)},
            "excel_data": {
                "arrayValue": {
                    "values": formatted_rows
                }
            }
        }
    }
    # Firebase Firestore me data add karein
    requests.post(url, json=payload)

# ================= TELEGRAM ADMIN COMMANDS =================
@bot.message_handler(commands=['admin'])
def admin_help(message):
    if message.from_user.id != ADMIN_ID: return
    help_text = """
👑 **Admin Control Panel**

🔹 **Balance Add Karein:**
`/add [User_ID] [Amount]`
_Example: /add 987654321 50_

🔹 **Balance Deduct Karein:**
`/deduct [User_ID] [Amount]`
_Example: /deduct 987654321 20_

🔹 **User Info Check:**
`/info [User_ID]`
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
        
    user_states[user_id] = {
        "step": "waiting_qty",
        "base_ca": int(ca_no)
    }
    bot.reply_to(message, "📊 Is CA number ke aage aapko **kitni quantity** (serial sequence) autofill karni hai? (E.g. 5, 10, 50):")

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
    
    # AUTOFILL: Serial sequence array generate karega line se
    ca_list = [str(base_ca + i) for i in range(qty)]
    user_states.pop(user_id, None) # state clean karein
    
    user_data = get_user_data(user_id)
    current_balance = user_data.get("balance", 0.0)
    max_possible_searches = int(current_balance // 10.0)
    
    if max_possible_searches == 0:
        bot.reply_to(message, "❌ Aapke wallet me minimum 1 search (₹10) ke liye bhi balance nahi hai.")
        return
        
    if qty > max_possible_searches:
        bot.send_message(message.chat.id, f"⚠️ Aapne {qty} requests ki hain, par aapke balance (₹{current_balance}) ke mutabik sirf **{max_possible_searches}** records process ho payenge.")
        ca_list = ca_list[:max_possible_searches]
    
    status_msg = bot.send_message(message.chat.id, f"⏳ processing 0/{len(ca_list)} items... Please wait...")
    
    bulk_results = []
    deducted_total = 0
    
    for idx, ca in enumerate(ca_list):
        # Database check and deduction (₹10 dynamic per item)
        fresh_data = get_user_data(user_id)
        fresh_bal = fresh_data.get("balance", 0.0) if fresh_data else 0.0
        
        if fresh_bal < 10.0:
            bot.send_message(message.chat.id, "❌ Processing ke bich balance khatam ho gaya!")
            break
            
        new_balance = fresh_bal - 10.0
        update_balance(user_id, new_balance)
        deducted_total += 10
        add_history_log(user_id, 10.0, "Bot Bulk Search", ca)
        
        # API Call Process
        try:
            api_url = f"https://billguru.kzthubbjdo.workers.dev/?ca_no={ca}"
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                raw_res = response.json()
                d = raw_res.get("data", {})
            else: d = {}
        except: d = {}
            
        # Standard Excel Headers (Exact sequence requested by you)
        row = {
            "Name": d.get("Name", "Not Found"),                  # Column A
            "Mobile_No": d.get("Mobile_No", "Not Found"),        # Column B
            "Email": d.get("Email", "Not Found"),                # Column C
            "Contract_Account": d.get("Contract_Account", ca),   # Column D
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
            "Bill_group": d.get("Bill_group", ""),
            "MoveInDt": d.get("MoveInDt", ""),
            "AppForm": d.get("AppForm", ""),
            "MoveOutDt": d.get("MoveOutDt", ""),
            "BP_PDCDt": d.get("BP_PDCDt", "null"),
            "Comments": d.get("Comments", ""),
            "Aadhar_No": d.get("Aadhar_No", "null"),
            "Idtype_Dom": d.get("Idtype_Dom", ""),
            "Mobile_Update": d.get("Mobile_Update", "null"),
            "Mobile_UpdateOn": d.get("Mobile_UpdateOn", "null"),
            "Mobile_New": d.get("Mobile_New", "null"),
            "Email_New": d.get("Email_New", ""),
            "Contact_Update_On": d.get("Contact_Update_On", ""),
            "mrdocno": d.get("mrdocno", "null"),
            "nextbilldate": d.get("nextbilldate", "null"),
            "acc_no": d.get("acc_no", "null"),
            "mandate_limit": d.get("mandate_limit", "null"),
            "mandate_date": d.get("mandate_date", "null"),
            "umrn": d.get("umrn", "null"),
            "IsCancelMandate": d.get("IsCancelMandate", "null"),
            "CancelRequestDate": d.get("CancelRequestDate", "null"),
            "Mrreason": d.get("Mrreason", "null"),
            "RegOTP": d.get("RegOTP", ""),
            "isSync": d.get("isSync", "true"),
            "KYCOTP": d.get("KYCOTP", ""),
            "KYCEMAILOTP": d.get("KYCEMAILOTP", ""),
            "LOGOTP": d.get("LOGOTP", "")
        }
        bulk_results.append(row)
        
        # Live status message update
        if (idx + 1) % 2 == 0 or (idx + 1) == len(ca_list):
            try:
                bot.edit_message_text(f"⏳ Processing {idx + 1}/{len(ca_list)} items... Please wait...", message.chat.id, status_msg.message_id)
            except: pass

    if len(bulk_results) == 0:
        bot.send_message(message.chat.id, "❌ Koi data fetch nahi ho paya.")
        return

    # Database backup me upload karein taaki Admin panel se download ho sake
    try:
        user_display_name = user_data.get("name", "Unknown")
        save_search_history_to_firestore(user_id, user_display_name, base_ca, len(bulk_results), bulk_results)
    except Exception as db_err:
        print(f"Firestore save error: {db_err}")

    # Generate Excel Locally
    df = pd.DataFrame(bulk_results)
    file_name = f"Bulk_Bill_{user_id}.xlsx"
    df.to_excel(file_name, index=False)
    
    # Final remaining balance show karne ke liye check
    final_data = get_user_data(user_id)
    final_bal = final_data.get("balance", 0.0) if final_data else 0.0
    
    # User ko sheet bhej do
    with open(file_name, "rb") as file:
        bot.send_document(
            message.chat.id, 
            file, 
            caption=f"✅ **Bulk Search Completed!**\n\n📊 Total Processed: `{len(bulk_results)}` items\n📉 Wallet Deducted: `₹{deducted_total}` (₹10/each)\n💰 Remaining Balance: `₹{final_bal}`",
            parse_mode="Markdown"
        )
        
    # Delete temporary local file
    if os.path.exists(file_name):
        os.remove(file_name)

if __name__ == "__main__":
    print("🤖 BABA MNGL Multi-threaded Bot successfully connected with Firebase and running fine...")
    bot.infinity_polling()
