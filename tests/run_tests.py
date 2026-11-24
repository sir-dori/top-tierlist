#!/usr/bin/env python3
"""Tests de l'appli tierlist.

Lance l'appli dans un navigateur sans écran (Playwright) avec un faux Spotify
qui imite les vrais pièges : réponses en retard, chanson jouée sous un autre
identifiant (relinking), etc.

Usage :  python3 tests/run_tests.py
Prérequis : pip install playwright && playwright install chromium
"""
import hashlib, http.server, json, os, re, socketserver, sys, threading, time, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTABLE = open(os.path.join(ROOT, "tests", "sortable.min.js")).read()

# ---------- catalogue : id Spotify -> titre ----------
SONGS = []
for line in open(os.path.join(ROOT, "songs.js"), encoding="utf-8"):
    line = line.strip().rstrip(",")
    if line.startswith('["'):
        SONGS.append(json.loads(line))
NAME = {s[4][2:]: s[0] for s in SONGS if s[4].startswith("t:")}
CHRONO = SONGS  # ordre par défaut de l'appli
S1, S2, S3 = CHRONO[0], CHRONO[1], CHRONO[2]
uri = lambda s: "spotify:track:" + s[4][2:]

# ---------- petit serveur web local ----------
class Q(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), Q)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{PORT}/index.html"

# ---------- faux Spotify ----------
class FakeSpotify:
    def __init__(self, lag=1.2, relink=True):
        self.lag, self.relink = lag, relink
        self.item = None; self.playing = False; self.pos = 0; self.t = time.time()
        self.pending = None; self.log = []; self.names = dict(NAME)
    def progress(self):
        return int(self.pos + ((time.time() - self.t) * 1000 if self.playing else 0))
    def setpos(self, ms): self.pos = ms; self.t = time.time()
    def handle(self, route):
        req = route.request; u = urllib.parse.urlparse(req.url); p = u.path; q = urllib.parse.parse_qs(u.query)
        J = lambda o, st=200: route.fulfill(status=st, body=json.dumps(o), content_type="application/json")
        if "accounts.spotify.com" in u.netloc:
            return J({"access_token": "tok", "expires_in": 3600})
        if p.endswith("/me/player/devices"):
            return J({"devices": [{"id": "phone", "is_active": True, "type": "Smartphone", "name": "Téléphone"}]})
        if p.endswith("/me/player/play"):
            body = json.loads(req.post_data) if req.post_data else None
            if body and body.get("uris"):
                u0 = body["uris"][0]; tid = u0.split(":")[-1]
                real = ("spotify:track:R" + tid) if self.relink else u0
                item = {"uri": real, "name": self.names.get(tid, "?"), "duration_ms": 200000, "album": {"images": []}}
                self.pending = (item, time.time() + self.lag)
                self.log.append(("play", u0, time.time()))
            else:
                self.playing = True; self.t = time.time()
                self.log.append(("resume", None, time.time()))
            return route.fulfill(status=204)
        if p.endswith("/me/player/pause"):
            self.pos = self.progress(); self.playing = False; self.log.append(("pause", None, time.time()))
            return route.fulfill(status=204)
        if p.endswith("/me/player/seek"):
            ms = int(q["position_ms"][0]); self.setpos(ms); self.log.append(("seek", ms, time.time()))
            return route.fulfill(status=204)
        if p.endswith("/me/player"):
            if self.pending and time.time() >= self.pending[1]:
                self.item = self.pending[0]; self.pending = None; self.playing = True; self.setpos(0)
            if not self.item: return route.fulfill(status=204)
            return J({"item": self.item, "is_playing": self.playing, "progress_ms": self.progress()})
        if p.endswith("/search"):
            qq = q["q"][0].replace(" twenty one pilots", ""); tid = "SR" + hashlib.md5(qq.encode()).hexdigest()[:12]
            self.names[tid] = qq
            return J({"tracks": {"items": [{"uri": "spotify:track:" + tid, "name": qq,
                     "artists": [{"name": "Twenty One Pilots"}], "album": {"name": "x", "images": []}}]}})
        return route.fulfill(status=404)
    def plays(self, since=0): return [x[1] for x in self.log if x[0] == "play" and x[2] >= since]
    def last(self, kind): return next((x for x in reversed(self.log) if x[0] == kind), None)

# ---------- outillage ----------
RESULTS = []
def test(fn):
    RESULTS.append(fn); return fn

