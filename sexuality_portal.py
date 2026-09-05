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


# ---------------------------------------------------------
# RECENT CHANGES API
# ---------------------------------------------------------

def iso_now():
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_recent_changes(
    since_timestamp
):
    """
    Отримує зміни від останньої
    синхронізації до поточного часу.

    Namespace:
      0  = статті
      4  = Вікіпедія
      14 = категорії
    """

    if not since_timestamp:
        return []

    changes = []

    rccontinue = None

    while True:
        params = {
            "action": "query",
            "list": "recentchanges",
            "rcstart": since_timestamp,
            "rcdir": "newer",
            "rclimit": "max",
            "rcnamespace": "0|4|14",
            "rcprop": (
                "title|timestamp|ids|flags"
            ),
        }

        if rccontinue:
            params[
                "rccontinue"
            ] = rccontinue

        request = SITE.simple_request(
            **params
        )

        data = request.submit()

        changes.extend(
            data.get(
                "query",
                {}
            ).get(
                "recentchanges",
                []
            )
        )

        continuation = data.get(
            "continue"
        )

        if not continuation:
            break

        rccontinue = continuation.get(
            "rccontinue"
        )

        if not rccontinue:
            break

    return changes


# ---------------------------------------------------------
# DETECT RELEVANT CHANGES
# ---------------------------------------------------------

def article_current_categories(
    title
):
    page = pywikibot.Page(
        SITE,
        title
    )

    if not page.exists():
        return set()

    try:
        return {
            category.title()
            for category
            in page.categories()
        }

    except Exception:
        return set()


def analyse_changes(
    changes,
    provenance,
    facts_cache
):
    changed_archives = set()

    provenance_dirty = False

    tracked_articles = set(
        provenance.keys()
    )

    tracked_categories = (
        get_tracked_categories(
            provenance
        )
    )

    for change in changes:
        title = change.get(
            "title",
            ""
        )

        # -----------------------------
        # DYK ARCHIVE
        # -----------------------------

        if title.startswith(
            ARCHIVE_PREFIX_FULL
        ):
            if not title.endswith(
                "/Шаблон"
            ):
                changed_archives.add(
                    title
                )

            continue

        # -----------------------------
        # CATEGORY CHANGE
        # -----------------------------

        if title.startswith(
            "Категорія:"
        ):
            if title in tracked_categories:
                provenance_dirty = True

            continue

        # -----------------------------
        # ARTICLE CHANGE
        # -----------------------------

        if ":" in title:
            continue

        # Стаття вже є у тематичному
        # provenance — могла змінити
        # категоризацію.
        if title in tracked_articles:
            provenance_dirty = True
            continue

        # Нова/раніше нетематична стаття
        # могла бути додана до нашого дерева.
        categories = (
            article_current_categories(
                title
            )
        )

        if (
            categories
            & tracked_categories
        ):
            provenance_dirty = True

    return (
        changed_archives,
        provenance_dirty
    )


# ---------------------------------------------------------
# FACT RELEVANCE
# ---------------------------------------------------------

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
            provenance_dirty
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

        if provenance_dirty:
            print(
                "\nВиявлено зміни "
                "тематичної категоризації."
            )

            provenance = (
                build_provenance()
            )

        else:
            print(
                "Тематичне дерево "
                "не змінилося."
            )

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