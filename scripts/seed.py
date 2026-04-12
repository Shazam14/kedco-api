"""
Seed script — run once to populate:
  1. All 26 currencies
  2. First admin user

Usage:
    cd ~/projects/api
    .venv/bin/python scripts/seed.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.currency import Currency, CurrencyCategory
from app.models.user import User, UserRole

CURRENCIES = [
    # code, name, flag, category, decimal_places
    # ── MAIN ──
    ("USD", "US Dollar",          "🇺🇸", CurrencyCategory.MAIN,   4),
    ("JPY", "Japanese Yen",       "🇯🇵", CurrencyCategory.MAIN,   4),
    ("KRW", "Korean Won",         "🇰🇷", CurrencyCategory.MAIN,   4),
    # ── 2ND ──
    ("EUR", "Euro",               "🇪🇺", CurrencyCategory.SECOND, 4),
    ("GBP", "British Pound",      "🇬🇧", CurrencyCategory.SECOND, 4),
    ("SGD", "Singapore Dollar",   "🇸🇬", CurrencyCategory.SECOND, 4),
    ("AUD", "Australian Dollar",  "🇦🇺", CurrencyCategory.SECOND, 4),
    ("HKD", "Hong Kong Dollar",   "🇭🇰", CurrencyCategory.SECOND, 4),
    ("CNY", "Chinese Yuan",       "🇨🇳", CurrencyCategory.SECOND, 4),
    ("MYR", "Malaysian Ringgit",  "🇲🇾", CurrencyCategory.SECOND, 4),
    ("NZD", "New Zealand Dollar", "🇳🇿", CurrencyCategory.SECOND, 4),
    ("TWD", "Taiwan Dollar",      "🇹🇼", CurrencyCategory.SECOND, 4),
    ("THB", "Thai Baht",          "🇹🇭", CurrencyCategory.SECOND, 4),
    # ── OTHERS ──
    ("SAR", "Saudi Riyal",        "🇸🇦", CurrencyCategory.OTHERS, 4),
    ("AED", "UAE Dirham",         "🇦🇪", CurrencyCategory.OTHERS, 4),
    ("QAR", "Qatar Riyal",        "🇶🇦", CurrencyCategory.OTHERS, 4),
    ("KWD", "Kuwaiti Dinar",      "🇰🇼", CurrencyCategory.OTHERS, 4),
    ("BHD", "Bahrain Dinar",      "🇧🇭", CurrencyCategory.OTHERS, 4),
    ("OMR", "Omani Rial",         "🇴🇲", CurrencyCategory.OTHERS, 4),
    ("CHF", "Swiss Franc",        "🇨🇭", CurrencyCategory.OTHERS, 4),
    ("CAD", "Canadian Dollar",    "🇨🇦", CurrencyCategory.OTHERS, 4),
    ("SEK", "Swedish Krona",      "🇸🇪", CurrencyCategory.OTHERS, 4),
    ("NOK", "Norwegian Krone",    "🇳🇴", CurrencyCategory.OTHERS, 4),
    ("DKK", "Danish Krone",       "🇩🇰", CurrencyCategory.OTHERS, 4),
    ("IDR", "Indonesian Rupiah",  "🇮🇩", CurrencyCategory.OTHERS, 4),
    ("VND", "Vietnamese Dong",    "🇻🇳", CurrencyCategory.OTHERS, 4),
    ("BND", "Brunei Dollar",      "🇧🇳", CurrencyCategory.OTHERS, 4),
    ("INR", "Indian Rupee",       "🇮🇳", CurrencyCategory.OTHERS, 4),
    ("JOD", "Jordan Dinar",       "🇯🇴", CurrencyCategory.OTHERS, 4),
]

ADMIN_USER = {
    "username":  "admin",
    "full_name": "Administrator",
    "email":     "admin@kedco.local",
    "password":  "ChangeMe@2026!",
    "role":      UserRole.admin,
    "branch":    None,
}

DEFAULT_PASSWORD = "Kedco@2026!"

STAFF_USERS = (
    # ── Supervisors ──
    [{"username": f"supervisor{i}", "full_name": f"Supervisor {i}",
      "role": UserRole.supervisor, "branch": None}
     for i in range(1, 3)]
    +
    # ── Cashiers (one per branch) ──
    [{"username": f"cashier{i}", "full_name": f"Cashier {i}",
      "role": UserRole.cashier, "branch": f"Branch {i}"}
     for i in range(1, 8)]
    +
    # ── Riders ──
    [{"username": f"rider{i:02d}", "full_name": f"Rider {i:02d}",
      "role": UserRole.rider, "branch": None}
     for i in range(1, 11)]
)


def seed_currencies(db):
    inserted = 0
    skipped = 0
    for code, name, flag, category, dp in CURRENCIES:
        existing = db.query(Currency).filter_by(code=code).first()
        if existing:
            skipped += 1
            continue
        db.add(Currency(
            code=code,
            name=name,
            flag=flag,
            category=category,
            decimal_places=dp,
            is_active="Y",
        ))
        inserted += 1
    db.commit()
    print(f"  Currencies — inserted: {inserted}, skipped (already exist): {skipped}")


def seed_admin(db):
    existing = db.query(User).filter_by(username=ADMIN_USER["username"]).first()
    if existing:
        print(f"  Admin '{ADMIN_USER['username']}' already exists — skipped")
        return
    db.add(User(
        username=ADMIN_USER["username"],
        full_name=ADMIN_USER["full_name"],
        email=ADMIN_USER["email"],
        password_hash=hash_password(ADMIN_USER["password"]),
        role=ADMIN_USER["role"],
        branch=ADMIN_USER["branch"],
        is_active=True,
    ))
    db.commit()
    print(f"  Admin '{ADMIN_USER['username']}' created — password: {ADMIN_USER['password']}")


def seed_staff(db):
    inserted = 0
    skipped  = 0
    for u in STAFF_USERS:
        if db.query(User).filter_by(username=u["username"]).first():
            skipped += 1
            continue
        db.add(User(
            username=u["username"],
            full_name=u["full_name"],
            password_hash=hash_password(DEFAULT_PASSWORD),
            role=u["role"],
            branch=u.get("branch"),
            is_active=True,
        ))
        inserted += 1
    db.commit()
    print(f"  Staff — inserted: {inserted}, skipped: {skipped}")
    if inserted:
        print(f"  Default password for all staff: {DEFAULT_PASSWORD}")


def main():
    print("Seeding database...")
    db = SessionLocal()
    try:
        seed_currencies(db)
        seed_admin(db)
        seed_staff(db)
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
