import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pywikibot


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

pywikibot.config.put_throttle = 1
pywikibot.config.maxlag = 5

SITE = pywikibot.Site("uk", "wikipedia")

TARGET_PAGE = "Портал:Сексуальність/Цікавинки"

ARCHIVE_PREFIX_FULL = (
    "Вікіпедія:Проєкт:Чи ви знаєте/Архів рубрики/"
)

ARCHIVE_PREFIX_API = (
    "Проєкт:Чи ви знаєте/Архів рубрики/"
)

ROOT_CATEGORIES = [
    "Категорія:Сексуальність",
    "Категорія:Сексологія",
    "Категорія:Еротика",
    "Категорія:Порнографія",
    "Категорія:Сексуальна орієнтація",
    "Категорія:Сексуальні практики",
    "Категорія:Проституція",
    "Категорія:Сексуальне здоров'я",
]

MAX_CATEGORY_DEPTH = 3

CACHE_DIR = Path(
    r"C:\Users\Admin\sexuality_portal_cache"
)
CACHE_DIR.mkdir(exist_ok=True)

PROVENANCE_CACHE = (
    CACHE_DIR / "thematic_provenance.json"
)

RECOGNIZED_CACHE = (
    CACHE_DIR / "recognized_articles.json"
)

FEATURED_LIST_PAGE = "Вікіпедія:Вибрані статті"
GOOD_LIST_PAGE = "Вікіпедія:Добрі статті"

FACTS_BY_PAGE_CACHE = (
    CACHE_DIR / "facts_by_page.json"
)

STATE_CACHE = (
    CACHE_DIR / "sync_state.json"
)


# ---------------------------------------------------------
# REGEX
# ---------------------------------------------------------

ALL_LINK_RE = re.compile(
    r"\[\[([^|\]#]+)"
)

BOLD_LINK_PATTERNS = [
    re.compile(
        r"'''\s*\[\[([^|\]#]+)"
        r"(?:\|[^\]]+)?\]\]\s*'''"
    ),
    re.compile(
        r"\[\[([^|\]#]+)\|'''[^']+'''\]\]"
    ),
]


# ---------------------------------------------------------
# TEXT NORMALIZATION
# ---------------------------------------------------------

STOP_WORDS = {
    "категорія",
    "статті",
    "стаття",
    "твори",
    "люди",
    "особи",
    "різне",
    "інше",
    "історія",
    "суспільство",
    "культура",
    "країна",
    "країни",
    "сша",
}


def normalize_title(title):
    return title.replace("_", " ").strip()


def clean_fact(fact):
    fact = re.sub(
        r"<!--.*?-->",
        "",
        fact
    )

    fact = re.sub(
        r"<small>\s*''\(\s*на фото\s*\)''\s*</small>",
        "",
        fact,
        flags=re.IGNORECASE,
    )

    fact = re.sub(
        r"[ \t]{2,}",
        " ",
        fact
    )

    return fact.strip()


def tokenize(text):
    words = re.findall(
        r"[а-яіїєґa-z]{4,}",
        text.lower()
    )

    suffixes = (
        "ями",
        "ами",
        "ові",
        "еві",
        "ого",
        "ому",
        "ими",
        "ій",
        "ий",
        "ом",
        "ем",
        "ах",
        "ях",
        "а",
        "я",
        "и",
        "і",
        "у",
        "ю",
        "е",
        "є",
    )

    result = set()

    for word in words:
        if word in STOP_WORDS:
            continue

        stem = word

        for suffix in suffixes:
            if (
                stem.endswith(suffix)
                and len(stem) - len(suffix) >= 4
            ):
                stem = stem[:-len(suffix)]
                break

        result.add(stem)

    return result


# ---------------------------------------------------------
# JSON
# ---------------------------------------------------------

def load_json(path, default=None):
    if not path.exists():
        return default

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save_json(path, data):
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

def load_recognized_cache():
    return load_json(
        RECOGNIZED_CACHE,
        {
            "featured": [],
            "good": [],
        }
    )


