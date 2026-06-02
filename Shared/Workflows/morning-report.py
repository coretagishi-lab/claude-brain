#!/usr/bin/env python3
"""
Morning Report: 毎朝8時に Discord へ日次レポートを送信

収集データ (API ゼロ — Claude API 非使用):
  1. VPS 正常稼働確認          systemd
  2. Notion 承認待ち件数        Notion REST API
  3. YouTube 昨日の再生数       YouTube Data API v3 / Analytics API
  4. 今週の Anthropic 使用料    Anthropic Usage REST API
  5. VPS 待機タスク件数         Notion REST API

使い方:
  python3 morning-report.py          # 通常実行
  python3 morning-report.py --dry    # Discord 送信せず内容を標準出力
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

ENV_FILE       = Path("/opt/ai-brain/.credentials/.env")
OAUTH_TOKEN    = Path("/opt/ai-brain/.credentials/gdrive-oauth-token.json")
NOTION_VERSION = "2022-06-28"
OUTBOX_DB_ID   = "36f1cad4-aa98-81fb-93d8-d40bfb95cff9"

DRY_RUN = "--dry" in sys.argv


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)="(.+)"$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


_load_env()

DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK_URL", "")
NOTION_TOKEN       = os.environ.get("NOTION_TOKEN", "")
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY    = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "")


# ── ① VPS 稼働確認 ─────────────────────────────────────────
TIMERS = [
    ("sync",           "ai-brain-sync"),
    ("memory-monitor", "ai-brain-memory-monitor"),
    ("auth-monitor",   "ai-brain-auth-monitor"),
    ("conoha-monitor", "ai-brain-conoha-monitor"),
]

def check_services() -> tuple[list[str], list[str]]:
    ok, warn = [], []
    for label, base in TIMERS:
        # タイマーが active か
        r = subprocess.run(["systemctl", "is-active", f"{base}.timer"],
                           capture_output=True, text=True)
        timer_active = r.stdout.strip() == "active"

        # 最終サービス実行結果
        r2 = subprocess.run(
            ["systemctl", "show", f"{base}.service", "--property=Result"],
            capture_output=True, text=True,
        )
        last_result = ""
        for line in r2.stdout.splitlines():
            if line.startswith("Result="):
                last_result = line.split("=", 1)[1].strip()

        if timer_active and last_result in ("success", ""):
            ok.append(label)
        elif timer_active and last_result != "success":
            warn.append(f"{label} (最終実行: {last_result})")
        else:
            warn.append(f"{label} (停止中)")
    return ok, warn


# ── ② Notion 承認待ち件数 ──────────────────────────────────
def _notion_query(filter_body: dict) -> list:
    if not NOTION_TOKEN:
        return []
    body = json.dumps({"filter": filter_body, "page_size": 100}).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{OUTBOX_DB_ID}/query",
        data=body, method="POST",
        headers={
            "Authorization":  f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read()).get("results", [])
    except Exception:
        return []


def get_notion_stats() -> dict:
    if not NOTION_TOKEN:
        return {"content": -1, "vps_tasks": -1}

    # コンテンツ審査待ち (draft = tagishi 未承認)
    content_draft    = _notion_query({"property": "status", "select": {"equals": "draft"}})
    # Go サイン後・VPS 処理前 (approved = VPS 待ち)
    content_approved = _notion_query({"property": "status", "select": {"equals": "approved"}})
    # VPS 待機タスク
    vps_tasks = _notion_query({
        "and": [
            {"property": "type",   "select": {"equals": "vps-task"}},
            {"property": "status", "select": {"equals": "pending"}},
        ]
    })

    return {
        "content":        len(content_draft) + len(content_approved),
        "content_detail": f"承認待ち {len(content_draft)}件 / VPS処理待ち {len(content_approved)}件",
        "vps_tasks":      len(vps_tasks),
    }


# ── ③ YouTube 昨日の再生数 ────────────────────────────────
def _get_access_token() -> str:
    """OAuth refresh token から access token を取得"""
    if not OAUTH_TOKEN.exists():
        return ""
    try:
        tok = json.loads(OAUTH_TOKEN.read_text())
        refresh = tok.get("refresh_token", "")
        client_id     = tok.get("client_id", "")
        client_secret = tok.get("client_secret", "")
        if not all([refresh, client_id, client_secret]):
            return ""
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read()).get("access_token", "")
    except Exception:
        return ""


def get_youtube_views() -> str:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # ── A: YouTube Analytics API (OAuth) ──
    if YOUTUBE_CHANNEL_ID:
        access_token = _get_access_token()
        if access_token:
            try:
                url = (
                    "https://youtubeanalytics.googleapis.com/v2/reports"
                    f"?ids=channel%3D%3D{YOUTUBE_CHANNEL_ID}"
                    f"&startDate={yesterday}&endDate={yesterday}"
                    "&metrics=views,estimatedMinutesWatched&dimensions=day"
                )
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )
                with urllib.request.urlopen(req, timeout=10) as res:
                    rows = json.loads(res.read()).get("rows", [])
                    if rows:
                        views = int(rows[0][1])
                        mins  = int(rows[0][2])
                        return f"{views:,} 回  /  {mins:,} 分視聴"
                    return f"0 回 ({yesterday})"
            except Exception:
                pass

    # ── B: YouTube Data API v3 (API key, 総再生数のみ) ──
    if YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID:
        try:
            url = (
                "https://www.googleapis.com/youtube/v3/channels"
                f"?part=statistics&id={YOUTUBE_CHANNEL_ID}&key={YOUTUBE_API_KEY}"
            )
            with urllib.request.urlopen(url, timeout=10) as res:
                items = json.loads(res.read()).get("items", [])
                if items:
                    total = int(items[0]["statistics"].get("viewCount", 0))
                    return f"総再生数 {total:,} 回（前日比: Analytics 要設定）"
        except Exception:
            pass

    if not YOUTUBE_CHANNEL_ID:
        return "設定待ち — YOUTUBE_CHANNEL_ID を tokens.md に追加してください"
    return "取得失敗（YouTube OAuth スコープを確認）"


# ── ④ Anthropic API 使用料 ────────────────────────────────
# Pricing (2025-06): https://www.anthropic.com/pricing
_PRICING = {
    "claude-sonnet-4": (3.0, 15.0),   # $/M tokens in/out
    "claude-haiku-4":  (0.8, 4.0),
    "claude-opus-4":   (15.0, 75.0),
}

def _match_price(model: str) -> tuple[float, float]:
    for k, v in _PRICING.items():
        if k in model.lower():
            return v
    return (3.0, 15.0)  # デフォルト Sonnet 相当


def get_api_usage() -> str:
    if not ANTHROPIC_KEY:
        return "ANTHROPIC_API_KEY 未設定"

    today      = date.today()
    week_start = today - timedelta(days=today.weekday())

    # Anthropic Usage API
    # https://docs.anthropic.com/en/api/usage
    url = (
        "https://api.anthropic.com/v1/usage"
        f"?start_time={week_start.isoformat()}T00:00:00Z"
    )
    req = urllib.request.Request(url, headers={
        "x-api-key":          ANTHROPIC_KEY,
        "anthropic-version":  "2023-06-01",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data  = json.loads(res.read())
            items = data.get("data") or data.get("usage") or []
            total = 0.0
            for item in items:
                model  = item.get("model", "")
                inp    = item.get("input_tokens", 0)
                out    = item.get("output_tokens", 0)
                p_in, p_out = _match_price(model)
                total += inp / 1_000_000 * p_in + out / 1_000_000 * p_out
            period = f"{week_start} 〜 {today}"
            return f"${total:.2f}  ({period})"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "API key の Usage 権限なし → console.anthropic.com/settings/billing"
        if e.code == 404:
            return "Usage API 未対応プラン → console.anthropic.com/settings/billing"
        return f"取得失敗 HTTP {e.code}"
    except Exception:
        return "取得失敗 → console.anthropic.com/settings/billing"


# ── Discord embed 組み立て ──────────────────────────────────
_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

def _svc_field(ok: list[str], warn: list[str]) -> str:
    lines = [f"　✅ {s}" for s in ok] + [f"　⚠️ {s}" for s in warn]
    summary = "✅ 全サービス正常" if not warn else f"⚠️ {len(warn)}件 要確認"
    return summary + "\n" + "\n".join(lines)


def build_embed(
    ok_svc: list[str], warn_svc: list[str],
    notion: dict,
    yt_views: str,
    api_cost: str,
) -> dict:
    now = datetime.now()
    wd  = _WEEKDAY_JP[now.weekday()]
    date_str = now.strftime(f"%Y-%m-%d ({wd})")

    # Notion
    if notion["content"] >= 0:
        notion_line = f"{notion['content']}件  ({notion.get('content_detail', '')})"
    else:
        notion_line = "取得失敗 — NOTION_TOKEN を確認してください"

    vps_count = notion["vps_tasks"]
    if vps_count < 0:
        vps_line = "取得失敗"
    elif vps_count == 0:
        vps_line = "0件 ✅"
    else:
        vps_line = f"**{vps_count}件 ← 要対応**"

    overall_ok = not warn_svc and vps_count == 0
    color = 0x00CC66 if overall_ok else 0xFF8800

    description = "\n\n".join([
        f"🖥️ **VPS稼働状況**\n{_svc_field(ok_svc, warn_svc)}",
        f"📋 **Notion承認待ち**\n{notion_line}",
        f"🎬 **YouTube 昨日の再生数**\n{yt_views}",
        f"💴 **今週の API 使用料**\n{api_cost}",
        f"⏳ **VPS待機タスク**\n{vps_line}",
    ])

    return {
        "username": "AI-Brain 朝報",
        "embeds": [{
            "title":       f"☀️ おはようございます — {date_str}",
            "description": description,
            "color":       color,
            "footer":      {"text": "AI-Brain Morning Report"},
        }],
    }


def send_discord(payload: dict) -> bool:
    if not DISCORD_WEBHOOK:
        return False
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "DiscordBot (AI-Brain, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status in (200, 204)
    except Exception as e:
        print(f"Discord 送信失敗: {e}", file=sys.stderr)
        return False


# ── メイン ─────────────────────────────────────────────────
def main() -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] 朝報 収集開始")

    ok_svc, warn_svc = check_services()
    print(f"  サービス: ✅ {len(ok_svc)}件 / ⚠️ {len(warn_svc)}件")

    notion = get_notion_stats()
    print(f"  Notion: コンテンツ {notion['content']}件 / VPSタスク {notion['vps_tasks']}件")

    yt_views = get_youtube_views()
    print(f"  YouTube: {yt_views}")

    api_cost = get_api_usage()
    print(f"  API使用料: {api_cost}")

    payload = build_embed(ok_svc, warn_svc, notion, yt_views, api_cost)

    if DRY_RUN:
        print("\n── DRY RUN: Discord には送信しません ──")
        for embed in payload["embeds"]:
            print(f"\n{embed['title']}\n{embed['description']}")
        return

    if not DISCORD_WEBHOOK:
        print("❌ DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        sys.exit(1)

    ok = send_discord(payload)
    print(f"[{ts}] {'✅ 送信完了' if ok else '❌ 送信失敗'}")


if __name__ == "__main__":
    main()
