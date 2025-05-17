# main.py

import os
import pickle
import base64
import re 
from datetime import datetime 
import html 

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials 
from googleapiclient.discovery import build
from google.cloud import storage
from bs4 import BeautifulSoup # Для извлечения текста из HTML

import vertexai
from vertexai.generative_models import GenerativeModel

# --- Конфигурация Gmail Агента и Google Cloud ---
# Эти значения будут в первую очередь браться из переменных окружения Cloud Run.
# Если они там не установлены, будут использованы значения по умолчанию (что не рекомендуется для GCS путей).
BUCKET_NAME = os.environ.get('GCS_BUCKET_NAME', 'gmailaiagent-id-gmail-agent-files') 
TOKEN_PICKLE_GCS_PATH = os.environ.get('TOKEN_PICKLE_GCS_PATH', 'gmail_tokens/token.pickle')
CLIENT_SECRET_GCS_PATH = os.environ.get('CLIENT_SECRET_GCS_PATH', 'gmail_tokens/client_secret_desktop.json')

SCOPES = ['https://mail.google.com/'] 
TEMP_TOKEN_PATH = '/tmp/token.pickle'
TEMP_CLIENT_SECRET_PATH = '/tmp/client_secret.json'

# --- Конфигурация для Vertex AI Gemini ---
# Предпочтительно устанавливать через переменные окружения в Cloud Run.
# Если они не установлены, используются значения ниже.
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "gmailaiagent-458710") 
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
GEMINI_MODEL_NAME = "gemini-1.5-flash-001"

MAX_EMAILS_TO_PROCESS = 5 
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- Правила Категоризации ---
# (Оставлены как в вашем исходном файле)
airdrops_domains = ["airdrops.io", "airdropalert.com", "mpost.io", "freecoins24.io", "latoken.com", "coinmarketcap.com", "coingecko.com", "binance.com", "bybit.com", "gate.io", "kucoin.com", "cryptobullsclub.com", "dappradar.com"]
crypto_domains = ["binance.com", "kucoin.com", "bybit.com", "okx.com", "cointelegraph.com", "decrypt.co", "coindesk.com", "kraken.com", "coinbase.com", "bitfinex.com", "messari.io", "blockworks.co"]
ai_original_domains = ["heygen.com", "openai.com", "midjourney.com", "anthropic.com", "runwayml.com", "elevenlabs.io", "naturalreaders.com", "perplexity.ai", "huggingface.co", "deepmind.com", "stability.ai", "meta.ai", "google.com", "microsoft.com"]
ai_new_domains = ["email.heygen.com", "learn.heygen.com", "hello.remove.bg"]
ai_combined_domains = list(set(ai_original_domains + ai_new_domains))
cnc_cad_domains = ["autodesk.com", "autodeskcommunications.com", "solidworks.com", "fusion360.autodesk.com", "mastercam.com", "haascnc.com", "grabcad.com", "edingcnc.com", "linuxcnc.org", "bobcad.com", "machsupport.com"]
stock_original_domains = ["revolut.com", "tradingview.com", "investing.com", "interactivebrokers.co.uk", "interactivebrokers.com", "bloomberg.com", "seekingalpha.com", "fidelity.com", "schwab.com", "e*trade.com", "robinhood.com", "marketwatch.com", "nasdaq.com"]
stock_new_domains = ["marketscreener.com", "email.interactivebrokers.com", "interactivebrokers-email.com", "yahoo.com", "investing.com", "bloomberg.com", "marketwatch.com", "cnbc.com", "tradingview.com", "morningstar.com", "seekingalpha.com", "finviz.com", "reuters.com"]
stock_combined_domains = list(set(stock_original_domains + stock_new_domains))

