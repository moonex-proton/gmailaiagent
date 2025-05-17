# Используем официальный базовый образ Python
FROM python:3.9-slim

# Устанавливаем рабочий каталог внутри контейнера
WORKDIR /app

# Копируем только файл зависимостей сначала для кэширования слоев Docker
COPY requirements.txt requirements.txt

# Устанавливаем зависимости
# Добавляем --no-input, чтобы pip не задавал интерактивных вопросов
RUN pip install --no-cache-dir --no-input -r requirements.txt

# Копируем весь остальной код приложения (включая main.py) в рабочий каталог
COPY . .

# Устанавливаем переменную окружения PORT (Cloud Run передаст актуальное значение)
ENV PORT 8080

# Запускаем Gunicorn.
# Он будет слушать порт $PORT и вызывать WSGI-объект 'application' из файла 'main.py'
CMD ["gunicorn", "--bind", "0.0.0.0:${PORT}", "main:application"]