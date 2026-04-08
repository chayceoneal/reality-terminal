#!/usr/bin/env python3
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
DASHBOARD_DIR = BASE_DIR / "dashboard"
CONFIG_PATH = BASE_DIR / "config.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

SALE_HINTS_POS = [
    "osobní vlastnictví",
    "balkon",
    "terasa",
    "sklep",
    "parkování",
    "výhled",
    "cihlová",
    "v dobrém stavu",
    "nízkoenergetický",
    "nizkoenergeticky",
]
RENT_HINTS_POS = [
    "po rekonstrukci",
    "kompletní rekonstrukci",
    "novostavba",
    "moderní",
    "nový",
    "zánovní",
    "ihned k nastěhování",
    "ve velmi dobrém stavu",
    "klimatizace",
    "kuchyňská linka na míru",
    "energetická třída b",
    "energetická třída c",
]
NEG_HINTS = [
    "před rekonstrukcí",
    "původní stav",
    "nutná rekonstrukce",
    "ke kompletní rekonstrukci",
    "horší stav",
]
PANEL_HINTS = ["panelová", "panelovy", "panelák", "panel"]
SCENIC_TERMS = [
    "výhled",
    "vyhled",
    "panorama",
    "slunný",
    "slunny",
    "jižní svah",
    "jizni svah",
    "klidná část",
    "klidna cast",
    "samota",
]


@dataclass
class Listing:
    category: str
    property_type: str
    listing_id: str
    url: str
    title: str
    layout: str | None
    locality: str | None
    area_m2: float | None
    price_czk: int | None
    monthly_total_czk: int | None
    inserted_at: str | None
    updated_at: str | None
    description: str | None
    condition_text: str | None
    features: list[str]
    score: float
    score_reasons: list[str]
    bucket: str = "main"
    is_new: bool = False


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text())


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)
    DASHBOARD_DIR.mkdir(exist_ok=True)


def search_url(category: str, config: dict[str, Any], property_type: str) -> str:
    region = config["base_region"]
    if property_type == "apartment":
        layouts = ",".join(config["apartment_layouts"])
        base = "https://www.sreality.cz/hledani/prodej/byty" if category == "sale" else "https://www.sreality.cz/hledani/pronajem/byty"
        extra = f"&velikost={quote(layouts, safe=',+')}"
    elif property_type == "family_home":
        base = "https://www.sreality.cz/hledani/prodej/domy" if category == "sale" else "https://www.sreality.cz/hledani/pronajem/domy"
        extra = ""
    elif property_type == "land":
        base = "https://www.sreality.cz/hledani/prodej/pozemky"
        extra = ""
    else:
        raise ValueError(f"Unknown property_type: {property_type}")

    return (
        f"{base}?region={quote('obec ' + region['name'])}"
        f"&region-id={region['region_id']}"
        f"&region-typ={region['region_type']}"
        f"&vzdalenost={region['distance_km']}"
        f"{extra}"
    )


def fetch(url: str) -> str:
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def extract_detail_urls(search_html: str) -> list[str]:
    found = re.findall(r'href="([^"]*/detail/[^"]+)"', search_html)
    output: list[str] = []
    seen: set[str] = set()
    for item in found:
        full = item if item.startswith("http") else f"https://www.sreality.cz{item}"
        if full not in seen:
            seen.add(full)
            output.append(full)
    return output


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_price(text: str) -> int | None:
    if not text:
        return None
    cleaned = text.replace("\xa0", " ")
    candidates = re.findall(r"(?:\d\s*){4,}", cleaned)
    if not candidates:
        return None
    joined = max(candidates, key=len)
    digits = re.sub(r"\D", "", joined)
    if len(digits) < 4:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_area_from_title(title: str) -> float | None:
    match = re.search(r"(\d+[\.,]?\d*)\s*m²", title)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def parse_layout_from_title(title: str) -> str | None:
    match = re.search(r"([0-9]\+(?:1|kk))", title, flags=re.I)
    return match.group(1) if match else None


def allowed_layout(layout: str | None, property_type: str, config: dict[str, Any]) -> bool:
    if property_type == "apartment":
        return layout in set(config["apartment_layouts"])
    return True


def extract_meta(name: str, html: str) -> str | None:
    match = re.search(rf'<meta[^>]+property="{re.escape(name)}"[^>]+content="([^"]+)"', html)
    if match:
        return clean_text(match.group(1))
    match = re.search(rf'<meta[^>]+name="{re.escape(name)}"[^>]+content="([^"]+)"', html)
    return clean_text(match.group(1)) if match else None