def open_app(pw, connect=False, fake=None, w=390, h=844):
    b = pw["browser"]; ctx = b.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page(); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.route("https://fonts.googleapis.com/**", lambda r: r.abort())
    page.route("https://fonts.gstatic.com/**", lambda r: r.abort())
    page.route("https://open.spotify.com/**", lambda r: r.abort())
    page.route("https://i.scdn.co/**", lambda r: r.abort())
    page.route("https://cdnjs.cloudflare.com/**", lambda r: r.fulfill(body=SORTABLE, content_type="application/javascript"))
    fake = fake or FakeSpotify()
    page.route("https://api.spotify.com/**", fake.handle)
    page.route("https://accounts.spotify.com/**", fake.handle)
    if connect:
        page.add_init_script("localStorage.setItem('top-tierlist-sp',JSON.stringify({cid:'0123456789abcdef0123456789abcdef',rt:'r',at:'a',exp:Date.now()+3.6e6,dev:'phone'}))")
    page.goto(URL); page.wait_for_timeout(500)
    return page, fake, errs, ctx

def title(p): return p.inner_text("#cTitle")
def dur_ok(p): return p.inner_text("#tDur") not in ("0:00", "")
def wait_until(p, cond, ms=6000):
    t = time.time()
    while time.time() - t < ms / 1000:
        if cond(): return True
        p.wait_for_timeout(150)
    return False
def rate(p, t): p.click(f'#tierBtns [data-t="{t}"]'); p.wait_for_timeout(650)
def check(c, msg):
    if not c: raise AssertionError(msg)

# ---------- tests ----------
@test
def demarrage_sans_erreur_et_sans_debordement(pw):
    for w in (360, 1280):
        p, f, errs, ctx = open_app(pw, w=w, h=800)
        check(not errs, f"erreurs JS : {errs}")
        sw = p.evaluate("document.documentElement.scrollWidth")
        check(sw <= w, f"la page déborde en largeur ({sw}px > {w}px)")
        check(title(p) == S1[0], f"première chanson attendue {S1[0]}, vu {title(p)}")
        ctx.close()

@test
def noter_passe_a_la_suivante_et_met_a_jour_la_courbe(pw):
    p, f, errs, ctx = open_app(pw)
    rate(p, "S")
    check(title(p) == S2[0], f"après notation on attend {S2[0]}, vu {title(p)}")
    check(p.inner_text("#nRated") == "(1)", "compteur de notes faux")
    check(p.inner_text("#dist .dlab span:first-child b") == "1", "la courbe ne compte pas la note S")
    check(not errs, errs); ctx.close()

@test
def double_appui_rapide_ne_note_qu_une_fois(pw):
    p, f, errs, ctx = open_app(pw)
    p.click('#tierBtns [data-t="S"]'); p.wait_for_timeout(80); p.click('#tierBtns [data-t="E"]'); p.wait_for_timeout(700)
    st = p.evaluate("JSON.parse(localStorage.getItem('top-tierlist-v1')).r")
    check(st.get(S1[0]) == "S", f"la 1re note doit rester S, vu {st}")
    check(title(p) == S2[0], "mauvaise chanson après double appui")
    ctx.close()

@test
def spotify_lecture_et_duree_malgre_autre_identifiant(pw):
    p, f, errs, ctx = open_app(pw, connect=True)
    p.click("#bPlay")
    check(wait_until(p, lambda: f.plays()), "aucune demande de lecture envoyée")
    check(f.plays()[-1] == uri(S1), f"mauvaise chanson lancée : {f.plays()[-1]}")
    check(wait_until(p, lambda: dur_ok(p)), "la durée reste à 0:00 (chanson non reconnue)")
    check(not errs, errs); ctx.close()

@test
def apres_notation_le_lecteur_reste_utilisable(pw):
    f = FakeSpotify(lag=1.5)
    p, f, errs, ctx = open_app(pw, connect=True, fake=f)
    p.click("#bPlay"); wait_until(p, lambda: dur_ok(p))
    t0 = time.time(); rate(p, "A")
    check(title(p) == S2[0], "pas passé à la chanson suivante")
    check(wait_until(p, lambda: f.plays(t0) and f.plays(t0)[-1] == uri(S2)), "la chanson suivante n'est pas lancée")
    check(wait_until(p, lambda: dur_ok(p), 7000), "durée inconnue après la notation : lecteur cassé")
    p.wait_for_timeout(1300)
    # barre de progression à 50 %
    box = p.locator("#seek").bounding_box()
    p.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] / 2); p.wait_for_timeout(300)
    sk = f.last("seek"); check(sk and 85000 <= sk[1] <= 115000, f"saut à 50 % attendu (~100 s), vu {sk}")
    p.click("#bFwd"); p.wait_for_timeout(300)
    sk2 = f.last("seek"); check(sk2[1] >= sk[1] + 8000, f"+10 s ne fonctionne pas : {sk2}")
    p.click("#bBack"); p.wait_for_timeout(300)
    sk3 = f.last("seek"); check(sk3[1] <= sk2[1] - 8000, f"-10 s ne fonctionne pas : {sk3}")
    p.click("#bPlay"); p.wait_for_timeout(300)
    check(f.last("pause") and f.last("pause")[2] > t0, "pause non envoyée")
    p.click("#bPlay"); p.wait_for_timeout(300)
    check(f.last("resume") and f.last("resume")[2] > t0, "reprise non envoyée (ou chanson relancée du début)")
    p.wait_for_timeout(1500)
    check(uri(S1) not in f.plays(t0), "l'appli a relancé la chanson d'avant !")
    check(title(p) == S2[0], "le titre affiché a changé tout seul")
    check(not errs, errs); ctx.close()

