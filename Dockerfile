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

# Устанавливаем переменную окружения PORT, если она не задана (Cloud Run сам ее задаст)
ENV PORT 8080

# Запускаем Gunicorn. Он будет слушать порт $PORT и вызывать функцию check_unread_emails_http из main.py
# Имя "main:check_unread_emails_http" означает:
# "main" - это имя вашего Python-файла (main.py)
# "check_unread_emails_http" - это имя вызываемого объекта (вашей функции) в этом файле.
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "main:check_unread_emails_http"]