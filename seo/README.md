# seo/ — инструменты продвижения

## дом-щенков.рф (13.11.2026)

Взяты из пакета «Аналитика под ключ» (seo/docs/ЧИТАТЬ-ПЕРВЫМ.md) только инструменты командной строки и
документация. Фронт и бэкенд пакета не переносились: у сайта свои баннер согласия (partials/cookie.html.j2),
счётчик после согласия и цели (assets/js/main.js), источник заявки (backend/app/services/attribution.py), а
оплат на сайте нет — офлайн-конверсии слать нечего. Проект описан в seo/project.json: счётчик 114070015, цели
lead_sent, form_open, contact_click, quiz_complete (их шлёт main.js), IndexNow с ключом из корня сайта.

Ключи — только вне git. Как их получает облачная сессия Claude:

* **Яндекс (Метрика, Вебмастер).** Токен приложения «Для доступа к API или отладки» с правами metrika:read,
  metrika:write, webmaster:hostinfo, webmaster:verify (docs/2-ДОСТУПЫ-К-API.md, раздел 1). Хранится сетевым
  секретом окружения: прокси сам подставляет заголовок. Метрика принимает «Bearer <токен>», Вебмастер — только
  «OAuth <токен>» (проверено 13.11). Прокси заменяет любой заголовок Authorization своим, поэтому командам
  нужен лишь непустой YANDEX_OAUTH_TOKEN — заглушка. Встроенный fetch в Node сам через прокси не ходит: без
  NODE_USE_ENV_PROXY запросы идут мимо него, без токена. Запуск в облачной сессии:

  ```bash
  export YANDEX_OAUTH_TOKEN=proxy-injected NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt NODE_NO_WARNINGS=1
  node seo/cli/doctor.mjs
  ```

  Секрет Метрики (api-metrika.yandex.net) сохранён 13.11 — «Bearer <токен>»; секрет Вебмастера
  (api.webmaster.yandex.net) — тот же токен со словом «OAuth» вместо «Bearer», он заводится в настройках
  окружения (Network secrets).
* **Google Search Console.** Ключ сервисного аккаунта подписывается внутри машины (JWT), прокси его не заменит:
  файл ключа должен лежать в ~/.seo-tools/google-service-account.json той машины, где идёт работа.
* **Директ.** direct.mjs — только проверка фраз и отчёт по запросам; управлять кампаниями эти инструменты не умеют.

Набор команд, которыми агент снимает данные из Метрики, Вебмастера, Search
Console и PageSpeed, находит проблемы и отправляет изменённые страницы
на переиндексацию. Кабинет и браузер для этого не нужны.

**Настройка доступов — [2-ДОСТУПЫ-К-API.md](docs/2-ДОСТУПЫ-К-API.md).**
Проверить, что уже работает:

```bash
node seo/cli/doctor.mjs
```

## Как это устроено

Ноль зависимостей: Node 18+ умеет `fetch`, а подпись ключа Google делается
встроенным `node:crypto`. Ставить пакеты ради четырёх HTTP-запросов не нужно —
`npm install` здесь не требуется вообще. Почему не берём готовые библиотеки и
сторонние MCP-серверы — в [1-МЕТОДОЛОГИЯ.md](docs/1-МЕТОДОЛОГИЯ.md), п. 3.8.

```
seo/
  SETUP.md             указатель на инструкцию по доступам
  .env.example         какие переменные нужны (с плейсхолдерами)
  .env                 секреты (вне git, права 600)
  project.example.json образец описания проекта
  project.json         домен, счётчик, список целей — КОММИТИТСЯ
  keys/                ключ сервисного аккаунта Google (вне git)
  data/                снимки данных для истории (вне git)
  lib/                 общий слой: env, http, вывод, авторизация
  cli/                 сами команды
```

Каждая команда печатает таблицу для человека, а с флагом `--json` — сырые
данные для скрипта или для ИИ-агента.

