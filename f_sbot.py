import os
import base64
import asyncio
import imaplib
import email
from email.header import decode_header
from google import genai
from telegram import Bot
from util import get_env_var

from dotenv import load_dotenv

load_dotenv()

# environment variables
PROFESSORS = get_env_var("PROFESSORS").split(",")
ACCOUNTS = get_env_var("ACCOUNTS").split(",")

GEMINI_API_KEY = get_env_var("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = get_env_var("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_env_var("TELEGRAM_CHAT_ID")

GMAIL_EMAIL = get_env_var("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = get_env_var("GMAIL_APP_PASSWORD")

# Setup Clients
client = genai.Client(api_key=GEMINI_API_KEY)
tg_bot = Bot(token=TELEGRAM_BOT_TOKEN)

# AI summarization using gemini prompt 
def summarize_student_email(email_text):
    if not email_text or len(email_text.strip()) < 10:
        return "No significant text content found in this email."
    
    # Clean long emails 
    clean_text = email_text[:8000] 

    # gemini prompt
    prompt = f"""
    You are an AI assistant for college students. 
    Summarize the email below into this exact bullet-point format:

    📩 From: [Professor/Dept Name]
    ⚠️ Priority: [Low/Medium/High/Urgent]
    ⏰ Deadline: [Specific Date & Time or 'None mentioned']
    🎭 Vibe Check: [Tone of the mail]
    🎯 The Bottom Line: [What do they actually want in simple terms?]
    📝 Summary: [2-line summary of the whole thing]

    Keep it brief, use emojis and be relatable to a student.

    Email: {clean_text}
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"🤖 AI Error: {e}"

# send message on telegram
async def send_to_telegram(message=None, file_path=None):
    try:
        if message:
            await tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as document:
                await tg_bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=document)
            print(f"✅ Document sent: {os.path.basename(file_path)}")
            os.remove(file_path) # Cleanup
    except Exception as e:
        print(f"❌ Telegram Delivery Error: {e}")

# checks mailbox for relevant emails every 10 minutes
async def process_mailbox(folder_name):
    print(f"📂 Checking folder: {folder_name}...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        mail.select(folder_name)

        # Search for UNREAD messages
        status, messages = mail.search(None, 'UNSEEN')
        if status != 'OK' or not messages[0]:
            mail.logout()
            return

        for msg_id in messages[0].split():
            res, data = mail.fetch(msg_id, "(RFC822)")
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            sender = msg.get("From", "")
            subject = msg.get("Subject", "No Subject")
            
            # Filter for specific professors
            is_prof = any(prof.lower() in sender.lower() for prof in PROFESSORS)

            if is_prof:
                print(f"📍 Match Found in {folder_name}: {subject}")
                
                email_body = ""
                attachments = []

                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))

                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            email_body += part.get_payload(decode=True).decode(errors='ignore')
                        
                        elif "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename:
                                # Create temp dir for attachments
                                if not os.path.exists("temp_files"):
                                    os.makedirs("temp_files")
                                filepath = os.path.join("temp_files", filename)
                                with open(filepath, 'wb') as f:
                                    f.write(part.get_payload(decode=True))
                                attachments.append(filepath)
                else:
                    email_body = msg.get_payload(decode=True).decode(errors='ignore')

                # Summarize email using AI
                summary = summarize_student_email(email_body)
                full_alert = f"🔔 *New Relevant Email Found in {folder_name}*\n\n{summary}"
                
                # Send Summary to telegram
                await send_to_telegram(message=full_alert)

                # Send Attachments if any
                for file in attachments:
                    await send_to_telegram(file_path=file)

        mail.close()
        mail.logout()

    except Exception as e:
        print(f"❌ Mail Error in {folder_name}: {e}")

# the main loop
async def main():
    print("🚀 Student Email Monitor Started...")
    # Check both inbox and spam folders
    target_folders = ["INBOX", '"[Gmail]/Spam"']
    
    while True:
        for folder in target_folders:
            await process_mailbox(folder)
        
        print("😴 Sleeping for 10 minutes...")
        await asyncio.sleep(600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Script stopped by user.")