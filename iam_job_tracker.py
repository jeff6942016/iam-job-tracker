#!/usr/bin/env python3
"""
IAM Job Posting Tracker
------------------------
Queries the Adzuna API for IAM-related job postings, scans each posting's
text for certifications, platforms, and protocols you care about, and writes
a frequency report (text + CSV) showing which terms recur most often.

Purpose: personal job-search research. Run it weekly to see which certs and
platforms keep appearing in the IAM roles you want, so you can prioritise
(e.g. confirm SC-300 vs. picking up Okta / SailPoint).

Setup:
  1. Register at https://developer.adzuna.com to get an app_id and app_key.
  2. Put them in the CONFIG section below (or set them as environment
     variables ADZUNA_APP_ID and ADZUNA_APP_KEY).
  3. pip install requests
  4. python iam_job_tracker.py
"""

import os
import csv
import re
import sys
import time
from collections import defaultdict
from datetime import date

import requests

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# Prefer environment variables; fall back to hard-coded strings.
APP_ID  = os.environ.get("ADZUNA_APP_ID",  "YOUR_APP_ID_HERE")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "YOUR_APP_KEY_HERE")

COUNTRY = "ca"                 # Canada. Change if needed (gb, us, ...).
RESULTS_PER_PAGE = 50          # Max Adzuna allows per page.
PAGES_PER_TERM = 1             # 1 page (50 results) per term is plenty weekly.
WHERE = "Toronto"              # Location filter; "" for country-wide.

# The searches you run. Each is one API call per page.
SEARCH_TERMS = [
    "IAM analyst",
    "identity and access management",
    "access management analyst",
    "identity analyst",
    "user access management",
]

# Terms to count. Keep them lowercase; matching is case-insensitive.
# Short/ambiguous terms (sso, pam, ping) use word-boundary matching so they
# don't match inside other words.
KEYWORDS = {
    "Certifications": [
        "security+", "sc-300", "sc-900", "az-500", "cissp", "cism",
        "cyberark certified", "okta certified", "sailpoint certified",
    ],
    "Platforms": [
        "okta", "sailpoint", "saviynt", "cyberark", "ping identity",
        "entra", "azure ad", "active directory", "oracle access manager",
        "oud", "forgerock", "microsoft entra",
    ],
    "Protocols & Concepts": [
        "saml", "oidc", "openid connect", "oauth", "sso", "mfa", "rbac",
        "pam", "ldap", "scim", "zero trust", "federation",
        "least privilege", "provisioning", "deprovisioning",
        "joiner", "mover", "leaver", "lifecycle",
    ],
    "Experience Signals": [
        "1 year", "2 years", "3 years", "4 years", "5 years",
    ],
}

# Terms that need whole-word matching to avoid false positives.
WORD_BOUNDARY_TERMS = {"sso", "pam", "mfa", "rbac", "ldap", "scim", "oidc",
                       "oud", "oauth", "saml"}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------
# FETCH
# ----------------------------------------------------------------------

def fetch_postings(term, page=1):
    """Return a list of posting dicts for one search term / page."""
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{COUNTRY}/search/{page}"
    )
    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": term,
        "results_per_page": RESULTS_PER_PAGE,
        "content-type": "application/json",
    }
    if WHERE:
        params["where"] = WHERE

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! request failed for '{term}' (page {page}): {e}")
        return []

    data = resp.json()
    return data.get("results", [])


def gather_all():
    """Query every term, dedupe by posting id, return list of postings."""
    seen_ids = set()
    postings = []
    for term in SEARCH_TERMS:
        print(f"Searching: {term}")
        for page in range(1, PAGES_PER_TERM + 1):
            results = fetch_postings(term, page)
            for job in results:
                jid = job.get("id")
                if jid and jid not in seen_ids:
                    seen_ids.add(jid)
                    postings.append(job)
            time.sleep(1)   # be polite; avoid hammering the API
    print(f"\nCollected {len(postings)} unique postings.\n")
    return postings


# ----------------------------------------------------------------------
# ANALYSE
# ----------------------------------------------------------------------

def term_in_text(term, text):
    """True if term appears in text. Whole-word match for ambiguous terms."""
    if term in WORD_BOUNDARY_TERMS:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def analyse(postings):
    """
    Count, per keyword, how many postings mention it (once per posting).
    Returns {category: {term: count}}.
    """
    counts = {cat: defaultdict(int) for cat in KEYWORDS}

    for job in postings:
        # Combine title + description; description is a truncated excerpt.
        text = (job.get("title", "") + " " +
                job.get("description", "")).lower()
        for cat, terms in KEYWORDS.items():
            for term in terms:
                if term_in_text(term, text):
                    counts[cat][term] += 1
    return counts


# ----------------------------------------------------------------------
# REPORT
# ----------------------------------------------------------------------

def write_text_report(counts, total, postings):
    stamp = date.today().isoformat()
    path = os.path.join(OUTPUT_DIR, f"iam_report_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"IAM JOB POSTING REPORT  -  {stamp}\n")
        f.write(f"Postings analysed: {total}\n")
        f.write("=" * 55 + "\n\n")

        for cat, term_counts in counts.items():
            f.write(f"{cat.upper()}\n")
            f.write("-" * len(cat) + "\n")
            ranked = sorted(term_counts.items(),
                            key=lambda kv: kv[1], reverse=True)
            for term, cnt in ranked:
                if cnt == 0:
                    continue
                pct = (cnt / total * 100) if total else 0
                f.write(f"  {term:<22} {cnt:>3} / {total}  ({pct:4.0f}%)\n")
            f.write("\n")

        f.write("=" * 55 + "\n")
        f.write("MATCHED POSTINGS\n\n")
        for job in postings:
            title = job.get("title", "n/a")
            company = job.get("company", {}).get("display_name", "n/a")
            link = job.get("redirect_url", "")
            f.write(f"  - {title} | {company}\n    {link}\n")
    print(f"Text report written: {path}")
    return path


def write_csv_report(counts, total):
    stamp = date.today().isoformat()
    path = os.path.join(OUTPUT_DIR, f"iam_report_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "term", "count", "total_postings",
                         "percent"])
        for cat, term_counts in counts.items():
            ranked = sorted(term_counts.items(),
                            key=lambda kv: kv[1], reverse=True)
            for term, cnt in ranked:
                pct = round((cnt / total * 100), 1) if total else 0
                writer.writerow([cat, term, cnt, total, pct])
    print(f"CSV report written:  {path}")
    return path


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    if "YOUR_APP_ID_HERE" in APP_ID or "YOUR_APP_KEY_HERE" in APP_KEY:
        print("ERROR: set your Adzuna APP_ID and APP_KEY first "
              "(in the CONFIG section or as environment variables).")
        sys.exit(1)

    postings = gather_all()
    if not postings:
        print("No postings returned. Check your credentials, search terms, "
              "or location.")
        return

    counts = analyse(postings)
    total = len(postings)
    write_text_report(counts, total, postings)
    write_csv_report(counts, total)
    print("\nDone. Open the report to see which terms recur most.")


if __name__ == "__main__":
    main()
