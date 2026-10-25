# Первый запуск n8n для BriefOps

n8n — редактор процессов из соединённых блоков. Здесь он принимает заявку и вызывает BriefOps, а второй процесс проверяет просрочки по расписанию. NVIDIA вызывается внутри BriefOps. Ключ NVIDIA в n8n не вводится.

## 1. Откройте два сервиса

BriefOps: из папки проекта выполните `python -X utf8 app.py`, откройте <http://127.0.0.1:8787>.

n8n пока не установлен. Для локального знакомства официальный вариант — `npx n8n` в отдельном терминале, затем <http://localhost:5678>. Node.js 24 уже есть на ноутбуке. При первом запуске npx скачает n8n и зависимости; мастер n8n попросит создать локальную учётную запись владельца. Если текущая версия n8n больше не поддерживает npm, используйте способ установки из официальной документации ниже. Облачный n8n не получит доступ к серверу на localhost.

## 2. Импортируйте готовые процессы

В редакторе нового workflow откройте меню → **Import from File** и выберите `workflows/intake.json`. Отдельным workflow импортируйте `workflows/sla.json`. Вручную собирать блоки не требуется.

Первый: **входящая заявка → сохранение → AI-разбор и CRM → проверка повтора → ответ источнику**.

Второй: **каждые пять минут → создать задачу по просроченной заявке**. Повторные проверки не создают дубли задач.

## 3. Настройте доступ к BriefOps

В терминале папки проекта выполните `python app.py --print-token`. Это отдельный локальный токен, а не NVIDIA API key.

В n8n создайте credential типа **Header Auth**:

- Name: `Authorization`
- Value: `Bearer ВАШ_ЛОКАЛЬНЫЙ_ТОКЕН`

Выберите credential в Webhook и двух HTTP Request первого workflow, затем в HTTP Request второго. Для внешнего источника в будущем лучше отдельный credential Webhook; этот локальный пример использует один токен. Не публикуйте credential или токен в GitHub.

## 4. Проверьте одну заявку

В Webhook нажмите **Listen for test event**, скопируйте его Test URL. В PowerShell из папки BriefOps:

```powershell
$briefToken = (Get-Content data/automation-token.txt -Raw).Trim()
$briefExample = Get-Content examples/inquiry.json -Raw
Invoke-RestMethod -Method Post -Uri 'ВСТАВЬТЕ_TEST_URL_ИЗ_N8N' -ContentType 'application/json; charset=utf-8' -Headers @{ Authorization = "Bearer $briefToken" } -Body ([Text.Encoding]::UTF8.GetBytes($briefExample))
```

В n8n откройте результат выполнения, в BriefOps найдите карточку и её историю. Повторите тот же запрос с тем же `message_id`: второй сделки быть не должно. Затем опубликуйте workflow и используйте **Production URL**, показанный вашим n8n. Включите второй workflow для расписания.

Оба сервиса работают, пока ноутбук включён и процессы запущены. Публичная ссылка работодателю требует отдельного размещения; GitHub хранит исходники, сам сервис он не запускает.

## Статус проверки

JSON-схемы, связи блоков и HTTP-контракт проверены тестами проекта. Импорт и выполнение в самом n8n ещё не проверялись. Встроенная очередь BriefOps уже выполняет процесс без n8n.

Официальные инструкции: [npm installation](https://docs.n8n.io/deploy/host-n8n/install-options/install-with-npm/), [Import/export](https://docs.n8n.io/workflows/export-import/), [Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).


## Публичное демо Render

Для подключения к облачному BriefOps скачайте экспорты с экрана «Автоматизация» на https://briefops.onrender.com: их HTTP-узлы уже содержат публичный адрес. Используйте отдельный cloud-токен интеграции, сохранённый владельцем локально в data/cloud-automation-token.txt. Локальный data/automation-token.txt относится к локальному серверу. Клиентский NVIDIA key не используется в n8n. Связь с публичным API проверена; запуск самого n8n ещё не выполнялся.
