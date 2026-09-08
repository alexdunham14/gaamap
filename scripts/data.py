"""Every fixture row, from every source.

fetch.py owns fixtures.json (gaa.ie: football and hurling) and fetch_camogie.py owns
camogie.json (camogie.ie). Each script writes only its own file, so neither can clobber
the other and the site still renders if one source is stale. Everything downstream —
geocoding, venue merging, and app.js — wants the union.
"""
import json
import os

FILES = ["fixtures.json", "camogie.json"]


def all_fixtures():
    rows = []
    for name in FILES:
        if os.path.exists(name):
            rows += json.load(open(name, encoding="utf-8"))["fixtures"]
    return rows
