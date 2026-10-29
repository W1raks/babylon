"""Языки приложения и определение языка текста без сети."""
import re

# код -> (название по-русски, самоназвание). Порядок: сначала частые, дальше по алфавиту.
LANGS = {
    "ru": ("Русский", "Русский"),
    "en": ("Английский", "English"),
    "de": ("Немецкий", "Deutsch"),
    "fr": ("Французский", "Français"),
    "es": ("Испанский", "Español"),
    "it": ("Итальянский", "Italiano"),
    "ja": ("Японский", "日本語"),
    "zh": ("Китайский", "中文 (简体)"),
    "ko": ("Корейский", "한국어"),
    "uk": ("Украинский", "Українська"),
    "pt": ("Португальский", "Português"),
    "pl": ("Польский", "Polski"),
    "tr": ("Турецкий", "Türkçe"),
    "ar": ("Арабский", "العربية"),
    "af": ("Африкаанс", "Afrikaans"),
    "sq": ("Албанский", "Shqip"),
    "am": ("Амхарский", "አማርኛ"),
    "hy": ("Армянский", "Հայերեն"),
    "az": ("Азербайджанский", "Azərbaycan"),
    "eu": ("Баскский", "Euskara"),
    "be": ("Белорусский", "Беларуская"),
    "bn": ("Бенгальский", "বাংলা"),
    "bs": ("Боснийский", "Bosanski"),
    "bg": ("Болгарский", "Български"),
    "my": ("Бирманский", "မြန်မာ"),
    "ca": ("Каталанский", "Català"),
    "ceb": ("Себуанский", "Cebuano"),
    "zt": ("Китайский традиционный", "中文 (繁體)"),
    "co": ("Корсиканский", "Corsu"),
    "hr": ("Хорватский", "Hrvatski"),
    "cs": ("Чешский", "Čeština"),
    "da": ("Датский", "Dansk"),
    "nl": ("Нидерландский", "Nederlands"),
    "eo": ("Эсперанто", "Esperanto"),
    "et": ("Эстонский", "Eesti"),
    "fi": ("Финский", "Suomi"),
    "fy": ("Фризский", "Frysk"),
    "gl": ("Галисийский", "Galego"),
    "ka": ("Грузинский", "ქართული"),
    "el": ("Греческий", "Ελληνικά"),
    "gu": ("Гуджарати", "ગુજરાતી"),
    "ht": ("Гаитянский креольский", "Kreyòl ayisyen"),
    "ha": ("Хауса", "Hausa"),
    "haw": ("Гавайский", "ʻŌlelo Hawaiʻi"),
    "he": ("Иврит", "עברית"),
    "hi": ("Хинди", "हिन्दी"),
    "hmn": ("Хмонг", "Hmoob"),
    "hu": ("Венгерский", "Magyar"),
    "is": ("Исландский", "Íslenska"),
    "ig": ("Игбо", "Igbo"),
    "id": ("Индонезийский", "Bahasa Indonesia"),
    "ga": ("Ирландский", "Gaeilge"),
    "jv": ("Яванский", "Basa Jawa"),
    "kn": ("Каннада", "ಕನ್ನಡ"),
    "kk": ("Казахский", "Қазақ"),
    "km": ("Кхмерский", "ខ្មែរ"),
    "rw": ("Киньяруанда", "Kinyarwanda"),
    "ku": ("Курдский", "Kurdî"),
    "ky": ("Киргизский", "Кыргызча"),
    "lo": ("Лаосский", "ລາວ"),
    "la": ("Латинский", "Latina"),
    "lv": ("Латышский", "Latviešu"),
    "lt": ("Литовский", "Lietuvių"),
    "lb": ("Люксембургский", "Lëtzebuergesch"),
    "mk": ("Македонский", "Македонски"),
    "mg": ("Малагасийский", "Malagasy"),
    "ms": ("Малайский", "Bahasa Melayu"),
    "ml": ("Малаялам", "മലയാളം"),
    "mt": ("Мальтийский", "Malti"),
    "mi": ("Маори", "Māori"),
    "mr": ("Маратхи", "मराठी"),
    "mn": ("Монгольский", "Монгол"),
    "ne": ("Непальский", "नेपाली"),
    "no": ("Норвежский", "Norsk"),
    "ny": ("Чичева", "Chichewa"),
    "or": ("Ория", "ଓଡ଼ିଆ"),
    "ps": ("Пушту", "پښتو"),
    "fa": ("Персидский", "فارسی"),
    "pa": ("Панджаби", "ਪੰਜਾਬੀ"),
    "ro": ("Румынский", "Română"),
    "sm": ("Самоанский", "Gagana Samoa"),
    "gd": ("Шотландский гэльский", "Gàidhlig"),
    "sr": ("Сербский", "Српски"),
    "st": ("Сесото", "Sesotho"),
    "sn": ("Шона", "Shona"),
    "sd": ("Синдхи", "سنڌي"),
    "si": ("Сингальский", "සිංහල"),
    "sk": ("Словацкий", "Slovenčina"),
    "sl": ("Словенский", "Slovenščina"),
    "so": ("Сомали", "Soomaali"),
    "su": ("Сунданский", "Basa Sunda"),
    "sw": ("Суахили", "Kiswahili"),
    "sv": ("Шведский", "Svenska"),
    "tl": ("Филиппинский", "Filipino"),
    "tg": ("Таджикский", "Тоҷикӣ"),
    "ta": ("Тамильский", "தமிழ்"),
    "tt": ("Татарский", "Татар"),
    "te": ("Телугу", "తెలుగు"),
    "th": ("Тайский", "ไทย"),
    "tk": ("Туркменский", "Türkmen"),
    "ur": ("Урду", "اردو"),
    "ug": ("Уйгурский", "ئۇيغۇرچە"),
    "uz": ("Узбекский", "Oʻzbek"),
    "vi": ("Вьетнамский", "Tiếng Việt"),
    "cy": ("Валлийский", "Cymraeg"),
    "xh": ("Коса", "isiXhosa"),
    "yi": ("Идиш", "ייִדיש"),
    "yo": ("Йоруба", "Yorùbá"),
    "zu": ("Зулу", "isiZulu"),
    "ba": ("Башкирский", "Башҡорт"),
    "cv": ("Чувашский", "Чӑвашла"),
    "sah": ("Якутский", "Саха тыла"),
}

