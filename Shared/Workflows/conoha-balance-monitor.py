#!/usr/bin/env python3
"""
ConoHa残高監視 + Discord通知

必要な環境変数 (~/.zshrc に追記):
  CONOHA_USERNAME    APIユーザー名   （管理画面 → 右上アカウント名 → API情報）
  CONOHA_PASSWORD    APIパスワード
  CONOHA_TENANT_ID   テナントID
  CONOHA_REGION      リージョン（省略可、デフォルト: tyo1）
  DISCORD_WEBHOOK_URL

使い方:
  python3 conoha-balance-monitor.py           # 残高チェック（launchd から呼ぶ）
  python3 conoha-balance-monitor.py --status  # 残高を表示して終了
  python3 conoha-balance-monitor.py --debug   # APIレスポンスをそのまま表示
"""
import os, sys, json, urllib.request, urllib.error, time
from datetime import datetime
from pathlib import Path

# ── 設定 ────────────────────────────────────────────────────
CONOHA_USERNAME  = os.environ.get("CONOHA_USERNAME", "")
CONOHA_PASSWORD  = os.environ.get("CONOHA_PASSWORD", "")
CONOHA_TENANT_ID = os.environ.get("CONOHA_TENANT_ID", "")
CONOHA_REGION    = os.environ.get("CONOHA_REGION", "tyo1")
DISCORD_WEBHOOK  = os.environ.get("DISCORD_WEBHOOK_URL", "")
THRESHOLD_JPY    = int(os.environ.get("CONOHA_BALANCE_THRESHOLD", "500"))
COOLDOWN_SEC     = 3600 * 6  # 6時間に1回まで通知

SCRIPT_DIR    = Path(__file__).resolve().parent
COOLDOWN_FILE = SCRIPT_DIR / ".conoha_alert_last"

IDENTITY_URL = f"https://identity.{CONOHA_REGION}.conoha.io/v2.0"
ACCOUNT_URL  = f"https://account.{CONOHA_REGION}.conoha.io/v1/{CONOHA_TENANT_ID}"

DEBUG = "--debug" in sys.argv

# ── ConoHa API ───────────────────────────────────────────────
def conoha_request(method, url, data=None, token=None):
    body = json.dumps(data).encode() if data else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["X-Auth-Token"] = token
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            body = res.read()
            return res.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return e.code, {"error": body}

def get_token():
    """ConoHa v2 認証トークンとサービスカタログを取得"""
    payload = {
        "auth": {
            "passwordCredentials": {
                "username": CONOHA_USERNAME,
                "password": CONOHA_PASSWORD,
            },
            "tenantId": CONOHA_TENANT_ID,
        }
    }
    status, res = conoha_request("POST", f"{IDENTITY_URL}/tokens", data=payload)
    if status != 200:
        raise RuntimeError(f"認証失敗 HTTP {status}: {res}")
    token   = res["access"]["token"]["id"]
    catalog = res["access"].get("serviceCatalog", [])
    return token, catalog

def find_account_url(catalog):
    """サービスカタログからアカウントAPIのURLを取得"""
    for svc in catalog:
        if svc.get("type") == "account":
            for ep in svc.get("endpoints", []):
                if ep.get("region", "").lower() == CONOHA_REGION.lower():
                    return ep.get("publicURL", "").rstrip("/")
    return ACCOUNT_URL  # フォールバック

def get_balance(token, account_base):
    """
    ConoHa チャージ残高を取得する。
    エンドポイント: GET /v1/{tenant_id}/payment-summary
    """
    url = f"{account_base}/payment-summary"
    status, res = conoha_request("GET", url, token=token)

    if DEBUG:
        print(f"\n[DEBUG] GET {url}")
        print(f"  HTTP {status}")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    if status == 404:
        # フォールバック: /billing-invoices から推算
        return _balance_from_invoices(token, account_base)

    if status != 200:
        raise RuntimeError(f"残高取得失敗 HTTP {status}: {res}")

    # payment_summary レスポンス例:
    # {"payment_summary": {"charge_amount": 1000, ...}}
    summary = res.get("payment_summary", res)
    balance = (
        summary.get("charge_amount")           # ConoHaチャージ残高
        or summary.get("prepaid_balance")
        or summary.get("balance")
        or summary.get("total_deposit")
        or 0
    )
    return int(balance)