def extract_body_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    return clean_text(text)


def split_description(body: str) -> str:
    start_markers = [
        "Naše společnost",
        "Exkluzivně nabízíme",
        "Nabízíme",
        "Hledáte bydlení",
        "Pronájem",
        "Prodej",
    ]
    end_markers = [
        "Celková cena",
        "Poznámka k ceně",
        "Příslušenství",
        "Energetická náročnost",
        "Stavba",
        "Infrastruktura",
        "Plocha",
        "Vlastnictví",
        "Zobrazeno",
        "Vloženo",
        "ID zakázky",
        "Napsat prodejci",
        "Prodejce",
        "Lokalita je pouze orientační",
        "Sreality.cz pomáhají",
        "Jakékoliv užití obsahu",
    ]

    start = 0
    for marker in start_markers:
        idx = body.find(marker)
        if idx != -1:
            start = idx
            break

    end = len(body)
    for marker in end_markers:
        idx = body.find(marker)
        if idx != -1 and idx > start:
            end = min(end, idx)

    desc = clean_text(body[start:end])
    if desc.startswith("Pronájem chat a chalup") or len(desc) < 80:
        return ""
    return desc


def parse_dates(body: str) -> tuple[str | None, str | None]:
    inserted = None
    updated = None

    match = re.search(r"Vloženo\s*:?\s*([0-9]{1,2}\.\s*[0-9]{1,2}\.\s*[0-9]{4})", body)
    if match:
        inserted = clean_text(match.group(1))

    match = re.search(r"Upraveno\s*:?\s*([0-9]{1,2}\.\s*[0-9]{1,2}\.\s*[0-9]{4})", body)
    if match:
        updated = clean_text(match.group(1))

    return inserted, updated


def parse_condition(body: str) -> str | None:
    match = re.search(r"Stavba\s*:?\s*(.{0,140})", body)
    if match:
        return clean_text(match.group(1))
    return None


def parse_features(body: str) -> list[str]:
    features: list[str] = []
    lowered = body.lower()
    for token in ["Balkon", "Sklep", "Lodžie", "Terasa", "Parkování", "Parkovací stání", "Zařízeno", "Zahrada"]:
        if token.lower() in lowered:
            features.append(token)
    if "bez výtahu" in lowered:
        features.append("Bez výtahu")
    elif "výtah" in lowered or "vytah" in lowered:
        features.append("Výtah")
    return features


def extract_listing_id(url: str, body: str) -> str:
    match = re.search(r"/(\d+)$", url)
    if match:
        return match.group(1)
    match = re.search(r"ID zakázky\s*:?\s*([0-9]+)", body)
    if match:
        return match.group(1)
    return str(abs(hash(url)))


def parse_detail(url: str, category: str, property_type: str) -> Listing:
    html = fetch(url)
    title = extract_meta("og:title", html) or extract_meta("twitter:title", html) or "Unknown listing"
    desc_meta = extract_meta("description", html) or ""
    body = extract_body_text(html)
    desc = split_description(body)

    locality = None
    if "," in title:
        locality = clean_text(title.split(",", 1)[1].replace("• Sreality.cz", ""))

    area = parse_area_from_title(title) or parse_area_from_title(desc_meta)
    price = parse_price(desc_meta)
    monthly_total = price if category == "rent" else None
    inserted_at, updated_at = parse_dates(body)
    condition_text = parse_condition(body)
    features = parse_features(body)
    layout = parse_layout_from_title(title)

    listing = Listing(
        category=category,
        property_type=property_type,
        listing_id=extract_listing_id(url, body),
        url=url,
        title=title.replace("• Sreality.cz", "").strip(),
        layout=layout,
        locality=locality,
        area_m2=area,
        price_czk=price,
        monthly_total_czk=monthly_total,
        inserted_at=inserted_at,
        updated_at=updated_at,
        description=desc or desc_meta,
        condition_text=condition_text,
        features=features,
        score=0.0,
        score_reasons=[],
    )
    score_listing(listing)
    return listing


