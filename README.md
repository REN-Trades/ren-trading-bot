from flask import Flask, request, jsonify
import requests
import time
import os
import json
from datetime import datetime

app = Flask(__name__)

TRADOVATE_USER = os.environ.get("TRADOVATE_USER")
TRADOVATE_PASS = os.environ.get("TRADOVATE_PASS")
TRADOVATE_CID  = int(os.environ.get("TRADOVATE_CID", 0))
TRADOVATE_SEC  = os.environ.get("TRADOVATE_SEC")
TRADOVATE_ACCT = os.environ.get("TRADOVATE_ACCT")
LIVE_MODE      = os.environ.get("LIVE_MODE", "false").lower() == "true"

BASE_URL = "https://live.tradovateapi.com/v1" if LIVE_MODE else "https://demo.tradovateapi.com/v1"

access_token = None
token_expiry = 0

def get_token():
    global access_token, token_expiry
    if access_token and time.time() < token_expiry:
        return access_token
    url = f"{BASE_URL}/auth/accesstokenrequest"
    body = {
        "name": TRADOVATE_USER,
        "password": TRADOVATE_PASS,
        "appId": "REN_BOT",
        "appVersion": "1.0",
        "cid": TRADOVATE_CID,
        "sec": TRADOVATE_SEC
    }
    r = requests.post(url, json=body)
    data = r.json()
    access_token = data.get("accessToken")
    token_expiry = time.time() + 3600
    print(f"[{datetime.now()}] Token erhalten")
    return access_token

def get_mnq_symbol():
    now = datetime.utcnow()
    month = now.month
    year  = now.year % 100
    if month <= 3:
        return f"MNQH{year}"
    elif month <= 6:
        return f"MNQM{year}"
    elif month <= 9:
        return f"MNQU{year}"
    else:
        return f"MNQZ{year}"

def cancel_existing_orders(token, symbol):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/order/cancelorder"
    orders_url = f"{BASE_URL}/order/list"
    r = requests.get(orders_url, headers=headers)
    orders = r.json() if r.status_code == 200 else []
    for order in orders:
        if order.get("symbol") == symbol and order.get("ordStatus") in ["PendingNew", "Working"]:
            requests.post(url, json={"orderId": order["id"]}, headers=headers)
    print(f"[{datetime.now()}] Bestehende Orders gecancelt")

def place_order(action, qty, sl, tp, tp1, tp1_pct):
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    symbol = get_mnq_symbol()
    order_url = f"{BASE_URL}/order/placeorder"

    print(f"[{datetime.now()}] Signal: {action} {qty}x {symbol} | SL:{sl} TP1:{tp1} TP:{tp}")

    main_order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol": symbol,
        "orderQty": qty,
        "orderType": "Market",
        "action": "Buy" if action == "buy" else "Sell",
        "timeInForce": "GTC",
        "isAutomated": True
    }
    r = requests.post(order_url, json=main_order, headers=headers)
    print(f"[{datetime.now()}] Main Order: {r.status_code} {r.text}")

    time.sleep(0.5)

    sl_order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol": symbol,
        "orderQty": qty,
        "orderType": "Stop",
        "stopPrice": round(sl, 2),
        "action": "Sell" if action == "buy" else "Buy",
        "timeInForce": "GTC",
        "isAutomated": True
    }
    requests.post(order_url, json=sl_order, headers=headers)

    tp1_qty = max(1, int(qty * tp1_pct / 100))
    tp1_order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol": symbol,
        "orderQty": tp1_qty,
        "orderType": "Limit",
        "price": round(tp1, 2),
        "action": "Sell" if action == "buy" else "Buy",
        "timeInForce": "GTC",
        "isAutomated": True
    }
    requests.post(order_url, json=tp1_order, headers=headers)

    tp_qty = qty - tp1_qty
    if tp_qty > 0:
        tp_order = {
            "accountSpec": TRADOVATE_ACCT,
            "symbol": symbol,
            "orderQty": tp_qty,
            "orderType": "Limit",
            "price": round(tp, 2),
            "action": "Sell" if action == "buy" else "Buy",
            "timeInForce": "GTC",
            "isAutomated": True
        }
        requests.post(order_url, json=tp_order, headers=headers)

    print(f"[{datetime.now()}] Alle Orders platziert ✅")

def move_sl_to_be(entry_price):
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    symbol = get_mnq_symbol()
    orders_url = f"{BASE_URL}/order/list"
    modify_url = f"{BASE_URL}/order/modifyorder"

    r = requests.get(orders_url, headers=headers)
    orders = r.json() if r.status_code == 200 else []

    for order in orders:
        if (order.get("symbol") == symbol and
            order.get("ordStatus") in ["PendingNew", "Working"] and
            order.get("orderType") == "Stop"):
            requests.post(modify_url, json={
                "orderId": order["id"],
                "orderQty": order["orderQty"],
                "orderType": "Stop",
                "stopPrice": round(entry_price, 2)
            }, headers=headers)
            print(f"[{datetime.now()}] SL auf BE {entry_price} gesetzt ✅")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        print(f"[{datetime.now()}] Webhook empfangen: {data}")
        action = data.get('action')

        if action in ["buy", "sell"]:
            qty     = int(data['qty'])
            sl      = float(data['sl'])
            tp      = float(data['tp'])
            tp1     = float(data['tp1'])
            tp1_pct = int(data.get('tp1_pct', 20))
            place_order(action, qty, sl, tp, tp1, tp1_pct)

        elif action == "move_be":
            entry = float(data['entry'])
            move_sl_to_be(entry)

        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"[{datetime.now()}] Fehler: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def home():
    symbol = get_mnq_symbol()
    mode = "LIVE" if LIVE_MODE else "DEMO"
    return f"REN Trading Bot ✅ | {mode} | Symbol: {symbol}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
