import argparse
import re
import time

import pandas as pd
import requests

GOOGLE_API_KEY = "ЗАГЛУШКА"
BREVO_API_KEY = "ЗАГЛУШКА"
SENDER_EMAIL = "ЗАГЛУШКА"
SENDER_NAME = "ЗАГЛУШКА"

XLSX = "leads.xlsx"
SUBJECT = "Пропозиція для {name}"
HTML = "<p>Добрий день!</p><p>Пишу до <b>{name}</b> з короткою пропозицією.</p><p>З повагою,<br>{sender}</p>"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def search_places(query, limit=40):
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.websiteUri,"
            "places.nationalPhoneNumber,places.rating,places.googleMapsUri,"
            "nextPageToken"
        ),
    }
    rows, token = [], None
    while len(rows) < limit:
        body = {"textQuery": query, "pageSize": 20}
        if token:
            body["pageToken"] = token
        r = requests.post(url, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for p in data.get("places", []):
            rows.append({
                "name": p.get("displayName", {}).get("text"),
                "address": p.get("formattedAddress"),
                "phone": p.get("nationalPhoneNumber"),
                "website": p.get("websiteUri"),
                "rating": p.get("rating"),
                "maps_url": p.get("googleMapsUri"),
            })
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(2)
    return rows[:limit]


def find_email(website):
    if not website:
        return None
    base = website.rstrip("/")
    for path in ("", "/contact", "/contacts"):
        try:
            html = requests.get(base + path, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"}).text
        except requests.RequestException:
            continue
        found = [e for e in EMAIL_RE.findall(html)
                 if not e.lower().endswith((".png", ".jpg", ".webp", ".gif"))]
        if found:
            return found[0].lower()
    return None


def cmd_search(args):
    rows = search_places(args.query, args.limit)
    for row in rows:
        row["email"] = find_email(row["website"])
        row["status"] = ""
    pd.DataFrame(rows).to_excel(XLSX, index=False)
    print(f"Saved {len(rows)} rows to {XLSX}")


def send_brevo(to_email, to_name, subject, html):
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "content-type": "application/json"},
        json={
            "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html,
        },
        timeout=30,
    )
    return r.status_code in (200, 201), r.text


def cmd_send(args):
    df = pd.read_excel(XLSX)
    for i, row in df.iterrows():
        email = row.get("email")
        if pd.isna(email) or row.get("status") == "sent":
            continue
        name = row["name"]
        if args.dry_run:
            print(f"[dry run] {email} ({name})")
            continue
        ok, resp = send_brevo(
            email, name,
            SUBJECT.format(name=name),
            HTML.format(name=name, sender=SENDER_NAME),
        )
        df.at[i, "status"] = "sent" if ok else f"error: {resp[:80]}"
        print("OK" if ok else "FAIL", email)
        time.sleep(1)
    if not args.dry_run:
        df.to_excel(XLSX, index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(func=cmd_search)
    m = sub.add_parser("send")
    m.add_argument("--dry-run", action="store_true")
    m.set_defaults(func=cmd_send)
    a = ap.parse_args()
    a.func(a)