# Код у Google, если отличается от нашего
GOOGLE = {"zh": "zh-CN", "zt": "zh-TW", "he": "iw", "jv": "jw"}
# Языки, для которых есть офлайн-модели Argos в обе стороны с английским (lt и ro только с BPE — нет)
OFFLINE = {"en", "ar", "az", "bg", "bn", "ca", "cs", "da", "de", "el", "eo", "es", "et", "eu", "fa", "fi", "fr",
           "ga", "gl", "he", "hi", "hu", "id", "it", "ja", "ko", "ky", "lv", "ms", "nb", "nl", "pl", "pt",
           "ru", "sk", "sl", "sq", "sv", "sw", "th", "tl", "tr", "uk", "ur", "vi", "zh", "zt"}
ARGOS = {"no": "nb"}  # наш код -> код пакета Argos

CJK = {"ja", "zh", "zt", "ko"}


def name(code: str) -> str:
    return LANGS.get(code, (code,))[0].lower()


def google_code(code: str) -> str:
    return GOOGLE.get(code, code)


def from_google(code: str) -> str:
    rev = {v: k for k, v in GOOGLE.items()}
    code = rev.get(code, code)
    return {"zh-cn": "zh", "zh-tw": "zt", "iw": "he", "jw": "jv"}.get(code.lower(), code.split("-")[0].lower())


def offline_ok(code: str) -> bool:
    return code in OFFLINE or ARGOS.get(code) in OFFLINE


def is_kana(c: str) -> bool:
    return "぀" <= c <= "ヿ" or "ｦ" <= c <= "ﾟ"


def is_han(c: str) -> bool:
    return "一" <= c <= "鿿" or "㐀" <= c <= "䶿" or "豈" <= c <= "﫿"


def is_hangul(c: str) -> bool:
    return "가" <= c <= "힯" or "ᄀ" <= c <= "ᇿ" or "㄰" <= c <= "㆏"


def is_cjk(c: str) -> bool:
    return is_kana(c) or is_han(c) or is_hangul(c)


