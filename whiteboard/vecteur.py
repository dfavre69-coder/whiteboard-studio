"""Images vectorielles : fichiers SVG et bibliothèque d'icônes.

Contrairement aux images classiques, un SVG décrit ses traits : la main
peut donc suivre exactement chaque chemin, dans l'ordre du fichier.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

DOSSIER_ICONES = Path(__file__).parent / "assets" / "icones"
FICHIER_ICONES = DOSSIER_ICONES / "tabler-outline.json.gz"
PREFIXE_ICONE = "icone:"
PREFIXE_CLIPART = "clipart:"
FICHIER_CLIPARTS = Path(__file__).parent / "assets" / "cliparts" / "fluent-flat.json.gz"


@dataclass
class Chemin:
    """Une forme du dessin : un ou plusieurs sous-chemins (polylignes)."""
    sous_chemins: list[np.ndarray]           # chaque tableau : (N, 2) en unités du document
    fermes: list[bool]
    trait: tuple[int, int, int] | None       # couleur du contour, None = pas de contour
    epaisseur: float                         # épaisseur du contour (unités du document)
    remplissage: tuple[int, int, int] | None
    trait_encre: bool = False                # contour noir : dessiné à la couleur de l'encre


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def _couleur_svg(c) -> tuple[int, int, int] | None:
    if c is None or getattr(c, "value", None) is None:
        return None
    if c.alpha is not None and c.alpha < 20:
        return None
    return (c.red, c.green, c.blue)


def _degrades(texte: str) -> dict[str, list[tuple[int, int, int]]]:
    """Couleurs des arrêts de chaque dégradé (svgelements ne les conserve pas)."""
    import xml.etree.ElementTree as ET

    import svgelements as S

    try:
        racine = ET.fromstring(texte.encode("utf-8"))
    except ET.ParseError:
        return {}
    bruts, liens = {}, {}
    for el in racine.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("linearGradient", "radialGradient") or not el.get("id"):
            continue
        couleurs = []
        for stop in el:
            if stop.tag.rsplit("}", 1)[-1] != "stop":
                continue
            valeur = stop.get("stop-color")
            m = re.search(r"stop-color\s*:\s*([^;]+)", stop.get("style", ""))
            if m:
                valeur = m.group(1).strip()
            try:
                c = S.Color(valeur or "black")
                couleurs.append((c.red, c.green, c.blue))
            except Exception:  # noqa: BLE001
                pass
        bruts[el.get("id")] = couleurs
        lien = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
        liens[el.get("id")] = lien.lstrip("#")
    resultat = {}
    for ident in bruts:
        vus, courant = set(), ident
        while courant and not bruts.get(courant) and courant not in vus:
            vus.add(courant)
            courant = liens.get(courant, "")
        resultat[ident] = bruts.get(courant, []) if courant else []
    return resultat


def _couleur_degrade(degrades: dict, valeur: str) -> tuple[int, int, int]:
    """Pour un remplissage en dégradé, on prend la couleur médiane des arrêts."""
    m = re.search(r"url\(\s*['\"]?#([^)'\"\s]+)", valeur or "")
    couleurs = degrades.get(m.group(1), []) if m else []
    if not couleurs:
        return (200, 200, 200)
    if len(couleurs) % 2 == 0:  # moyenne des deux arrêts du milieu
        a, b = couleurs[len(couleurs) // 2 - 1], couleurs[len(couleurs) // 2]
        return tuple((x + y) // 2 for x, y in zip(a, b))  # type: ignore[return-value]
    return couleurs[len(couleurs) // 2]


def lire_svg(texte: str) -> list[Chemin]:
    import svgelements as S

    texte = texte.replace("currentColor", "#000000")
    degrades = _degrades(texte)
    svg = S.SVG.parse(io.StringIO(texte), reify=True)
    chemins: list[Chemin] = []
    elements = [e for e in svg.elements() if isinstance(e, S.Shape)]
    # pas d'échantillonnage : environ 1/600 de la taille du dessin
    boites = [S.Path(e).bbox() for e in elements]
    boites = [b for b in boites if b is not None]
    if not boites:
        return []
    taille = max(max(b[2] for b in boites) - min(b[0] for b in boites),
                 max(b[3] for b in boites) - min(b[1] for b in boites), 1e-6)
    pas = taille / 600

    for e in elements:
        if str(e.values.get("display", "")).strip() == "none" or \
           str(e.values.get("visibility", "")).strip() == "hidden":
            continue
        valeur_fill = str(e.values.get("fill", ""))
        fill = _couleur_svg(e.fill)
        if valeur_fill.startswith("url("):
            fill = _couleur_degrade(degrades, valeur_fill)
        stroke = _couleur_svg(e.stroke)
        if str(e.values.get("stroke", "")).startswith("url("):
            stroke = _couleur_degrade(degrades, str(e.values.get("stroke")))
        if fill is None and stroke is None:
            continue
        ep = float(getattr(e, "implicit_stroke_width", None) or e.stroke_width or 1.0) if stroke else 0.0
        sous, fermes = _aplatir(S.Path(e), pas)
        if not sous:
            continue
        chemins.append(Chemin(sous, fermes, stroke, ep, fill,
                              trait_encre=stroke is not None and max(stroke) < 60))
    return chemins


def _aplatir(chemin, pas: float) -> tuple[list[np.ndarray], list[bool]]:
    """Polylignes d'un chemin SVG. Chaque « Z » termine un sous-chemin, même sans « M » ensuite
    (en SVG, le tracé repart alors du début du sous-chemin fermé : trous des formes « evenodd »)."""
    import svgelements as S

    sous, fermes = [], []

    def finir(pts, ferme):
        if len(pts) >= 2 or (len(pts) == 1 and ferme):
            sous.append(np.array(pts, dtype=np.float64))
            fermes.append(ferme)
        elif len(pts) == 1:  # point isolé (« m0 0 » des icônes) : petit segment
            sous.append(np.array([pts[0], (pts[0][0] + pas, pts[0][1])], dtype=np.float64))
            fermes.append(False)

    for brut in chemin.as_subpaths():
        pts: list[tuple[float, float]] = []
        ferme = False
        for seg in S.Path(brut):
            if isinstance(seg, S.Move):
                if pts:
                    finir(pts, ferme)
                pts, ferme = ([(seg.end.x, seg.end.y)] if seg.end is not None else []), False
            elif isinstance(seg, S.Close):
                if pts:
                    debut = pts[0]
                    pts.append(debut)
                    finir(pts, True)
                    pts, ferme = [debut], False  # un tracé qui continue repart d'ici
                continue
            elif isinstance(seg, S.Line):
                pts.append((seg.end.x, seg.end.y))
            else:
                try:
                    longueur = seg.length(error=1e-3)
                except Exception:  # noqa: BLE001
                    longueur = abs(seg.end - seg.start) if seg.start is not None else 1.0
                n = max(2, min(400, int(longueur / max(pas, 1e-9)) + 1))
                for t in np.linspace(0, 1, n)[1:]:
                    p = seg.point(float(t))
                    pts.append((p.x, p.y))
        if len(pts) > 1:
            finir(pts, ferme)
    return sous, fermes


# ---------------------------------------------------------------------------
# Bibliothèque d'icônes (Tabler Icons, licence MIT)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def catalogue_icones() -> dict:
    """{nom: {"c": catégorie, "t": [mots-clés], "d": [tracés]}}"""
    if not FICHIER_ICONES.exists():
        return {}
    with gzip.open(FICHIER_ICONES, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def svg_icone(nom: str) -> str:
    info = catalogue_icones().get(nom)
    if info is None:
        raise KeyError(f"Icône inconnue : « {nom} »")
    chemins = []
    for d in info["d"]:
        if d.startswith("*"):
            chemins.append(f'<path d="{d[1:]}" fill="#000000" stroke="#000000"/>')
        else:
            chemins.append(f'<path d="{d}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            + "".join(chemins) + "</svg>")


@lru_cache(maxsize=1)
def catalogue_cliparts() -> dict:
    """{nom: {"l": libellé, "c": catégorie, "t": [mots-clés], "e": emoji, "s": svg}}"""
    if not FICHIER_CLIPARTS.exists():
        return {}
    with gzip.open(FICHIER_CLIPARTS, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def est_clipart(source: str) -> bool:
    return source.startswith(PREFIXE_CLIPART)


def nom_clipart(source: str) -> str:
    return source[len(PREFIXE_CLIPART):].strip()


def _sans_accents(s: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return s.replace("œ", "oe").replace("æ", "ae")


def chercher_cliparts(requete: str, categorie: str = "", limite: int = 300) -> list[str]:
    """Cliparts correspondant à la requête (noms et mots-clés français, ou anglais)."""
    cat = catalogue_cliparts()
    mots = [m for m in re.split(r"[\s,;'’-]+", _sans_accents(requete.strip())) if m]
    resultats = []
    for nom, info in cat.items():
        if categorie and info.get("c") != categorie:
            continue
        if not mots:
            resultats.append((0, nom))
            continue
        libelle = _sans_accents(info.get("l", ""))
        tags = [_sans_accents(t) for t in info.get("t", [])]
        score = 0
        for m in mots:
            if libelle == m or nom == m:
                score += 100
            elif libelle.startswith(m):
                score += 70
            elif re.search(rf"\b{re.escape(m)}", libelle):
                score += 55
            elif any(t == m for t in tags):
                score += 50
            elif any(t.startswith(m) for t in tags):
                score += 15
            elif m in nom:
                score += 10
            elif any(m in t for t in tags):
                score += 5
            else:
                score = -1
                break
        if score > 0:
            resultats.append((-score, nom))
    resultats.sort(key=lambda r: (r[0], len(r[1]), r[1]))
    return [n for _, n in resultats[:limite]]


def categories_cliparts() -> list[str]:
    return sorted({info.get("c", "") for info in catalogue_cliparts().values() if info.get("c")})


def est_icone(source: str) -> bool:
    return source.startswith(PREFIXE_ICONE)


def nom_icone(source: str) -> str:
    return source[len(PREFIXE_ICONE):].strip()


PASTILLES = {
    # nom : (couleur du disque, symbole) — symboles dessinés dans un carré unité
    "ok": ((67, 176, 71), "coche"), "oui": ((67, 176, 71), "coche"), "valide": ((67, 176, 71), "coche"),
    "non": ((229, 57, 53), "croix"), "faux": ((229, 57, 53), "croix"), "interdit": ((229, 57, 53), "croix"),
    "attention": ((251, 140, 0), "exclamation"), "alerte": ((251, 140, 0), "exclamation"),
    "question": ((30, 136, 229), "question"), "plus": ((67, 176, 71), "plus"), "moins": ((229, 57, 53), "moins"),
    "etoile": ((253, 216, 53), "etoile"), "coeur": ((236, 64, 122), "coeur"), "hausse": ((67, 176, 71), "hausse"),
    "baisse": ((229, 57, 53), "baisse"),
}


def _cercle(cx, cy, r, n=48):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], axis=1)
    return np.vstack([pts, pts[:1]])


def chemins_pastille(nom: str) -> list[Chemin]:
    """Pastille ronde (dans le carré 0-1) : disque blanc, disque coloré, symbole blanc."""
    couleur, symbole = PASTILLES[nom]
    blanc = (255, 255, 255)
    res = [Chemin([_cercle(.5, .5, .5)], [True], None, 0, blanc),
           Chemin([_cercle(.5, .5, .44)], [True], (30, 30, 30), .05, couleur)]
    trait = lambda pts: Chemin([np.array(pts, float)], [False], blanc, .11, None)  # noqa: E731
    if symbole == "coche":
        res.append(trait([(.3, .52), (.44, .66), (.71, .37)]))
    elif symbole == "croix":
        res += [trait([(.33, .33), (.67, .67)]), trait([(.67, .33), (.33, .67)])]
    elif symbole == "plus":
        res += [trait([(.5, .28), (.5, .72)]), trait([(.28, .5), (.72, .5)])]
    elif symbole == "moins":
        res.append(trait([(.28, .5), (.72, .5)]))
    elif symbole == "exclamation":
        res += [trait([(.5, .26), (.5, .58)]), trait([(.5, .72), (.5, .73)])]
    elif symbole == "question":
        t = np.linspace(np.pi * 1.05, np.pi * 2.35, 20)
        arc = [(.5 + .15 * np.cos(a), .4 + .13 * np.sin(a)) for a in t]
        res += [trait(arc + [(.5, .58)]), trait([(.5, .73), (.5, .74)])]
    elif symbole in ("hausse", "baisse"):
        pts = [(.28, .66), (.45, .5), (.56, .58), (.72, .36)] if symbole == "hausse" else \
              [(.28, .36), (.45, .52), (.56, .44), (.72, .66)]
        res.append(trait(pts))
        fin = pts[-1]
        res.append(trait([(fin[0] - .13, fin[1] + (0 if symbole == "hausse" else -.0)), fin,
                          (fin[0], fin[1] + (.13 if symbole == "hausse" else -.13))]))
    elif symbole == "etoile":
        t = np.linspace(-np.pi / 2, 1.5 * np.pi, 11)
        r = np.where(np.arange(11) % 2 == 0, .3, .13)
        res.append(Chemin([np.stack([.5 + r * np.cos(t), .52 + r * np.sin(t)], axis=1)], [True], blanc, .04, blanc))
    elif symbole == "coeur":
        t = np.linspace(0, 2 * np.pi, 60)
        x = 16 * np.sin(t) ** 3
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        res.append(Chemin([np.stack([.5 + x / 48, .52 + y / 48], axis=1)], [True], blanc, .03, blanc))
    return res


def _transformer(chemins, echelle: float, dx: float, dy: float) -> list[Chemin]:
    return [Chemin([s * echelle + (dx, dy) for s in c.sous_chemins], c.fermes, c.trait, c.epaisseur * echelle,
                   c.remplissage, c.trait_encre) for c in chemins]


def _boite(chemins) -> tuple[float, float, float, float]:
    tous = np.concatenate([s for c in chemins for s in c.sous_chemins])
    return (*tous.min(axis=0), *tous.max(axis=0))


def rogner_chemins(chemins, x0, y0, x1, y1) -> list[Chemin]:
    """Découpe les formes dans un rectangle (cadrage d'un SVG plus grand que sa vue)."""
    def couper(poly, garde, inter):
        res = []
        for i in range(len(poly)):
            a, b = poly[i - 1], poly[i]
            if garde(b):
                if not garde(a):
                    res.append(inter(a, b))
                res.append(b)
            elif garde(a):
                res.append(inter(a, b))
        return res

    def inter_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / ((b[0] - a[0]) or 1e-9))

    def inter_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-9), y)

    sortie = []
    for c in chemins:
        sous, fermes = [], []
        for s, ferme in zip(c.sous_chemins, c.fermes):
            if ferme or c.remplissage is not None:
                poly = [tuple(p) for p in s]
                for garde, inter in ((lambda p: p[0] >= x0, inter_x(x0)), (lambda p: p[0] <= x1, inter_x(x1)),
                                     (lambda p: p[1] >= y0, inter_y(y0)), (lambda p: p[1] <= y1, inter_y(y1))):
                    poly = couper(poly, garde, inter) if poly else poly
                if len(poly) >= 3:
                    sous.append(np.array(poly + poly[:1], float))
                    fermes.append(True)
            else:
                dedans = (s[:, 0] >= x0) & (s[:, 0] <= x1) & (s[:, 1] >= y0) & (s[:, 1] <= y1)
                if dedans.sum() >= 2:
                    sous.append(s[dedans])
                    fermes.append(False)
        if sous:
            sortie.append(Chemin(sous, fermes, c.trait, c.epaisseur, c.remplissage, c.trait_encre))
    return sortie


