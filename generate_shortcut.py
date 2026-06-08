#!/usr/bin/env python3
"""
Generate Inbox-to-GitHub.shortcut
  - Import Questionでトークンを1回だけ入力
  - 実行するたびにテキスト入力 → GitHub API経由でInbox/inbox.mdに追記
"""
import plistlib, uuid

def g(): return str(uuid.uuid4()).upper()

# ── Action UUIDs ──────────────────────────────────────────────
A_ASK  = g()   # Ask for Input
A_DATE = g()   # Current Date
A_FMT  = g()   # Format Date
A_GET  = g()   # GET file from GitHub
A_DICT = g()   # Parse JSON to Dictionary
A_SHA  = g()   # Extract sha
A_B64C = g()   # Extract content (base64)
A_DEC  = g()   # Base64 Decode
A_TXT  = g()   # Build new content text
A_ENC  = g()   # Base64 Encode
A_PUT  = g()   # PUT to GitHub
A_ALT  = g()   # Show Result
Q_TOK  = g()   # Import Question: GitHub Token

URL = "https://api.github.com/repos/coretagishi-lab/claude-brain/contents/Inbox/inbox.md"

# ── Serialization helpers ─────────────────────────────────────
def ts(s):
    """Plain literal text"""
    return {"Value": {"string": s}, "WFSerializationType": "WFTextTokenString"}

def av(uid, name):
    """Single reference to another action's output"""
    return {
        "Value": {
            "attachmentsByRange": {
                "{0, 1}": {"OutputName": name, "OutputUUID": uid, "Type": "ActionOutput"}
            },
            "string": "￼"
        },
        "WFSerializationType": "WFTextTokenString"
    }

def ct(*parts):
    """
    Build a WFTextTokenString from mixed text + variable references.
    Each part is either:
      - str  → literal text
      - (uid, "a", name) → reference to an action output
      - (uid, "q")       → reference to an import question
    """
    s, att = "", {}
    for p in parts:
        if isinstance(p, str):
            s += p
        else:
            uid, kind, *rest = p
            pos = len(s)
            s += "￼"
            if kind == "a":
                att[f"{{{pos}, 1}}"] = {
                    "OutputName": rest[0],
                    "OutputUUID": uid,
                    "Type": "ActionOutput"
                }
            else:  # "q" = import question
                att[f"{{{pos}, 1}}"] = {
                    "UUID": uid,
                    "Type": "ImportQuestion"
                }
    return {
        "Value": {"attachmentsByRange": att, "string": s},
        "WFSerializationType": "WFTextTokenString"
    }

def hdr(*pairs):
    """WFHTTPHeaders value"""
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": ts(k), "WFValue": v}
                for k, v in pairs
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue"
    }

def json_body(*pairs):
    """WFHTTPBody as JSON key-value dict"""
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": ts(k), "WFValue": v}
                for k, v in pairs
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue"
    }

# Shared auth header value
AUTH = ct("token ", (Q_TOK, "q"))