def fetch_article_links_from_page(page_title):
    """
    Повертає всі посилання з указаного службового списку
    на сторінки основного простору назв.

    Один такий список читається через MediaWiki API
    пакетно самим Pywikibot, без окремого запиту на кожну статтю.
    """
    page = pywikibot.Page(
        SITE,
        page_title
    )

    try:
        return {
            normalize_title(linked_page.title())
            for linked_page in page.linkedPages(
                namespaces=0
            )
        }
    except Exception as exc:
        print(
            f"Не вдалося прочитати {page_title}: {exc}"
        )
        return None


def update_recognized_cache(provenance):
    """
    Формує тематичний список вибраних і добрих статей.

    Джерелом статусу є два штатні списки української
    Вікіпедії. Після їх завантаження перетин із тематичним
    provenance виконується локально.
    """
    cache = load_recognized_cache()

    print(
        "\nОновлюю список відзначених статей..."
    )

    featured_links = fetch_article_links_from_page(
        FEATURED_LIST_PAGE
    )
    good_links = fetch_article_links_from_page(
        GOOD_LIST_PAGE
    )

    if featured_links is None or good_links is None:
        print(
            "Не вдалося оновити відзначені статті; "
            "залишаю попередній кеш."
        )
        return cache

    thematic_titles = set(
        provenance.keys()
    )

    featured = sorted(
        thematic_titles & featured_links
    )

    # Якщо стаття раптом присутня в обох службових списках,
    # показуємо її лише як вибрану — це вищий статус.
    good = sorted(
        (thematic_titles & good_links)
        - set(featured)
    )

    cache = {
        "featured": featured,
        "good": good,
    }

    save_json(
        RECOGNIZED_CACHE,
        cache
    )

    print(
        "Відзначені статті:"
    )
    print(
        f"  вибраних: {len(featured)}"
    )
    print(
        f"  добрих: {len(good)}"
    )

    return cache


# ---------------------------------------------------------
# WIKILINK PARSING
# ---------------------------------------------------------

def get_all_links(fact):
    return {
        normalize_title(title)
        for title in ALL_LINK_RE.findall(fact)
    }


def get_bold_subjects(fact):
    subjects = set()

    for pattern in BOLD_LINK_PATTERNS:
        for title in pattern.findall(fact):
            subjects.add(
                normalize_title(title)
            )

    return subjects


# ---------------------------------------------------------
# FACT ARCHIVE
# ---------------------------------------------------------

def extract_facts(text):
    result = []

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("* "):
            result.append(line)

    return result


def get_all_archive_pages():
    return list(
        SITE.allpages(
            prefix=ARCHIVE_PREFIX_API,
            namespace=4
        )
    )


def build_initial_facts_cache():
    print(
        "\n=== СТВОРЮЮ КЕШ АРХІВІВ ===\n"
    )

    cache = {}

    pages = get_all_archive_pages()

    for i, page in enumerate(
        pages,
        start=1
    ):
        title = page.title()

        if title.endswith("/Шаблон"):
            continue

        print(
            f"{i}/{len(pages)}: {title}"
        )

        cache[title] = extract_facts(
            page.text
        )

        time.sleep(0.1)

    save_json(
        FACTS_BY_PAGE_CACHE,
        cache
    )

    print(
        f"\nЗакешовано архівів: "
        f"{len(cache)}"
    )

    return cache


def update_archive_page(
    title,
    cache
):
    print(
        f"Оновлюю архів: {title}"
    )

    page = pywikibot.Page(
        SITE,
        title
    )

    if not page.exists():
        cache.pop(
            title,
            None
        )
        return

    cache[title] = extract_facts(
        page.text
    )


def flatten_facts(cache):
    result = []

    for facts in cache.values():
        result.extend(facts)

    return result


# ---------------------------------------------------------
# PROVENANCE
# ---------------------------------------------------------

