# DevOps Lab 10 — K8s tools & utils (Helm, Kompose, Kustomize)

Andrey Kosberg — DevOps Course, Lab 10: инструменты поверх «голого» Kubernetes — **Helm** (пакетный менеджер, чарты, релизы, upgrade/uninstall) и **Kompose** (конвертация `docker-compose.yaml` в k8s-манифесты/Helm-чарт) в Task 1, **Kustomize** (base + overlays, без шаблонизации) в Task 2.

Все команды ниже выполнены **по-настоящему** на виртуальной машине `devops-lab01` (тот же стенд, что в Lab 01-09) через SSH (`andrey@127.0.0.1:2223`). Кластер — тот же minikube, что был поднят в Lab 9, `minikube tunnel --bind-address 10.0.2.15` запущен ещё с той лабораторной и продолжал работать на протяжении всей Lab 10 без перезапуска.

## Стенд

| | |
|---|---|
| VM | devops-lab01 (Ubuntu 24.04 noble, тот же стенд, что в Lab 01-09) |
| RAM / CPU | 4096 МБ / 2 ядра (увеличено ещё в Lab 9) |
| IP VM внутри NAT | `10.0.2.15` |
| kubectl | v1.37.1 (включает `kubectl kustomize` / `kubectl apply -k`, Kustomize v5.8.1) |
| minikube | v1.39.0, драйвер `docker`, кластер поднят ещё в Lab 9 |
| Helm | v3.22.1 (`get-helm-3` install-скрипт) |
| Kompose | v1.36.0 (бинарник с GitHub Releases) |
| `minikube tunnel` | запущен ещё в Lab 9 (`sudo minikube tunnel --bind-address 10.0.2.15 &`), не перезапускался — оба Task'а проверялись через один и тот же тоннель |
| Память на момент работы | `free -h` → ~3.8Gi total, ~2.2-2.3Gi available даже при одновременно поднятых Task 1 (3 пода) и Task 2 (dev+prod, 5 подов) |

## Содержимое репозитория

```
devops-lab10-k8s-tools-utils/
├── task1-helm-kompose/
│   ├── monitoring-src/                  # compose-проект prometheus-grafana (вход для Kompose), без изменений из Lab 8
│   │   ├── compose.yaml
│   │   ├── prometheus/prometheus.yml
│   │   └── grafana/provisioning/{datasources,dashboards}/...
│   └── promgra-chart/                   # Helm chart: сгенерирован kompose + доработан руками
│       ├── Chart.yaml                   # name: promgra, описание всех ручных правок
│       ├── values.yaml                  # EXTERNAL_IP / EXTERNAL_PORT / GF_ADMIN_PASSWORD / imagePullPolicy
│       └── templates/
│           ├── grafana-deployment.yaml  # + imagePullPolicy: Never, пароль из values
│           ├── grafana-service.yaml     # + type: LoadBalancer, externalIPs, порт из values
│           ├── grafana-data-persistentvolumeclaim.yaml
│           ├── prometheus-deployment.yaml
│           ├── prometheus-service.yaml
│           ├── prometheus-cm0-configmap.yaml   # сгенерирован kompose из prometheus.yml
│           ├── prom-data-persistentvolumeclaim.yaml
│           ├── blackbox-deployment.yaml
│           └── blackbox-service.yaml
├── task2-kustomize/
│   ├── flask_redis_v3/                  # app.py VERSION 3 - все параметры через переменные окружения
│   │   ├── app.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── base/
│   │   ├── kustomization.yaml           # resources + configMapGenerator (дефолты)
│   │   ├── web-deployment.yaml          # envFrom: configMapRef, без хардкода env
│   │   ├── web-service.yaml             # LoadBalancer
│   │   ├── redis-deployment.yaml
│   │   └── redis-service.yaml
│   └── overlays/
│       ├── dev/                         # namespace dev, 1 реплика, порт 8002, APP_COLOR=green
│       │   ├── kustomization.yaml
│       │   └── namespace.yaml
│       └── prod/                        # namespace prod, 3 реплики, порт 8003, APP_COLOR=red, requests/limits
│           ├── kustomization.yaml
│           └── namespace.yaml
├── screenshots/                          # 7 скриншотов реального выполнения
└── README.md
```

## Задание и как оно выполнено

Лекция и практика Л10/П10 «K8s tools & utils». Постановка задачи (слайд 15):

