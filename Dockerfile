# Используем официальный базовый образ Python
FROM python:3.9-slim

# Устанавливаем рабочий каталог внутри контейнера
WORKDIR /app

# Копируем файл зависимостей в рабочий каталог
COPY requirements.txt requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения в рабочий каталог
COPY . .

# Cloud Run будет вызывать вашу HTTP-функцию (check_unread_emails_http), 
# поэтому специальная команда CMD для запуска веб-сервера типа Gunicorn здесь не обязательна,
# если ваша функция настроена как точка входа в Cloud Run.
# Если бы вы хотели запустить веб-сервер, вы бы добавили Gunicorn в requirements.txt
# и использовали бы что-то вроде:
# CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:check_unread_emails_http"]