"""Product attribute extraction for faceted filtering (brand, specs, listing flags).

Listing titles on marketplaces are free text ("MacBook Air M1 8GB 256GB OVP mit
Rechnung"), so specs are pulled out with rules here. Structured data from a
source (e.g. Shopify vendor) and optional AI extraction override these guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AttributeDef:
    name: str
    label: str
    kind: str  # "enum" | "number" | "flag"
    group: str
    unit: str | None = None


ATTRIBUTES: list[AttributeDef] = [
    AttributeDef("category", "Category", "enum", "General"),
    AttributeDef("brand", "Brand", "enum", "General"),
    AttributeDef("model", "Model", "enum", "General"),
    AttributeDef("color", "Colour", "enum", "General"),
    AttributeDef("year", "Model year", "number", "General"),
    AttributeDef("storage_gb", "Storage", "number", "Specs", "GB"),
    AttributeDef("ram_gb", "RAM", "number", "Specs", "GB"),
    AttributeDef("cpu", "Processor", "enum", "Specs"),
    AttributeDef("gpu", "Graphics", "enum", "Specs"),
    AttributeDef("vram_gb", "Graphics memory", "number", "Specs", "GB"),
    AttributeDef("screen_in", "Screen size", "number", "Specs", "″"),
    AttributeDef("resolution", "Resolution", "enum", "Specs"),
    AttributeDef("refresh_hz", "Refresh rate", "number", "Specs", "Hz"),
    AttributeDef("megapixels", "Camera resolution", "number", "Specs", "MP"),
    AttributeDef("original_box", "Original box", "flag", "Listing details"),
    AttributeDef("warranty", "Warranty", "flag", "Listing details"),
    AttributeDef("invoice", "Invoice / receipt", "flag", "Listing details"),
    AttributeDef("defective", "Defective / for parts", "flag", "Listing details"),
]
ATTRIBUTE_BY_NAME = {a.name: a for a in ATTRIBUTES}


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


# --------------------------------------------------------------------- brands
_BRANDS = [
    "Apple", "Samsung", "Lenovo", "Dell", "HP", "Asus", "Acer", "MSI", "Sony", "Nintendo", "Microsoft",
    "Canon", "Nikon", "Fujifilm", "Panasonic", "Olympus", "Leica", "LG", "Xiaomi", "Google", "OnePlus",
    "Huawei", "Honor", "Oppo", "Motorola", "Nokia", "Fairphone", "Bose", "JBL", "Sennheiser", "Beyerdynamic",
    "Philips", "Bosch", "Siemens", "Miele", "Dyson", "DJI", "GoPro", "Garmin", "Logitech", "Razer",
    "Corsair", "SteelSeries", "AMD", "Intel", "Nvidia", "Gigabyte", "Zotac", "Palit", "Sapphire",
    "Western Digital", "Seagate", "Crucial", "Kingston", "Toshiba", "Synology", "QNAP", "AVM", "TP-Link",
    "Netgear", "Sonos", "Teufel", "Bang & Olufsen", "Marshall", "Nothing", "Framework", "Valve",
    "Raspberry Pi", "Tefal", "De'Longhi", "Jura", "Sage", "Braun", "Oral-B", "Brother", "Epson",
    "Specialized", "Trek", "Canyon", "Cube", "Brompton", "Shimano", "Lego", "Tamron", "Sigma",
]
_SERIES = {
    "Apple": r"iphone|ipad|macbook|imac|mac\s?mini|mac\s?studio|airpods|apple\s?watch|homepod",
    "Lenovo": r"thinkpad|ideapad|ideatab|thinkcentre|legion|yoga",
    "Samsung": r"galaxy",
    "Google": r"pixel",
    "Sony": r"playstation|ps[345]\b|alpha\s?a?\d|walkman|wh-1000",
    "Microsoft": r"xbox|surface",
    "Nintendo": r"switch\s?(?:oled|lite)|game\s?boy|wii",
    "Asus": r"zenbook|vivobook|\brog\b",
    "Dell": r"\bxps\b|latitude|inspiron|alienware|precision",
    "HP": r"elitebook|probook|pavilion|omen|zbook",
    "Acer": r"aspire|predator",
    "Nvidia": r"geforce|founders\s?edition",
    "Western Digital": r"\bwd\b",
    "Valve": r"steam\s?deck",
}
_BRAND_RULES = (
    [(_rx(rf"(?<![\w-]){re.escape(b)}(?![\w-])"), b, 0) for b in _BRANDS]
    + [(_rx(pat), brand, 1) for brand, pat in _SERIES.items()]
)

# ----------------------------------------------------------------- categories
_CATEGORIES = [  # first match wins, so specific/compound kinds come first
    ("Laptops", r"laptop|notebook|macbook|thinkpad|chromebook|ultrabook|zenbook|vivobook|ideapad|elitebook|"
                r"\bxps\b|latitude|probook"),
    ("Tablets", r"tablet|ipad|ideatab|galaxy\s?tab|surface\s?pro"),
    ("Smartphones", r"smartphone|handy|iphone|galaxy\s?[sazm]\d|pixel\s?\d|oneplus\s?\d|fairphone"),
    ("Smartwatches", r"smartwatch|apple\s?watch|galaxy\s?watch|fitness\s?tracker|forerunner|fenix"),
    ("Headphones", r"kopfhörer|headphones?|headset|earbuds|in-ear|airpods|wh-1000"),
    ("Consoles", r"konsole|console|playstation|ps5|ps4|xbox|nintendo\s?switch|steam\s?deck"),
    ("Graphics cards", r"grafikkarte|graphics\s?card|\bgpu\b"),
    ("Desktop PCs", r"gaming\s?pc|desktop|\bpc\b|mini\s?pc|mac\s?mini|imac"),
    ("Graphics cards", r"rtx\s?\d{4}|gtx\s?\d{3,4}|radeon|\brx\s?\d{4}"),
    ("Processors", r"prozessor|processor|\bcpu\b"),
    ("Monitors", r"monitor|bildschirm|display\b"),
    ("TVs", r"\btv\b|fernseher|television|oled\s?\d{2}|qled"),
    ("Cameras", r"kamera|camera|dslr|dslm|systemkamera|spiegelreflex|eos\s|alpha\s?a?\d|gopro"),
    ("Lenses", r"objektiv|\blens\b|\d{2,3}\s?-\s?\d{2,3}\s?mm|\d{2,3}\s?mm\s?f\/?\d"),
    ("Drones", r"drohne|drone|dji\s?(?:mini|air|mavic)"),
    ("Storage", r"\bssd\b|\bhdd\b|festplatte|hard\s?drive|nvme|usb-?stick|speicherkarte|sd-?karte|\bnas\b"),
    ("Memory", r"arbeitsspeicher|\bram\b.*\bddr|\bddr[345]\b"),
    ("Audio", r"lautsprecher|speaker|soundbar|verstärker|amplifier|plattenspieler|turntable"),
    ("Bikes", r"fahrrad|e-?bike|pedelec|mountainbike|rennrad|gravel|\bbike\b"),
    ("Kitchen", r"kaffeevollautomat|espresso|kaffeemaschine|coffee|thermomix|mixer|airfryer|heißluftfritteuse"),
    ("Toys", r"\blego\b|spielzeug|\btoy\b"),
]
_CATEGORY_RULES = [(_rx(p), c) for c, p in _CATEGORIES]

# --------------------------------------------------------------------- colours
_COLORS = {
    "Black": r"schwarz|black|midnight|mitternacht|onyx",
    "White": r"weiß|weiss|white|polarstern|starlight",
    "Silver": r"silber|silver",
    "Gray": r"grau|gr[ae]y|graphit|titan(?:ium)?\b",
    "Gold": r"\bgold\b|roségold|rose\s?gold",
    "Blue": r"\bblau|\bblue|navy",
    "Red": r"\brot\b|\bred\b|product\s?red",
    "Green": r"\bgrün|\bgreen|mint",
    "Pink": r"\bpink\b|\brosa\b",
    "Purple": r"\blila\b|violett|purple|lavendel|lavender",
    "Yellow": r"\bgelb|yellow",
    "Orange": r"\borange\b",
    "Beige": r"\bbeige\b|creme|cream",
    "Brown": r"\bbraun\b|brown",
}
_COLOR_RULES = [(_rx(p), c) for c, p in _COLORS.items()]

# ------------------------------------------------------------------------ specs
_CPU_RULES = [
    (_rx(r"core\s?ultra\s?([579])\b"), "Intel Core Ultra {0}"),
    (_rx(r"\bi([3579])(?:[\s-]?\d{3,5}[a-z0-9]{0,4})?\b"), "Intel Core i{0}"),
    (_rx(r"\bryzen\s?(?:ai\s?)?([3579])\b"), "AMD Ryzen {0}"),
    (_rx(r"\b(celeron|pentium|xeon)\b"), "Intel {0}"),
    (_rx(r"\b(athlon|threadripper)\b"), "AMD {0}"),
    (_rx(r"snapdragon\s?(x\s?(?:elite|plus)|8\s?(?:\+\s?)?gen\s?\d|\d{3})?"), "Qualcomm Snapdragon {0}"),
]
_APPLE_CHIP = _rx(r"\bm([1-5])(?:\s?(pro|max|ultra))?\b")
_GPU_RULES = [
    (_rx(r"\b(rtx|gtx)\s?(\d{3,4})\s?(ti\s?super|ti|super)?\b"), "NVIDIA"),
    (_rx(r"\b(?:radeon\s?)?(rx)\s?(\d{3,4})\s?(xtx|xt|gre)?\b"), "AMD"),
    (_rx(r"\b(arc)\s?([ab]\d{3})\b"), "Intel"),
]
_SIZE = _rx(r"(\d+(?:[.,]\d+)?)\s?(tb|gb)\b")
_RAM_STORAGE_PAIR = _rx(r"\b(\d{1,2})\s?(?:gb)?\s?/\s?(\d{2,4})\s?(gb|tb)\b")
_RAM_CTX = _rx(r"\bram\b|ddr\d|lpddr|arbeitsspeicher|memory|\bmem\b")
_VRAM_CTX = _rx(r"gddr\d|vram")
_STORAGE_CTX = _rx(r"ssd|hdd|nvme|emmc|festplatte|storage|speicher|\brom\b|flash|m\.2")
_SCREEN = _rx(r"(\d{1,3}(?:[.,]\d{1,2})?)\s?(?:\"|″|”|''|zoll\b|-?inch\b|in\b|-zoll\b)")
_REFRESH = _rx(r"\b(\d{2,3})\s?hz\b")
_MEGAPIXEL = _rx(r"\b(\d{1,3}(?:[.,]\d)?)\s?(?:mp|mpx|megapixel)\b")
_YEAR = _rx(r"\b(19[89]\d|20[0-4]\d)\b")
_RESOLUTIONS = [
    (_rx(r"\b8k\b|4320p"), "8K"),
    (_rx(r"\b4k\b|\buhd\b|2160p|3840\s?x\s?2160"), "4K UHD"),
    (_rx(r"\bwqhd\b|\bqhd\b|1440p|2560\s?x\s?1440"), "QHD 1440p"),
    (_rx(r"full\s?hd|\bfhd\b|1080p|1920\s?x\s?1080"), "Full HD 1080p"),
    (_rx(r"hd\s?ready|\b720p\b"), "HD 720p"),
]
_NEGATION = _rx(r"(?:kein\w*|ohne|nicht|no|not|without|w/o)\s+(?:\w+\s+)?$")
_FLAGS = {
    "original_box": _rx(r"\bovp\b|originalverpack|original\s?verpackung|originalkarton|with\s+box|in\s+box|\bboxed\b|"
                        r"\bsealed\b|versiegelt|\bnib\b|\bbnib\b"),
    "warranty": _rx(r"garantie|warranty|gewährleistung|applecare"),
    "invoice": _rx(r"rechnung|invoice|receipt|quittung|kaufbeleg"),
    "defective": _rx(r"defekt|for\s+parts|not\s+working|\bbroken\b|kaputt|bastler|ersatzteil|spares\s+or\s+repair"),
}


# Colour words in these categories are usually product line names ("WD Red", "Samsung EVO").
_COLORLESS = {"Storage", "Memory", "Processors", "Graphics cards"}


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def fmt_number(value: float) -> str:
    return f"{value:g}"


def _find_brand(text: str) -> str | None:
    best: tuple[int, int, str] | None = None
    for pattern, brand, priority in _BRAND_RULES:
        m = pattern.search(text)
        if m and (best is None or (priority, m.start()) < best[:2]):
            best = (priority, m.start(), brand)
    return best[2] if best else None


def _flag_present(pattern: re.Pattern[str], text: str) -> bool:
    for m in pattern.finditer(text):
        if not _NEGATION.search(text[max(0, m.start() - 25):m.start()]):
            return True
    return False


def _sizes(text: str, attrs: dict[str, float]) -> None:
    pair = _RAM_STORAGE_PAIR.search(text)
    if pair:
        attrs["ram_gb"] = float(pair.group(1))
        attrs["storage_gb"] = _num(pair.group(2)) * (1000 if pair.group(3).lower() == "tb" else 1)
        return
    unlabeled: list[float] = []
    for m in _SIZE.finditer(text):
        gb = _num(m.group(1)) * (1000 if m.group(2).lower() == "tb" else 1)
        # Context words belong to the nearest size token: look up to the next/previous number only,
        # and prefer the word after the size ("512GB SSD") over the one before it ("RAM 16GB").
        after = re.split(r"\d", text[m.end():m.end() + 14])[0]
        before = re.split(r"\d", text[max(0, m.start() - 14):m.start()])[-1]
        for ctx in (after, before):
            if _VRAM_CTX.search(ctx):
                attrs.setdefault("vram_gb", gb)
            elif _RAM_CTX.search(ctx):
                attrs.setdefault("ram_gb", gb)
            elif _STORAGE_CTX.search(ctx):
                attrs.setdefault("storage_gb", gb)
            else:
                continue
            break
        else:
            unlabeled.append(gb)
    if not unlabeled:
        return
    unlabeled.sort()
    if "storage_gb" not in attrs and unlabeled[-1] >= 16:
        attrs["storage_gb"] = unlabeled.pop()
    if "ram_gb" not in attrs and unlabeled and "storage_gb" in attrs and unlabeled[-1] <= 64:
        attrs["ram_gb"] = unlabeled.pop()


def extract_attributes(title: str, description: str | None = None) -> dict[str, str]:
    """Rule-based attribute extraction. Returns {name: value} with numbers as plain strings."""
    text = f"{title} {description or ''}".strip()
    out: dict[str, str] = {}

    if brand := _find_brand(title) or _find_brand(text):
        out["brand"] = brand
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(title):
            out["category"] = category
            break
    for pattern, color in _COLOR_RULES:
        if out.get("category") in _COLORLESS:
            break
        if pattern.search(title):
            out["color"] = color
            break

    for pattern, template in _CPU_RULES:
        if m := pattern.search(text):
            groups = [g for g in m.groups() if g]
            out["cpu"] = template.format(*(g.title() if g.isalpha() else g for g in groups) or [""]).strip()
            break
    if "cpu" not in out and out.get("brand") == "Apple" and (m := _APPLE_CHIP.search(text)):
        out["cpu"] = f"Apple M{m.group(1)}" + (f" {m.group(2).title()}" if m.group(2) else "")

    for pattern, vendor in _GPU_RULES:
        if m := pattern.search(text):
            series, number, suffix = m.group(1).upper(), m.group(2).upper(), (m.group(3) or "").upper()
            suffix = suffix.replace("TI SUPER", "Ti SUPER").replace("TI", "Ti")
            out["gpu"] = f"{vendor} {series} {number} {suffix}".strip()
            break

    sizes: dict[str, float] = {}
    _sizes(text, sizes)
    if out.get("category") == "Graphics cards" and "vram_gb" not in sizes and "storage_gb" in sizes \
            and sizes["storage_gb"] <= 24:
        sizes["vram_gb"] = sizes.pop("storage_gb")
    out.update({k: fmt_number(v) for k, v in sizes.items()})

    for m in _SCREEN.finditer(text):
        size = _num(m.group(1))
        if 4 <= size <= 110 and size not in (2.5, 3.5):
            out["screen_in"] = fmt_number(size)
            break
    if m := _REFRESH.search(text):
        if 50 <= int(m.group(1)) <= 600:
            out["refresh_hz"] = m.group(1)
    if m := _MEGAPIXEL.search(text):
        out["megapixels"] = fmt_number(_num(m.group(1)))
    for pattern, label in _RESOLUTIONS:
        if pattern.search(text):
            out["resolution"] = label
            break
    if m := _YEAR.search(title):
        if int(m.group(1)) <= date.today().year + 1:
            out["year"] = m.group(1)

    for name, pattern in _FLAGS.items():
        if _flag_present(pattern, text):
            out[name] = "yes"
    return out


def numeric_value(name: str, value: str) -> float | None:
    definition = ATTRIBUTE_BY_NAME.get(name)
    if definition is None or definition.kind != "number":
        return None
    try:
        return _num(str(value).split()[0])
    except (ValueError, IndexError):
        return None
