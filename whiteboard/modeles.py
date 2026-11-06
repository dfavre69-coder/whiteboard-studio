"""Scènes prédéfinies : mises en page prêtes à l'emploi.

Chaque modèle place le titre, le texte et les visuels de la scène, et ajoute
des traits à main levée (flèches, soulignés, cercles…) dessinés eux aussi
par la main.

Dans le champ « texte », une ligne = un élément. Une icône ou une image peut
précéder le libellé entre crochets :
    [rocket] Lancer le projet
    [C:/images/logo.png] Notre partenaire
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

import numpy as np

from .projet import Scene
from .vecteur import PREFIXE_ICONE


@dataclass(frozen=True)
class InfoModele:
    libelle: str
    description: str
    aide_titre: str
    aide_texte: str
    exemple: dict


MODELES: dict[str, InfoModele] = {
    "libre": InfoModele(
        "Image et texte", "Un titre, une image (ou icône, ou SVG) et une légende.",
        "Titre en haut", "Légende sous l'image (ou texte centré s'il n'y a pas d'image)",
        dict(titre="Mon sujet", image="icone:bulb", texte="Une phrase pour l'expliquer")),
    "titre": InfoModele(
        "Titre de chapitre", "Un grand titre souligné, un sous-titre et une icône facultative.",
        "Grand titre", "Sous-titre",
        dict(titre="Chapitre 1", texte="Les bases à connaître", image="icone:book")),
    "liste": InfoModele(
        "Liste à puces", "Des points qui s'écrivent l'un après l'autre, avec coches ou icônes.",
        "Titre de la liste", "Un point par ligne — [icône] au début pour remplacer la coche",
        dict(titre="Les 3 règles d'or", texte="Être curieux\nPratiquer chaque jour\nPartager ce qu'on apprend")),
    "etapes": InfoModele(
        "Étapes reliées", "Un processus en 2 à 6 étapes reliées par des flèches.",
        "Titre du processus", "Une étape par ligne : [icône] Libellé",
        dict(titre="Comment ça marche", texte="[bulb] L'idée\n[tools] La fabrication\n[rocket] Le lancement")),
    "comparaison": InfoModele(
        "Comparaison", "Deux ou trois colonnes côte à côte, séparées par des traits.",
        "Titre de la comparaison", "Une colonne par ligne : [icône] Libellé",
        dict(titre="Avant / Après", texte="[mood-sad] Avant : tout à la main\n[mood-happy] Après : automatisé")),
    "chiffre": InfoModele(
        "Chiffre clé", "Un nombre géant entouré, avec sa légende.",
        "Le chiffre (ex. 87 %)", "Ce que représente ce chiffre",
        dict(titre="87 %", texte="des spectateurs retiennent mieux une vidéo dessinée", image="icone:users")),
    "citation": InfoModele(
        "Citation", "Une citation entre guillemets et son auteur.",
        "Auteur", "Le texte de la citation",
        dict(titre="Albert Einstein", texte="La logique vous mènera d'un point A à un point B. "
                                            "L'imagination vous mènera partout.")),
    "fin": InfoModele(
        "Fin de vidéo", "Remerciements et appel à l'action (abonnement, j'aime, commentaire).",
        "Message de fin", "Actions, une par ligne : [icône] Libellé (vide = actions par défaut)",
        dict(titre="Merci d'avoir regardé !", texte="")),
}

ACTIONS_FIN = "[clipart:cloche] Abonnez-vous\n[clipart:pouce-vers-le-haut] J'aime\n[clipart:bulle-de-parole] Commentez"


def analyser_items(texte: str) -> list[tuple[str | None, str]]:
    """« [visuel] libellé » → [(source du visuel ou None, libellé)]."""
    items = []
    for ligne in texte.replace("\r\n", "\n").split("\n"):
        ligne = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", ligne).strip()
        if not ligne:
            continue
        visuel = None
        m = re.match(r"^\[([^\]]+)\]\s*(.*)$", ligne)
        if m:
            ref, ligne = m.group(1).strip(), m.group(2).strip()
            if ref.startswith(("icone:", "clipart:")) or re.search(r"[\\/]|\.(svg|png|jpe?g|webp|bmp|gif)$", ref, re.I):
                visuel = ref
            else:
                visuel = PREFIXE_ICONE + ref
        items.append((visuel, ligne))
    return items


# ---------------------------------------------------------------------------
# Traits à main levée
# ---------------------------------------------------------------------------
class Crayon:
    """Produit des polylignes légèrement tremblées, toujours les mêmes pour une scène donnée."""

    def __init__(self, graine: str, amplitude: float):
        self.rng = random.Random(graine)
        self.a = amplitude

    def _tremble(self, pts: np.ndarray, force: float = 1.0) -> np.ndarray:
        n = len(pts)
        if n < 3:
            return pts
        phase = [self.rng.uniform(0, 2 * math.pi) for _ in range(2)]
        t = np.linspace(0, 1, n)
        d = np.gradient(pts, axis=0)
        nrm = np.hypot(d[:, 0], d[:, 1])[:, None] + 1e-9
        perp = np.stack([-d[:, 1], d[:, 0]], axis=1) / nrm
        bruit = (np.sin(t * 2 * math.pi * 1.3 + phase[0]) * 0.6 + np.sin(t * 2 * math.pi * 3.1 + phase[1]) * 0.4)
        return pts + perp * (bruit * self.a * force)[:, None]

    def ligne(self, a, b, courbure: float = 0.0) -> np.ndarray:
        a, b = np.asarray(a, float), np.asarray(b, float)
        t = np.linspace(0, 1, 40)[:, None]
        pts = a + (b - a) * t
        if courbure:
            d = b - a
            perp = np.array([-d[1], d[0]]) / (np.hypot(*d) + 1e-9)
            pts = pts + perp * (np.sin(t * math.pi) * courbure)
        return self._tremble(pts, 0.5)

    def fleche(self, a, b) -> list[np.ndarray]:
        a, b = np.asarray(a, float), np.asarray(b, float)
        long = float(np.hypot(*(b - a)))
        corps = self.ligne(a, b, courbure=long * 0.06 * self.rng.choice([-1, 1]))
        d = corps[-1] - corps[-6]
        ang = math.atan2(d[1], d[0])
        tete = min(long * 0.35, self.a * 9)
        pointes = []
        for s in (-1, 1):
            g = ang + math.pi + s * 0.5
            pointes.append(self.ligne(corps[-1], corps[-1] + tete * np.array([math.cos(g), math.sin(g)])))
        return [corps] + pointes

    def ellipse(self, cx, cy, rx, ry, tours: float = 1.12) -> np.ndarray:
        debut = self.rng.uniform(-2.6, -2.0)
        t = np.linspace(debut, debut + 2 * math.pi * tours, 120)
        variation = 1 + 0.04 * np.sin(t * 1.5 + self.rng.uniform(0, 6))
        return np.stack([cx + rx * np.cos(t) * variation, cy + ry * np.sin(t) * variation], axis=1)

    def souligne(self, x0, x1, y) -> np.ndarray:
        t = np.linspace(0, 1, 60)
        x = x0 + (x1 - x0) * t
        yy = y + np.sin(t * math.pi * 2 + self.rng.uniform(0, 3)) * self.a * 0.8 - t * self.a
        return np.stack([x, yy], axis=1)

    def coche(self, cx, cy, s) -> np.ndarray:
        pts = np.array([[cx - s * 0.45, cy], [cx - s * 0.1, cy + s * 0.35], [cx + s * 0.5, cy - s * 0.4]])
        dense = np.concatenate([np.linspace(pts[0], pts[1], 12), np.linspace(pts[1], pts[2], 20)[1:]])
        return self._tremble(dense, 0.3)


# ---------------------------------------------------------------------------
# Outils de mise en page
# ---------------------------------------------------------------------------
def _titre_haut(fab, texte: str, taille: float | None = None):
    """Titre en haut de l'écran ; renvoie (élément, ordonnée du bas)."""
    el = fab.texte(texte, taille or fab.R * 0.095, fab.W - 2 * fab.mx, lignes_max=2)
    if el is None:
        return None, fab.my
    el.placer(cx=fab.W / 2, y=fab.my)
    return el, el.y + el.hauteur + int(fab.H * 0.03)