def build_provenance():
    print(
        "\n=== ПЕРЕБУДОВУЮ "
        "ТЕМАТИЧНИЙ PROVENANCE ===\n"
    )

    provenance = {}

    # Категорію достатньо обходити один раз
    # для кожного конкретного шляху.
    visited = set()

    def walk(
        category,
        depth,
        path
    ):
        category_title = (
            category.title()
        )

        clean_category = (
            category_title.removeprefix(
                "Категорія:"
            )
        )

        current_path = (
            path + [clean_category]
        )

        visit_key = (
            category_title,
            tuple(path),
            depth
        )

        if visit_key in visited:
            return

        visited.add(visit_key)

        print(
            f"{category_title} "
            f"({depth}/{MAX_CATEGORY_DEPTH})"
        )

        try:
            for article in category.articles(
                namespaces=0
            ):
                title = normalize_title(
                    article.title()
                )

                path_string = (
                    " > ".join(current_path)
                )

                provenance.setdefault(
                    title,
                    []
                )

                if (
                    path_string
                    not in provenance[title]
                ):
                    provenance[
                        title
                    ].append(
                        path_string
                    )

        except Exception as exc:
            print(
                "Помилка читання "
                f"статей: {exc}"
            )

        if depth >= MAX_CATEGORY_DEPTH:
            return

        try:
            subcategories = list(
                category.subcategories()
            )

            for subcat in subcategories:
                walk(
                    subcat,
                    depth + 1,
                    current_path
                )

        except Exception as exc:
            print(
                "Помилка читання "
                f"підкатегорій: {exc}"
            )

        # Не молотимо API без пауз.
        time.sleep(0.12)

    for root in ROOT_CATEGORIES:
        walk(
            pywikibot.Category(
                SITE,
                root
            ),
            0,
            []
        )

    save_json(
        PROVENANCE_CACHE,
        provenance
    )

    print(
        "\nСтатей із provenance: "
        f"{len(provenance)}"
    )

    return provenance


def get_tracked_categories(
    provenance
):
    result = set()

    for paths in provenance.values():
        for path in paths:
            for category in path.split(
                " > "
            ):
                result.add(
                    "Категорія:"
                    + category
                )

    result.update(
        ROOT_CATEGORIES
    )

    return result

def build_category_paths(
    provenance
):
    """
    Будує індекс:

    назва категорії ->
    всі відомі шляхи до неї
    у тематичному дереві.
    """

    result = {}

    for paths in provenance.values():
        for path in paths:
            parts = path.split(
                " > "
            )

            for i, category in enumerate(
                parts
            ):
                prefix = " > ".join(
                    parts[:i + 1]
                )

                result.setdefault(
                    category,
                    set()
                ).add(
                    prefix
                )

    # Кореневі категорії повинні
    # бути відомі навіть якщо в них
    # зараз немає статей.
    for root in ROOT_CATEGORIES:
        clean = root.removeprefix(
            "Категорія:"
        )

        result.setdefault(
            clean,
            set()
        ).add(
            clean
        )

    return result


def refresh_article_provenance(title, provenance, category_paths):
    """Оновлює provenance однієї статті. Повертає True/False."""
    page = pywikibot.Page(SITE, title)

    try:
        if not page.exists():
            provenance.pop(title, None)
            return True

        categories = {
            category.title().removeprefix("Категорія:")
            for category in page.categories()
        }
    except Exception as exc:
        print(f"Не вдалося прочитати категорії {title}: {exc}")
        return False

    new_paths = set()

    for category in categories:
        new_paths.update(category_paths.get(category, []))

    if new_paths:
        provenance[title] = sorted(new_paths)
    else:
        provenance.pop(title, None)

    return True

def remove_category_branch_paths(
    category_name,
    provenance
):
    """
    Прибирає зі старого provenance
    лише шляхи, які проходять через
    конкретну категорію.

    Інші незалежні тематичні шляхи
    тієї самої статті зберігаються.
    """

    for article in list(
        provenance.keys()
    ):
        paths = provenance[
            article
        ]

        remaining = []

        for path in paths:
            parts = path.split(
                " > "
            )

            if category_name not in parts:
                remaining.append(
                    path
                )

        if remaining:
            provenance[
                article
            ] = remaining
        else:
            del provenance[
                article
            ]


