#!/usr/bin/env python3
"""
IAM Job Posting Tracker  (v2)
-----------------------------
Queries the Adzuna API for IAM-related job postings, scans each posting for
certifications, platforms, and protocols you care about, and writes a
frequency report (text + CSV). v2 adds: expanded keyword lists with common
spelling variants, a relevance filter to drop non-IAM noise, per-role-type
tagging, an optional full-text fetch from each posting's link (to get past
Adzuna's truncated excerpts), and a running trend file that merges every run.

Purpose: personal job-search research. Run it weekly to see which certs and
platforms recur in the IAM roles you want.

Setup:
  1. Register at https://developer.adzuna.com for an app_id and app_key.
  2. Put them in CONFIG below or set env vars ADZUNA_APP_ID / ADZUNA_APP_KEY.
  3. pip install requests
  4. python iam_job_tracker.py
"""

import os
import csv
import re
import sys
import json
import time
from collections import defaultdict
from datetime import date

import requests

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

APP_ID  = os.environ.get("e9daaa57",  "e9daaa57")
APP_KEY = os.environ.get("4fba93534ef85a142efbf6ba7386b05b", "4fba93534ef85a142efbf6ba7386b05b")

COUNTRY = "ca"
RESULTS_PER_PAGE = 50
PAGES_PER_TERM = 1
WHERE = ""          # "" for country-wide

# Try to fetch the full posting text from each job's redirect_url.
# This gets past Adzuna's truncated excerpts, but is slower and some sites
# block it, so failures are expected and skipped silently. Set False to
# rely on Adzuna's excerpt only (fast, but thin data).
FETCH_FULL_TEXT = True
FETCH_TIMEOUT = 12         # seconds per full-text fetch
FETCH_MAX = 60             # cap how many full fetches per run (politeness/time)

# A posting must contain at least this many core-identity terms to be counted
# as a genuine IAM role (filters out generic "analyst" noise).
RELEVANCE_MIN_CORE_HITS = 1

# Searches to run. The key is the role-type label used for per-type tagging.
SEARCH_TERMS = {
    "analyst": [
        "IAM analyst",
        "identity and access management analyst",
        "access management analyst",
        "identity analyst",
        "IAM security analyst",
        "access governance analyst",
        "user access analyst",
        "identity security analyst",
    ],
    "engineer": [
        "IAM engineer",
        "identity engineer",
        "identity and access management engineer",
        "IAM security engineer",
        "IAM systems engineer",
        "IAM automation engineer",
        "directory services engineer",
        "access management engineer",
    ],
    "consultant": [
        "IAM consultant",
        "identity access management consultant",
        "identity and access management consultant",
        "IAM implementation consultant",
        "IAM security consultant",
        "identity governance consultant",
    ],
    "admin": [
        "identity administrator",
        "user access administrator",
        "IAM administrator",
        "IAM admin",
        "identity and access management administrator",
        "access control administrator",
        "directory administrator",
    ],

    # New essential categories
    "architect": [
        "IAM architect",
        "identity architect",
        "identity and access management architect",
        "enterprise IAM architect",
        "IAM solution architect",
        "identity security architect",
    ],
    "developer": [
        "IAM developer",
        "identity developer",
        "identity and access management developer",
        "IAM integration developer",
        "IAM software engineer",
    ],
    "specialist": [
        "IAM specialist",
        "identity specialist",
        "identity and access management specialist",
        "access management specialist",
        "access control specialist",
    ],
    "manager_lead": [
        "IAM manager",
        "identity and access management manager",
        "IAM lead",
        "IAM team lead",
        "identity governance manager",
        "head of IAM",
    ],

    # Niche / Sub-domain categories (PAM & IGA)
    "pam": [
        "PAM engineer",
        "PAM analyst",
        "PAM administrator",
        "privileged access management engineer",
        "privileged access management analyst",
        "privileged access management specialist",
    ],
    "iga": [
        "IGA engineer",
        "IGA analyst",
        "identity governance engineer",
        "identity governance analyst",
        "identity governance specialist",
    ],

    # Optional: Popular Tool/Vendor-Specific Search Terms
    "vendor_specific": [
        "SailPoint engineer",
        "SailPoint developer",
        "Okta engineer",
        "Okta administrator",
        "CyberArk engineer",
        "CyberArk administrator",
        "Ping Identity engineer",
        "ForgeRock developer",
        "Microsoft Entra engineer",
        "Azure AD administrator",
    ]
}