def _visuel_centre(fab, source, cx, cy, w, h):
    el = fab.visuel(source, w, h) if source else None
    if el is not None:
        el.placer(cx=cx, cy=cy)
    return el


def _crayon(fab, scene: Scene) -> Crayon:
    return Crayon(f"{scene.modele}|{scene.titre}|{scene.texte}", fab.trait * 0.9)


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
def modele_libre(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    elements = []
    haut, bas = fab.my, H - fab.my
    a_image = bool(sc.image.strip())
    texte = sc.texte.strip()
    titre = sc.titre.strip()
    if titre and (a_image or texte):
        el, haut = _titre_haut(fab, titre)
        elements.append(el)
    elif titre:
        el = fab.texte(titre, R * 0.14, W - 2 * fab.mx, lignes_max=3)
        elements.append(el.placer(cx=W / 2, cy=H / 2))
    legende = None
    if texte and a_image:
        legende = fab.texte(texte, R * 0.066, W - 2 * fab.mx, lignes_max=2)
        legende.placer(cx=W / 2, y=bas - legende.hauteur)
        bas = legende.y - int(H * 0.03)
    elif texte:
        dispo = bas - haut
        t = R * 0.08
        el = fab.texte(texte, t, (W - 2 * fab.mx) * 0.9, lignes_max=max(1, int(dispo // (t * 1.25))))
        elements.append(el.placer(cx=W / 2, y=haut + max(0, (dispo - el.hauteur) // 2)))
    if a_image:
        elements.append(_visuel_centre(fab, sc.image, W / 2, (haut + bas) / 2, W - 2 * fab.mx, max(10, bas - haut)))
    elements.append(legende)
    return elements


def modele_titre(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    icone = fab.visuel(sc.image, R * 0.26, R * 0.26) if sc.image.strip() else None
    titre = fab.texte(sc.titre or " ", R * 0.13, W - 2 * fab.mx, lignes_max=2)
    sous = fab.texte(sc.texte, R * 0.06, W - 2 * fab.mx, lignes_max=2)
    ecart = R * 0.04
    hauteurs = [e.hauteur for e in (icone, titre, sous) if e is not None] + [R * 0.04]
    y = (H - sum(hauteurs) - ecart * (len(hauteurs) - 1)) / 2
    elements = []
    if icone is not None:
        elements.append(icone.placer(cx=W / 2, y=y))
        y += icone.hauteur + ecart
    if titre is not None:
        elements.append(titre.placer(cx=W / 2, y=y))
        y += titre.hauteur
        larg = titre.largeur * 0.85
        elements.append(fab.traits([cr.souligne(W / 2 - larg / 2, W / 2 + larg / 2, y + R * 0.01)],
                                   fab.trait * 1.3))
        y += R * 0.04 + ecart
    if sous is not None:
        elements.append(sous.placer(cx=W / 2, y=y))
    return elements


def modele_liste(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    el, haut = _titre_haut(fab, sc.titre)
    elements.append(el)
    items = analyser_items(sc.texte)[:8] or [(None, "…")]
    zone_x, zone_w = fab.mx, W - 2 * fab.mx
    if sc.image.strip():
        if fab.vertical:
            h_img = (H - fab.my - haut) * 0.35
            elements.append(_visuel_centre(fab, sc.image, W / 2, haut + h_img / 2, zone_w, h_img))
            haut += h_img + R * 0.03
        else:
            larg_img = zone_w * 0.38
            elements.append(_visuel_centre(fab, sc.image, W - fab.mx - larg_img / 2, (haut + H - fab.my) / 2,
                                           larg_img, H - fab.my - haut))
            zone_w *= 0.58
    dispo = H - fab.my - haut
    h_ligne = min(R * 0.17, dispo / len(items))
    taille = min(R * 0.078, h_ligne * 0.55)
    marque = min(h_ligne * 0.62, R * 0.1)
    # on prépare les textes pour centrer le bloc horizontalement
    textes = [fab.texte(libelle, taille, zone_w - marque * 1.4, lignes_max=2, aligne="gauche")
              for _, libelle in items]
    larg_bloc = marque * 1.3 + max((t.largeur for t in textes if t is not None), default=0)
    zone_x += max(0, (zone_w - larg_bloc) / 2)
    y = haut + (dispo - h_ligne * len(items)) / 2
    for (visuel, _), texte in zip(items, textes):
        cy = y + h_ligne / 2
        cx_marque = zone_x + marque / 2
        if visuel:
            elements.append(_visuel_centre(fab, visuel, cx_marque, cy, marque, marque))
        else:
            elements.append(fab.traits([cr.coche(cx_marque, cy, marque * 0.7)], fab.trait * 1.2))
        if texte is not None:
            elements.append(texte.placer(x=zone_x + marque * 1.3, cy=cy))
        y += h_ligne
    return elements


def _numero(fab, cr, n, cx, cy, d):
    cercle = fab.traits([cr.ellipse(cx, cy, d / 2, d / 2)])
    chiffre = fab.texte(str(n), d * 0.6, d)
    return [cercle, chiffre.placer(cx=cx, cy=cy - d * 0.04) if chiffre else None]


def modele_etapes(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    el, haut = _titre_haut(fab, sc.titre)
    elements.append(el)
    items = analyser_items(sc.texte)[:6] or [(None, "Étape")]
    n = len(items)
    zone_w = W - 2 * fab.mx
    dispo = H - fab.my - haut
    if not fab.vertical:
        col = zone_w / n
        s = min(col * 0.55, dispo * 0.48)
        cy = haut + dispo * 0.38
        for i, (visuel, libelle) in enumerate(items):
            cx = fab.mx + col * (i + 0.5)
            vis = _visuel_centre(fab, visuel, cx, cy, s, s) if visuel else None
            elements += [vis] if vis is not None else _numero(fab, cr, i + 1, cx, cy, s * 0.7)
            lab = fab.texte(libelle, min(R * 0.058, col * 0.16), col * 0.92, lignes_max=3)
            if lab is not None:
                elements.append(lab.placer(cx=cx, y=cy + s / 2 + R * 0.035))
            if i < n - 1:
                x0, x1 = cx + s / 2 + col * 0.06, cx + col - s / 2 - col * 0.06
                if x1 - x0 > R * 0.03:
                    elements.append(fab.traits(cr.fleche((x0, cy), (x1, cy))))
    else:
        ligne = dispo / n
        s = min(ligne * 0.6, zone_w * 0.3)
        cx = fab.mx + s / 2
        for i, (visuel, libelle) in enumerate(items):
            cy = haut + ligne * (i + 0.4)
            vis = _visuel_centre(fab, visuel, cx, cy, s, s) if visuel else None
            elements += [vis] if vis is not None else _numero(fab, cr, i + 1, cx, cy, s * 0.7)
            lab = fab.texte(libelle, min(R * 0.07, ligne * 0.3), zone_w - s * 1.3, lignes_max=3, aligne="gauche")
            if lab is not None:
                elements.append(lab.placer(x=cx + s * 0.75, cy=cy))
            if i < n - 1:
                y0, y1 = cy + s / 2 + ligne * 0.05, cy + ligne - s / 2 - ligne * 0.05
                if y1 - y0 > R * 0.03:
                    elements.append(fab.traits(cr.fleche((cx, y0), (cx, y1))))
    return elements


def modele_comparaison(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    el, haut = _titre_haut(fab, sc.titre)
    elements.append(el)
    items = analyser_items(sc.texte)[:3] or [(None, "A"), (None, "B")]
    n = len(items)
    bas = H - fab.my
    if not fab.vertical:
        col = (W - 2 * fab.mx) / n
        for i, (visuel, libelle) in enumerate(items):
            cx = fab.mx + col * (i + 0.5)
            lab = fab.texte(libelle, R * 0.062, col * 0.85, lignes_max=3)
            h_lab = lab.hauteur if lab else 0
            h_vis = bas - haut - h_lab - R * 0.04
            if visuel:
                elements.append(_visuel_centre(fab, visuel, cx, haut + h_vis / 2, col * 0.72, h_vis * 0.9))
            if lab is not None:
                elements.append(lab.placer(cx=cx, y=bas - h_lab))
            if i < n - 1:
                x = fab.mx + col * (i + 1)
                vs = fab.texte("VS", R * 0.075, col) if n == 2 else None
                if vs is not None:
                    milieu = (haut + bas) / 2
                    vs.placer(cx=x, cy=milieu)
                    elements.append(fab.traits([cr.ligne((x, haut), (x, vs.y - R * 0.01)),
                                                cr.ligne((x, vs.y + vs.hauteur + R * 0.01), (x, bas))]))
                    elements.append(vs)
                else:
                    elements.append(fab.traits([cr.ligne((x, haut), (x, bas))]))
    else:
        ligne = (bas - haut) / n
        for i, (visuel, libelle) in enumerate(items):
            y0 = haut + ligne * i
            lab = fab.texte(libelle, R * 0.07, W - 2 * fab.mx, lignes_max=2)
            h_lab = lab.hauteur if lab else 0
            if visuel:
                elements.append(_visuel_centre(fab, visuel, W / 2, y0 + (ligne - h_lab) / 2,
                                               W - 2 * fab.mx, (ligne - h_lab) * 0.8))
            if lab is not None:
                elements.append(lab.placer(cx=W / 2, y=y0 + ligne - h_lab - R * 0.02))
            if i < n - 1:
                elements.append(fab.traits([cr.ligne((fab.mx, y0 + ligne), (W - fab.mx, y0 + ligne))]))
    return elements


def modele_chiffre(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    chiffre = fab.texte(sc.titre.strip() or "?", R * 0.26, W - 2 * fab.mx, lignes_max=1)
    legende = fab.texte(sc.texte, R * 0.07, W - 2 * fab.mx, lignes_max=2)
    icone = fab.visuel(sc.image, R * 0.3, R * 0.3) if sc.image.strip() else None
    rx = max(chiffre.largeur * 0.62, chiffre.hauteur * 0.8)  # demi-axes du cercle autour du chiffre
    ry = chiffre.hauteur * 0.6
    h_leg = legende.hauteur if legende else 0
    cy = (H - h_leg - R * 0.05) / 2
    if icone is not None and not fab.vertical:
        ecart = R * 0.06
        total = icone.largeur + ecart + 2 * rx
        x = (W - total) / 2
        elements.append(icone.placer(x=x, cy=cy))
        chiffre.placer(cx=x + icone.largeur + ecart + rx, cy=cy)
    elif icone is not None:
        chiffre.placer(cx=W / 2, cy=cy + R * 0.08)
        elements.append(icone.placer(cx=W / 2, y=chiffre.y + chiffre.hauteur * 0.52 - ry - icone.hauteur - R * 0.04))
    else:
        chiffre.placer(cx=W / 2, cy=cy)
    elements.append(chiffre)
    c = (chiffre.x + chiffre.largeur / 2, chiffre.y + chiffre.hauteur * 0.52)
    elements.append(fab.traits([cr.ellipse(c[0], c[1], rx, ry)], fab.trait * 1.2))
    if legende is not None:
        elements.append(legende.placer(cx=W / 2, y=c[1] + ry + R * 0.05))
    return elements


def modele_citation(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    larg = (W - 2 * fab.mx) * (0.78 if not fab.vertical else 0.9)
    texte = sc.texte.strip() or "…"
    if not texte.startswith(("«", "“", '"')):
        texte = f"« {texte} »"
    citation = fab.texte(texte, R * 0.085, larg, lignes_max=6)
    auteur = fab.texte(f"— {sc.titre.strip()}", R * 0.058, larg) if sc.titre.strip() else None
    guillemet = fab.texte("“", R * 0.32, R * 0.4)
    h = citation.hauteur + (auteur.hauteur + R * 0.04 if auteur else 0)
    citation.placer(cx=W / 2, y=(H - h) / 2 + R * 0.04)
    elements = []
    if guillemet is not None:
        # grand guillemet décoratif en haut à gauche de la citation
        gx = max(fab.mx * 0.5, citation.x - guillemet.largeur * 0.55)
        elements.append(guillemet.placer(x=gx, y=citation.y - guillemet.hauteur * 0.42))
    elements.append(citation)
    if auteur is not None:
        auteur.placer(x=citation.x + citation.largeur - auteur.largeur, y=citation.y + citation.hauteur + R * 0.04)
        elements.append(auteur)
        elements.append(fab.traits([cr.souligne(auteur.x + auteur.largeur * 0.1, auteur.x + auteur.largeur,
                                                auteur.y + auteur.hauteur + R * 0.005)]))
    return elements


def modele_fin(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    elements = []
    haut = fab.my
    if sc.image.strip():
        logo = _visuel_centre(fab, sc.image, W / 2, haut + R * 0.1, R * 0.2, R * 0.2)
        if logo is not None:
            elements.append(logo)
            haut = logo.y + logo.hauteur + R * 0.03
    titre = fab.texte(sc.titre.strip() or "Merci !", R * 0.11, W - 2 * fab.mx, lignes_max=2)
    if titre is not None:
        elements.append(titre.placer(cx=W / 2, y=haut + R * 0.03))
        haut = titre.y + titre.hauteur + R * 0.05
    items = analyser_items(sc.texte.strip() or ACTIONS_FIN)[:4]
    n = max(1, len(items))
    bas = H - fab.my
    if not fab.vertical:
        col = (W - 2 * fab.mx) / n
        s = min(col * 0.45, (bas - haut) * 0.55)
        for i, (visuel, libelle) in enumerate(items):
            cx = fab.mx + col * (i + 0.5)
            cy = haut + (bas - haut) * 0.4
            elements.append(_visuel_centre(fab, visuel, cx, cy, s, s))
            lab = fab.texte(libelle, R * 0.06, col * 0.9, lignes_max=2)
            if lab is not None:
                elements.append(lab.placer(cx=cx, y=cy + s / 2 + R * 0.03))
    else:
        ligne = (bas - haut) / n
        s = ligne * 0.55
        for i, (visuel, libelle) in enumerate(items):
            cy = haut + ligne * (i + 0.5)
            elements.append(_visuel_centre(fab, visuel, fab.mx + s / 2, cy, s, s))
            lab = fab.texte(libelle, R * 0.075, W - 2 * fab.mx - s * 1.3, aligne="gauche")
            if lab is not None:
                elements.append(lab.placer(x=fab.mx + s * 1.3, cy=cy))
    return elements


FONCTIONS = {
    "libre": modele_libre, "titre": modele_titre, "liste": modele_liste, "etapes": modele_etapes,
    "comparaison": modele_comparaison, "chiffre": modele_chiffre, "citation": modele_citation,
    "fin": modele_fin,
}


def construire(fab, scene: Scene):
    return [e for e in FONCTIONS.get(scene.modele, modele_libre)(fab, scene) if e is not None]


def scene_exemple(code: str) -> Scene:
    info = MODELES.get(code, MODELES["libre"])
    return Scene(modele=code, **info.exemple)