def batch_page_categories(titles):
    """
    Повертає категорії для набору сторінок пакетними API-запитами.

    Це принципово важливо для RecentChanges: замість одного запиту
    на кожну змінену сторінку ми перевіряємо до 50 сторінок за раз.

    Повертає dict {title: set(category_titles)} або None при помилці.
    """
    titles = sorted(set(titles))

    if not titles:
        return {}

    result = {
        title: set()
        for title in titles
    }

    batch_size = 50

    for offset in range(0, len(titles), batch_size):
        batch = titles[offset:offset + batch_size]
        clcontinue = None

        while True:
            params = {
                "action": "query",
                "prop": "categories",
                "titles": "|".join(batch),
                "cllimit": "max",
                "redirects": 1,
            }

            if clcontinue:
                params["clcontinue"] = clcontinue

            try:
                data = SITE.simple_request(**params).submit()
            except Exception as exc:
                print(
                    "Не вдалося пакетно прочитати категорії: "
                    f"{exc}"
                )
                return None

            query = data.get("query", {})
            pages = query.get("pages", {})

            # API може нормалізувати або редиректити назви.
            normalized = {
                item.get("to"): item.get("from")
                for item in query.get("normalized", [])
                if item.get("to") and item.get("from")
            }
            redirects = {
                item.get("to"): item.get("from")
                for item in query.get("redirects", [])
                if item.get("to") and item.get("from")
            }

            for page_data in pages.values():
                api_title = page_data.get("title")
                if not api_title:
                    continue

                original_title = (
                    redirects.get(api_title)
                    or normalized.get(api_title)
                    or api_title
                )

                if original_title not in result:
                    # У рідкісному випадку подвійної нормалізації
                    # прив'язуємо до API title, щоб дані не загубилися.
                    original_title = api_title
                    result.setdefault(original_title, set())

                for category in page_data.get("categories", []):
                    category_title = category.get("title")
                    if category_title:
                        result[original_title].add(category_title)

            continuation = data.get("continue")
            if not continuation:
                break

            clcontinue = continuation.get("clcontinue")
            if not clcontinue:
                break

    return result


def classify_dirty_categories(dirty_categories, provenance):
    """
    Визначає релевантні змінені категорії.

    Уже відомі категорії визначаються локально без API.
    Невідомі категорії перевіряються пакетно: релевантною вважається
    лише категорія, яка зараз має відомого тематичного parent.

    Повертає list або None при помилці API.
    """
    tracked_categories = get_tracked_categories(provenance)

    known = sorted(
        title
        for title in dirty_categories
        if title in tracked_categories
        or title in ROOT_CATEGORIES
    )

    unknown = sorted(
        set(dirty_categories)
        - set(known)
    )

    relevant = list(known)

    if not unknown:
        return relevant

    parents_by_category = batch_page_categories(unknown)

    if parents_by_category is None:
        return None

    ignored_count = 0

    for category_title in unknown:
        parents = parents_by_category.get(
            category_title,
            set()
        )

        if parents & tracked_categories:
            relevant.append(category_title)
        else:
            ignored_count += 1

    if ignored_count:
        print(
            "Ігнорую сторонні категорії: "
            f"{ignored_count}"
        )

    return sorted(set(relevant))


def classify_dirty_articles(dirty_articles, provenance, category_paths):
    """
    Визначає релевантні змінені статті.

    Статті, які вже є в provenance, релевантні одразу.
    Решта перевіряється пакетно за поточними категоріями.

    Повертає list або None при помилці API.
    """
    tracked_articles = set(provenance)

    known = sorted(
        title
        for title in dirty_articles
        if title in tracked_articles
    )

    unknown = sorted(
        set(dirty_articles)
        - set(known)
    )

    relevant = list(known)

    if not unknown:
        return relevant

    categories_by_article = batch_page_categories(unknown)

    if categories_by_article is None:
        return None

    tracked_category_titles = {
        "Категорія:" + category_name
        for category_name in category_paths
    }

    for title in unknown:
        categories = categories_by_article.get(
            title,
            set()
        )

        if categories & tracked_category_titles:
            relevant.append(title)

    return sorted(set(relevant))


