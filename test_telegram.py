import config
import claude_client
import requests

TG = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
print("Waiting for message... send something to @myshams_bot now")
r = requests.get(f"{TG}/getUpdates", params={"timeout": 30}, timeout=35)
updates = r.json().get("result", [])
if not updates:
    print("No message received in 30 seconds")
else:
    msg = updates[0]["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    print(f"Got message from chat_id {chat_id}: {text}")
    print("Calling Claude...")
    reply = claude_client.chat(text)
    print(f"Reply: {reply[:300]}")
    resp = requests.post(f"{TG}/sendMessage", json={"chat_id": chat_id, "text": reply})
    print(f"Telegram send status: {resp.status_code}")
    print("Sent!")
