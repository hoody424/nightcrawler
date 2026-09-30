import pytest

from nightcrawler.attributes import extract_attributes, numeric_value


@pytest.mark.parametrize("title,expected", [
    ("Apple MacBook Air M1 8GB 256GB Space Grau OVP mit Rechnung",
     {"brand": "Apple", "category": "Laptops", "cpu": "Apple M1", "ram_gb": "8", "storage_gb": "256",
      "color": "Gray", "original_box": "yes", "invoice": "yes"}),
    ('Lenovo ThinkPad T14 Gen 2 i5-1135G7 16GB RAM 512GB SSD 14" Full HD',
     {"brand": "Lenovo", "cpu": "Intel Core i5", "ram_gb": "16", "storage_gb": "512", "screen_in": "14",
      "resolution": "Full HD 1080p"}),
    ("MSI GeForce RTX 4070 Ti SUPER 16GB GDDR6X Grafikkarte",
     {"brand": "MSI", "category": "Graphics cards", "gpu": "NVIDIA RTX 4070 Ti SUPER", "vram_gb": "16"}),
    ("Gaming PC Ryzen 7 5800X RTX 3080 32GB 1TB NVMe",
     {"category": "Desktop PCs", "cpu": "AMD Ryzen 7", "storage_gb": "1000", "ram_gb": "32"}),
    ("Samsung Odyssey G7 27 Zoll QHD 240Hz Monitor defekt",
     {"screen_in": "27", "refresh_hz": "240", "resolution": "QHD 1440p", "defective": "yes"}),
    ("WD Red 4TB NAS Festplatte", {"brand": "Western Digital", "storage_gb": "4000"}),
])
def test_extract(title, expected):
    attrs = extract_attributes(title)
    for key, value in expected.items():
        assert attrs.get(key) == value, (key, attrs)


def test_negated_flags_are_ignored():
    attrs = extract_attributes("iPhone 13 128GB keine Garantie, nicht defekt, ohne OVP")
    assert "warranty" not in attrs and "defective" not in attrs and "original_box" not in attrs


def test_colour_skipped_for_storage_products():
    assert "color" not in extract_attributes("WD Red 4TB NAS Festplatte")


def test_numeric_value():
    assert numeric_value("storage_gb", "512") == 512
    assert numeric_value("brand", "Apple") is None