def has_household_restriction(text: str) -> bool:
    phrases = [
        "bez dětí",
        "bez deti",
        "bez dítěte",
        "bez ditete",
        "bez psa",
        "bez psů",
        "bez psu",
        "bez domácích mazlíčků",
        "bez domacich mazlicku",
        "bez zvířat",
        "bez zvirat",
        "preferuji bezdetný pár",
        "preferuji bezdetny par",
        "preferujeme bez dětí",
        "preferujeme bez deti",
        "ne pro rodinu s dětmi",
        "ne pro rodinu s detmi",
        "bez mazlíčků",
        "bez mazlicku",
    ]
    return any(phrase in text for phrase in phrases)


def score_listing(listing: Listing) -> None:
    config = load_config()
    cfg = config["soft_price"]
    score = 0.0
    reasons: list[str] = []
    bucket = "main"

    text = f"{listing.description or ''} {listing.condition_text or ''}".lower()
    area = listing.area_m2 or 0
    layout = listing.layout

    if listing.property_type == "land":
        if area >= 1200:
            score += 24
            reasons.append("generous plot size")
        elif area >= 800:
            score += 18
            reasons.append("solid plot size")
        elif area >= 400:
            score += 10
            reasons.append("usable plot size")

        for term in SCENIC_TERMS:
            if term in text:
                score += 8
                reasons.append(f"scenic signal: {term}")
                break

        if any(term in text for term in ["stavební", "stavebni", "k výstavbě", "k vystavbe"]):
            score += 12
            reasons.append("buildable land signal")
    else:
        min_area = config["family_home_min_area_m2"] if listing.property_type == "family_home" else config["min_area_m2"]
        if area >= 95:
            score += 24
            reasons.append("very generous floor area")
        elif area >= 85:
            score += 20
            reasons.append("large floor area")
        elif area >= min_area:
            score += 14
            reasons.append("meets size target")
        else:
            if listing.property_type == "apartment" and layout in {"3+1", "3+kk"}:
                score -= 8
                reasons.append("below target size but still 3-room")
                bucket = "below-target"
            else:
                score -= 24
                reasons.append(f"below {min_area} m² target")
                bucket = "below-target"

        if listing.property_type == "family_home":
            score += 18
            reasons.append("family house category")
        elif layout in {"4+kk", "4+1"}:
            score += 22
            reasons.append("excellent family layout")
        elif layout in {"3+1", "3+kk"}:
            score += 18
            reasons.append("preferred 3-room layout")
        elif layout in {"2+1", "2+kk"}:
            score += 8
            reasons.append("acceptable 2-room layout")
        else:
            score -= 20
            reasons.append("outside target layouts")

        has_outdoor = any(x in text for x in ["balkon", "balkón", "terasa", "lodžie", "lodzie", "lodžii", "zahrada", "garden"])
        if has_outdoor:
            score += 16
            reasons.append("balcony / terrace / garden")
        else:
            score -= 14
            reasons.append("no balcony or outdoor space detected")

    if listing.category == "sale":
        if listing.property_type != "land" and any(x in text for x in PANEL_HINTS):
            score += 5
            reasons.append("panel is acceptable / practical")
        if listing.property_type != "land" and any(x in text for x in ["původní stav", "pred rekonstrukci", "před rekonstrukcí", "k rekonstrukci"]):
            score += 5
            reasons.append("renovation canvas")
        if any(x in text for x in ["osobní vlastnictví", "osobni vlastnictvi"]):
            score += 3
            reasons.append("personal ownership")
    else:
        if any(x in text for x in ["vybavený", "vybaveno", "zařízeno", "částečně zařízeno"]):
            score -= 4
            reasons.append("furnished / less ideal")
        if has_household_restriction(text):
            score -= 30
            reasons.append("family / pet restriction")
        if any(x in text for x in ["nekuřáky", "nekuraky"]):
            score -= 6
            reasons.append("smoking restriction")
        if any(x in text for x in ["po rekonstrukci", "kompletní rekonstrukci", "novostavba", "moderní", "nový", "zánovní"]):
            score += 10
            reasons.append("move-in ready vibe")
        if any(x in text for x in ["původní stav", "starší kuchyň", "starší koupelna", "umakart"]):
            score -= 12
            reasons.append("dated interior signal")

    pos_hints = RENT_HINTS_POS if listing.category == "rent" else SALE_HINTS_POS
    for hint in pos_hints:
        if hint in text:
            score += 3
            reasons.append(f"positive signal: {hint}")
            break
    for hint in NEG_HINTS:
        if hint in text:
            score -= 4 if listing.category == "sale" else 8
            reasons.append(f"negative signal: {hint}")
            break

    if any(x in text for x in ["energetická náročnost: velmi úsporná", "energetická náročnost: úsporná", "b - velmi úsporná", "c - úsporná"]):
        score += 8
        reasons.append("better energy efficiency signal")

    price = listing.monthly_total_czk if listing.category == "rent" else listing.price_czk
    if price is not None:
        if listing.category == "sale":
            sale_good_under = cfg["family_home_sale_good_under"] if listing.property_type == "family_home" else cfg["sale_good_under"]
            if price <= cfg["sale_excellent_under"]:
                score += 18
                reasons.append("excellent sale price band")
            elif price <= sale_good_under:
                score += 10
                reasons.append("good sale price band")
            elif price <= cfg["sale_stretch_under"]:
                score += 2
                reasons.append("stretch but still plausible")
                bucket = "stretch" if score > 20 else bucket
            else:
                score -= 8
                reasons.append("above preferred sale range")
                bucket = "stretch"

            if listing.property_type == "land":
                if price <= cfg["land_sale_good_under"]:
                    score += 8
                    reasons.append("reasonable land price")
            elif area > 0:
                price_per_m2 = price / area
                if price_per_m2 < 60000:
                    score += 14
                    reasons.append("strong value per m²")
                elif price_per_m2 < 80000:
                    score += 8
                    reasons.append("good value per m²")
                elif price_per_m2 > 110000:
                    score -= 8
                    reasons.append("weak value per m²")
        else:
            if price <= cfg["rent_excellent_under"]:
                score += 18
                reasons.append("excellent monthly cost")
            elif price <= cfg["rent_good_under"]:
                score += 10
                reasons.append("reasonable monthly cost")
            elif price <= cfg["rent_stretch_under"]:
                score += 1
                reasons.append("stretch rent")
                bucket = "stretch" if score > 20 else bucket
            else:
                score -= 10
                reasons.append("expensive for rent target")
                bucket = "stretch"

            if area > 0:
                rent_per_m2 = price / area
                if rent_per_m2 < 260:
                    score += 8
                    reasons.append("good rent per m²")
                elif rent_per_m2 > 420:
                    score -= 8
                    reasons.append("expensive for the space")

    if any(x in text for x in ["vlak", "nádraží", "nadrazi"]):
        score += 4
        reasons.append("train-access hint")

    if any(x in text for x in ["parkování", "parkovací stání", "garáž", "garaz"]):
        score += 2
        reasons.append("parking available")

    if any(x in text for x in ["pěší", "docházkové vzdálenosti", "občanská vybavenost", "v docházkové vzdálenosti"]):
        score += 5
        reasons.append("walkability signal")

    if "bez výtahu" in text and area >= 85:
        score -= 2
        reasons.append("larger unit without lift")

    if listing.category == "sale" and price and price > cfg["sale_stretch_under"]:
        bucket = "stretch"
    if listing.category == "rent" and price and price > cfg["rent_stretch_under"]:
        bucket = "stretch"

    listing.score = round(score, 1)
    listing.score_reasons = reasons[:7]
    listing.bucket = bucket