# Частые короткие слова: по ним короткий латинский текст определяется надёжнее модели
_STOP = {
    "en": "the and is are was were of to in that it you for on with this have be not but they at from by what i hello hi yes no",
    "de": "der die das und ist nicht ich sie es ein eine zu mit auf für den dem von sich auch wie aber wir hallo ja nein",
    "fr": "le la les et est un une des du pas que qui dans pour sur avec ce il elle je vous nous au sont bonjour oui non",
    "it": "il lo la gli le e è un una che di non per con sono del della questo come più anche ma ho ciao sì grazie",
    "es": "el la los las y es un una que de no por con para del como más pero su lo está son al muy hola sí gracias",
    "pt": "o a os as e é um uma que de não por com para do da como mais mas seu está são ao muito olá obrigado você",
    "pl": "i w na z się że nie do to jest jak co ale tak po czy dla cześć dziękuję",
    "nl": "de het een en is niet ik je van in op met voor dat zijn maar hallo dank",
    "tr": "ve bir bu da de ne için ile gibi çok ama var yok merhaba teşekkürler",
}
_STOP = {k: set(v.split()) for k, v in _STOP.items()}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

_IDENT = None


def _model():
    """py3langid (97 языков, ~4 МБ), ограниченный нашими языками. Загружается один раз."""
    global _IDENT
    if _IDENT is None:
        try:
            import py3langid
            from py3langid import langid

            py3langid.classify("x")  # создаёт модель внутри модуля
            known = set(langid.IDENTIFIER.nb_classes)
            py3langid.set_languages(sorted(c for c in known if c in LANGS or c == "nb"))
            _IDENT = py3langid
        except Exception:
            _IDENT = False
    return _IDENT or None


def warm_up():
    """Загрузить модель заранее (первая загрузка ~0,9 с) — чтобы первая фраза живых субтитров не ждала."""
    _model()


def _script(letters: list[str]) -> str | None:
    """Язык по письменности, где она однозначна."""
    n = len(letters)
    hangul = sum(map(is_hangul, letters))
    kana = sum(map(is_kana, letters))
    han = sum(map(is_han, letters))
    asian = hangul + kana + han
    if asian / n > 0.3:
        if hangul >= max(kana, han):
            return "ko"
        return "ja" if kana >= max(1, 0.1 * asian) else "zh"
    counts = {
        "el": sum("Ͱ" <= c <= "Ͽ" for c in letters),
        "hy": sum("԰" <= c <= "֏" for c in letters),
        "ka": sum("Ⴀ" <= c <= "ჿ" for c in letters),
        "he": sum("֐" <= c <= "׿" for c in letters),
        "th": sum("฀" <= c <= "๿" for c in letters),
        "hi": sum("ऀ" <= c <= "ॿ" for c in letters),
    }
    best = max(counts, key=counts.get)
    return best if counts[best] / n > 0.5 else None


def detect(text: str) -> str:
    """Вернуть код языка (без сети)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    by_script = _script(letters)
    if by_script:
        return by_script
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ") / len(letters)
    words = _WORD.findall(text.lower())
    low = text.lower()
    if cyr > 0.5:
        if any(c in "ыэё" for c in low) and not any(c in "іїєґў" for c in low):
            return "ru"  # этих букв нет ни в украинском, ни в болгарском
        if len(letters) < 12:
            # коротко: украинские и белорусские буквы видно сразу, иначе русский
            if any(c in "іїєґ" for c in text.lower()):
                return "uk"
            if "ў" in text.lower():
                return "be"
            return "ru"
    elif (len(words) <= 3 or len(letters) < 20) and sum(c.isascii() or "\u00c0" <= c <= "\u024f"
                                                     for c in letters) / len(letters) > 0.8:
        # латиница, одно-два слова: модель путается, смотрим частые слова и буквы
        score = {k: sum(1 for w in words if w in s) for k, s in _STOP.items()}
        best = max(score, key=score.get)
        if score[best]:
            return best
        marks = {"de": "äöüß", "es": "ñ¿¡", "fr": "çœ", "pt": "ãõ", "pl": "ąęłńśźż", "tr": "ğış"}
        for k, chars in marks.items():
            if any(c in text.lower() for c in chars):
                return k
        return "en"
    model = _model()
    if model is None:
        return "ru" if cyr > 0.5 else "en"
    code = model.classify(text)[0]
    if code in ("uk", "be") and cyr > 0.5 and not any(c in "іїєґў'" for c in low):
        return "ru"  # без украинских и белорусских букв модель часто путает их с русским
    return {"nb": "no"}.get(code, code)


def default_target(src: str, preferred: str = "ru", fallback: str = "en") -> str:
    """Куда переводить: на любимый язык, а если текст уже на нём, то на запасной."""
    return fallback if src == preferred else preferred