# Core identity terms used ONLY for the relevance filter.
CORE_IDENTITY_TERMS = [
    "identity", "access management", "iam", "active directory", "entra",
    "provisioning", "sso", "rbac", "okta", "sailpoint", "directory",
    "authentication", "least privilege", "lifecycle",
]

# Terms to count, with variants folded in. Keep lowercase.
KEYWORDS = {
    "Certifications": [
        "security+", "security +", "comptia security", "sc-300", "sc 300",
        "identity and access administrator", "sc-900", "sc 900",
        "az-500", "az 500", "cissp", "cism", "cisa", "okta certified",
        "sailpoint certified", "cyberark certified",
    ],
    "Platforms": [
        "okta", "sailpoint", "saviynt", "cyberark", "ping identity", "ping",
        "entra", "microsoft entra", "azure ad", "active directory",
        "oracle access manager", "oud", "forgerock", "beyondtrust",
    ],
    "Protocols & Concepts": [
        "saml", "oidc", "openid connect", "oauth", "sso", "single sign-on",
        "mfa", "multi-factor", "rbac", "role-based access", "pam",
        "privileged access", "ldap", "scim", "zero trust", "federation",
        "least privilege", "provisioning", "deprovisioning", "iga",
        "identity governance", "joiner", "mover", "leaver", "lifecycle",
        "conditional access", "pim", "just-in-time", "directory services",
    ],
    "Experience Signals": [
        "1 year", "2 years", "3 years", "4 years", "5 years",
        "6 years", "7 years",
    ],
}

WORD_BOUNDARY_TERMS = {"sso", "pam", "mfa", "rbac", "ldap", "scim", "oidc",
                       "oud", "oauth", "saml", "ping", "iga", "cisa", "pim",
                       "cism", "iam"}

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
TREND_FILE = os.path.join(OUTPUT_DIR, "iam_trend.csv")


# ----------------------------------------------------------------------
# FETCH
# ----------------------------------------------------------------------

def fetch_postings(term, page=1):
    url = f"https://api.adzuna.com/v1/api/jobs/{COUNTRY}/search/{page}"
    params = {
        "app_id": APP_ID, "app_key": APP_KEY, "what": term,
        "results_per_page": RESULTS_PER_PAGE, "content-type": "application/json",
    }
    if WHERE:
        params["where"] = WHERE
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! request failed for '{term}': {e}")
        return []
    return resp.json().get("results", [])


