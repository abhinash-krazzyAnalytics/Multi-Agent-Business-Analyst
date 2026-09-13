"""
Generates a small sample business SQLite database so the multi-agent
analyst has something real to query out of the box.

Tables:
    sales(id, sale_date, region, category, product, amount, quantity)
    products(product, category, unit_cost)
    regions(region, country)

Run directly to (re)build database/business.db:
    python database/create_sample_db.py
"""

import sqlite3
import random
import os
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "business.db")

REGIONS = [
    ("North America", "USA"),
    ("Europe", "Germany"),
    ("Asia Pacific", "Japan"),
    ("Latin America", "Brazil"),
]

CATEGORIES = {
    "Electronics": ["Wireless Headphones", "Smart Speaker", "Laptop Stand", "USB-C Hub"],
    "Clothing": ["Cotton T-Shirt", "Denim Jacket", "Running Shoes", "Wool Sweater"],
    "Home & Kitchen": ["Coffee Maker", "Blender", "Cutting Board Set", "Air Fryer"],
    "Sporting Goods": ["Yoga Mat", "Dumbbell Set", "Cycling Helmet", "Tennis Racket"],
}

UNIT_COST_RANGE = (8, 220)


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE regions (
            region TEXT PRIMARY KEY,
            country TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE products (
            product TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            unit_cost REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date TEXT NOT NULL,
            region TEXT NOT NULL,
            category TEXT NOT NULL,
            product TEXT NOT NULL,
            amount REAL NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (region) REFERENCES regions(region),
            FOREIGN KEY (product) REFERENCES products(product)
        )
    """)

    cur.executemany("INSERT INTO regions VALUES (?, ?)", REGIONS)

    random.seed(42)

    product_rows = []
    for category, products in CATEGORIES.items():
        for product in products:
            unit_cost = round(random.uniform(*UNIT_COST_RANGE), 2)
            product_rows.append((product, category, unit_cost))
    cur.executemany("INSERT INTO products VALUES (?, ?, ?)", product_rows)

    # Generate ~2 years of daily sales (2024-01-01 through 2025-12-31)
    start = date(2024, 1, 1)
    end = date(2025, 12, 31)
    day = start

    sales_rows = []
    region_names = [r[0] for r in REGIONS]

    while day <= end:
        # Seasonal + weekly + yearly-growth multiplier so trends are visible
        month_factor = 1.0 + 0.35 * math_sin_month(day.month)
        weekday_factor = 1.15 if day.weekday() >= 5 else 1.0
        year_growth = 1.0 if day.year == 2024 else 1.18

        n_transactions = int(random.randint(6, 14) * month_factor * weekday_factor * year_growth)

        for _ in range(max(1, n_transactions)):
            category = random.choice(list(CATEGORIES.keys()))
            product = random.choice(CATEGORIES[category])
            region = random.choice(region_names)
            quantity = random.randint(1, 6)
            base_price = next(p[2] for p in product_rows if p[0] == product) * random.uniform(1.4, 2.2)
            amount = round(base_price * quantity, 2)

            sales_rows.append((day.isoformat(), region, category, product, amount, quantity))

        day += timedelta(days=1)

    cur.executemany(
        "INSERT INTO sales (sale_date, region, category, product, amount, quantity) VALUES (?, ?, ?, ?, ?, ?)",
        sales_rows,
    )

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM sales")
    count = cur.fetchone()[0]
    conn.close()

    print(f"Built {DB_PATH} with {count} sales rows.")


def math_sin_month(month: int) -> float:
    import math
    # Peak sales in Nov/Dec (holiday season), trough in Feb
    return math.sin((month - 2) / 12 * 2 * math.pi)


if __name__ == "__main__":
    build_database()