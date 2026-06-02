#!/usr/bin/env python3
"""
メモリ監視 + Discord通知 + ゾンビプロセス解放（macOS / Linux 両対応）

監視ロジック:
  空きメモリが FREE_THRESHOLD_MB 未満 → 警告
  macOS: vm_stat / Linux: /proc/meminfo

クールダウン: 1時間に1回まで通知（連続スパム防止）

使い方:
  python3 memory-monitor.py           # 1回チェック
  python3 memory-monitor.py --status  # 現在状況を表示
  python3 memory-monitor.py --clean   # ゾンビプロセス解放のみ
"""
import os, sys, re, subprocess, json, urllib.request, time, platform
from pathlib import Path
from datetime import datetime

DISCORD_WEBHOOK   = os.environ.get("DISCORD_WEBHOOK_URL", "")
FREE_THRESHOLD_MB = int(os.environ.get("MEMORY_FREE_MIN_MB", "0"))    # 0=無効
USED_THRESHOLD_MB = int(os.environ.get("MEMORY_USED_MAX_MB", "800"))  # 使用量がこれ超で警告
COOLDOWN_SEC      = 3600  # 1時間

SCRIPT_DIR    = Path(__file__).resolve().parent
COOLDOWN_FILE = SCRIPT_DIR / ".memory_alert_last"

# ── メモリ統計 ────────────────────────────────────────────────
def get_memory_stats():
    if platform.system() == "Darwin":
        return _get_memory_macos()
    return _get_memory_linux()

def _get_memory_macos():
    result = subprocess.run(["vm_stat"], capture_output=True, text=True)
    pages  = {}
    for line in result.stdout.splitlines():
        m = re.match(r"(.+?):\s+(\d+)", line)
        if m:
            pages[m.group(1).strip()] = int(m.group(2))

    ps = 4096
    active     = pages.get("Pages active", 0)
    wired      = pages.get("Pages wired down", 0)
    compressed = pages.get("Pages occupied by compressor", 0)
    inactive   = pages.get("Pages inactive", 0)
    free       = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)

    used_mb  = (active + wired + compressed) * ps // 1024 // 1024
    free_mb  = (free + inactive) * ps // 1024 // 1024
    total_mb = (active + wired + compressed + inactive + free) * ps // 1024 // 1024
    pct      = round(used_mb / total_mb * 100, 1) if total_mb else 0

    return {"used_mb": used_mb, "free_mb": free_mb, "total_mb": total_mb, "pct": pct}

def _get_memory_linux():
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            m = re.match(r"(\w+):\s+(\d+)", line)
            if m:
                mem[m.group(1)] = int(m.group(2))  # kB単位

    total_mb = mem.get("MemTotal", 0) // 1024
    free_mb  = mem.get("MemAvailable", 0) // 1024  # free + reclaimable cache
    used_mb  = total_mb - free_mb
    pct      = round(used_mb / total_mb * 100, 1) if total_mb else 0

    return {"used_mb": used_mb, "free_mb": free_mb, "total_mb": total_mb, "pct": pct}

