#!/usr/bin/env python3
import re, os
from datetime import datetime

ZSHRC  = os.path.expanduser("~/.zshrc")
VAULT  = os.path.expanduser("~/Desktop/ClaudeProjects/AI-Brain")
OUTPUT = os.path.join(VAULT, "Shared", "Knowledge", "mac-config.md")

SECRET = re.compile(r"TOKEN|KEY|PASSWORD|PASSWD|WEBHOOK|SECRET|BOT|CREDENTIAL", re.I)

def mask_line(line):
    m = re.match(r'^(\s*(?:export\s+)?)(\w+)(=)(["\x27]?)(.+?)(["\x27]?)(\s*)$', line)
    if m and SECRET.search(m.group(2)):
        pre, var, eq, q1, val, q2, suf = m.groups()
        return f"{pre}{var}{eq}{q1}****{q2}{suf}"
    return line

lines = open(ZSHRC, encoding="utf-8").read().splitlines()
masked = "\n".join(mask_line(l) for l in lines)
now = datetime.now().strftime("%Y-%m-%d %H:%M")

header = (
    "---\n"
    "type: reference\n"
    "title: Mac ~/.zshrc 設定スナップショット（シークレット値マスク済み）\n"
    f"updated: {now}\n"
    "source: ~/.zshrc\n"
    "---\n\n"
    "# Mac 環境変数設定（~/.zshrc）\n\n"
    "> 自動生成: launchd com.ai-brain.mac-config-sync が毎日午前3時に更新\n"
    "> シークレット値（KEY/TOKEN/PASSWORD等）はマスク済み\n\n"
    "```zsh\n"
)

content = header + masked + "\n```\n"

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
open(OUTPUT, "w", encoding="utf-8").write(content)
print(f"✅ mac-config.md 更新完了 ({now})")