def refresh_category_branch(category_title, provenance):
    """
    Оновлює тільки одну ВЖЕ РЕЛЕВАНТНУ тематичну гілку.

    Невідома нетематична категорія не є причиною для повного
    rebuild. False повертається лише при реальній помилці API.
    """
    category_name = category_title.removeprefix("Категорія:")
    category_paths = build_category_paths(provenance)
    old_paths = set(category_paths.get(category_name, []))

    category = pywikibot.Category(SITE, category_title)

    try:
        exists = category.exists()
    except Exception as exc:
        print(f"Не вдалося перевірити {category_title}: {exc}")
        return False

    if not exists:
        if old_paths:
            remove_category_branch_paths(category_name, provenance)
        return True

    new_paths = set()

    if category_title in ROOT_CATEGORIES:
        new_paths.add(category_name)

    try:
        parents = list(category.categories())
    except Exception as exc:
        print(f"Не вдалося прочитати {category_title}: {exc}")
        return False

    for parent in parents:
        parent_name = parent.title().removeprefix("Категорія:")

        for parent_path in category_paths.get(parent_name, []):
            parent_depth = len(parent_path.split(" > ")) - 1

            if parent_depth < MAX_CATEGORY_DEPTH:
                new_paths.add(parent_path + " > " + category_name)

    # Якщо категорія була тематичною, але тепер втратила
    # тематичного батька — видаляємо її стару гілку.
    if not new_paths:
        if old_paths:
            remove_category_branch_paths(category_name, provenance)
        return True

    remove_category_branch_paths(category_name, provenance)
    visited = set()

    def walk(current_category, depth, current_path):
        key = (
            current_category.title(),
            depth,
            tuple(current_path),
        )

        if key in visited:
            return True

        visited.add(key)
        path_string = " > ".join(current_path)

        try:
            for article in current_category.articles(namespaces=0):
                title = normalize_title(article.title())
                provenance.setdefault(title, [])

                if path_string not in provenance[title]:
                    provenance[title].append(path_string)
        except Exception as exc:
            print(
                f"Помилка читання {current_category.title()}: {exc}"
            )
            return False

        if depth >= MAX_CATEGORY_DEPTH:
            return True

        try:
            subcategories = list(current_category.subcategories())
        except Exception as exc:
            print(
                f"Помилка підкатегорій {current_category.title()}: {exc}"
            )
            return False

        for subcat in subcategories:
            clean = subcat.title().removeprefix("Категорія:")

            if not walk(
                subcat,
                depth + 1,
                current_path + [clean],
            ):
                return False

        return True

    for path in new_paths:
        parts = path.split(" > ")
        depth = len(parts) - 1

        if depth <= MAX_CATEGORY_DEPTH:
            if not walk(category, depth, parts):
                return False

    return True

def iso_now():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_recent_changes(since_timestamp):
    """
    Отримує лише зміни, які реально можуть впливати на портал:

    1) categorize у просторах статей і категорій;
    2) edit/new у просторі Вікіпедія для архівів «Чи знаєте ви».

    Два окремі запити не тягнуть звичайні редагування статей,
    які нам для provenance не потрібні.
    """
    if not since_timestamp:
        return []

    def fetch(params):
        result = []
        rccontinue = None

        while True:
            request_params = {
                "action": "query",
                "list": "recentchanges",
                "rcstart": since_timestamp,
                "rcdir": "newer",
                "rclimit": "max",
                "rcprop": "title|timestamp|ids",
                **params,
            }

            if rccontinue:
                request_params["rccontinue"] = rccontinue

            data = SITE.simple_request(**request_params).submit()

            result.extend(
                data.get("query", {}).get("recentchanges", [])
            )

            continuation = data.get("continue")
            if not continuation:
                break

            rccontinue = continuation.get("rccontinue")
            if not rccontinue:
                break

        return result

    changes = []

    # Зміни членства у категоріях.
    changes.extend(
        fetch({
            "rcnamespace": "0|14",
            "rctype": "categorize",
        })
    )

    # Редагування архівів «Чи знаєте ви».
    changes.extend(
        fetch({
            "rcnamespace": "4",
            "rctype": "edit|new",
        })
    )

    changes.sort(key=lambda item: item.get("timestamp", ""))
    return changes

def analyse_changes(changes, provenance, facts_cache):
    """
    Лише класифікує RecentChanges.

    Важливо: на цьому етапі ми НЕ вирішуємо, що будь-яка
    змінена категорія належить до нашого тематичного дерева.
    Це перевіряється окремо, щоб випадкова категорія не могла
    запустити повний rebuild provenance.
    """
    changed_archives = set()
    dirty_articles = set()
    dirty_categories = set()

    for change in changes:
        title = change.get("title", "")
        change_type = change.get("type", "")

        if title.startswith(ARCHIVE_PREFIX_FULL):
            if not title.endswith("/Шаблон"):
                changed_archives.add(title)
            continue

        if change_type != "categorize":
            continue

        if title.startswith("Категорія:"):
            dirty_categories.add(title)
            continue

        if ":" not in title:
            dirty_articles.add(title)

    return changed_archives, dirty_articles, dirty_categories

