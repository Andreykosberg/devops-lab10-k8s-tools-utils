import os
import time
import socket

from flask import Flask, Response
import redis
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)
cache = redis.Redis(host='redis', port=6379)

# VERSION 3 (Lab 10): параметры окружения вынесены в переменные среды,
# чтобы одна и та же Docker-образ работал по-разному в dev/prod оверлеях
# Kustomize (Task 2) без пересборки образа.
APP_ENV = os.environ.get('APP_ENV', 'local')
GREETING_MESSAGE = os.environ.get('GREETING_MESSAGE', 'Hello World')
APP_COLOR = os.environ.get('APP_COLOR', 'default')

# Доп. задание (унаследовано из Lab 08/09): нативная метрика Prometheus - счётчик посещений сайта.
VIEW_COUNT = Counter(
    'view_count',
    'Общее количество посещений сайта',
    ['service']
)


def get_hit_count():
    retries = 5
    while True:
        try:
            return cache.incr('hits')
        except redis.exceptions.ConnectionError as exc:
            if retries == 0:
                raise exc
            retries -= 1
            time.sleep(0.5)


@app.route('/')
def hello():
    count = get_hit_count()
    VIEW_COUNT.labels(service='Flask-Redis-App').inc()
    return (
        f'{GREETING_MESSAGE} VERSION 3! Эта страница была просмотрена {count} раз(а).\n'
        f'Запрос обработал Pod: {socket.gethostname()}\n'
        f'Окружение (APP_ENV): {APP_ENV} | Цвет (APP_COLOR): {APP_COLOR}\n'
        f'Andrey Kosberg — DevOps Course, Lab 10 (K8s tools & utils).\n'
    )


@app.route('/env')
def env_info():
    # Доп. эндпоинт: удобно для скриптовой проверки, какие именно
    # переменные окружения получил контейнер в dev/prod оверлее.
    return {
        'APP_ENV': APP_ENV,
        'GREETING_MESSAGE': GREETING_MESSAGE,
        'APP_COLOR': APP_COLOR,
        'pod': socket.gethostname(),
    }


@app.route('/metrics')
def metrics():
    # Доп. задание: endpoint для нативной выдачи метрик в формате Prometheus.
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