# ── AI-Brain プロセスのメモリ合計 ─────────────────────────────
def get_aibrain_process_mb():
    """AI-Brain ディレクトリ配下で動いている python3 プロセスの RSS 合計"""
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    total  = 0
    procs  = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        cmd = parts[10]
        if "python3" in cmd and "AI-Brain" in cmd:
            try:
                rss_kb = int(parts[5])
                total += rss_kb
                procs.append((rss_kb // 1024, cmd[:50]))
            except ValueError:
                pass
    return total // 1024, procs  # MB

# ── ゾンビプロセス解放 ────────────────────────────────────────
def kill_zombies():
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    count  = 0
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) > 7 and parts[7] == "Z":
            pid = parts[1]
            parent_res = subprocess.run(
                ["ps", "-o", "ppid=", "-p", pid], capture_output=True, text=True
            )
            ppid = parent_res.stdout.strip()
            if ppid and ppid != "1":
                subprocess.run(["kill", "-CHLD", ppid], capture_output=True)
            count += 1
    return count

# ── 長時間アイドルの AI-Brain プロセスを終了 ────────────────
def kill_stale_aibrain(max_hours=2):
    """max_hours 以上動き続けている AI-Brain python3 プロセスを終了"""
    result = subprocess.run(["ps", "-eo", "pid,etime,command"], capture_output=True, text=True)
    killed = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etime, cmd = parts
        if "python3" not in cmd or "AI-Brain" not in cmd:
            continue
        # etime format: [[DD-]HH:]MM:SS
        m = re.match(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", etime)
        if not m:
            continue
        days  = int(m.group(1) or 0)
        hours = int(m.group(2) or 0)
        total_hours = days * 24 + hours
        if total_hours >= max_hours:
            subprocess.run(["kill", pid], capture_output=True)
            killed.append((pid, cmd[:40]))
    return killed

# ── クールダウン ──────────────────────────────────────────────
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

# ── Discord 通知 ──────────────────────────────────────────────
def send_discord(stats):
    if not DISCORD_WEBHOOK:
        print("  ⚠️  DISCORD_WEBHOOK_URL が未設定です", file=sys.stderr)
        return False

    bar_used = "█" * min(10, int(stats["pct"] / 10))
    bar_free = "░" * (10 - len(bar_used))

    payload = {
        "username": "AI-Brain Monitor",
        "embeds": [{
            "title": "⚠️ メモリが逼迫してきました",
            "description": "プランアップグレードを検討してください",
            "color": 0xFF4444,
            "fields": [
                {
                    "name": "使用量 / 空き",
                    "value": f"使用: **{stats['used_mb']} MB**\n空き: **{stats['free_mb']} MB**",
                    "inline": True,
                },
                {
                    "name": "使用率",
                    "value": f"**{stats['pct']}%**\n`{bar_used}{bar_free}`",
                    "inline": True,
                },
                {
                    "name": "合計 / 警戒ライン",
                    "value": f"合計: {stats['total_mb']} MB\n警戒: 空き < {FREE_THRESHOLD_MB} MB",
                    "inline": True,
                },
            ],
            "footer": {
                "text": f"AI-Brain Memory Monitor • {datetime.now().strftime('%Y-%m-%d %H:%M')}"
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

# ── メイン ────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    # ゾンビ解放は常時実行
    zombies = kill_zombies()
    stale   = kill_stale_aibrain(max_hours=2)

    if "--clean" in args:
        print(f"ゾンビプロセス解放: {zombies} 件")
        if stale:
            for pid, cmd in stale:
                print(f"  長時間プロセス終了 PID={pid}: {cmd}")
        return

    stats = get_memory_stats()
    ai_mb, ai_procs = get_aibrain_process_mb()
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 警告条件: 使用量が閾値超 OR 空きが閾値未満
    over_used = USED_THRESHOLD_MB > 0 and stats["used_mb"] > USED_THRESHOLD_MB
    low_free  = FREE_THRESHOLD_MB > 0 and stats["free_mb"] < FREE_THRESHOLD_MB
    alert     = over_used or low_free

    if "--status" in args:
        bar = "█" * int(stats["pct"] / 10) + "░" * (10 - int(stats["pct"] / 10))
        icon = "⚠️ " if alert else "✅"
        print(f"[{ts}] {icon} メモリ状況")
        print(f"  使用: {stats['used_mb']} MB / {stats['total_mb']} MB  [{bar}] {stats['pct']}%")
        if USED_THRESHOLD_MB:
            print(f"  警戒ライン: 使用 > {USED_THRESHOLD_MB} MB")
        if FREE_THRESHOLD_MB:
            print(f"  警戒ライン: 空き < {FREE_THRESHOLD_MB} MB  (現在 {stats['free_mb']} MB)")
        if ai_mb:
            print(f"  AI-Brain プロセス: {ai_mb} MB")
            for mb, cmd in ai_procs:
                print(f"    {mb} MB  {cmd}")
        if zombies:
            print(f"  ゾンビ解放: {zombies} 件")
        if stale:
            print(f"  長時間プロセス終了: {len(stale)} 件")
        return

    if alert:
        if should_notify():
            ok = send_discord(stats)
            reason = f"使用 {stats['used_mb']}MB > {USED_THRESHOLD_MB}MB" if over_used else \
                     f"空き {stats['free_mb']}MB < {FREE_THRESHOLD_MB}MB"
            if ok:
                mark_notified()
                print(f"[{ts}] ⚠️ {reason} — Discord通知送信")
            else:
                print(f"[{ts}] ⚠️ {reason} — Discord送信失敗")
        # else: クールダウン中はサイレント
    # else: 正常時はサイレント（ログ肥大化防止）

    if zombies or stale:
        print(f"[{ts}] 🧹 クリーンアップ: ゾンビ {zombies}件 / 長時間プロセス {len(stale)}件")

if __name__ == "__main__":
    main()