def article_paths(
    article,
    provenance
):
    return provenance.get(
        article,
        []
    )


def path_tokens(paths):
    result = set()

    for path in paths:
        result |= tokenize(path)

    return result


def evaluate_fact(
    fact,
    provenance
):
    subjects = get_bold_subjects(
        fact
    )

    all_links = get_all_links(
        fact
    )

    thematic_subjects = {
        subject
        for subject in subjects
        if subject in provenance
    }

    if not thematic_subjects:
        return None

    thematic_links = {
        link
        for link in all_links
        if link in provenance
    }

    supporting_links = (
        thematic_links
        - thematic_subjects
    )

    matched_paths = {}

    for subject in thematic_subjects:
        matched_paths[
            subject
        ] = article_paths(
            subject,
            provenance
        )

    # Найнадійніший випадок:
    # тематичний subject +
    # ще одна тематична сутність.
    if supporting_links:
        return {
            "fact": fact,
            "subjects": sorted(
                subjects
            ),
            "thematic_subjects": sorted(
                thematic_subjects
            ),
            "supporting_links": sorted(
                supporting_links
            ),
            "paths": matched_paths,
            "reason": (
                "multiple_thematic_entities"
            ),
        }

    # Другий рівень:
    # зміст факту відповідає
    # тематичному шляху.
    fact_tokens = tokenize(
        fact
    )

    subject_path_tokens = set()

    for subject in thematic_subjects:
        subject_path_tokens |= (
            path_tokens(
                matched_paths[
                    subject
                ]
            )
        )

    overlap = sorted(
        fact_tokens
        & subject_path_tokens
    )

    if len(overlap) >= 2:
        return {
            "fact": fact,
            "subjects": sorted(
                subjects
            ),
            "thematic_subjects": sorted(
                thematic_subjects
            ),
            "supporting_links": [],
            "paths": matched_paths,
            "reason": (
                "path_text_overlap"
            ),
            "overlap": overlap,
        }

    return None


def find_relevant_facts(
    facts,
    provenance
):
    relevant = []

    seen = set()

    for raw_fact in facts:
        fact = clean_fact(
            raw_fact
        )

        if not fact:
            continue

        # Не дублюємо однакові факти,
        # якщо вони випадково є
        # в кількох архівах.
        if fact in seen:
            continue

        seen.add(fact)

        result = evaluate_fact(
            fact,
            provenance
        )

        if result:
            relevant.append(
                result
            )

    return relevant


# ---------------------------------------------------------
# PORTAL UPDATE
# ---------------------------------------------------------

