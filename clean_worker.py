with open("/Users/chandan/leadflow/cloudflare_worker/index.js", "r") as f:
    code = f.read()

# Find the second sendStats and everything up to the duplicate of sendDrafts if it exists
import re
# We just need to remove the duplicate `sendStats` function!
code = re.sub(r'async function sendStats\(chatId, msgId\) \{.*?return tgSend\("editMessageText", \{ chat_id: chatId, message_id: msgId, text, parse_mode: "Markdown", reply_markup \}\);\n      \}\n', '', code, count=1, flags=re.DOTALL)

with open("/Users/chandan/leadflow/cloudflare_worker/index.js", "w") as f:
    f.write(code)