> Берём за основу 2 docker-compose проекта из прошлых работ – flask-redis и prometheus-grafana.
>
> Задачи:
> 1. Из проекта prometheus-grafana создаём helm-chart и развёртываем в k8s.
> 2. Из проекта flask-app создаём prod и dev окружения через kustomize

Оба пункта выполнены полностью, по шагам ниже.

---

## Task 1. Prometheus-Grafana → Helm chart (Kompose + ручная доводка)

### 1.1. Установка Helm и Kompose

Перед началом — уборка ресурсов Lab 9 из `default` namespace (голые Deployment/Service больше не нужны, дальше всё через Helm/Kustomize):

```bash
$ kubectl delete all --all -n default
pod "flask-app-9f945fd44-2cmpj" deleted
pod "redis-587784b748-l6vd7" deleted
service "redis" deleted
service "service-devops" deleted
deployment.apps "flask-app" deleted
deployment.apps "redis" deleted
```

Helm 3 — официальным install-скриптом, Kompose — готовым бинарником с GitHub Releases:

```bash
$ curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
$ sudo bash get_helm.sh
helm installed into /usr/local/bin/helm
$ helm version --short
v3.22.1+gd6c1a0e

$ curl -fsSL -o kompose https://github.com/kubernetes/kompose/releases/download/v1.36.0/kompose-linux-amd64
$ sudo install -m 0755 kompose /usr/local/bin/kompose
$ kompose version
1.36.0 (ae2a39403)
```

### 1.2. Исходный compose-проект и подготовка образов

За основу взят **prometheus-grafana**, а не flask-redis — так прямо требует слайд 15 методички. Проект — без изменений перенесён из `devops-lab08-docker-compose/monitoring/` (`task1-helm-kompose/monitoring-src/`):

```yaml
services:
  prometheus:
    image: prom/prometheus
    ports: ["9090:9090"]
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prom_data:/prometheus
  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_AUTH_ANONYMOUS_ENABLED=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
  blackbox:
    image: prom/blackbox-exporter
    ports: ["9115:9115"]
volumes:
  prom_data: {}
  grafana_data: {}
```

Образы `prom/prometheus`, `grafana/grafana`, `prom/blackbox-exporter` уже были стянуты host-Docker'ом ещё в Lab 8 — не тянем их заново из интернета, а грузим прямо в containerd minikube:

```bash
$ minikube image load docker.io/grafana/grafana:latest docker.io/prom/prometheus:latest \
    docker.io/prom/blackbox-exporter:latest
$ minikube image ls | grep -E 'grafana|prometheus|blackbox'
docker.io/prom/prometheus:latest
docker.io/prom/blackbox-exporter:latest
docker.io/grafana/grafana:latest
```

### 1.3. `kompose convert --chart` — генерация «сырого» чарта

```bash
$ cd monitoring-src && kompose convert --chart -f compose.yaml
WARN Restart policy 'unless-stopped' in service grafana is not supported, convert it to 'always'
WARN Restart policy 'unless-stopped' in service blackbox is not supported, convert it to 'always'
WARN Restart policy 'unless-stopped' in service prometheus is not supported, convert it to 'always'
WARN File don't exist or failed to check if the directory is empty: stat :/var/lib/grafana: no such file or directory
WARN Failed to check if the directory is empty: open dashboards: no such file or directory
WARN Skip file in path .../grafana/provisioning
WARN File don't exist or failed to check if the directory is empty: stat :/prometheus: no such file or directory
INFO Kubernetes file "compose/templates/blackbox-service.yaml" created
INFO Kubernetes file "compose/templates/grafana-service.yaml" created
INFO Kubernetes file "compose/templates/prometheus-service.yaml" created
INFO Kubernetes file "compose/templates/blackbox-deployment.yaml" created
INFO Kubernetes file "compose/templates/grafana-deployment.yaml" created
INFO Kubernetes file "compose/templates/grafana-data-persistentvolumeclaim.yaml" created
INFO Kubernetes file "compose/templates/prometheus-deployment.yaml" created
INFO Kubernetes file "compose/templates/prom-data-persistentvolumeclaim.yaml" created
INFO Kubernetes file "compose/templates/prometheus-cm0-configmap.yaml" created
INFO chart created in "compose/"
```