def current_snapshot_path(category: str) -> Path:
    return DATA_DIR / f"current-{category}.json"


def load_previous_ids(category: str) -> set[str]:
    path = current_snapshot_path(category)
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text())
        return {item["listing_id"] for item in payload.get("listings", [])}
    except Exception:
        return set()


def save_snapshot(category: str, listings: list[Listing]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at": now,
        "category": category,
        "listings": [asdict(item) for item in listings],
    }
    current_snapshot_path(category).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    HISTORY_DIR.joinpath(f"{datetime.now().strftime('%Y-%m-%d')}-{category}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )


def collect_category(category: str, property_type: str) -> list[Listing]:
    config = load_config()
    html = fetch(search_url(category, config, property_type))
    urls = extract_detail_urls(html)
    listings: list[Listing] = []
    prev_ids = load_previous_ids(f"{property_type}-{category}")

    for url in urls:
        try:
            item = parse_detail(url, category, property_type)
            if not allowed_layout(item.layout, property_type, config):
                continue
            if property_type != "land" and category == "rent":
                combined_text = f"{item.description or ''} {item.condition_text or ''}".lower()
                if has_household_restriction(combined_text):
                    continue
            item.is_new = item.listing_id not in prev_ids
            listings.append(item)
            time.sleep(0.35)
        except Exception as exc:
            print(f"WARN failed to parse {url}: {exc}")

    listings.sort(key=lambda x: x.score, reverse=True)
    save_snapshot(f"{property_type}-{category}", listings)
    return listings


def fmt_czk(value: int | None) -> str:
    if value is None:
        return "?"
    return f"{value:,} Kč".replace(",", " ")


def translate_reason(reason: str, lang: str) -> str:
    if lang == "cs":
        mapping = {
            "very generous floor area": "velmi velkorysá plocha",
            "large floor area": "velká plocha",
            "meets size target": "splňuje cílovou velikost",
            "below target size but still 3-room": "pod cílovou velikostí, ale stále 3 pokoje",
            "preferred 3-room layout": "preferovaná 3pokojová dispozice",
            "acceptable 2-room layout": "přijatelná 2pokojová dispozice",
            "outside target layouts": "mimo cílové dispozice",
            "excellent family layout": "výborná rodinná dispozice",
            "family house category": "rodinný dům",
            "balcony / terrace / garden": "balkon / terasa / zahrada",
            "no balcony or outdoor space detected": "bez zjevného venkovního prostoru",
            "panel is acceptable / practical": "panel je v pořádku / praktický",
            "renovation canvas": "dobrý základ pro rekonstrukci",
            "personal ownership": "osobní vlastnictví",
            "furnished / less ideal": "zařízené / méně ideální",
            "family / pet restriction": "omezení pro děti / mazlíčky",
            "smoking restriction": "omezení kvůli kouření",
            "move-in ready vibe": "působí připraveně k nastěhování",
            "dated interior signal": "signál staršího interiéru",
            "excellent sale price band": "výborná cenová hladina pro koupi",
            "good sale price band": "dobrá cenová hladina pro koupi",
            "stretch but still plausible": "nad preferencí, ale stále možné",
            "above preferred sale range": "nad preferovanou cenou koupě",
            "strong value per m²": "silná hodnota za m²",
            "good value per m²": "dobrá hodnota za m²",
            "weak value per m²": "slabší hodnota za m²",
            "excellent monthly cost": "výborné měsíční náklady",
            "reasonable monthly cost": "rozumné měsíční náklady",
            "stretch rent": "nájem na hraně",
            "expensive for rent target": "drahé pro cílový nájem",
            "good rent per m²": "dobrý nájem za m²",
            "expensive for the space": "drahé vzhledem k ploše",
            "train-access hint": "náznak dobré dostupnosti vlakem",
            "parking available": "parkování k dispozici",
            "walkability signal": "signál dobré pěší dostupnosti",
            "larger unit without lift": "větší byt bez výtahu",
            "better energy efficiency signal": "lepší energetická účinnost",
            "generous plot size": "velkorysý pozemek",
            "solid plot size": "solidní velikost pozemku",
            "usable plot size": "použitelná velikost pozemku",
            "buildable land signal": "signál stavebního pozemku",
            "reasonable land price": "rozumná cena pozemku",
        }
        if reason.startswith("positive signal: "):
            return "pozitivní signál: " + reason.split(": ", 1)[1]
        if reason.startswith("negative signal: "):
            return "negativní signál: " + reason.split(": ", 1)[1]
        if reason.startswith("scenic signal: "):
            return "signál výhledu: " + reason.split(": ", 1)[1]
        return mapping.get(reason, reason)
    return reason


def render_listing(item: Listing, lang: str = "en") -> str:
    subtitle = " | ".join(
        part
        for part in [
            item.layout,
            f"{int(item.area_m2)} m²" if item.area_m2 else None,
            item.locality,
            fmt_czk(item.monthly_total_czk if item.category == "rent" else item.price_czk),
        ]
        if part
    )
    badge = ""
    if item.is_new:
        badge = '<span class="badge new">NEW</span>' if lang == "en" else '<span class="badge new">NOVÉ</span>'
    reasons = " · ".join(escape(translate_reason(x, lang)) for x in item.score_reasons)
    desc = escape((item.description or "")[:380])
    return f"""
    <div class='card'>
      <div class='card-top'><span class='score'>{item.score:.1f}</span>{badge}</div>
      <a class='title' href='{escape(item.url)}' target='_blank' rel='noreferrer'>{escape(item.title)}</a>
      <div class='meta'>{escape(subtitle)}</div>
      <div class='reasons'>{reasons}</div>
      <p class='desc'>{desc}</p>
    </div>
    """


def generate_dashboard(
    apartment_sale: list[Listing],
    apartment_rent: list[Listing],
    family_home_sale: list[Listing],
    family_home_rent: list[Listing],
    land_sale: list[Listing],
) -> None:
    config = load_config()
    region_name = config["base_region"]["name"]
    distance_km = config["base_region"]["distance_km"]
    dashboard_title = f"REALITY TERMINAL // {region_name.upper()} + {distance_km} KM"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    apt_sale_new = [x for x in apartment_sale if x.is_new]
    apt_rent_new = [x for x in apartment_rent if x.is_new]
    home_sale_new = [x for x in family_home_sale if x.is_new]
    home_rent_new = [x for x in family_home_rent if x.is_new]
    land_new = [x for x in land_sale if x.is_new]

    apt_sale_main = [x for x in apartment_sale if x.bucket == "main"]
    apt_rent_main = [x for x in apartment_rent if x.bucket == "main"]
    home_sale_main = [x for x in family_home_sale if x.bucket == "main"]
    home_rent_main = [x for x in family_home_rent if x.bucket == "main"]
    land_main = [x for x in land_sale if x.bucket == "main"]

    all_items = apartment_sale + apartment_rent + family_home_sale + family_home_rent + land_sale
    below_target = [x for x in all_items if x.bucket == "below-target"]
    stretch = [x for x in all_items if x.bucket == "stretch"]

    labels = {
        "en": {
            "title": dashboard_title,
            "meta1": f"Last refresh: {generated} | region: {region_name} | radius: {distance_km} km",
            "meta2": f"New today: apt sale={len(apt_sale_new)} | apt rent={len(apt_rent_new)} | home sale={len(home_sale_new)} | home rent={len(home_rent_new)} | land={len(land_new)} | below-target={len(below_target)} | stretch={len(stretch)}",
            "apt_sale_new": "NEW TODAY // APARTMENT SALE",
            "apt_rent_new": "NEW TODAY // APARTMENT RENT",
            "apt_sale_top": "TOP APARTMENT SALE CANDIDATES",
            "apt_rent_top": "TOP APARTMENT RENT CANDIDATES",
            "home_sale_top": "TOP FAMILY HOMES // SALE",
            "home_rent_top": "TOP FAMILY HOMES // RENT",
            "land_top": "SCENIC LAND / COTTAGE POTENTIAL",
            "below": "BELOW TARGET BUT NOTABLE",
            "stretch": "STRETCH / FUN",
            "no_apt_sale_new": "No new apartment sale matches.",
            "no_apt_rent_new": "No new apartment rent matches.",
            "no_apt_sale_main": "No main apartment sale candidates.",
            "no_apt_rent_main": "No main apartment rent candidates.",
            "no_home_sale_main": "No strong family home sale candidates.",
            "no_home_rent_main": "No strong family home rent candidates.",
            "no_land_main": "No scenic land candidates right now.",
            "no_below": "Nothing notable below target.",
            "no_stretch": "No stretch listings worth flagging.",
            "lang_switch": '<a href="#" onclick="setLang(\'en\');return false;">EN</a> | <a href="#" onclick="setLang(\'cs\');return false;">CS</a>',
        },
        "cs": {
            "title": dashboard_title,
            "meta1": f"Poslední obnovení: {generated} | lokalita: {region_name} | radius: {distance_km} km",
            "meta2": f"Nové dnes: byty prodej={len(apt_sale_new)} | byty nájem={len(apt_rent_new)} | domy prodej={len(home_sale_new)} | domy nájem={len(home_rent_new)} | pozemky={len(land_new)} | pod cílem={len(below_target)} | stretch={len(stretch)}",
            "apt_sale_new": "NOVÉ DNES // PRODEJ BYTŮ",
            "apt_rent_new": "NOVÉ DNES // NÁJEM BYTŮ",
            "apt_sale_top": "NEJZAJÍMAVĚJŠÍ PRODEJE BYTŮ",
            "apt_rent_top": "NEJZAJÍMAVĚJŠÍ NÁJMY BYTŮ",
            "home_sale_top": "NEJZAJÍMAVĚJŠÍ RODINNÉ DOMY // PRODEJ",
            "home_rent_top": "NEJZAJÍMAVĚJŠÍ RODINNÉ DOMY // NÁJEM",
            "land_top": "POZEMKY S VÝHLEDEM / POTENCIÁL NA CHALUPU",
            "below": "POD CÍLEM, ALE STOJÍ ZA POHLED",
            "stretch": "STRETCH / FUN",
            "no_apt_sale_new": "Žádné nové prodeje bytů.",
            "no_apt_rent_new": "Žádné nové nájmy bytů.",
            "no_apt_sale_main": "Žádní hlavní kandidáti na prodej bytů.",
            "no_apt_rent_main": "Žádní hlavní kandidáti na nájem bytů.",
            "no_home_sale_main": "Žádní silní kandidáti na prodej rodinných domů.",
            "no_home_rent_main": "Žádní silní kandidáti na nájem rodinných domů.",
            "no_land_main": "Teď nic zajímavého mezi pozemky s výhledem.",
            "no_below": "Nic zajímavého pod cílem.",
            "no_stretch": "Žádné stretch nabídky, které stojí za vyvěšení.",
            "lang_switch": '<a href="#" onclick="setLang(\'en\');return false;">EN</a> | <a href="#" onclick="setLang(\'cs\');return false;">CS</a>',
        },
    }

    def section(title: str, body: str, lang: str) -> str:
        return f"<div class='section lang-{lang}'><h2>{escape(title)}</h2><div class='grid'>{body}</div></div>"

    parts: list[str] = []
    for lang in ["en", "cs"]:
        labels_for_lang = labels[lang]
        parts.append(f"<div class='langblock lang-{lang}'>")
        parts.append(section(labels_for_lang["apt_sale_new"], "".join(render_listing(x, lang) for x in apt_sale_new[:10]) or f'<div class="card">{escape(labels_for_lang["no_apt_sale_new"])}</div>', lang))
        parts.append(section(labels_for_lang["apt_rent_new"], "".join(render_listing(x, lang) for x in apt_rent_new[:10]) or f'<div class="card">{escape(labels_for_lang["no_apt_rent_new"])}</div>', lang))
        parts.append(section(labels_for_lang["apt_sale_top"], "".join(render_listing(x, lang) for x in apt_sale_main[:12]) or f'<div class="card">{escape(labels_for_lang["no_apt_sale_main"])}</div>', lang))
        parts.append(section(labels_for_lang["apt_rent_top"], "".join(render_listing(x, lang) for x in apt_rent_main[:12]) or f'<div class="card">{escape(labels_for_lang["no_apt_rent_main"])}</div>', lang))
        parts.append(section(labels_for_lang["home_sale_top"], "".join(render_listing(x, lang) for x in home_sale_main[:10]) or f'<div class="card">{escape(labels_for_lang["no_home_sale_main"])}</div>', lang))
        parts.append(section(labels_for_lang["home_rent_top"], "".join(render_listing(x, lang) for x in home_rent_main[:10]) or f'<div class="card">{escape(labels_for_lang["no_home_rent_main"])}</div>', lang))
        parts.append(section(labels_for_lang["land_top"], "".join(render_listing(x, lang) for x in land_main[:10]) or f'<div class="card">{escape(labels_for_lang["no_land_main"])}</div>', lang))
        parts.append(section(labels_for_lang["below"], "".join(render_listing(x, lang) for x in below_target[:12]) or f'<div class="card">{escape(labels_for_lang["no_below"])}</div>', lang))
        parts.append(section(labels_for_lang["stretch"], "".join(render_listing(x, lang) for x in stretch[:12]) or f'<div class="card">{escape(labels_for_lang["no_stretch"])}</div>', lang))
        parts.append("</div>")

    html = f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Reality Terminal</title>
  <style>
    body {{ background:#050805; color:#89ff89; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; margin:0; padding:24px; }}
    a {{ color:#a8ffb0; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .wrap {{ max-width:1200px; margin:0 auto; }}
    .head {{ border:1px solid #1f5f1f; padding:16px; margin-bottom:20px; box-shadow:0 0 18px rgba(59,255,59,0.08) inset; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(320px,1fr)); gap:14px; }}
    .card {{ border:1px solid #174717; padding:14px; background:#091109; }}
    .title {{ display:block; font-size:16px; font-weight:700; margin:8px 0; }}
    .meta, .desc, .reasons {{ color:#a4dca4; font-size:13px; line-height:1.45; }}
    .score {{ display:inline-block; padding:4px 8px; border:1px solid #36d936; font-weight:700; }}
    .badge {{ margin-left:8px; padding:4px 8px; border:1px solid #9fff9f; }}
    .new {{ background:#103510; }}
    h1, h2 {{ margin:0 0 12px 0; }}
    .section {{ margin:26px 0; }}
    .small {{ color:#78b878; font-size:12px; }}
    .toolbar {{ margin-top:8px; font-size:13px; }}
    .langblock {{ display:none; }}
    .langblock.active {{ display:block; }}
    @media (max-width: 700px) {{
      body {{ padding: 12px; }}
      .head {{ padding: 12px; }}
      .grid {{ grid-template-columns: 1fr; gap: 10px; }}
      .card {{ padding: 12px; }}
      .title {{ font-size: 15px; }}
      .meta, .desc, .reasons, .small, .toolbar {{ font-size: 12px; }}
    }}
  </style>
  <script>
    function setLang(lang) {{
      localStorage.setItem('pw-lang', lang);
      document.querySelectorAll('.langblock').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.lang-' + lang).forEach(el => el.classList.add('active'));
      document.getElementById('meta1').textContent = document.getElementById('meta1-' + lang).textContent;
      document.getElementById('meta2').textContent = document.getElementById('meta2-' + lang).textContent;
    }}
    window.addEventListener('DOMContentLoaded', () => {{
      const lang = localStorage.getItem('pw-lang') || 'en';
      setLang(lang);
    }});
  </script>
</head>
<body>
<div class='wrap'>
  <div class='head'>
    <h1>{escape(labels['en']['title'])}</h1>
    <div id='meta1' class='small'></div>
    <div id='meta2' class='small'></div>
    <div class='toolbar'>{labels['en']['lang_switch']}</div>
    <div id='meta1-en' style='display:none'>{escape(labels['en']['meta1'])}</div>
    <div id='meta2-en' style='display:none'>{escape(labels['en']['meta2'])}</div>
    <div id='meta1-cs' style='display:none'>{escape(labels['cs']['meta1'])}</div>
    <div id='meta2-cs' style='display:none'>{escape(labels['cs']['meta2'])}</div>
  </div>
  {''.join(parts)}
</div>
</body>
</html>"""
    DASHBOARD_DIR.joinpath("index.html").write_text(html)


def write_summary(
    apartment_sale: list[Listing],
    apartment_rent: list[Listing],
    family_home_sale: list[Listing],
    family_home_rent: list[Listing],
    land_sale: list[Listing],
) -> None:
    groups = {
        "Apartment sale": [x for x in apartment_sale if x.is_new],
        "Apartment rent": [x for x in apartment_rent if x.is_new],
        "Family home sale": [x for x in family_home_sale if x.is_new],
        "Family home rent": [x for x in family_home_rent if x.is_new],
        "Land": [x for x in land_sale if x.is_new],
    }

    lines: list[str] = []
    total_new = sum(len(v) for v in groups.values())
    if total_new == 0:
        lines.append("Nothing new this morning. Dashboard refreshed.")
    else:
        lines.append("New matches found across property watch.")
        for label, items in groups.items():
            if items:
                lines.append(f"{label}: {len(items)} new")
                for item in items[:3]:
                    price = item.monthly_total_czk if item.category == "rent" else item.price_czk
                    lines.append(f"- {item.title} | {fmt_czk(price)} | score {item.score:.1f}")

    (BASE_DIR / "latest-summary.txt").write_text("\n".join(lines))


def main() -> None:
    ensure_dirs()
    apartment_sale = collect_category("sale", "apartment")
    apartment_rent = collect_category("rent", "apartment")
    family_home_sale = collect_category("sale", "family_home")
    family_home_rent = collect_category("rent", "family_home")
    land_sale = collect_category("sale", "land")

    generate_dashboard(apartment_sale, apartment_rent, family_home_sale, family_home_rent, land_sale)
    write_summary(apartment_sale, apartment_rent, family_home_sale, family_home_rent, land_sale)

    print(
        f"Collected apartment_sale={len(apartment_sale)} apartment_rent={len(apartment_rent)} "
        f"family_home_sale={len(family_home_sale)} family_home_rent={len(family_home_rent)} land_sale={len(land_sale)}"
    )
    print(f"Dashboard: {DASHBOARD_DIR / 'index.html'}")
    print(f"Summary: {BASE_DIR / 'latest-summary.txt'}")


if __name__ == "__main__":
    main()
