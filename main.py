# main.py (Тестовая версия для проверки Gunicorn и Cloud Run)

def application(environ, start_response):
    """
    Простое WSGI-совместимое приложение для тестирования.
    Gunicorn будет вызывать этот объект 'application'.
    """
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    
    message = "Hello from Gunicorn in Cloud Run (test app)!\nPython script is running.\n"
    
    # Эта строка поможет нам увидеть в логах Cloud Run, что функция действительно вызвана
    print("SUCCESS: Test application 'application' in main.py was called by Gunicorn and is serving a request.")
    
    return [message.encode("utf-8")]

# Если вы хотите иметь возможность запустить этот файл напрямую для локального теста (хотя Gunicorn этого не требует)
# То это не будет использоваться Cloud Run / Gunicorn
if __name__ == '__main__':
    try:
        from wsgiref.simple_server import make_server
        port = 8080
        httpd = make_server('', port, application)
        print(f"Локальный тестовый WSGI сервер запущен на порту {port}...")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Локальный тестовый сервер остановлен.")
    except Exception as e:
        print(f"Ошибка запуска локального тестового сервера: {e}")