Kompose сам: создал `prometheus-cm0-configmap.yaml` из смонтированного `prometheus.yml` (volume → ConfigMap + `subPath`), создал PVC для `prom_data`/`grafana_data`, перевёл все 3 сервиса в Deployment+Service. Папку `grafana/provisioning` (bind-mount с датасорсами/дашбордами) конвертировать не смог («Skip file in path») — ожидаемое ограничение Kompose для вложенных директорий с конфигами Grafana, не критично для демонстрации самого стека.

### 1.4. Ручная доводка чарта (`promgra-chart/`)

У «сырого» чарта от kompose: нет `values.yaml` (все значения — литералы), `grafana-service.yaml` — обычный `ClusterIP` (недоступен снаружи ВМ), образы без `imagePullPolicy` (значит `IfNotPresent`/`Always` по умолчанию → попытка реального pull → `ImagePullBackOff`, т.к. образы загружены только в minikube, а не в публичный registry). Исправлено руками, по аналогии со слайдами 25-34 методички:

1. **Chart.yaml**: `name: compose` → `name: promgra` (чарт переименован, папка `compose/` → `promgra-chart/`).
2. **`grafana-service.yaml`**: добавлен `type: LoadBalancer` и `externalIPs: [{{ .Values.EXTERNAL_IP }}]`, порт параметризован — Grafana торчит наружу ВМ через тот же `minikube tunnel`, что и Kustomize-сервисы Task 2.
3. **`values.yaml`** (создан с нуля — kompose его не генерирует):
   ```yaml
   EXTERNAL_IP: "10.0.2.15"
   EXTERNAL_PORT: 3000
   GF_ADMIN_PASSWORD: "admin"
   images:
     grafana: grafana/grafana
     prometheus: prom/prometheus
     blackbox: prom/blackbox-exporter
     pullPolicy: Never
   ```
4. Во все 3 Deployment добавлен `imagePullPolicy: Never` — образы уже в minikube, лишний pull не нужен и упал бы с ошибкой.
5. `GF_SECURITY_ADMIN_PASSWORD` в `grafana-deployment.yaml` теперь берётся из `{{ .Values.GF_ADMIN_PASSWORD }}`, а не зашит литералом `admin` — пароль можно сменить через `helm upgrade --set` без правки манифеста.

### 1.5. `helm lint` → `helm package` → `helm install` → проверка

```bash
$ helm lint promgra-chart/
[INFO] Chart.yaml: icon is recommended
1 chart(s) linted, 0 chart(s) failed

$ helm package promgra-chart/
Successfully packaged chart and saved it to: /home/andrey/lab10-k8s/task1-helm-kompose/promgra-0.1.0.tgz

$ helm install promgra ./promgra-0.1.0.tgz
NAME: promgra
LAST DEPLOYED: Tue Oct 27 08:19:28 2026
NAMESPACE: default
STATUS: deployed
REVISION: 1

$ kubectl wait --for=condition=available --timeout=90s deployment/grafana deployment/prometheus deployment/blackbox
deployment.apps/grafana condition met
deployment.apps/prometheus condition met
deployment.apps/blackbox condition met

$ kubectl get pods,svc,pvc
pod/blackbox-688fd4ddfd-8vvsc    1/1   Running
pod/grafana-5f9cff7746-wbxrm     1/1   Running
pod/prometheus-b45ccd9f-957d8    1/1   Running
service/grafana      LoadBalancer   10.98.218.102   127.0.0.1,10.0.2.15   3000:32487/TCP
service/prometheus   ClusterIP      10.96.215.84    <none>                9090/TCP
service/blackbox     ClusterIP      10.105.173.69   <none>                9115/TCP
persistentvolumeclaim/grafana-data   Bound   100Mi
persistentvolumeclaim/prom-data      Bound   100Mi
```

Реальная проверка всех трёх компонентов — Grafana снаружи ВМ через LoadBalancer, Prometheus/Blackbox изнутри кластера:

```bash
$ curl -s -o /dev/null -w 'Grafana HTTP: %{http_code}\n' http://10.0.2.15:3000/login
Grafana HTTP: 200
$ curl -s http://10.0.2.15:3000/api/health
{"database": "ok", "version": "13.2.4", "commit": "0e79aef9d91abf3bdadae9af15763029072fb45b"}

$ kubectl exec deploy/prometheus -- wget -qO- http://localhost:9090/-/healthy
Prometheus Server is Healthy.

$ kubectl exec deploy/blackbox -- wget -qO- http://localhost:9115/metrics | head -3
# HELP blackbox_exporter_build_info ...
blackbox_exporter_build_info{...,version="0.29.1"} 1
```