CATEGORIZATION_RULES = [
    {"name": "Airdrops", "senders_domains": airdrops_domains, "subject_keywords": ["airdrop", "token distribution", "claim now", "free tokens", "crypto rewards", "snapshot", "airdrop alert", "token giveaway", "retrodrop", "claimable", "claim", "free mint"]},
    {"name": "Crypto", "senders_domains": crypto_domains, "subject_keywords": ["bitcoin", "ethereum", "blockchain", "defi", "staking", "smart contract", "wallet", "crypto news", "web3", "altcoin"]},
    {"name": "AI new features/services", "senders_domains": ai_combined_domains, "subject_keywords": ["gpt", "ai update", "new model", "api release", "multimodal", "diffusion", "llm", "ai tools", "ai launch", "open source ai"]},
    {"name": "CNC, CAD/CAM", "senders_domains": cnc_cad_domains, "subject_keywords": ["g-code", "toolpath", "cam update", "cad drawing", "post processor", "cnc programming", "fusion 360", "solidworks", "machine setup", "machining"]},
    {"name": "Stock market/brokers", "senders_domains": stock_combined_domains, "subject_keywords": ["earnings report", "market update", "s&p500", "nasdaq", "portfolio", "dividend", "analyst rating", "buy/sell alert", "etf", "stock analysis"]}
]

def extract_domain(email_address):
    if not email_address: return ""
    match = re.search(r"@([\w.-]+)", email_address)
    return match.group(1).lower() if match else ""

def download_from_gcs(bucket_name, source_blob_name, destination_file_name):
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        if not blob.exists(storage_client):
            print(f"Файл {source_blob_name} не найден в бакете {bucket_name}.")
            return False
        blob.download_to_filename(destination_file_name)
        print(f"Файл {source_blob_name} загружен из GCS в {destination_file_name}")
        return True
    except Exception as e:
        print(f"Ошибка при загрузке файла {source_blob_name} из GCS: {e}")
        raise 

def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        print(f"Файл {source_file_name} загружен в GCS как {destination_blob_name}")
        return True
    except Exception as e:
        print(f"Ошибка при загрузке файла {source_file_name} в GCS: {e}")
        return False

def get_gmail_service_automated():
    creds = None
    if not download_from_gcs(BUCKET_NAME, TOKEN_PICKLE_GCS_PATH, TEMP_TOKEN_PATH):
        print(f"КРИТИЧНО: Не удалось загрузить {TOKEN_PICKLE_GCS_PATH}. Проверьте имя бакета и путь к файлу в GCS, а также права доступа сервисного аккаунта ({os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'Default Compute SA')}) к бакету.")
        return None
    if os.path.exists(TEMP_TOKEN_PATH):
        try:
            with open(TEMP_TOKEN_PATH, 'rb') as token_file:
                creds = pickle.load(token_file)
        except Exception as e:
            print(f"Ошибка загрузки/десериализации токена из {TEMP_TOKEN_PATH}: {e}. Файл может быть поврежден.")
            if os.path.exists(TEMP_TOKEN_PATH): os.remove(TEMP_TOKEN_PATH)
            return None
    else:
        print(f"КРИТИЧНО: Файл токена {TEMP_TOKEN_PATH} не существует после попытки загрузки.")
        return None
    
    if not isinstance(creds, Credentials):
        print(f"КРИТИЧНО: Загруженный объект не Credentials. Тип: {type(creds)}. Файл токена {TOKEN_PICKLE_GCS_PATH} в GCS, вероятно, поврежден или имеет неверный формат.")
        if os.path.exists(TEMP_TOKEN_PATH): os.remove(TEMP_TOKEN_PATH)
        return None

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            print("Токен истек, пытаемся обновить...")
            if not download_from_gcs(BUCKET_NAME, CLIENT_SECRET_GCS_PATH, TEMP_CLIENT_SECRET_PATH):
                print(f"КРИТИЧНО: Не удалось загрузить {CLIENT_SECRET_GCS_PATH} для обновления токена.")
                return None
            try:
                creds.refresh(Request())
                print("Токен успешно обновлен.")
                with open(TEMP_TOKEN_PATH, 'wb') as token_file: pickle.dump(creds, token_file)
                if not upload_to_gcs(BUCKET_NAME, TEMP_TOKEN_PATH, TOKEN_PICKLE_GCS_PATH):
                    print(f"ПРЕДУПРЕЖДЕНИЕ: Не удалось загрузить обновленный токен в GCS.")
            except Exception as e:
                print(f"КРИТИЧЕСКАЯ ОШИБКА обновления токена: {e}. Проверьте {CLIENT_SECRET_GCS_PATH}.")
                if os.path.exists(TEMP_TOKEN_PATH): os.remove(TEMP_TOKEN_PATH)
                return None
        else:
            print("КРИТИЧНО: Нет валидных creds или refresh_token. Пересоздайте token.pickle с SCOPES=['https://mail.google.com/'] и client_secret_desktop.json для Desktop app.")
            if os.path.exists(TEMP_TOKEN_PATH): os.remove(TEMP_TOKEN_PATH)
            return None
    try:
        service = build('gmail', 'v1', credentials=creds)
        print("Успешно создан сервис Gmail API!")
        return service
    except Exception as e:
        print(f"Ошибка при создании Gmail API service: {e}")
        return None

