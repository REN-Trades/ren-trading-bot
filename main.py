from flask import Flask, request, jsonify
import requests
import time
import os
import json
from datetime import datetime
 
app = Flask(__name__)
 
# ── Env Variables (in Railway setzen) ──────────────────────────────────────
TRADOVATE_USER  = os.environ.get("TRADOVATE_USER")
TRADOVATE_PASS  = os.environ.get("TRADOVATE_PASS")
TRADOVATE_CID   = int(os.environ.get("TRADOVATE_CID", 0))
TRADOVATE_SEC   = os.environ.get("TRADOVATE_SEC")
TRADOVATE_ACCT  = os.environ.get("TRADOVATE_ACCT")
LIVE_MODE       = os.environ.get("LIVE_MODE", "false").lower() == "true"
 
# ── API Base URL ────────────────────────────────────────────────────────────
BASE_URL = "https://live.tradovateapi.com/v1" if LIVE_MODE else "https://demo.tradovateapi.com/v1"
 
access_token  = None
token_expiry  = 0
 
 
# ── Auth ────────────────────────────────────────────────────────────────────
def get_token():
    global access_token, token_expiry
    if access_token and time.time() < token_expiry:
        return access_token
 
    url  = f"{BASE_URL}/auth/accesstokenrequest"
    body = {
        "name":       TRADOVATE_USER,
        "password":   TRADOVATE_PASS,
        "appId":      "REN_BOT",
        "appVersion": "1.0",
        "cid":        TRADOVATE_CID,
        "sec":        TRADOVATE_SEC,
    }
    r            = requests.post(url, json=body)
    data         = r.json()
    access_token = data.get("accessToken")
    token_expiry = time.time() + 3600
    print(f"[{datetime.now()}] Token erhalten")
    return access_token
 
 
# ── Symbol Helper (rollierende MNQ Futures) ─────────────────────────────────
def get_mnq_symbol():
    now   = datetime.utcnow()
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
 
 
# ── Order Placement ─────────────────────────────────────────────────────────
def place_order(action, symbol, qty, sl, tp, tp1):
    token   = get_token()
    headers = {"Authorization": f"Bearer {token}"}
 
    order_url = f"{BASE_URL}/order/placeorder"
 
    # Haupt-Order (Market)
    order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol":      symbol,
        "orderQty":    qty,
        "orderType":   "Market",
        "action":      "Buy" if action == "buy" else "Sell",
        "timeInForce": "GTC",
        "isAutomated": True,
    }
    r          = requests.post(order_url, json=order, headers=headers)
    order_data = r.json()
    print(f"[{datetime.now()}] Haupt-Order: {order_data}")
 
    # Stop Loss Order
    sl_order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol":      symbol,
        "orderQty":    qty,
        "orderType":   "Stop",
        "stopPrice":   sl,
        "action":      "Sell" if action == "buy" else "Buy",
        "timeInForce": "GTC",
        "isAutomated": True,
    }
    requests.post(order_url, json=sl_order, headers=headers)
    print(f"[{datetime.now()}] SL Order platziert: {sl}")
 
    # TP1 Order (ca. 39% der Position)
    tp1_qty   = max(1, int(qty * 0.39))
    tp1_order = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol":      symbol,
        "orderQty":    tp1_qty,
        "orderType":   "Limit",
        "price":       tp1,
        "action":      "Sell" if action == "buy" else "Buy",
        "timeInForce": "GTC",
        "isAutomated": True,
    }
    requests.post(order_url, json=tp1_order, headers=headers)
    print(f"[{datetime.now()}] TP1 Order platziert: {tp1} (qty: {tp1_qty})")
 
    # TP Final Order (Rest der Position)
    tp_qty    = qty - tp1_qty
    tp_order  = {
        "accountSpec": TRADOVATE_ACCT,
        "symbol":      symbol,
        "orderQty":    tp_qty,
        "orderType":   "Limit",
        "price":       tp,
        "action":      "Sell" if action == "buy" else "Buy",
        "timeInForce": "GTC",
        "isAutomated": True,
    }
    requests.post(order_url, json=tp_order, headers=headers)
    print(f"[{datetime.now()}] TP Final Order platziert: {tp} (qty: {tp_qty})")
 
    print(f"[{datetime.now()}] Alle Orders platziert — SL: {sl} | TP1: {tp1} | TP: {tp}")
 
 
# ── Webhook Endpoint ─────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"[{datetime.now()}] Signal empfangen: {data}")
 
    try:
        action = data["action"]          # "buy" oder "sell"
        symbol = data.get("symbol", get_mnq_symbol())
        qty    = int(data["qty"])
        sl     = float(data["sl"])
        tp     = float(data["tp"])
        tp1    = float(data["tp1"])
    except (KeyError, ValueError) as e:
        print(f"[{datetime.now()}] Fehler beim Parsen: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
 
    place_order(action, symbol, qty, sl, tp, tp1)
    return jsonify({"status": "ok", "symbol": symbol, "action": action, "qty": qty})
 
 
# ── Health Check ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    mode = "LIVE" if LIVE_MODE else "DEMO"
    return jsonify({
        "status": "running",
        "mode":   mode,
        "time":   str(datetime.utcnow()),
    })
 
 
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
