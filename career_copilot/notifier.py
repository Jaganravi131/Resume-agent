import os
import urllib.request
import urllib.parse
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger("career_copilot.notifier")


def _safe_terminal_text(text: str) -> str:
    return text.encode("ascii", errors="replace").decode("ascii")


def _chunk_message(message: str, max_len: int = 3500) -> list[str]:
    if len(message) <= max_len:
        return [message]

    chunks: list[str] = []
    current = ""
    for line in message.splitlines(keepends=True):
        if len(current) + len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""
            if len(line) > max_len:
                for i in range(0, len(line), max_len):
                    chunks.append(line[i : i + max_len])
            else:
                current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def send_whatsapp_message(message: str) -> bool:
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    receiver = os.environ.get("WHATSAPP_TO_NUMBER")

    if not token or not phone_number_id or not receiver:
        logger.warning("WhatsApp credentials not configured in environment variables.")
        print(_safe_terminal_text(f"[WhatsApp Mock Message]:\n{message}\n"))
        return False

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": receiver,
        "type": "text",
        "text": {"body": message},
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = response.read()
            res_json = json.loads(res_data.decode("utf-8"))
            return bool(res_json)
    except Exception as e:
        logger.error("Failed to send WhatsApp message: %s", e)
        print(_safe_terminal_text(f"[WhatsApp Error] Message fell back to terminal:\n{message}\n"))
        return False

def send_telegram_message(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram credentials not configured in environment variables.")
        print(_safe_terminal_text(f"[Telegram Mock Message]:\n{message}\n"))
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    parse_mode = os.environ.get("TELEGRAM_PARSE_MODE", "")
    all_ok = True

    for chunk in _chunk_message(message):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = response.read()
                res_json = json.loads(res_data.decode("utf-8"))
                if not res_json.get("ok", False):
                    all_ok = False
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)
            print(_safe_terminal_text(f"[Telegram Error] Message fell back to terminal:\n{chunk}\n"))
            all_ok = False

    return all_ok

def send_email(subject: str, html_content: str) -> bool:
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = os.environ.get("SMTP_PORT", "587")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if password:
        password = password.replace(" ", "")
    receiver = os.environ.get("RECEIVER_EMAIL")

    if not smtp_server or not username or not password or not receiver:
        logger.warning("SMTP configuration not fully set up in environment variables.")
        print(_safe_terminal_text(f"[Email Mock] Subject: {subject}\nContent:\n{html_content}\n"))
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = receiver

    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.starttls()
        server.login(username, password)
        server.sendmail(username, receiver, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        print(_safe_terminal_text(f"[Email Error] Subject: {subject} failed to send.\n"))
        return False