def get_email_details(service, user_id, msg_id):
    try:
        message = service.users().messages().get(userId=user_id, id=msg_id, format='full').execute()
        email_data = {'id': message.get('id'), 'subject': '', 'from': '', 'date': '', 'body': ''}
        payload = message.get('payload', {})
        headers = payload.get('headers', [])
        
        for header in headers:
            name = header.get('name', '').lower()
            value = header.get('value', '')
            if name == 'subject': email_data['subject'] = value
            elif name == 'from': email_data['from'] = value
            elif name == 'date': email_data['date'] = value

        body_text = ""
        if 'parts' in payload:
            for part in payload.get('parts', []):
                if part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data')
                    if data: body_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace'); break
            if not body_text:
                for part in payload.get('parts', []):
                    if part.get('mimeType') == 'text/html':
                        data = part.get('body', {}).get('data')
                        if data: html_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace'); soup = BeautifulSoup(html_body, "html.parser"); body_text = soup.get_text(separator='\n', strip=True); break
        elif 'body' in payload and 'data' in payload.get('body', {}): 
            data = payload.get('body', {}).get('data')
            if data:
                decoded_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                if payload.get('mimeType') == 'text/html': soup = BeautifulSoup(decoded_body, "html.parser"); body_text = soup.get_text(separator='\n', strip=True)
                else: body_text = decoded_body
        
        if not body_text: body_text = message.get('snippet', '')
        email_data['body'] = body_text.strip()
        return email_data
    except Exception as e:
        print(f"Ошибка при получении деталей (full) сообщения {msg_id}: {e}")
        return None

