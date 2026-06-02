#!/usr/bin/env python3
"""
Auth Error Monitor + Self-Repair + Discord Notify

ai-brain-*.log / .err を監視して認証エラーを検出し、
tokens.md から認証情報を再読み込み → サービス再起動 → Discord 通知する。

使い方:
  python3 auth-monitor.py           # 通常監視（systemd から呼ぶ）
  python3 auth-monitor.py --status  # 最後の修復状況を表示
  python3 auth-monitor.py --force   # クールダウン無視して強制修復
  python3 auth-monitor.py --dry-run # 検出のみ（修復しない）
"""
import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

CRED_DIR      = Path("/opt/ai-brain/.credentials")
ENV_FILE      = CRED_DIR / ".env"
OFFSET_FILE   = CRED_DIR / ".log_offsets.json"
COOLDOWN_FILE = CRED_DIR / ".auth_repair_last"
SCRIPT_DIR    = Path(__file__).resolve().parent
CRED_LOADER   = SCRIPT_DIR / "cred-loader.py"
TASK_REPORTER = SCRIPT_DIR / "vps-task-reporter.py"
COOLDOWN_SEC  = 300  # 5分に1回まで修復実行

LOG_FILES = [
    "/var/log/ai-brain-sync.log",
    "/var/log/ai-brain-sync.err",
    "/var/log/ai-brain-conoha.log",
    "/var/log/ai-brain-conoha.err",
    "/var/log/ai-brain-memory.log",
    "/var/log/ai-brain-memory.err",
]

# 認証エラーパターン → 影響サービス名（.service なし）
AUTH_PATTERNS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"(401|Unauthorized|Bad credentials|Invalid token|token is invalid)", re.I),
     ["ai-brain-sync", "ai-brain-conoha-monitor"]),
    (re.compile(r"(403|Forbidden)", re.I),
     ["ai-brain-sync"]),
    (re.compile(r"(認証失敗|Authentication failed|auth error|CONOHA.*error)", re.I),
     ["ai-brain-conoha-monitor"]),
]


# ── ログ差分スキャン ──────────────────────────────────────────
def load_offsets() -> dict:
    try:
        return json.loads(OFFSET_FILE.read_text()) if OFFSET_FILE.exists() else {}
    except Exception:
        return {}


def save_offsets(offsets: dict) -> None:
    CRED_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    OFFSET_FILE.write_text(json.dumps(offsets))
    OFFSET_FILE.chmod(0o600)


def scan_logs() -> list[tuple[str, set[str]]]:
    """新着ログ行を走査して認証エラーを検出。戻り値: [(log_path, {services})]"""
    offsets = load_offsets()
    found: list[tuple[str, set[str]]] = []

    for log_str in LOG_FILES:
        log_path = Path(log_str)
        if not log_path.exists():
            continue

        offset = offsets.get(log_str, 0)
        size   = log_path.stat().st_size

        if size < offset:
            offset = 0  # ローテーション検出

        if size == offset:
            continue  # 新着なし

        with open(log_path, "rb") as f:
            f.seek(offset)
            new_text = f.read().decode("utf-8", errors="replace")

        offsets[log_str] = size

        affected: set[str] = set()
        for pattern, services in AUTH_PATTERNS:
            if pattern.search(new_text):
                affected.update(services)

        if affected:
            found.append((log_str, affected))

    save_offsets(offsets)
    return found