def update_portal(
    relevant
):
    if not relevant:
        print(
            "\nНемає релевантних "
            "фактів. Портал не змінено."
        )
        return

    selected = random.sample(
        relevant,
        min(
            5,
            len(relevant)
        )
    )

    output = "\n".join(
        item["fact"]
        for item in selected
    )

    print(
        "\n=== НОВИЙ БЛОК ===\n"
    )

    print(output)

    page = pywikibot.Page(
        SITE,
        TARGET_PAGE
    )

    new_text = (
        output
        + "\n\n"
        + "<noinclude>"
        + "[[Категорія:"
        + "Портал:Сексуальність]]"
        + "</noinclude>"
    )

    # Якщо при 3 фактах порядок
    # випадково той самий —
    # зайву правку не робимо.
    if page.text.strip() == (
        new_text.strip()
    ):
        print(
            "\nВміст не змінився. "
            "Редагування не потрібне."
        )
        return

    page.text = new_text

    page.save(
        summary=(
            "Автоматичне оновлення "
            "блоку «Цікавинки»"
        )
    )

    print(
        "\nПортал успішно "
        "оновлено."
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    SITE.login()

    print(
        "=== PORTAL SYNC ==="
    )

    state = load_json(
        STATE_CACHE,
        {}
    )

    previous_sync = state.get(
        "last_sync"
    )

    # ---------------------------------
    # PROVENANCE
    # ---------------------------------

    provenance = load_json(
        PROVENANCE_CACHE
    )

    if provenance is None:
        provenance = (
            build_provenance()
        )

    else:
        print(
            "\nProvenance із кешу: "
            f"{len(provenance)} статей"
        )

    # ---------------------------------
    # FACT CACHE
    # ---------------------------------

    facts_cache = load_json(
        FACTS_BY_PAGE_CACHE
    )

    if facts_cache is None:
        facts_cache = (
            build_initial_facts_cache()
        )

    else:
        print(
            "Архівів у кеші: "
            f"{len(facts_cache)}"
        )

    # ---------------------------------
    # ONLINE CHANGES
    # ---------------------------------

    current_sync = iso_now()

    if previous_sync:
        print(
            "\nПеревіряю зміни після:"
        )
        print(previous_sync)

        changes = get_recent_changes(
            previous_sync
        )

        print(
            "Recent changes: "
            f"{len(changes)}"
        )

        (
            changed_archives,
            dirty_articles,
            dirty_categories
        ) = analyse_changes(
            changes,
            provenance,
            facts_cache
        )

        # -----------------------------
        # UPDATE ONLY CHANGED ARCHIVES
        # -----------------------------

        if changed_archives:
            print(
                "\nЗмінені архіви "
                "«Чи знаєте ви»: "
                f"{len(changed_archives)}"
            )

            for title in sorted(
                changed_archives
            ):
                update_archive_page(
                    title,
                    facts_cache
                )

            save_json(
                FACTS_BY_PAGE_CACHE,
                facts_cache
            )

        else:
            print(
                "\nНових/змінених "
                "архівів немає."
            )

        # -----------------------------
        # PROVENANCE ONLY IF NEEDED
        # -----------------------------

        relevant_dirty_categories = classify_dirty_categories(
            dirty_categories,
            provenance,
        )

        if relevant_dirty_categories is None:
            print(
                "\nНе вдалося безпечно перевірити тематичні "
                "категорії. last_sync не буде оновлено."
            )
            return

        category_paths = build_category_paths(provenance)

        relevant_dirty_articles = classify_dirty_articles(
            dirty_articles,
            provenance,
            category_paths,
        )

        if relevant_dirty_articles is None:
            print(
                "\nНе вдалося безпечно перевірити тематичні "
                "статті. last_sync не буде оновлено."
            )
            return

        if relevant_dirty_categories or relevant_dirty_articles:
            print(
                "\nРелевантні зміни тематичної категоризації:"
            )
            print(
                f"  статей: {len(relevant_dirty_articles)}"
            )
            print(
                f"  категорій: {len(relevant_dirty_categories)}"
            )

            for category_title in relevant_dirty_categories:
                print(f"Оновлюю гілку: {category_title}")

                if not refresh_category_branch(
                    category_title,
                    provenance,
                ):
                    print(
                        "\nПомилка інкрементального оновлення "
                        "provenance. last_sync не буде оновлено."
                    )
                    return

            category_paths = build_category_paths(provenance)

            for title in relevant_dirty_articles:
                if not refresh_article_provenance(
                    title,
                    provenance,
                    category_paths,
                ):
                    print(
                        "\nПомилка інкрементального оновлення "
                        "статті. last_sync не буде оновлено."
                    )
                    return

            save_json(PROVENANCE_CACHE, provenance)

            print("Provenance оновлено інкрементально.")
        else:
            print("Тематичне дерево не змінилося.")

    else:
        print(
            "\nЦе перший запуск "
            "інкрементальної версії."
        )
        print(
            "Поточні кеші використано "
            "як стартову точку."
        )

    # ---------------------------------
    # RECOGNIZED CONTENT
    # ---------------------------------

    recognized = update_recognized_cache(
        provenance
    )

    # ---------------------------------
    # FILTER
    # ---------------------------------

    facts = flatten_facts(
        facts_cache
    )

    print(
        "\nФактів у кеші: "
        f"{len(facts)}"
    )

    relevant = (
        find_relevant_facts(
            facts,
            provenance
        )
    )

    print(
        "Релевантних фактів: "
        f"{len(relevant)}"
    )

    # ---------------------------------
    # WRITE PORTAL
    # ---------------------------------

    update_portal(
        relevant
    )

    # ---------------------------------
    # SAVE SYNC STATE
    # ---------------------------------

    save_json(
        STATE_CACHE,
        {
            "last_sync": current_sync
        }
    )

    print(
        "\nСинхронізацію завершено."
    )
    print(
        "last_sync = "
        + current_sync
    )


if __name__ == "__main__":
    main()