### 1.6. `helm upgrade --set` и `helm uninstall`

Демонстрация обновления релиза без правки файлов чарта — новый внешний порт Grafana и новый пароль администратора через `--set` (оба параметра заранее вынесены в `values.yaml`, п. 1.4):

```bash
$ helm upgrade promgra ./promgra-0.1.0.tgz --set EXTERNAL_PORT=3456 --set GF_ADMIN_PASSWORD=sup3rsecret
Release "promgra" has been upgraded. Happy Helming!
REVISION: 2

$ kubectl get svc grafana
grafana   LoadBalancer   10.98.218.102   127.0.0.1,10.0.2.15   3456:32487/TCP

$ helm history promgra
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         deployed    Upgrade complete

$ curl -s -o /dev/null -w 'Grafana на новом порту 3456: HTTP %{http_code}\n' http://10.0.2.15:3456/login
Grafana на новом порту 3456: HTTP 200
```

Завершение жизненного цикла релиза — `helm uninstall` удаляет всё разом (Deployment'ы, Service'ы, PVC):

```bash
$ helm uninstall promgra
release "promgra" uninstalled

$ kubectl get pods,svc,pvc
NAME                 TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)
service/kubernetes   ClusterIP   10.96.0.1    <none>        443/TCP
# (поды/PVC были в состоянии Terminating, через пару секунд исчезли полностью)
$ helm history promgra
Error: release: not found
```

---

## Task 2. flask-app → dev/prod окружения через Kustomize

### 2.1. Приложение VERSION 3 — параметризация через переменные окружения

Тот же Flask+Redis счётчик посещений, что и в Lab 9, но теперь **без единого хардкода** текста приветствия/цвета/названия окружения — всё приходит через `os.environ`, чтобы один и тот же Docker-образ (`flask:v3`) работал по-разному в dev и в prod без пересборки:

```python
APP_ENV = os.environ.get('APP_ENV', 'local')
GREETING_MESSAGE = os.environ.get('GREETING_MESSAGE', 'Hello World')
APP_COLOR = os.environ.get('APP_COLOR', 'default')

@app.route('/')
def hello():
    count = get_hit_count()
    return (
        f'{GREETING_MESSAGE} VERSION 3! Эта страница была просмотрена {count} раз(а).\n'
        f'Запрос обработал Pod: {socket.gethostname()}\n'
        f'Окружение (APP_ENV): {APP_ENV} | Цвет (APP_COLOR): {APP_COLOR}\n'
    )
```

### 2.2. Структура `base` + `overlays/{dev,prod}`

`base/kustomization.yaml` — общие ресурсы + `configMapGenerator` с «дефолтными» значениями (их переопределяют оверлеи через `behavior: merge`):

```yaml
resources:
  - redis-deployment.yaml
  - redis-service.yaml
  - web-deployment.yaml
  - web-service.yaml
configMapGenerator:
  - name: flask-env-config
    literals:
      - APP_ENV=base
      - GREETING_MESSAGE=Hello from Kustomize Base
      - APP_COLOR=gray
```

`base/web-deployment.yaml` подключает переменные окружения через `envFrom: configMapRef` (не хардкод в манифесте):

```yaml
containers:
  - name: web
    image: flask:v3
    imagePullPolicy: Never
    envFrom:
      - configMapRef:
          name: flask-env-config
    readinessProbe:
      httpGet: {path: /, port: 5000}
    livenessProbe:
      httpGet: {path: /, port: 5000}
```

`overlays/dev/kustomization.yaml` — отдельный namespace, 1 реплика, порт LoadBalancer **8002**, свои значения ConfigMap:

```yaml
namespace: dev
resources:
  - namespace.yaml
  - ../../base
replicas:
  - name: web
    count: 1
configMapGenerator:
  - name: flask-env-config
    behavior: merge
    literals:
      - APP_ENV=dev
      - GREETING_MESSAGE=Hello from Kustomize DEV
      - APP_COLOR=green
patches:
  - target: {kind: Service, name: web}
    patch: |-
      - op: replace
        path: /spec/ports/0/port
        value: 8002
```