def mark_email_as_read(service, user_id, msg_id):
    try:
        service.users().messages().modify(userId=user_id, id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()
        print(f"  Письмо {msg_id} помечено как прочитанное.")
        return True
    except Exception as e:
        print(f"  Ошибка при пометке письма {msg_id} как прочитанного: {e}")
        return False

def categorize_email(email_details):
    sender_full = email_details.get('from', '').lower()
    subject_lower = email_details.get('subject', '').lower()
    sender_domain = extract_domain(sender_full)
    for rule in CATEGORIZATION_RULES:
        if sender_domain and rule.get("senders_domains") and sender_domain in rule["senders_domains"]: return rule["name"]
        if rule.get("subject_keywords") and any(keyword.lower() in subject_lower for keyword in rule["subject_keywords"]): return rule["name"]
    return "Прочие письма и адресаты"

def summarize_email_with_gemini(email_text, project_id, location, model_name):
    if not email_text: return "Текст письма отсутствует, резюме не создано."
    try:
        try: vertexai.init(project=project_id, location=location)
        except Exception: pass # Игнорируем, если SDK уже инициализирован

        model = GenerativeModel(model_name)
        max_chars_for_summary = 25000 
        email_text_for_summary = email_text[:max_chars_for_summary] if len(email_text) > max_chars_for_summary else email_text

        prompt = f"""Ты — AI ассистент, который помогает анализировать электронные письма.
Твоя задача — очень кратко изложить суть следующего письма на русском языке в одном или двух предложениях.
Сосредоточься на главной теме письма.
Примеры хороших резюме:
- "Рекламная кампания по продаже велосипедов компании X."
- "Анонс конференции на тему 'AI и ничего больше'."
- "Уведомление о предстоящем вебинаре по машинному обучению."
- "Запрос дополнительной информации по проекту Y."

Не добавляй никаких вступлений вроде "Это письмо о..." или "Резюме письма:". Просто предоставь саму суть.

Текст письма для анализа:
---
{email_text_for_summary}
---
Краткое резюме на русском языке:"""

        generation_config = {"max_output_tokens": 150, "temperature": 0.3, "top_p": 0.95}
        response = model.generate_content(prompt, generation_config=generation_config)
        
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            return response.candidates[0].content.parts[0].text.strip()
        elif hasattr(response, 'text') and response.text: return response.text.strip()
        else: print(f"Не удалось получить валидный ответ от Gemini. Ответ: {response}"); return "Резюме не создано (ответ API не содержит ожидаемых данных)."
    except Exception as e:
        print(f"Ошибка при вызове Gemini API ({type(e).__name__}): {e}")
        import traceback; print(traceback.format_exc())
        return f"Ошибка при создании резюме ({type(e).__name__})"

def generate_html_report(processed_emails_info, remaining_unread_count):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_rows = ""
    for item in processed_emails_info:
        category = html.escape(item.get('category', 'н/д'))
        date_str = item.get('date', 'н/д')
        date_display = html.escape(date_str) # Упрощенный вывод даты
        sender = html.escape(item.get('from', 'н/д'))
        subject_full = item.get('subject', 'Без темы')
        subject_preview = html.escape(" ".join(subject_full.split()[:5]) + ("..." if len(subject_full.split()) > 5 else ""))
        summary_llm = html.escape(item.get('summary', 'Резюме отсутствует'))
        html_rows += f"<tr><td>{category}</td><td>{date_display}</td><td>{sender}</td><td>{subject_preview}</td><td>{summary_llm}</td></tr>"

    html_content = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>Отчет Gmail Агента c LLM</title>
<style>body{{font-family:Arial,sans-serif;margin:20px;background-color:#f4f4f4;color:#333}}h1{{color:#333}}h2{{color:#555}}
table{{border-collapse:collapse;width:100%;margin-bottom:20px;box-shadow:0 2px 3px rgba(0,0,0,0.1);background-color:white}}
th,td{{border:1px solid #ddd;padding:10px;text-align:left;word-break:break-word}}th{{background-color:#e9e9e9}}
tr:nth-child(even){{background-color:#f9f9f9}}.summary{{margin-top:20px;padding:15px;background-color:#e7f3fe;border-left:5px solid #2196F3}}
.summary p{{margin:5px 0}}</style></head><body><h1>Отчет о проверке Gmail (с LLM резюме)</h1><p>Время проверки: {current_time}</p>
<h2>Обработанные письма (до {MAX_EMAILS_TO_PROCESS} за запуск):</h2>
{'<table><tr><th>Категория</th><th>Дата</th><th>Отправитель</th><th>Тема (начало)</th><th>Резюме LLM (RU)</th></tr>' + html_rows + '</table>' if processed_emails_info else "<p>В этом запуске письма для детальной обработки не найдены или не были обработаны.</p>"}
<div class="summary"><p>Всего обработано и помечено как прочитанные в этом запуске: {len(processed_emails_info)} писем.</p>
<p>Оставшееся количество непрочитанных сообщений в ящике: {remaining_unread_count}</p></div>
<footer><p><small>Project ID: {GCP_PROJECT_ID}, Region: {GCP_REGION}, Model: {GEMINI_MODEL_NAME}</small></p></footer>
</body></html>"""
    return html_content

def check_unread_emails_http(request):
    print(f"Функция check_unread_emails_http вызвана. Project ID: {GCP_PROJECT_ID}, Region: {GCP_REGION}")
    
    if 'not-set' in BUCKET_NAME or 'not-set' in TOKEN_PICKLE_GCS_PATH or 'not-set' in CLIENT_SECRET_GCS_PATH:
        error_message = "КРИТИЧНО: Переменные окружения для GCS (GCS_BUCKET_NAME, TOKEN_PICKLE_GCS_PATH, CLIENT_SECRET_GCS_PATH) не установлены корректно в Cloud Run."
        print(error_message); return (f"<html><body><h1>Критическая ошибка конфигурации</h1><p>{html.escape(error_message)}</p></body></html>", 500, {'Content-Type': 'text/html; charset=utf-8'})

    gmail_service = get_gmail_service_automated()
    processed_emails_info_for_html = [] 
    if gmail_service:
        try:
            response_list = gmail_service.users().messages().list(userId='me', q='is:unread', maxResults=MAX_EMAILS_TO_PROCESS).execute()
            messages = response_list.get('messages', [])
            print(f"Найдено {len(messages)} непрочитанных для обработки (максимум {MAX_EMAILS_TO_PROCESS}).")

            if messages:
                for msg_summary in messages:
                    msg_id = msg_summary['id']
                    print(f"\nОбработка письма ID: {msg_id}")
                    email_details = get_email_details(gmail_service, 'me', msg_id)
                    if email_details:
                        category = categorize_email(email_details)
                        print(f"  Письмо ID [{msg_id}] от '{email_details.get('from', 'N/A')}' тема '{email_details.get('subject', 'N/A')}' -> категория: '{category}'.")
                        
                        email_body = email_details.get('body', '')
                        summary_text = "Резюме не создано (нет текста)."
                        if email_body:
                            print(f"  Отправка текста (первые 100 сим: '{email_body[:100]}...') на суммирование.")
                            summary_text = summarize_email_with_gemini(email_body, GCP_PROJECT_ID, GCP_REGION, GEMINI_MODEL_NAME)
                            print(f"  Резюме LLM: {summary_text}")
                        
                        processed_emails_info_for_html.append({"category": category, "date": email_details.get('date', 'н/д'), "from": email_details.get('from', 'н/д'), "subject": email_details.get('subject', 'Без темы'), "summary": summary_text})
                        mark_email_as_read(gmail_service, 'me', msg_id)
            
            remaining_unread_count = "н/д"
            try:
                unread_label_info = gmail_service.users().labels().get(userId='me', id='UNREAD').execute()
                remaining_unread_count = unread_label_info.get('messagesUnread', 0)
            except Exception as e_unread: print(f"Не удалось получить кол-во непрочитанных: {e_unread}")
            print(f"Оставшееся количество непрочитанных: {remaining_unread_count}")
            return (generate_html_report(processed_emails_info_for_html, remaining_unread_count), 200, {'Content-Type': 'text/html; charset=utf-8'})
        except Exception as e:
            import traceback; error_message = f"Ошибка: {e}\n{traceback.format_exc()}"
            print(error_message); return (f"<html><body><h1>Ошибка</h1><pre>{html.escape(error_message)}</pre></body></html>", 500, {'Content-Type': 'text/html; charset=utf-8'})
    else:
        error_message = "Не удалось получить сервис Gmail. Проверьте конфигурацию токенов и GCS."
        print(error_message); return (f"<html><body><h1>Критическая ошибка</h1><p>{html.escape(error_message)}</p></body></html>", 500, {'Content-Type': 'text/html; charset=utf-8'})

if __name__ == '__main__':
    print("Запуск локального теста...")
    # Убедитесь, что переменные окружения установлены для локального теста или используйте значения по умолчанию.
    # Для локального теста Vertex AI может потребоваться `gcloud auth application-default login`.
    os.environ.setdefault('GCS_BUCKET_NAME', 'gmailaiagent-id-gmail-agent-files')
    os.environ.setdefault('TOKEN_PICKLE_GCS_PATH', 'gmail_tokens/token.pickle')
    os.environ.setdefault('CLIENT_SECRET_GCS_PATH', 'gmail_tokens/client_secret_desktop.json')
    os.environ.setdefault('GCP_PROJECT_ID', 'gmailaiagent-458710')
    os.environ.setdefault('GCP_REGION', 'us-central1')

    BUCKET_NAME = os.environ['GCS_BUCKET_NAME'] # Перечитываем на случай если os.environ.get вернул default
    TOKEN_PICKLE_GCS_PATH = os.environ['TOKEN_PICKLE_GCS_PATH']
    CLIENT_SECRET_GCS_PATH = os.environ['CLIENT_SECRET_GCS_PATH']
    GCP_PROJECT_ID = os.environ['GCP_PROJECT_ID']
    GCP_REGION = os.environ['GCP_REGION']

    print(f"Локальный тест использует: Бакет GCS='{BUCKET_NAME}', Project ID='{GCP_PROJECT_ID}', Region='{GCP_REGION}'")
    class MockRequest: method = 'GET'
    response_content, status_code, _ = check_unread_emails_http(MockRequest())
    print(f"\nЛокальный тест завершен. Статус: {status_code}")
    if status_code == 200:
        with open("local_gmail_report.html", "w", encoding="utf-8") as f: f.write(response_content)
        print("Отчет сохранен в local_gmail_report.html")
    else: print(f"Ответ (ошибка):\n{response_content}")