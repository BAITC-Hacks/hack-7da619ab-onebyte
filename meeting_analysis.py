"""Small, deterministic Russian/Kazakh fallback; no models or network calls."""

import re
from collections import Counter


UNKNOWN_OWNER = "Не определён"
UNKNOWN_DEADLINE = "Не определён"
ANALYSIS_NOTE = (
    "Локальный анализ по правилам: саммари составлено из фраз транскрипта. "
    "Проверьте поручения перед использованием. Неопределённые поля отмечены явно; "
    "относительные сроки сохранены как в записи."
)

# Explicit action forms, not past-tense reports such as «отчёт подготовлен».
ACTION = re.compile(
    r"\b(?:подготов(?:ить|ь|ьте|ит|ят|им)|сдела(?:ть|й|йте|ет|ют|ем)|"
    r"отправ(?:ить|ь|ьте|ит|ят|им)|провер(?:ить|ь|ьте|ит|ят|им)|"
    r"соглас(?:овать|уй|уйте|ует|уют|уем)|предостав(?:ить|ь|ьте|ит|ят|им)|"
    r"разработа(?:ть|й|йте|ет|ют|ем)|обнов(?:ить|и|ите|ит|ят|им)|"
    r"собра(?:ть)|собер(?:и|ите|ёт|ет|ут|ём|ем)|"
    r"прове(?:сти|ди|дите|дёт|дет|дут|дём|дем)|"
    r"организ(?:овать|уй|уйте|ует|уют|уем)|назнач(?:ить|ь|ьте|ит|ат|им)|"
    r"исправ(?:ить|ь|ьте|ит|ят|им)|заверш(?:ить|и|ите|ит|ат|им)|"
    r"обсуд(?:ить|и|ите|ит|ят|им)|направ(?:ить|ь|ьте|ит|ят|им)|"
    r"состав(?:ить|ь|ьте|ит|ят|им)|свя(?:заться|жись|житесь|жется|жутся)|"
    r"уточн(?:ить|и|ите|ит|ят|им)|обеспеч(?:ить|ь|ьте|ит|ат|им)|"
    r"ұсын(?:у|сын|ыңыз|ады)|дайында(?:у|сын|ңыз|йды)|"
    r"әзірле(?:у|сін|ңіз|йді)|жібер(?:у|сін|іңіз|еді)|"
    r"тексер(?:у|сін|іңіз|еді)|орында(?:у|сын|ңыз|йды)|"
    r"жаңарт(?:у|сын|ыңыз|ады)|өткіз(?:у|сін|іңіз|еді)|"
    r"келіс(?:у|сін|іңіз|еді)|аяқта(?:у|сын|ңыз|йды))\b",
    re.IGNORECASE,
)
INTENT = re.compile(
    r"\b(?:нужно|надо|необходимо|поручаю|поручить|поручаем|прошу|просим|"
    r"должен|должна|должны|договорились|решили|давайте|тапсырамын|"
    r"тапсырылсын|міндетті|керек|қажет|тапсырма)\b", re.IGNORECASE,
)
NEGATED = re.compile(
    r"\b(?:не\s+(?:нужно|надо|требуется|следует|будем)|"
    r"не\s+(?:подгот\w*|отправ\w*|дела\w*|провер\w*|соглас\w*)|"
    r"керек\s+емес|қажет\s+емес|отмен\w*|выполнено|орындалды)\b",
    re.IGNORECASE,
)
NAME = r"[А-ЯЁӘҒҚҢӨҰҮҺІA-Z][а-яёәғқңөұүһіa-z]+(?:-[А-ЯЁӘҒҚҢӨҰҮҺІA-Z][а-яёәғқңөұүһіa-z]+)?"
PERSON = rf"{NAME}(?:\s+{NAME}){{0,2}}"
NOT_NAMES = set(
    "сегодня завтра послезавтра коллеги нужно надо необходимо прошу поручаю "
    "поручить поручаем мы вы я он она они давайте решили договорились "
    "также затем это после до на к в по ответственный срок сроки задача задачи отчет отчёт "
    "документы договор смета бюджет проект решение если чтобы пожалуйста "
    "самрук казына бүгін ертең біз сіз мен ол тапсырма жауапты келесі".split()
)
OWNER_MARKER = re.compile(
    rf"(?i:ответственн(?:ый|ая|ые)\s*[:—-]?|жауапты\s*[:—-]?)\s*({PERSON})"
)
MONTH_RU = r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
MONTH_KK = r"(?:қаңтар|ақпан|наурыз|сәуір|мамыр|маусым|шілде|тамыз|қыркүйек|қазан|қараша|желтоқсан)"
DATE = rf"(?:\d{{1,2}}[./]\d{{1,2}}(?:[./]\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+{MONTH_RU}(?:\s+\d{{4}}(?:\s+года)?)?)"
DEADLINE_PATTERNS = [
    rf"\b(?:до|к|не\s+позднее|срок\s*[:—-]?)\s+{DATE}",
    r"\b(?:до|к|на)\s+(?:(?:следующ\w+|эт\w+)\s+)?(?:понедельник\w*|вторник\w*|сред[ауые]|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)\b",
    r"\b(?:до\s+конца|к\s+концу)\s+(?:(?:этой|следующей|текущей)\s+)?(?:дня|недели|месяца|квартала|года)\b",
    r"\b(?:через|в\s+течение)\s+(?:\d+|один|одного|два|двух|три|трёх|трех|пять|пяти)\s+(?:рабоч\w+\s+)?(?:день|дня|дней|недел\w*|час\w*|месяц\w*)\b",
    r"\b(?:(?:до|на)\s+)?(?:послезавтра|завтра|сегодня)(?:\s+до\s+\d{1,2}(?::\d{2})?)?\b",
    r"\b(?:на\s+следующей\s+неделе|до\s+\d{1,2}:\d{2})\b",
    rf"\b(?:\d{{1,2}}\s+{MONTH_KK}(?:ға|ге|қа|ке)?|\d{{1,2}}[./]\d{{1,2}}(?:[./]\d{{2,4}})?(?:-?(?:ға|ге|қа|ке)))\s+дейін\b",
    r"\b(?:дүйсенбі|сейсенбі|сәрсенбі|бейсенбі|жұма|сенбі|жексенбі)(?:ға|ге|қа|ке)\s+дейін\b",
    r"\b(?:(?:келесі|осы)\s+)?(?:аптаның|айдың|күннің)\s+соңына\s+дейін\b",
    r"\b(?:\d+|бір|екі|үш|бес)\s+(?:жұмыс\s+)?(?:күн|апта|ай)\s+ішінде\b",
    r"\b(?:ертең|бүгін|бүрсігүні|келесі\s+аптада)\b",
]
DEADLINES = [re.compile(pattern, re.IGNORECASE) for pattern in DEADLINE_PATTERNS]