`overlays/prod/kustomization.yaml` — то же самое, но namespace `prod`, **3 реплики** (в методичке 5, урезано ради памяти ВМ), порт **8003**, и дополнительный JSON6902-патч, которого нет в dev — явные `requests`/`limits` на контейнер (показывает, что оверлеи патчат не только реплики/порты, но и ресурсы):

```yaml
replicas:
  - name: web
    count: 3
patches:
  - target: {kind: Service, name: web}
    patch: |- # port -> 8003
  - target: {kind: Deployment, name: web}
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/resources
        value:
          requests: {cpu: "50m", memory: "32Mi"}
          limits: {cpu: "200m", memory: "96Mi"}
```

Рендер dev-оверлея одной командой (`kubectl kustomize`, без `apply` — удобно для ревью перед выкаткой), реальный вывод:

```bash
$ kubectl kustomize overlays/dev
apiVersion: v1
kind: Namespace
metadata:
  name: dev
---
apiVersion: v1
data:
  APP_COLOR: green
  APP_ENV: dev
  GREETING_MESSAGE: Hello from Kustomize DEV
kind: ConfigMap
metadata:
  name: flask-env-config-67mt6mmcg9      # имя с хешем - Kustomize меняет его при каждом
  namespace: dev                          # изменении содержимого (immutable ConfigMap pattern)
---
...
spec:
  ports:
  - port: 8002
    targetPort: 5000
  type: LoadBalancer
---
...
spec:
  replicas: 1
  template:
    spec:
      containers:
      - envFrom:
        - configMapRef:
            name: flask-env-config-67mt6mmcg9
        image: flask:v3
        imagePullPolicy: Never
```

### 2.3. `kubectl apply -k` — dev и prod одновременно

```bash
$ kubectl apply -k overlays/dev
namespace/dev created
configmap/flask-env-config-67mt6mmcg9 created
service/redis created
service/web created
deployment.apps/redis created
deployment.apps/web created

$ kubectl apply -k overlays/prod
namespace/prod created
configmap/flask-env-config-752m6dk7tg created
service/redis created
service/web created
deployment.apps/redis created
deployment.apps/web created

$ kubectl get pods,svc -n dev
pod/web-58cffb667f-zdvd4   1/1   Running
service/web   LoadBalancer   8002:32522/TCP

$ kubectl get pods,svc -n prod
pod/web-6fcc9d7d5b-2mcg7   1/1   Running
pod/web-6fcc9d7d5b-kkljs   1/1   Running
pod/web-6fcc9d7d5b-qchpg   1/1   Running
service/web   LoadBalancer   8003:30597/TCP
```

### 2.4. Проверка — два изолированных окружения через один tunnel

```bash
$ curl -s http://10.0.2.15:8002/   # dev
Hello from Kustomize DEV VERSION 3! Эта страница была просмотрена 4 раз(а).
Запрос обработал Pod: web-58cffb667f-zdvd4
Окружение (APP_ENV): dev | Цвет (APP_COLOR): green

$ for i in 1 2 3; do curl -s http://10.0.2.15:8003/; done   # prod
Hello from Kustomize PROD VERSION 3! Эта страница была просмотрена 10 раз(а).
Запрос обработал Pod: web-6fcc9d7d5b-kkljs
Hello from Kustomize PROD VERSION 3! Эта страница была просмотрена 11 раз(а).
Запрос обработал Pod: web-6fcc9d7d5b-kkljs
Hello from Kustomize PROD VERSION 3! Эта страница была просмотрена 12 раз(а).
Запрос обработал Pod: web-6fcc9d7d5b-2mcg7
Окружение (APP_ENV): prod | Цвет (APP_COLOR): red (во всех трёх)
```

Итог: один и тот же `base`, два полностью изолированных окружения в разных namespace — разные тексты приветствия, разные цвета, разное число реплик (1 vs 3), разный порт наружу, и при этом видно переключение между репликами prod по имени Pod'а в ответах LoadBalancer'а.

---

## Нюансы и наблюдения