def _charger_simple(source: str) -> list[Chemin]:
    from .personnages import donnees, est_personne, svg_personne

    if est_personne(source):
        vue = [float(v) for v in donnees()["viewBox"].split()]
        return rogner_chemins(lire_svg(svg_personne(source)), vue[0], vue[1], vue[0] + vue[2], vue[1] + vue[3])
    if est_icone(source):
        return lire_svg(svg_icone(nom_icone(source)))
    if est_clipart(source):
        info = catalogue_cliparts().get(nom_clipart(source))
        if info is None:
            raise KeyError(f"Clipart inconnu : « {nom_clipart(source)} »")
        return lire_svg(info["s"])
    return lire_svg(Path(source).read_text(encoding="utf-8", errors="replace"))


def _source_partie(partie: str) -> str | None:
    """Élément ajouté après « + » : pastille, ou autre visuel (clipart de préférence)."""
    p = partie.strip()
    if not p:
        return None
    if p.startswith((PREFIXE_ICONE, PREFIXE_CLIPART, "personne:")) or p.lower().endswith(".svg"):
        return p
    if p in catalogue_cliparts():
        return PREFIXE_CLIPART + p
    if p in catalogue_icones():
        return PREFIXE_ICONE + p
    trouves = chercher_cliparts(p, limite=1)
    return PREFIXE_CLIPART + trouves[0] if trouves else None


