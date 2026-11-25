#!/usr/bin/env python3
"""Met à jour le numéro de version de songs.js dans index.html (évite que le
téléphone garde une vieille liste en cache). Lancé automatiquement par les tests."""
import hashlib, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h = hashlib.md5(open(os.path.join(ROOT, "songs.js"), "rb").read()).hexdigest()[:8]
p = os.path.join(ROOT, "index.html"); s = open(p, encoding="utf-8").read()
n = re.sub(r'<script src="songs\.js(\?v=\w+)?"></script>', f'<script src="songs.js?v={h}"></script>', s)
if n != s: open(p, "w", encoding="utf-8").write(n); print("version de songs.js →", h)