- **Task 1 переделан с flask-redis на prometheus-grafana.** Изначально (по инерции с предыдущих лабораторных, где основным стендом был flask-redis) чарт был собран из flask-redis — после сверки с методичкой (слайд 15: «Из проекта **prometheus-grafana** создаём helm-chart») вся работа Task 1 была переделана с нуля на правильном проекте. flask-redis используется только в Task 2, как и требуется («Из проекта flask-app создаём prod и dev окружения через kustomize»).
- **`grafana/provisioning` не конвертировался Kompose в ConfigMap** (в отличие от примера на слайде 24 методички, где `datasource.yml`/`prometheus.yml` оба стали ConfigMap). У текущей версии Kompose (1.36.0) конвертация прошла только для `prometheus.yml` (простой bind-mount файла), а вложенная директория `grafana/provisioning/{datasources,dashboards}` была пропущена (`WARN Skip file in path`) — ограничение самого инструмента на вложенные директории, не ошибка конфигурации. Для целей лабораторной (продемонстрировать Helm+Kompose workflow) это не критично — Grafana поднимается и отвечает на `/api/health` без preconfigured datasource.
- **`minikube image load` вместо pull из интернета.** Образы `prom/prometheus`, `grafana/grafana`, `prom/blackbox-exporter` уже лежали в host-Docker (контейнеры Lab 8 `monitoring-*`) — вместо повторного скачивания (десятки-сотни МБ, Grafana ~1.9ГБ) они загружены напрямую в containerd minikube командой `minikube image load`, с `imagePullPolicy: Never` в чарте, чтобы Kubernetes не пытался их перекачать из registry.
- **`spec.externalIPs` помечен как deprecated** (`kubectl`/API выдаёт предупреждение `"Warning: spec.externalIPs is deprecated and may no longer be implemented in some clusters"`), но в данной версии minikube (containerd, kindnet) продолжает работать и остаётся единственным простым способом получить реальный внешний IP для LoadBalancer-сервиса вместе с `minikube tunnel` — решение идентично тому, что уже использовалось в Lab 9.
- **Порт Grafana после `helm upgrade --set EXTERNAL_PORT=3456` стал откликаться не сразу** — `kubectl get svc` сразу показал новый порт `3456:32487/TCP`, но первый `curl` на `3456` вернул `000` (connection refused), пока не прошло несколько секунд на синхронизацию `kube-proxy`/`minikube tunnel`; после паузы оба порта (`3000` и `3456`) отвечали какое-то время одновременно — особенность кеширования слушателей `minikube tunnel`, а не ошибка конфигурации Helm-релиза (`kubectl get svc`/`helm history` подтверждают, что сам Service и release обновились мгновенно и корректно).
- **Реплики prod уменьшены с 5 (методичка) до 3** — тот же компромисс, что и в Lab 9, под ограниченную память учебной ВМ с minikube (3.8Gi, из которых Task 1 (3 пода) и Task 2 (dev+prod, 5 подов) занимали одновременно ~1.6Gi, доступно оставалось ~2.2-2.3Gi).
- **Один и тот же `minikube tunnel`** (запущен ещё в Lab 9 с `--bind-address 10.0.2.15`) обслуживал три разных LoadBalancer-сервиса в этой лабораторной одновременно (`grafana:3000→3456`, `web.dev:8002`, `web.prod:8003`) без перезапуска — подтверждает, что один тоннель покрывает произвольное число LoadBalancer Service'ов в кластере, если все они используют `externalIPs` на тот же адрес ВМ.

## Скриншоты

Все скриншоты в папке `screenshots/` — рендер РЕАЛЬНОГО вывода команд, полученного по SSH:

1. `01-cleanup-helm-kompose-install.png` — уборка ресурсов Lab 9 из `default` + установка Helm 3.22.1 и Kompose 1.36.0
2. `02-kompose-convert-chart.png` — compose.yaml prometheus-grafana, `minikube image load`, `kompose convert --chart` (сырой chart)
3. `03-helm-chart-fix-install-verify.png` — `promgra-chart` (LoadBalancer+externalIPs, values.yaml), `helm install` + проверка Grafana/Prometheus
4. `04-helm-upgrade-uninstall.png` — `helm upgrade --set` (новый порт/пароль Grafana) → `helm uninstall`
5. `05-kustomize-structure-render-dev.png` — структура `base`/`overlays(dev,prod)` + `kubectl kustomize overlays/dev`
6. `06-kustomize-apply-dev-prod.png` — `kubectl apply -k overlays/dev` и `overlays/prod` одновременно (1 vs 3 реплики)
7. `07-dev-prod-side-by-side-verify.png` — dev (8002, 1 реплика) и prod (8003, 3 реплики) отвечают одновременно через один tunnel