# ── Action list ───────────────────────────────────────────────
actions = [

    # 1. テキスト入力
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.ask.for.input",
        "WFWorkflowActionParameters": {
            "UUID": A_ASK,
            "CustomOutputName": "UserInput",
            "WFAskActionPrompt": "Inboxに追加するメモを入力してください",
            "WFInputType": "Text",
        }
    },

    # 2. 現在日時取得
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.date",
        "WFWorkflowActionParameters": {
            "UUID": A_DATE,
            "CustomOutputName": "CurrentDate",
        }
    },

    # 3. 日時フォーマット
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.format.date",
        "WFWorkflowActionParameters": {
            "UUID": A_FMT,
            "CustomOutputName": "FormattedDate",
            "WFDateFormatStyle": "Custom",
            "WFDateCustomFormat": "yyyy-MM-dd HH:mm",
            "WFInput": av(A_DATE, "CurrentDate"),
        }
    },

    # 4. GitHub API GET（現在のファイル取得）
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "UUID": A_GET,
            "CustomOutputName": "FileJSON",
            "WFHTTPMethod": "GET",
            "WFURL": URL,
            "WFHTTPHeaders": hdr(
                ("Authorization", AUTH),
                ("Accept", ts("application/vnd.github.v3+json")),
            ),
            "WFShowHUD": False,
        }
    },

    # 5. JSON → Dictionary
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.detect.dictionary",
        "WFWorkflowActionParameters": {
            "UUID": A_DICT,
            "CustomOutputName": "FileDict",
            "WFInput": av(A_GET, "FileJSON"),
        }
    },

    # 6. sha 取得
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": A_SHA,
            "CustomOutputName": "FileSHA",
            "WFInput": av(A_DICT, "FileDict"),
            "WFDictionaryKey": "sha",
        }
    },

    # 7. content (base64) 取得
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "UUID": A_B64C,
            "CustomOutputName": "B64Content",
            "WFInput": av(A_DICT, "FileDict"),
            "WFDictionaryKey": "content",
        }
    },

    # 8. Base64 デコード
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.base64encode",
        "WFWorkflowActionParameters": {
            "UUID": A_DEC,
            "CustomOutputName": "OldContent",
            "WFInput": av(A_B64C, "B64Content"),
            "WFEncodeAction": "Decode",
            "WFBase64LineBreakMode": "None",
        }
    },

    # 9. 新しい内容を組み立て
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": A_TXT,
            "CustomOutputName": "NewContent",
            "WFTextActionText": ct(
                (A_DEC, "a", "OldContent"),
                "\n- ",
                (A_FMT, "a", "FormattedDate"),
                " ",
                (A_ASK, "a", "UserInput"),
            ),
        }
    },

    # 10. Base64 エンコード
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.base64encode",
        "WFWorkflowActionParameters": {
            "UUID": A_ENC,
            "CustomOutputName": "NewB64",
            "WFInput": av(A_TXT, "NewContent"),
            "WFEncodeAction": "Encode",
            "WFBase64LineBreakMode": "None",
        }
    },

    # 11. GitHub API PUT（ファイル更新）
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "UUID": A_PUT,
            "CustomOutputName": "PutResult",
            "WFHTTPMethod": "PUT",
            "WFURL": URL,
            "WFHTTPHeaders": hdr(
                ("Authorization", AUTH),
                ("Content-Type", ts("application/json")),
                ("Accept", ts("application/vnd.github.v3+json")),
            ),
            "WFHTTPBodyType": "JSON",
            "WFHTTPBody": json_body(
                ("message", ts("Add inbox entry via iPhone Shortcut")),
                ("content", av(A_ENC, "NewB64")),
                ("sha",     av(A_SHA, "FileSHA")),
            ),
            "WFShowHUD": False,
        }
    },

    # 12. 完了通知
    {
        "WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
        "WFWorkflowActionParameters": {
            "UUID": A_ALT,
            "Text": ts("✅ Inboxに追加しました！"),
        }
    },

]

# ── Shortcut plist ────────────────────────────────────────────
shortcut = {
    "WFWorkflowClientVersion": "1154.4.1",
    "WFWorkflowHasShortcutInputVariables": False,
    "WFWorkflowIcon": {
        "WFWorkflowIconStartColor": 1027883519,   # blue
        "WFWorkflowIconGlyphNumber": 59511,        # pencil
    },
    "WFWorkflowImportQuestions": [
        {
            "UUID": Q_TOK,
            "ParameterKey": "GitHubToken",
            "Category": "Parameter",
            "Text": (
                "GitHubのPersonal Access Tokenを入力してください\n"
                "（Settings → Developer settings → Fine-grained tokens\n"
                " → coretagishi-lab/claude-brain → Contents: Read & Write）"
            ),
            "DefaultValue": "",
        }
    ],
    "WFWorkflowInputContentItemClasses": [],
    "WFWorkflowMinimumClientVersion": "900",
    "WFWorkflowMinimumClientVersionString": "900",
    "WFWorkflowName": "Inbox → claude-brain",
    "WFWorkflowNoInputBehavior": {
        "Name": "WFWorkflowNoInputBehaviorAskForInput",
        "Parameters": {}
    },
    "WFWorkflowOutputContentItemClasses": [],
    "WFWorkflowTypes": [],
    "WFWorkflowActions": actions,
}

# ── Write binary plist ────────────────────────────────────────
out = "/Users/tagishitakuya/Desktop/ClaudeProjects/AI-Brain/Inbox-to-GitHub.shortcut"
with open(out, "wb") as f:
    plistlib.dump(shortcut, f, fmt=plistlib.FMT_BINARY)

print(f"✅ Generated: {out}")
print(f"   Actions: {len(actions)}")
print(f"   Import Question UUID: {Q_TOK}")