@test
def notations_enchainees_avec_spotify_lent(pw):
    f = FakeSpotify(lag=2.0)
    p, f, errs, ctx = open_app(pw, connect=True, fake=f)
    t0 = time.time()
    for t in "SAB": rate(p, t)
    check(title(p) == CHRONO[3][0], f"devrait être sur {CHRONO[3][0]}, vu {title(p)}")
    check(wait_until(p, lambda: f.plays(t0) and f.plays(t0)[-1] == uri(CHRONO[3])), f"dernière lecture ≠ chanson affichée : {f.plays(t0)}")
    check(wait_until(p, lambda: dur_ok(p), 8000), "lecteur pas synchronisé après plusieurs notes rapides")
    p.wait_for_timeout(1500)
    check(f.plays(t0)[-1] == uri(CHRONO[3]), "une ancienne chanson a été relancée après coup")
    ctx.close()

@test
def annuler_revient_a_la_chanson_et_retire_la_note(pw):
    p, f, errs, ctx = open_app(pw, connect=True)
    rate(p, "S"); rate(p, "B")
    t0 = time.time(); p.click("#bUndo"); p.wait_for_timeout(600)
    check(title(p) == S2[0], f"annuler devait revenir à {S2[0]}, vu {title(p)}")
    check(p.inner_text("#nRated") == "(1)", "la note annulée est toujours comptée")
    check(wait_until(p, lambda: f.plays(t0) and f.plays(t0)[-1] == uri(S2)), "la chanson rouverte n'est pas relancée")
    ctx.close()

@test
def glisser_deposer_dans_la_tierlist_puis_annuler(pw):
    p, f, errs, ctx = open_app(pw, w=1000, h=900)
    rate(p, "S"); p.click("#tabBoard"); p.wait_for_timeout(300)
    src = p.locator('#board .items[data-tier="S"] .item').first.bounding_box()
    dst = p.locator('#board .items[data-tier="D"]').bounding_box()
    p.mouse.move(src["x"] + 10, src["y"] + 10); p.mouse.down()
    for i in range(1, 16):
        p.mouse.move(src["x"] + 10 + (dst["x"] + 60 - src["x"]) * i / 15, src["y"] + 10 + (dst["y"] + dst["height"] / 2 - src["y"]) * i / 15)
        p.wait_for_timeout(25)
    p.mouse.up(); p.wait_for_timeout(400)
    check(p.locator('#board .items[data-tier="D"] .item').count() == 1, "la chanson n'a pas été déplacée en D")
    check(p.inner_text("#dist2 .dlab span:nth-child(5) b") == "1", "la courbe n'a pas suivi le déplacement")
    p.click("#bUndo2"); p.wait_for_timeout(300)
    check(p.locator('#board .items[data-tier="S"] .item').count() == 1, "annuler n'a pas remis la chanson en S")
    check(not errs, errs); ctx.close()

@test
def notes_conservees_apres_rechargement(pw):
    p, f, errs, ctx = open_app(pw)
    rate(p, "C"); p.reload(); p.wait_for_timeout(500)
    check(p.inner_text("#nRated") == "(1)", "les notes ont disparu au rechargement")
    ctx.close()

# ---------- lancement ----------
if __name__ == "__main__":
    ok = 0
    with sync_playwright() as pwr:
        pw = {"browser": pwr.chromium.launch()}
        for fn in RESULTS:
            name = fn.__name__.replace("_", " ")
            try:
                fn(pw); ok += 1; print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ✗ {name} → {e}")
        pw["browser"].close()
    print(f"\n{ok}/{len(RESULTS)} tests réussis")
    srv.shutdown(); sys.exit(0 if ok == len(RESULTS) else 1)