def _owner(sentence: str) -> str:
    explicit = OWNER_MARKER.search(sentence)
    if explicit:
        return explicit.group(1)
    delegated = re.search(rf"(?i:поруч(?:аю|аем|ить))\s+({PERSON})", sentence)
    if delegated:
        return delegated.group(1)
    # Subject or direct address before the action. Never infer a speaker from «я».
    action = ACTION.search(sentence)
    prefix = sentence[:action.start()] if action else sentence
    role = re.search(
        r"\b(?:отдел\s+[а-яё]+|команда\s+[а-яё]+|бухгалтерия|юрист|"
        r"[а-яәғқңөұүһі]+\s+бөлімі)\b", prefix, re.IGNORECASE,
    )
    if role:
        return role.group()
    for match in re.finditer(PERSON, prefix):
        candidate = match.group()
        if candidate.split()[0].lower() not in NOT_NAMES:
            return candidate
    return UNKNOWN_OWNER


def _deadline(sentence: str) -> str:
    for pattern in DEADLINES:
        match = pattern.search(sentence)
        if match:
            return match.group()
    # A standalone labelled deadline is explicit even without «до» / «дейін».
    labelled = re.search(r"(?i)\b(?:срок|мерзім[і]?)\s*[:—-]\s*([^.!?;]+)", sentence)
    if labelled:
        return labelled.group(1).strip()
    return UNKNOWN_DEADLINE


def _sentences(transcript: str) -> list[str]:
    # Whisper line breaks are segments, not necessarily sentence boundaries.
    text = re.sub(r"\s+", " ", transcript).strip()
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+", text) if part.strip()]


def analyze_transcript(transcript: str) -> dict:
    sentences = _sentences(transcript)
    tasks = []
    seen = set()
    for index, sentence in enumerate(sentences):
        if sentence.endswith("?") or NEGATED.search(sentence):
            continue
        if not ACTION.search(sentence) and not INTENT.search(sentence):
            continue
        # Avoid treating isolated modal words as complete tasks.
        if len(sentence.split()) < 3:
            continue
        owner, deadline = _owner(sentence), _deadline(sentence)
        # Attach explicit metadata immediately following a task, never arbitrary context.
        for following in sentences[index + 1:index + 3]:
            if not re.match(r"(?i)^(?:ответственн[а-яё]*|жауапты|срок|мерзім)\b", following):
                break
            if owner == UNKNOWN_OWNER:
                owner = _owner(following)
            if deadline == UNKNOWN_DEADLINE:
                deadline = _deadline(following)
        key = re.sub(r"\W+", " ", sentence.lower()).strip()
        if key not in seen:
            seen.add(key)
            tasks.append({
                "assignee": owner,
                "description": sentence,
                "deadline": deadline,
                "status": "В работе",
            })

    # Extractive summary: rank source sentences, then preserve their original order.
    frequencies = Counter(re.findall(r"\b[а-яёәғқңөұүһіa-z]{5,}\b", transcript.lower()))
    def score(item):
        index, sentence = item
        keywords = re.findall(r"\b[а-яёәғқңөұүһіa-z]{5,}\b", sentence.lower())
        relevance = sum(frequencies[word] for word in set(keywords)) / max(1, len(keywords))
        decision = bool(re.search(r"(?i)решили|договорились|итог|обсудили|шешім|келістік|талқыла", sentence))
        return 5 * decision + 3 * bool(ACTION.search(sentence)) + relevance + (index == 0)
    candidates = [(i, s) for i, s in enumerate(sentences) if len(s.split()) >= 3]
    selected = sorted(sorted(candidates, key=score, reverse=True)[:4])
    summary = "\n".join(s if len(s) <= 350 else s[:347].rsplit(" ", 1)[0] + "…" for _, s in selected)
    return {
        "summary": summary or ("Содержательных фраз для саммари недостаточно." if sentences else "В записи нет распознанной речи."),
        "tasks": tasks,
        "analysis_method": "rule-based",
        "analysis_note": ANALYSIS_NOTE,
    }