## Команды

### Обзор

```bash
node seo/cli/doctor.mjs                 карта доступов: что работает, что нет
node seo/cli/report.mjs --days 28       сводка по всем сервисам разом
node seo/cli/report.mjs --save          та же сводка + снимок в seo/data/
```

### Яндекс

```bash
node seo/cli/webmaster.mjs summary          страницы в поиске, ИКС, проблемы
node seo/cli/webmaster.mjs queries          запросы: показы, клики, позиции
node seo/cli/webmaster.mjs monitoring       связка «запрос → страница»
node seo/cli/webmaster.mjs dropped          что выпало из поиска и почему
node seo/cli/webmaster.mjs broken           битые внутренние ссылки
node seo/cli/webmaster.mjs problems         диагностика Яндекса
node seo/cli/webmaster.mjs recrawl /uslugi/ отправить страницу на переобход

node seo/cli/metrika.mjs summary            трафик с динамикой
node seo/cli/metrika.mjs landings           страницы входа из поиска
node seo/cli/metrika.mjs goals              достижения целей
node seo/cli/metrika.mjs annotate "…"       отметка на графике: что меняли
node seo/cli/metrika.mjs counters           все счётчики аккаунта

node seo/cli/goals.mjs plan                 какие цели не заведены
node seo/cli/goals.mjs create               завести недостающие
```

На аккаунте несколько счётчиков, и любая команда Метрики умеет работать
с любым из них — номером или куском названия:

```bash
node seo/cli/metrika.mjs summary --counter 12345678
node seo/cli/metrika.mjs summary --counter "часть названия"
```

### Google

```bash
node seo/cli/gsc.mjs summary                клики, показы, CTR, позиция
node seo/cli/gsc.mjs opportunities          запросы на позициях 8–25
node seo/cli/gsc.mjs zero-click             показы есть, кликов нет
node seo/cli/gsc.mjs inspect /uslugi/       что Google знает о странице

node seo/cli/psi.mjs                        скорость главной
node seo/cli/psi.mjs all --limit 15         обход сайта
```

### Индексация

```bash
node seo/cli/indexnow.mjs changed           уведомить об изменившихся страницах
node seo/cli/webmaster.mjs recrawl-changed  их же — на переобход в Яндексе
```

### Подбор запросов

```bash
node seo/cli/bing.mjs related "дизайн сайта"    связанные запросы
node seo/cli/bing.mjs keyword "дизайн сайта"    частотность по неделям
node seo/cli/direct.mjs has-volume "фраза"      ищут такое вообще или нет
```

## Обычный цикл работы

```bash
node seo/cli/report.mjs --days 28 --save   # что происходит
# ... правки в коде сайта ...
<сборка и деплой сайта>                    # выложить
node seo/cli/indexnow.mjs changed          # сказать Яндексу и Bing
node seo/cli/webmaster.mjs recrawl-changed # и поставить в очередь переобхода
node seo/cli/metrika.mjs annotate "Переписал title на страницах услуг"
```

Последняя команда важнее, чем кажется: через месяц на графике будет виден
перелом, и никто уже не вспомнит, что именно тогда меняли.

## Что стоит помнить, глядя на цифры

**Метрика занижает абсолютные числа.** Счётчик стартует только после согласия
на cookie — кто баннер закрыл, в статистику не попал. Доли и динамика при этом
достоверны.

**Search Console отстаёт на 2–3 дня.** Пустые последние дни — не поломка.
Команды это уже учитывают и сдвигают период.

**Эффект правки виден не завтра.** Робот Яндекса приходит до трёх суток,
выдача обновляется до двух недель после обхода. Мерить раньше бессмысленно.

**У данных короткая память.** Связка «запрос → страница» в Вебмастере живёт
две недели, история Search Console — 16 месяцев скользящим окном. Отсюда
`report.mjs --save`: раз в неделю складывать снимок, иначе через год сравнить
будет не с чем.