@lru_cache(maxsize=256)
def charger_vecteur(source: str) -> tuple[Chemin, ...]:
    """Lit un visuel vectoriel : fichier .svg, « icone:nom », « clipart:nom », « personne:… »,
    ou une composition « visuel+visuel » / « visuel+pastille » (ex. clipart:maison+ok)."""
    parties = [p.strip() for p in source.split("+")] if "+" in source else [source]
    if len(parties) > 1 and not parties[0].lower().endswith(".svg") and Path(source).exists():
        parties = [source]  # un vrai fichier dont le nom contient « + »
    base = _charger_simple(parties[0])
    if len(parties) == 1 or not base:
        return tuple(base)
    x0, y0, x1, y1 = _boite(base)
    taille = max(x1 - x0, y1 - y0)
    resultat = list(base)
    coins = [(1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (0.0, 0.0)]  # bas droite, bas gauche, haut droite, haut gauche
    for n, partie in enumerate(parties[1:]):
        cle = _sans_accents(partie)
        if cle in PASTILLES:
            ajout, cote = chemins_pastille(cle), 0.38
        else:
            src = _source_partie(partie)
            if src is None:
                continue
            ajout, cote = list(_charger_simple(src)), 0.5
            if not ajout:
                continue
        ax0, ay0, ax1, ay1 = _boite(ajout)
        e = taille * cote / max(ax1 - ax0, ay1 - ay0, 1e-9)
        cx, cy = coins[n % 4]
        # l'élément ajouté déborde un peu du coin, comme un autocollant
        px = x0 + cx * (x1 - x0) - (ax1 - ax0) * e * (0.75 if cx else 0.25)
        py = y0 + cy * (y1 - y0) - (ay1 - ay0) * e * (0.75 if cy else 0.25)
        resultat += _transformer(ajout, e, px - ax0 * e, py - ay0 * e)
    return tuple(resultat)


def est_vectoriel(source: str) -> bool:
    base = source.split("+")[0].strip() if "+" in source and not Path(source).exists() else source
    return (est_icone(base) or est_clipart(base) or base.startswith("personne:")
            or base.lower().endswith(".svg"))


# Recherche en français : quelques mots courants traduits vers les mots-clés anglais.
FRANCAIS = {
    "idée": "bulb", "idee": "bulb", "ampoule": "bulb", "lumière": "light", "argent": "cash",
    "euro": "currency-euro", "monnaie": "coin", "banque": "building-bank", "maison": "home",
    "voiture": "car", "vélo": "bike", "velo": "bike", "avion": "plane", "train": "train",
    "bateau": "ship", "fusée": "rocket", "fusee": "rocket", "livre": "book", "lecture": "book",
    "école": "school", "ecole": "school", "élève": "student", "étudiant": "school", "professeur": "teacher",
    "personne": "user", "utilisateur": "user", "gens": "users", "groupe": "users", "équipe": "users",
    "famille": "users", "enfant": "baby", "bébé": "baby", "homme": "man", "femme": "woman",
    "coeur": "heart", "cœur": "heart", "amour": "heart", "santé": "heart-rate", "médecin": "stethoscope",
    "hôpital": "building-hospital", "hopital": "building-hospital", "médicament": "pill", "pilule": "pill",
    "temps": "clock", "horloge": "clock", "heure": "clock", "calendrier": "calendar", "date": "calendar",
    "téléphone": "phone", "telephone": "phone", "ordinateur": "device-desktop", "portable": "device-laptop",
    "écran": "device-desktop", "smartphone": "device-mobile", "tablette": "device-tablet",
    "courriel": "mail", "mail": "mail", "lettre": "mail", "message": "message", "discussion": "messages",
    "parler": "message", "question": "question-mark", "aide": "help", "recherche": "search", "chercher": "search",
    "loupe": "search", "outil": "tool", "outils": "tools", "réglage": "settings", "paramètres": "settings",
    "engrenage": "settings", "sécurité": "shield", "securite": "shield", "cadenas": "lock", "clé": "key",
    "cle": "key", "graphique": "chart-bar", "statistique": "chart-bar", "courbe": "chart-line",
    "camembert": "chart-pie", "croissance": "trending-up", "hausse": "trending-up", "baisse": "trending-down",
    "objectif": "target", "cible": "target", "but": "target", "réussite": "trophy", "victoire": "trophy",
    "trophée": "trophy", "médaille": "medal", "étoile": "star", "etoile": "star", "drapeau": "flag",
    "arbre": "tree", "plante": "plant", "fleur": "flower", "feuille": "leaf", "nature": "leaf",
    "soleil": "sun", "lune": "moon", "nuage": "cloud", "pluie": "cloud-rain", "neige": "snowflake",
    "météo": "cloud", "terre": "world", "monde": "world", "planète": "planet", "globe": "world",
    "carte": "map", "lieu": "map-pin", "position": "map-pin", "chemin": "route", "route": "road",
    "ville": "building-skyscraper", "immeuble": "building", "usine": "building-factory",
    "magasin": "building-store", "boutique": "building-store", "panier": "shopping-cart", "achat": "shopping-cart",
    "cadeau": "gift", "fête": "confetti", "musique": "music", "note": "music", "vidéo": "video",
    "video": "video", "caméra": "camera", "photo": "camera", "micro": "microphone", "podcast": "microphone",
    "écouter": "headphones", "casque": "headphones", "jeu": "device-gamepad", "sport": "ball-football",
    "ballon": "ball-football", "course": "run", "vélo électrique": "bike", "nourriture": "tools-kitchen-2",
    "manger": "tools-kitchen-2", "café": "coffee", "cafe": "coffee", "eau": "droplet", "goutte": "droplet",
    "feu": "flame", "énergie": "bolt", "energie": "bolt", "électricité": "bolt", "batterie": "battery",
    "attention": "alert-triangle", "danger": "alert-triangle", "erreur": "x", "valider": "check",
    "ok": "check", "vrai": "check", "faux": "x", "oui": "thumb-up", "non": "thumb-down", "aimer": "thumb-up",
    "pouce": "thumb-up", "partager": "share", "abonner": "bell", "abonnement": "bell", "cloche": "bell",
    "notification": "bell", "flèche": "arrow", "fleche": "arrow", "droite": "arrow-right", "gauche": "arrow-left",
    "haut": "arrow-up", "bas": "arrow-down", "cerveau": "brain", "réfléchir": "brain", "pensée": "brain",
    "science": "flask", "chimie": "flask", "atome": "atom", "microscope": "microscope", "robot": "robot",
    "ia": "robot", "intelligence": "brain", "code": "code", "programme": "code", "données": "database",
    "donnees": "database", "serveur": "server", "réseau": "network", "wifi": "wifi", "internet": "world-www",
    "nuage informatique": "cloud", "document": "file-text", "fichier": "file", "dossier": "folder",
    "crayon": "pencil", "écrire": "pencil", "stylo": "pen", "liste": "list", "tâche": "checklist",
    "check-list": "checklist", "travail": "briefcase", "entreprise": "building", "contrat": "file-certificate",
    "loi": "scale", "justice": "scale", "balance": "scale", "poids": "weight", "dessin": "brush",
    "peinture": "palette", "couleur": "palette", "histoire": "history", "château": "building-castle",
    "chateau": "building-castle", "église": "building-church", "musée": "building-museum",
    "montagne": "mountain", "mer": "ripple", "plage": "beach", "chien": "dog", "chat": "cat",
    "oiseau": "feather", "poisson": "fish", "insecte": "bug", "ampoule éteinte": "bulb-off",
    "sourire": "mood-smile", "content": "mood-happy", "triste": "mood-sad", "colère": "mood-angry",
    "puzzle": "puzzle", "pièce": "puzzle", "lien": "link", "main": "hand-stop", "poignée de main": "heart-handshake",
    "accord": "heart-handshake", "partenariat": "heart-handshake", "étape": "stairs", "escalier": "stairs",
    "progrès": "trending-up", "démarrer": "player-play", "lecture vidéo": "player-play",
}


def chercher_icones(requete: str, categorie: str = "", limite: int = 300) -> list[str]:
    """Noms d'icônes correspondant à la requête (français ou anglais)."""
    cat = catalogue_icones()
    q = requete.strip().lower()
    mots = [m for m in re.split(r"[\s,;]+", q) if m]
    if q in FRANCAIS:
        mots = [FRANCAIS[q]]
    else:
        mots = [FRANCAIS.get(m, m) for m in mots]
    resultats: list[tuple[int, str]] = []
    for nom, info in cat.items():
        if categorie and info.get("c") != categorie:
            continue
        if not mots:
            resultats.append((0, nom))
            continue
        score = 0
        for m in mots:
            if nom == m:
                score += 100
            elif nom.startswith(m):
                score += 40
            elif m in nom:
                score += 20
            elif any(m in str(t).lower() for t in info.get("t", [])):
                score += 10
            else:
                score = -1
                break
        if score > 0:
            resultats.append((-score, nom))
    resultats.sort(key=lambda r: (r[0], len(r[1]), r[1]))
    return [n for _, n in resultats[:limite]]


def categories_icones() -> list[str]:
    return sorted({info.get("c", "") for info in catalogue_icones().values() if info.get("c")})


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
@dataclass
class VecteurRendu:
    croquis_alpha: np.ndarray        # float 0-1 : le tracé à l'encre
    finale: np.ndarray | None        # RGB en couleur, ou None si le dessin est monochrome
    points: np.ndarray               # (N, 3) : x, y, rayon — parcours de la main
    largeur: int
    hauteur: int
    origine: tuple[float, float] = (0.0, 0.0)   # position du coin, avec fixe=True


def rendre_vecteur(chemins: list[Chemin] | tuple[Chemin, ...], largeur_max: int, hauteur_max: int,
                   epaisseur_min: float, epaisseur_max: float, fond: tuple[int, int, int],
                   encre: tuple[int, int, int], couleur: bool = True, fixe: bool = False) -> VecteurRendu | None:
    """Met le dessin à l'échelle de la boîte, le rastérise et calcule le parcours."""
    if not chemins:
        return None
    tous = np.concatenate([s for c in chemins for s in c.sous_chemins])
    x0, y0 = tous.min(axis=0)
    x1, y1 = tous.max(axis=0)
    bord_doc = max((c.epaisseur for c in chemins), default=0) / 2
    w_doc = max(1e-6, x1 - x0 + 2 * bord_doc)
    h_doc = max(1e-6, y1 - y0 + 2 * bord_doc)
    marge = epaisseur_max  # place pour l'épaisseur des traits dessinés
    if fixe:  # coordonnées déjà à l'échelle de l'écran
        f = 1.0
    else:
        f = min((largeur_max - 2 * marge) / w_doc, (hauteur_max - 2 * marge) / h_doc)
        f = max(f, 1e-6)
    W = max(2, int(math.ceil(w_doc * f + 2 * marge)))
    H = max(2, int(math.ceil(h_doc * f + 2 * marge)))
    ox, oy = marge - (x0 - bord_doc) * f, marge - (y0 - bord_doc) * f

    def px(pts: np.ndarray) -> np.ndarray:
        return np.stack([pts[:, 0] * f + ox, pts[:, 1] * f + oy], axis=1)

    k = 2  # sur-échantillonnage
    alpha = Image.new("L", (W * k, H * k), 0)
    da = ImageDraw.Draw(alpha)
    # Phase « couleurs » seulement si le dessin a des remplissages ou des contours colorés
    a_couleur = couleur and any(c.remplissage is not None or (c.trait is not None and not c.trait_encre)
                                for c in chemins)
    img = Image.new("RGB", (W * k, H * k), fond) if a_couleur else None
    di = ImageDraw.Draw(img) if img is not None else None

    points: list[tuple[float, float, float]] = []
    for c in chemins:
        sous_px = [px(s) for s in c.sous_chemins]
        # épaisseur du trait à l'encre (croquis)
        ep_reelle = c.epaisseur * f if c.trait is not None else 0.0
        ep = min(epaisseur_max, max(epaisseur_min, ep_reelle if ep_reelle > 0 else epaisseur_min))
        sombre = c.trait is None and c.remplissage is not None and max(c.remplissage) < 90
        if c.remplissage is not None:
            # Une forme pleine cache ce qui a été dessiné avant elle (peintre) : on efface
            # les traits qu'elle recouvre, sinon le croquis montre des lignes cachées.
            masque = Image.new("1", alpha.size, 0)
            for s in sous_px:
                if len(s) >= 3:
                    m = Image.new("1", alpha.size, 0)
                    ImageDraw.Draw(m).polygon([tuple(p) for p in s * k], fill=1)
                    masque = ImageChops.logical_xor(masque, m)
            alpha.paste(255 if sombre else 0, mask=masque)
        for s in sous_px:
            _ligne(da, s * k, (ep * 0.5 if sombre else ep) * k, 255)
        # version en couleur : remplissage puis contour
        if di is not None:
            if c.remplissage is not None:
                masque = Image.new("1", img.size, 0)
                for s, ferme in zip(sous_px, c.fermes):
                    if len(s) >= 3:
                        m = Image.new("1", img.size, 0)
                        ImageDraw.Draw(m).polygon([tuple(p) for p in s * k], fill=1)
                        masque = ImageChops.logical_xor(masque, m)
                img.paste(c.remplissage, mask=masque)
            if c.trait is not None:
                coul = encre if c.trait_encre else c.trait
                for s in sous_px:
                    _ligne(di, s * k, max(ep_reelle, 1.0) * k, coul)
            elif c.remplissage is not None:
                for s in sous_px:  # liseré discret, comme le croquis
                    _ligne(di, s * k, ep * 0.6 * k, encre)
        # parcours de la main
        r = ep / 2 + 1.5
        espacement = max(1.2, r * 0.7)
        for s in sous_px:
            for p in _reechantillonner(s, espacement):
                points.append((p[0], p[1], r))

    alpha = alpha.resize((W, H), Image.LANCZOS)
    finale = np.asarray(img.resize((W, H), Image.LANCZOS)) if img is not None else None
    a = np.asarray(alpha).astype(np.float32) / 255
    pts = np.array(points, dtype=np.float32).reshape(-1, 3)
    if len(pts):
        # la main ne repasse pas sur les traits cachés par une forme posée par-dessus
        xs = np.clip(pts[:, 0].astype(int), 0, W - 1)
        ys = np.clip(pts[:, 1].astype(int), 0, H - 1)
        pts = pts[a[ys, xs] > 0.15]
    return VecteurRendu(a, finale, pts, W, H, (float(x0 - bord_doc - marge), float(y0 - bord_doc - marge)))


def _ligne(d: ImageDraw.ImageDraw, pts: np.ndarray, largeur: float, fill) -> None:
    w = max(1, int(round(largeur)))
    liste = [tuple(map(float, p)) for p in pts]
    if len(liste) >= 2:
        d.line(liste, fill=fill, width=w, joint="curve")
    r = w / 2
    for x, y in (liste[0], liste[-1]):  # extrémités arrondies
        d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _reechantillonner(pts: np.ndarray, pas: float) -> np.ndarray:
    if len(pts) < 2:
        return pts
    seg = np.diff(pts, axis=0)
    long = np.hypot(seg[:, 0], seg[:, 1])
    cumul = np.concatenate([[0], np.cumsum(long)])
    total = cumul[-1]
    if total < 1e-6:
        return pts[:1]
    n = max(2, int(total / pas) + 1)
    t = np.linspace(0, total, n)
    x = np.interp(t, cumul, pts[:, 0])
    y = np.interp(t, cumul, pts[:, 1])
    return np.stack([x, y], axis=1)


@lru_cache(maxsize=1)
def _planche_vignettes() -> Image.Image | None:
    chemin = FICHIER_CLIPARTS.parent / "vignettes.jpg"
    return Image.open(chemin).convert("RGB") if chemin.exists() else None


def vignette_clipart(nom: str, taille: int = 48, fond=(255, 255, 255)) -> Image.Image:
    """Petite image en couleur d'un clipart pour le sélecteur (précalculée si possible)."""
    info = catalogue_cliparts().get(nom, {})
    planche = _planche_vignettes()
    if planche is not None and "v" in info:
        T, cols = 56, planche.width // 56
        i = info["v"]
        img = planche.crop(((i % cols) * T, (i // cols) * T, (i % cols + 1) * T, (i // cols + 1) * T))
        return img if taille == T else img.resize((taille, taille), Image.LANCZOS)
    return _vignette_clipart_calculee(nom, taille, fond)


def _vignette_clipart_calculee(nom: str, taille: int, fond) -> Image.Image:
    rendu = rendre_vecteur(charger_vecteur(PREFIXE_CLIPART + nom), taille, taille, 0.8, 1.2, fond,
                           (30, 30, 30), couleur=True)
    img = Image.new("RGB", (taille, taille), fond)
    if rendu is None:
        return img
    if rendu.finale is not None:
        source = Image.fromarray(rendu.finale)
    else:
        source = Image.new("RGB", (rendu.largeur, rendu.hauteur), fond)
        a = Image.fromarray((rendu.croquis_alpha * 255).astype(np.uint8))
        source.paste((30, 30, 30), mask=a)
    img.paste(source, ((taille - rendu.largeur) // 2, (taille - rendu.hauteur) // 2))
    return img


def vignette_icone(nom: str, taille: int = 48, couleur=(30, 30, 30), fond=(255, 255, 255)) -> Image.Image:
    """Petite image d'une icône pour le sélecteur."""
    rendu = rendre_vecteur(charger_vecteur(PREFIXE_ICONE + nom), taille, taille,
                           max(1.0, taille / 22), max(1.5, taille / 14), fond, couleur, couleur=False)
    img = Image.new("RGB", (taille, taille), fond)
    if rendu is None:
        return img
    a = Image.fromarray((rendu.croquis_alpha * 255).astype(np.uint8))
    trait = Image.new("RGB", a.size, couleur)
    img.paste(trait, ((taille - a.width) // 2, (taille - a.height) // 2), a)
    return img


# Polylignes « dessinées à la main » pour les modèles de scène ----------------
def chemins_depuis_polylignes(polylignes: list[np.ndarray], epaisseur: float = 1.0,
                              fermes: list[bool] | None = None) -> list[Chemin]:
    fermes = fermes or [False] * len(polylignes)
    return [Chemin([np.asarray(p, dtype=np.float64)], [f], (0, 0, 0), epaisseur, None, trait_encre=True)
            for p, f in zip(polylignes, fermes)]