def fetch_full_text(url):
    """Best-effort fetch of the full posting page. Returns '' on any failure."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (personal job-search research)"}
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        # Strip HTML tags crudely; we only need words for keyword matching.
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text)
        return text
    except requests.RequestException:
        return ""


def gather_all():
    """Query every term, tag with role type, dedupe by id."""
    seen = set()
    postings = []
    for role_type, terms in SEARCH_TERMS.items():
        for term in terms:
            print(f"Searching [{role_type}]: {term}")
            for page in range(1, PAGES_PER_TERM + 1):
                for job in fetch_postings(term, page):
                    jid = job.get("id")
                    if jid and jid not in seen:
                        seen.add(jid)
                        job["_role_type"] = role_type
                        postings.append(job)
                time.sleep(1)
    print(f"\nCollected {len(postings)} unique postings.")

    if FETCH_FULL_TEXT:
        print("Fetching full text (best effort)...")
        got = 0
        for job in postings:
            if got >= FETCH_MAX:
                break
            url = job.get("redirect_url", "")
            if url:
                full = fetch_full_text(url)
                if full:
                    job["_full_text"] = full
                    got += 1
                time.sleep(0.5)
        print(f"  full text retrieved for {got} postings.\n")
    return postings


# ----------------------------------------------------------------------
# ANALYSE
# ----------------------------------------------------------------------

def posting_text(job):
    """Prefer full fetched text; fall back to Adzuna title + excerpt."""
    base = (job.get("title", "") + " " + job.get("description", ""))
    full = job.get("_full_text", "")
    return (base + " " + full).lower()


def term_in_text(term, text):
    if term in WORD_BOUNDARY_TERMS:
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def is_relevant(text):
    hits = sum(1 for t in CORE_IDENTITY_TERMS if term_in_text(t, text))
    return hits >= RELEVANCE_MIN_CORE_HITS


def analyse(postings):
    counts = {cat: defaultdict(int) for cat in KEYWORDS}
    by_role = defaultdict(lambda: defaultdict(int))   # role_type -> term -> n
    relevant = []
    for job in postings:
        text = posting_text(job)
        if not is_relevant(text):
            continue
        relevant.append(job)
        rtype = job.get("_role_type", "other")
        for cat, terms in KEYWORDS.items():
            for term in terms:
                if term_in_text(term, text):
                    counts[cat][term] += 1
                    by_role[rtype][term] += 1
    return counts, by_role, relevant


# ----------------------------------------------------------------------
# REPORT
# ----------------------------------------------------------------------

def write_text_report(counts, by_role, relevant, total_fetched):
    stamp = date.today().isoformat()
    path = os.path.join(OUTPUT_DIR, f"iam_report_{stamp}.txt")
    n = len(relevant)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"IAM JOB POSTING REPORT  -  {stamp}\n")
        f.write(f"Postings fetched: {total_fetched} | "
                f"Relevant (IAM) postings analysed: {n}\n")
        f.write(f"Full-text fetch: {'ON' if FETCH_FULL_TEXT else 'OFF'}\n")
        f.write("=" * 60 + "\n\n")
        for cat, tc in counts.items():
            f.write(f"{cat.upper()}\n{'-'*len(cat)}\n")
            for term, cnt in sorted(tc.items(), key=lambda kv: kv[1], reverse=True):
                if cnt:
                    pct = (cnt / n * 100) if n else 0
                    f.write(f"  {term:<26} {cnt:>3} / {n}  ({pct:4.0f}%)\n")
            f.write("\n")

        f.write("=" * 60 + "\nBY ROLE TYPE (top terms each)\n\n")
        for rtype, tc in by_role.items():
            top = sorted(tc.items(), key=lambda kv: kv[1], reverse=True)[:8]
            top = [f"{t} ({c})" for t, c in top if c]
            f.write(f"  {rtype}: {', '.join(top) if top else '(none)'}\n")
        f.write("\n" + "=" * 60 + "\nRELEVANT POSTINGS\n\n")
        for job in relevant:
            title = job.get("title", "n/a")
            company = job.get("company", {}).get("display_name", "n/a")
            f.write(f"  - [{job.get('_role_type','?')}] {title} | {company}\n"
                    f"    {job.get('redirect_url','')}\n")
    print(f"Text report: {path}")


def write_csv_report(counts, relevant):
    stamp = date.today().isoformat()
    path = os.path.join(OUTPUT_DIR, f"iam_report_{stamp}.csv")
    n = len(relevant)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "term", "count", "relevant_postings", "percent"])
        for cat, tc in counts.items():
            for term, cnt in sorted(tc.items(), key=lambda kv: kv[1], reverse=True):
                pct = round((cnt / n * 100), 1) if n else 0
                w.writerow([cat, term, cnt, n, pct])
    print(f"CSV report:  {path}")


def append_trend(counts, relevant):
    """Append this run's counts to a running trend file for week-over-week view."""
    stamp = date.today().isoformat()
    n = len(relevant)
    exists = os.path.exists(TREND_FILE)
    with open(TREND_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["date", "category", "term", "count",
                        "relevant_postings", "percent"])
        for cat, tc in counts.items():
            for term, cnt in tc.items():
                if cnt:
                    pct = round((cnt / n * 100), 1) if n else 0
                    w.writerow([stamp, cat, term, cnt, n, pct])
    print(f"Trend file updated: {TREND_FILE}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    if "YOUR_APP_ID_HERE" in APP_ID or "YOUR_APP_KEY_HERE" in APP_KEY:
        print("ERROR: set your Adzuna APP_ID and APP_KEY first.")
        sys.exit(1)

    postings = gather_all()
    if not postings:
        print("No postings returned. Check credentials, terms, or location.")
        return

    counts, by_role, relevant = analyse(postings)
    write_text_report(counts, by_role, relevant, len(postings))
    write_csv_report(counts, relevant)
    append_trend(counts, relevant)
    print(f"\nDone. {len(relevant)} relevant of {len(postings)} fetched.")


if __name__ == "__main__":
    main()