def _balance_from_invoices(token, account_base):
    """フォールバック: 最新の未払い請求額をプロキシ値として返す"""
    url = f"{account_base}/billing-invoices?limit=1&offset=0"
    status, res = conoha_request("GET", url, token=token)

    if DEBUG:
        print(f"\n[DEBUG] Fallback GET {url}")
        print(f"  HTTP {status}")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    if status != 200:
        raise RuntimeError(f"請求書取得失敗 HTTP {status}")

    invoices = res.get("billing_invoices", [])
    if not invoices:
        return 0
    latest = invoices[0]
    # 残高として "deposit_amount" や "total_amount" が返ることがある
    return int(latest.get("deposit_amount") or latest.get("total_amount") or 0)

# ── Discord 通知 ─────────────────────────────────────────────
def send_discord(balance):
    if not DISCORD_WEBHOOK:
        print("  ⚠️  DISCORD_WEBHOOK_URL が未設定です", file=sys.stderr)
        return False

    payload = {
        "username": "AI-Brain Monitor",
        "embeds": [{
            "title": "💴 ConoHaの残高が少なくなっています",
            "description": (
                "チャージしてください。\n"
                "残高確認はこちら：https://manage.conoha.jp/Account/BillingSetting/"
            ),
            "color": 0xFF8800,
            "fields": [
                {"name": "現在の残高",  "value": f"**¥{balance:,}**",       "inline": True},
                {"name": "警告ライン",  "value": f"¥{THRESHOLD_JPY:,} 未満", "inline": True},
            ],
            "footer": {
                "text": f"ConoHa Balance Monitor • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            },
        }]
    }
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        DISCORD_WEBHOOK, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (AI-Brain, 1.0)",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status in (200, 204)
    except Exception as e:
        print(f"  Discord送信エラー: {e}", file=sys.stderr)
        return False

# ── クールダウン ─────────────────────────────────────────────
def should_notify():
    if not COOLDOWN_FILE.exists():
        return True
    try:
        last = float(COOLDOWN_FILE.read_text().strip())
        return (time.time() - last) > COOLDOWN_SEC
    except Exception:
        return True

def mark_notified():
    COOLDOWN_FILE.write_text(str(time.time()))

# ── メイン ───────────────────────────────────────────────────
def main():
    # 環境変数チェック
    missing = [v for v in ["CONOHA_USERNAME", "CONOHA_PASSWORD", "CONOHA_TENANT_ID"]
               if not os.environ.get(v)]
    if missing:
        print(f"❌ 環境変数が未設定です: {', '.join(missing)}")
        print("   ~/.zshrc に以下を追記してください:")
        print("   export CONOHA_USERNAME=your_api_user")
        print("   export CONOHA_PASSWORD=your_api_password")
        print("   export CONOHA_TENANT_ID=your_tenant_id")
        sys.exit(1)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
        token, catalog = get_token()
        account_base   = find_account_url(catalog)
        balance        = get_balance(token, account_base)
    except RuntimeError as e:
        print(f"[{ts}] ❌ ConoHa API エラー: {e}")
        sys.exit(1)

    if "--status" in sys.argv or DEBUG:
        status_icon = "⚠️ " if balance < THRESHOLD_JPY else "✅"
        print(f"[{ts}] {status_icon} ConoHa残高: ¥{balance:,}  (警告ライン: ¥{THRESHOLD_JPY:,})")
        return

    if balance < THRESHOLD_JPY:
        if should_notify():
            ok = send_discord(balance)
            if ok:
                mark_notified()
                print(f"[{ts}] ⚠️ ConoHa残高 ¥{balance:,} < ¥{THRESHOLD_JPY:,} — Discord通知送信")
            else:
                print(f"[{ts}] ⚠️ ConoHa残高 ¥{balance:,} < ¥{THRESHOLD_JPY:,} — Discord送信失敗")
        # クールダウン中はサイレント
    # 正常時もサイレント（ログ肥大化防止）

if __name__ == "__main__":
    main()