# ── 認証情報リロード ──────────────────────────────────────────
def reload_creds() -> bool:
    if not CRED_LOADER.exists():
        print(f"❌ cred-loader.py が見つかりません: {CRED_LOADER}", file=sys.stderr)
        return False
    result = subprocess.run(
        [sys.executable, str(CRED_LOADER), "--update-profile"],
        capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(f"❌ cred-loader エラー:\n{result.stderr.strip()}", file=sys.stderr)
        return False
    return True


# ── サービス再起動 ────────────────────────────────────────────
def restart_service(name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "restart", f"{name}.service"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    print(f"  {'✅' if ok else '❌'} systemctl restart {name}")
    return ok


# ── VPS 待機タスク登録 ────────────────────────────────────────
def report_pending_task(errors: list) -> None:
    """自己修復できなかった問題を Notion に登録する"""
    if not TASK_REPORTER.exists():
        return
    error_summary = "\n".join(f"- {log.split('/')[-1]}: {', '.join(svcs)}" for log, svcs in errors)
    subprocess.run(
        [sys.executable, str(TASK_REPORTER),
         "--title",  "認証エラー: 自己修復失敗",
         "--detail", f"以下のログで認証エラーを検出しましたが、tokens.md からの修復に失敗しました:\n{error_summary}",
         "--action", (
             "1. tokens.md の値を確認してください\n"
             "   `python3 /opt/ai-brain/Shared/Workflows/cred-loader.py --check`\n"
             "2. 期限切れのトークンを更新してください\n"
             "3. `cred-loader.py --update-profile` を再実行してください"
         ),
         "--source", "auth-monitor"],
        capture_output=True, text=True,
    )


# ── Discord 通知 ──────────────────────────────────────────────
def get_discord_webhook() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            m = re.match(r'^DISCORD_WEBHOOK_URL="(.+)"$', line)
            if m:
                return m.group(1)
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


def send_discord(repairs: list[dict]) -> bool:
    webhook = get_discord_webhook()
    if not webhook:
        print("⚠️  DISCORD_WEBHOOK_URL が未設定のため通知スキップ", file=sys.stderr)
        return False

    fields = [
        {
            "name": f"📋 {r['log'].split('/')[-1]}",
            "value": f"再起動: `{'`, `'.join(r['services'])}`",
            "inline": False,
        }
        for r in repairs
    ]
    payload = {
        "username": "AI-Brain Auth Monitor",
        "embeds": [{
            "title": "🔧 認証エラーを自動修復しました",
            "description": (
                "ログで認証エラーを検出。`tokens.md` から認証情報を再読み込みし、"
                "影響サービスを再起動しました。"
            ),
            "color": 0x00BB00,
            "fields": fields,
            "footer": {
                "text": f"AI-Brain Auth Monitor • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            },
        }],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "DiscordBot (AI-Brain, 1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            ok = res.status in (200, 204)
            print(f"  {'✅' if ok else '❌'} Discord 通知 (HTTP {res.status})")
            return ok
    except Exception as e:
        print(f"  ❌ Discord 送信エラー: {e}", file=sys.stderr)
        return False


# ── クールダウン ──────────────────────────────────────────────
def should_repair() -> bool:
    try:
        last = float(COOLDOWN_FILE.read_text().strip())
        return (time.time() - last) > COOLDOWN_SEC
    except Exception:
        return True


def mark_repaired() -> None:
    CRED_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(str(time.time()))
    COOLDOWN_FILE.chmod(0o600)


# ── メイン ────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    dry  = "--dry-run" in args
    force = "--force" in args

    if "--status" in args:
        if COOLDOWN_FILE.exists():
            last = float(COOLDOWN_FILE.read_text().strip())
            elapsed = int((time.time() - last) / 60)
            print(f"最後の修復: {elapsed} 分前")
        else:
            print("修復履歴なし")
        return

    errors = scan_logs()
    if not errors:
        return  # 正常 — サイレント

    print(f"[{ts}] ⚠️  認証エラーを検出 ({len(errors)} 件):")
    for log, services in errors:
        print(f"  {log.split('/')[-1]} → {', '.join(services)}")

    if dry:
        print("  --dry-run のためスキップ")
        return

    if not force and not should_repair():
        print(f"  ⏳ クールダウン中のためスキップ（次回修復まで待機）")
        return

    # 1. 認証情報を再読み込み
    if not reload_creds():
        report_pending_task(errors)  # 修復不能 → Notion に待機タスク登録
        return

    # 2. 影響サービスを再起動
    all_services: set[str] = set()
    for _, svcs in errors:
        all_services.update(svcs)

    restarted = [svc for svc in sorted(all_services) if restart_service(svc)]

    # すべてのサービス再起動が失敗した場合も待機タスクに登録
    if all_services and not restarted:
        report_pending_task(errors)

    # 3. Discord 通知（修復成功分のみ）
    if restarted:
        repairs = [{"log": log, "services": list(svcs)} for log, svcs in errors]
        send_discord(repairs)

    mark_repaired()
    print(f"[{ts}] ✅ 修復完了: {', '.join(restarted) or 'なし（待機タスク登録済み）'}")


if __name__ == "__main__":
    main()
