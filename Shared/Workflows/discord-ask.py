#!/usr/bin/env python3
"""
Discord Ask: VPS から Discord に質問を送り、返信待ち状態を登録する

webhook でメッセージを送信 → .discord_pending.json に action を記録。
discord-responder.py が「1」か「2」を受け取ったらここに書いた action を実行する。

使い方:
  # API ゼロで即実行できるアクション (action1-type=api_zero)
  python3 discord-ask.py \\
    --question "ai-brain-sync が認証エラーで失敗しています。" \\
    --action1-type api_zero \\
    --action1-cmd "python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --update-profile && systemctl restart ai-brain-sync.service" \\
    --action1-label "今すぐ認証情報を再読み込みして再起動する" \\
    --action2-label "後で Claude Code で対応する" \\
    --notion-title "ai-brain-sync 認証エラー" \\
    --notion-detail "sync サービスが 401 エラーで失敗。tokens.md の GitHub.PAT が期限切れの可能性。" \\
    --source "auth-monitor"

  # Claude Code が必要なアクション (action1-type=api_needed)
  python3 discord-ask.py \\
    --question "Canva テンプレートが見つかりません。テンプレート名を確認してください。" \\
    --action1-type api_needed \\
    --action1-label "ターミナルで確認・修正する" \\
    --action2-label "スキップして次の動画へ進む" \\
    --notion-title "Canva テンプレート不明" \\
    --notion-detail "テンプレート名 [xxx] が見つからない。Canva 上の名前を確認して CLAUDE.md を更新。" \\
    --source "canva-pipeline"
"""
import argparse, json, os, re, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

PENDING_FILE = Path("/opt/ai-brain/.credentials/.discord_pending.json")
ENV_FILE     = Path("/opt/ai-brain/.credentials/.env")


def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        m = re.match(r'^(\w+)="(.+)"$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


_load_env()
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_webhook(question: str, a1_label: str, a2_label: str) -> bool:
    if not DISCORD_WEBHOOK:
        print("⚠️  DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        return False

    payload = {
        "username": "AI-Brain VPS",
        "embeds": [{
            "title": "❓ 確認が必要です",
            "description": question,
            "color": 0x5865F2,
            "fields": [
                {"name": "1️⃣", "value": a1_label, "inline": True},
                {"name": "2️⃣", "value": a2_label, "inline": True},
            ],
            "footer": {
                "text": f"「1」か「2」で返信してください  •  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            },
        }],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        DISCORD_WEBHOOK, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (AI-Brain, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status in (200, 204)
    except Exception as e:
        print(f"webhook 送信失敗: {e}", file=sys.stderr)
        return False


def write_pending(args: argparse.Namespace) -> None:
    PENDING_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = {
        "asked_at":     datetime.now().isoformat(),
        "question":     args.question,
        "action_1": {
            "type":    args.action1_type,
            "command": args.action1_cmd,
            "label":   args.action1_label,
        },
        "action_2": {
            "label": args.action2_label,
        },
        "notion_title":  args.notion_title or args.question[:60],
        "notion_detail": args.notion_detail or args.question,
        "source":        args.source,
    }
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    PENDING_FILE.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",      required=True)
    parser.add_argument("--action1-type",  choices=["api_zero", "api_needed"],
                        default="api_needed", dest="action1_type")
    parser.add_argument("--action1-cmd",   default="", dest="action1_cmd")
    parser.add_argument("--action1-label", required=True, dest="action1_label")
    parser.add_argument("--action2-label", required=True, dest="action2_label")
    parser.add_argument("--notion-title",  default="", dest="notion_title")
    parser.add_argument("--notion-detail", default="", dest="notion_detail")
    parser.add_argument("--source",        default="vps")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 既存の pending があれば上書き警告
    if PENDING_FILE.exists():
        try:
            old = json.loads(PENDING_FILE.read_text())
            print(f"⚠️  既存の質問を上書きします: {old.get('question', '')[:40]}")
        except Exception:
            pass

    write_pending(args)
    print(f"[{ts}] ✅ pending 登録: {args.question[:50]}")

    ok = send_webhook(args.question, args.action1_label, args.action2_label)
    print(f"[{ts}] {'✅' if ok else '❌'} Discord 送信")


if __name__ == "__main__":
    main()
