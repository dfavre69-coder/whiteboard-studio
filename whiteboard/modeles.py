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
from .vecteur import PREFIXE_ICONE, Chemin


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
    "graphique": InfoModele(
        "Graphique en barres", "Des barres dessinées à partir de vrais chiffres, avec leurs valeurs.",
        "Titre du graphique", "Une barre par ligne : Libellé : valeur (ex. 2020 : 45 %)",
        dict(titre="Abonnés de la chaîne", texte="2023 : 1 200\n2024 : 3 500\n2025 : 8 900")),
    "proportion": InfoModele(
        "Proportion en pictogrammes", "« 3 sur 10 » montré par des silhouettes, dont certaines colorées.",
        "La proportion (ex. 3 sur 10, ou 30 %)", "Ce qu'elle représente",
        dict(titre="1 sur 4", texte="des Français pratique un instrument de musique")),
    "chronologie": InfoModele(
        "Frise chronologique", "Des dates reliées sur une ligne du temps.",
        "Titre de la frise", "Une date par ligne : Date : événement (ou [visuel] Date : événement)",
        dict(titre="La conquête spatiale", texte="[clipart:satellite] 1957 : Spoutnik\n"
                                                "[clipart:astronaute] 1969 : Premiers pas sur la Lune\n"
                                                "[clipart:fusee] 1998 : Station spatiale")),
    "personnage": InfoModele(
        "Personnage qui parle", "Un personnage avec une bulle de parole ou de pensée.",
        "Titre (facultatif)", "Contenu de la bulle : texte, ou [visuel] puis texte",
        dict(titre="", image="personne:femme,pensive,lunettes",
             texte="Et si on automatisait tout ça ?")),
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
            if ref.startswith(("icone:", "clipart:", "personne:")) or re.search(r"[\\/]|\.(svg|png|jpe?g|webp|bmp|gif)$", ref, re.I):
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
        corps = self.ligne(a, b, courbure=min(long * 0.06, self.a * 4) * self.rng.choice([-1, 1]))
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


PALETTE = [(91, 141, 239), (242, 166, 90), (108, 194, 139), (232, 105, 125), (155, 126, 222), (76, 195, 201),
           (246, 205, 76), (141, 153, 174)]
NOMBRE = r"(-?\d[\d\s\u202f\u00a0]*(?:[.,]\d+)?)"


def _nombre(texte: str) -> float | None:
    m = re.search(NOMBRE, texte)
    if not m:
        return None
    try:
        return float(re.sub(r"[\s\u202f\u00a0]", "", m.group(1)).replace(",", "."))
    except ValueError:
        return None


def _rectangle_tremble(cr: Crayon, x0, y0, x1, y1) -> np.ndarray:
    pts = np.concatenate([cr.ligne((x0, y1), (x0, y0)), cr.ligne((x0, y0), (x1, y0))[1:],
                          cr.ligne((x1, y0), (x1, y1))[1:], cr.ligne((x1, y1), (x0, y1))[1:]])
    return np.vstack([pts, pts[:1]])


def _forme(points, remplissage, ep) -> Chemin:
    return Chemin([np.asarray(points, float)], [True], (30, 30, 30), ep, remplissage, trait_encre=True)


def modele_graphique(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    el, haut = _titre_haut(fab, sc.titre)
    elements.append(el)
    donnees = []
    for _, ligne in analyser_items(sc.texte)[:8]:
        if ":" in ligne:
            libelle, valeur = ligne.rsplit(":", 1)
        else:
            m = re.search(NOMBRE, ligne)
            libelle, valeur = (ligne[:m.start()], ligne[m.start():]) if m else (ligne, "")
        v = _nombre(valeur)
        if v is not None:
            donnees.append((libelle.strip(), valeur.strip(), v))
    if not donnees:
        return elements + [fab.texte("(ajoutez des lignes « Libellé : valeur »)", R * 0.05, W * 0.8)
                           .placer(cx=W / 2, cy=H / 2)]
    n = len(donnees)
    t_lab, t_val = min(R * 0.055, (W - 2 * fab.mx) / n * 0.2), R * 0.05
    bas = H - fab.my - t_lab * 2.6
    x0, x1 = fab.mx + R * 0.04, W - fab.mx
    hmax = bas - haut - t_val * 1.8
    elements.append(fab.traits([cr.ligne((x0, haut + t_val), (x0, bas)), cr.ligne((x0, bas), (x1, bas))]))
    vmax = max(abs(v) for *_, v in donnees) or 1
    col = (x1 - x0) / n
    larg = col * 0.58
    for i, (libelle, brut, v) in enumerate(donnees):
        cx = x0 + col * (i + 0.5)
        h = max(fab.trait * 2, hmax * abs(v) / vmax)
        barre = _forme(_rectangle_tremble(cr, cx - larg / 2, bas - h, cx + larg / 2, bas), PALETTE[i % len(PALETTE)],
                       fab.trait)
        elements.append(fab.dessin([barre]))
        val = fab.texte(brut, t_val, col)
        if val is not None:
            elements.append(val.placer(cx=cx, y=bas - h - val.hauteur - R * 0.005))
        lab = fab.texte(libelle, t_lab, col * 0.95, lignes_max=2)
        if lab is not None:
            elements.append(lab.placer(cx=cx, y=bas + R * 0.01))
    return elements


def _silhouette(cx, cy, s, couleur, ep) -> list[Chemin]:
    """Pictogramme de personne (tête + buste) dans un carré de côté s centré en (cx, cy)."""
    t = np.linspace(0, 2 * np.pi, 40)
    tete = np.stack([cx + s * .17 * np.cos(t), cy - s * .22 + s * .17 * np.sin(t)], axis=1)
    a = np.linspace(np.pi, 2 * np.pi, 30)
    epaules = np.stack([cx + s * .32 * np.cos(a), cy + s * .45 + s * .42 * np.sin(a)], axis=1)
    buste = np.vstack([epaules, [[cx + s * .32, cy + s * .45], [cx - s * .32, cy + s * .45]], epaules[:1]])
    return [_forme(np.vstack([tete, tete[:1]]), couleur, ep), _forme(buste, couleur, ep)]


def modele_proportion(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    elements = []
    source = f"{sc.titre} {sc.texte}"
    m = re.search(r"(\d+)\s*(?:sur|/|personnes? sur)\s*(\d+)", source)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
    else:
        p = re.search(r"(\d+(?:[.,]\d+)?)\s*%", source)
        x, y = (round(float(p.group(1).replace(",", ".")) / 10), 10) if p else (1, 4)
    if y > 20:  # au-delà, on ramène à 10 silhouettes
        x, y = round(x * 10 / y), 10
    x = max(0, min(x, y))
    el, haut = _titre_haut(fab, sc.titre or f"{x} sur {y}", R * 0.12)
    elements.append(el)
    legende = fab.texte(sc.texte, R * 0.065, W - 2 * fab.mx, lignes_max=2)
    bas = H - fab.my - (legende.hauteur + R * 0.04 if legende else 0)
    cols = y if y <= 10 else (y + 1) // 2
    lignes = 1 if y <= 10 else 2
    if fab.vertical and y > 5:
        cols, lignes = 5, (y + 4) // 5
    s = min((W - 2 * fab.mx) / cols, (bas - haut) / lignes * 0.9, R * 0.34)
    total_l = s * cols
    for i in range(y):
        r_, c_ = divmod(i, cols)
        cx = (W - total_l) / 2 + s * (c_ + 0.5)
        cy = haut + ((bas - haut) - s * lignes) / 2 + s * (r_ + 0.5)
        couleur = PALETTE[3] if i < x else (222, 222, 222)
        elements.append(fab.dessin(_silhouette(cx, cy, s * 0.9, couleur, fab.trait)))
    if legende is not None:
        elements.append(legende.placer(cx=W / 2, y=bas + R * 0.03))
    return elements


def modele_chronologie(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    el, haut = _titre_haut(fab, sc.titre)
    elements.append(el)
    items = []
    for visuel, ligne in analyser_items(sc.texte)[:6]:
        date, _, evenement = ligne.partition(":")
        items.append((visuel, date.strip(), evenement.strip()))
    if not items:
        return elements
    n = len(items)
    if not fab.vertical:
        y_axe = haut + (H - fab.my - haut) * 0.52
        x0, x1 = fab.mx, W - fab.mx
        elements.append(fab.traits(cr.fleche((x0, y_axe), (x1, y_axe))))
        col = (x1 - x0 - R * 0.05) / n
        for i, (visuel, date, evt) in enumerate(items):
            cx = x0 + col * (i + 0.5)
            elements.append(fab.dessin([_forme(_cercle_plein(cx, y_axe, R * 0.018), PALETTE[i % len(PALETTE)],
                                               fab.trait)]))
            d = fab.texte(date, R * 0.06, col * 0.95)
            if d is not None:
                elements.append(d.placer(cx=cx, y=y_axe - R * 0.03 - d.hauteur))
            if visuel:
                taille = min(col * 0.6, (y_axe - haut) - (d.hauteur if d else 0) - R * 0.06)
                vis = _visuel_centre(fab, visuel, cx, (d.y if d else y_axe) - taille / 2 - R * 0.01, taille, taille)
                if vis is not None:
                    elements.append(vis)
            e = fab.texte(evt, R * 0.045, col * 0.92, lignes_max=3)
            if e is not None:
                elements.append(e.placer(cx=cx, y=y_axe + R * 0.035))
    else:
        x_axe = fab.mx + R * 0.12
        y0, y1 = haut, H - fab.my
        elements.append(fab.traits(cr.fleche((x_axe, y0), (x_axe, y1))))
        ligne = (y1 - y0 - R * 0.05) / n
        for i, (visuel, date, evt) in enumerate(items):
            cy = y0 + ligne * (i + 0.5)
            elements.append(fab.dessin([_forme(_cercle_plein(x_axe, cy, R * 0.022), PALETTE[i % len(PALETTE)],
                                               fab.trait)]))
            d = fab.texte(date, R * 0.07, W - x_axe - fab.mx, aligne="gauche")
            e = fab.texte(evt, R * 0.055, W - x_axe - fab.mx - R * 0.05, lignes_max=2, aligne="gauche")
            hauteur = (d.hauteur if d else 0) + (e.hauteur if e else 0)
            y = cy - hauteur / 2
            if d is not None:
                elements.append(d.placer(x=x_axe + R * 0.05, y=y))
                y += d.hauteur
            if e is not None:
                elements.append(e.placer(x=x_axe + R * 0.05, y=y))
    return elements


def _cercle_plein(cx, cy, r):
    t = np.linspace(0, 2 * np.pi, 36)
    pts = np.stack([cx + r * np.cos(t), cy + r * np.sin(t)], axis=1)
    return np.vstack([pts, pts[:1]])


def _bulle(cr: Crayon, x0, y0, x1, y1, pointe, pensee: bool) -> list[np.ndarray]:
    """Contour de bulle (parole : rectangle arrondi + pointe ; pensée : nuage + petites bulles)."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    if pensee:
        t = np.linspace(0, 2 * np.pi, 160)
        festons = 1 + 0.045 * np.abs(np.sin(t * 7))
        contour = np.stack([cx + rx * np.cos(t) * festons, cy + ry * np.sin(t) * festons], axis=1)
        traits = [contour]
        px, py = pointe
        bx, by = cx + (px - cx) * 0.55, cy + ry * 0.95
        for k, f in enumerate((0.35, 0.65, 0.88)):
            x = bx + (px - bx) * f
            y = by + (py - by) * f
            r = ry * (0.16 - 0.04 * k)
            tt = np.linspace(0, 2 * np.pi, 30)
            traits.append(np.stack([x + r * np.cos(tt), y + r * np.sin(tt)], axis=1))
        return traits
    r = min(rx, ry) * 0.35
    coins = []
    for (ax, ay, a0) in ((x1 - r, y0 + r, -np.pi / 2), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, np.pi / 2),
                         (x0 + r, y0 + r, np.pi)):
        a = np.linspace(a0, a0 + np.pi / 2, 10)
        coins.append(np.stack([ax + r * np.cos(a), ay + r * np.sin(a)], axis=1))
    contour = np.vstack(coins + [coins[0][:1]])
    # pointe dirigée vers le personnage, partant du bord le plus proche
    px, py = pointe
    if py > y1 + ry * 0.3:                     # personnage en dessous
        bx_, by_ = min(max(px, x0 + r * 2), x1 - r * 2), y1 - 1
        larg = (min(rx * 0.12, r), 0)
    elif px < x0:                               # personnage à gauche
        bx_, by_ = x0 + 1, min(max(py, y0 + r * 2), y1 - r * 1.5)
        larg = (0, min(ry * 0.18, r))
    else:                                       # à droite
        bx_, by_ = x1 - 1, min(max(py, y0 + r * 2), y1 - r * 1.5)
        larg = (0, min(ry * 0.18, r))
    # longueur de la pointe limitée : elle désigne le personnage sans le toucher
    dx, dy = px - bx_, py - by_
    d = math.hypot(dx, dy) or 1
    lmax = max(rx, ry) * 0.6
    ex, ey = bx_ + dx * min(1, lmax / d), by_ + dy * min(1, lmax / d)
    q = [(bx_ - larg[0], by_ - larg[1]), (ex, ey), (bx_ + larg[0], by_ + larg[1])]
    return [cr._tremble(contour, 0.4), np.array(q, float)]


def modele_personnage(fab, sc: Scene):
    W, H, R = fab.W, fab.H, fab.R
    cr = _crayon(fab, sc)
    elements = []
    haut = fab.my
    if sc.titre.strip():
        el, haut = _titre_haut(fab, sc.titre)
        elements.append(el)
    source = sc.image.strip() or "personne:" + (sc.titre or sc.texte or "content")[:20]
    items = analyser_items(sc.texte)
    visuel_bulle = items[0][0] if items else None
    texte_bulle = "\n".join(l for _, l in items).strip()
    pensee = bool(re.search(r"pensi|pense|reflech|reve|medit", source.lower())) or texte_bulle.startswith(("…", "..."))
    if fab.vertical:
        boite_p = (fab.mx, H * 0.52, W - 2 * fab.mx, H * 0.48 - fab.my)
        zone_b = (fab.mx, haut + R * 0.02, W - fab.mx, H * 0.47)
    else:
        boite_p = (fab.mx, haut + (H - haut) * 0.18, W * 0.42 - fab.mx, H - fab.my - haut - (H - haut) * 0.18)
        zone_b = (W * 0.46, haut + R * 0.02, W - fab.mx, H * 0.66)
    bx, by, bw, bh = boite_p
    perso = fab.visuel(source, bw, bh)
    if perso is not None:
        perso.placer(cx=bx + bw / 2, y=by + bh - perso.hauteur)
        elements.append(perso)
        tete = (perso.x + perso.largeur * (0.62 if not fab.vertical else 0.5), perso.y + perso.hauteur * 0.12)
    else:
        tete = (bx + bw / 2, by)
    # contenu de la bulle
    zx0, zy0, zx1, zy1 = zone_b
    larg_max = (zx1 - zx0) * 0.8
    contenu = []
    if visuel_bulle:
        v = fab.visuel(visuel_bulle, larg_max * 0.5, (zy1 - zy0) * 0.42)
        if v is not None:
            contenu.append(v)
    t = fab.texte(texte_bulle, R * 0.06, larg_max, lignes_max=4)
    if t is not None:
        contenu.append(t)
    if not contenu:
        return elements
    h_contenu = sum(c.hauteur for c in contenu) + R * 0.02 * (len(contenu) - 1)
    l_contenu = max(c.largeur for c in contenu)
    marge = R * (0.07 if pensee else 0.05)
    cxb = (zx0 + zx1) / 2
    cyb = zy0 + (zy1 - zy0) / 2
    x0, x1 = cxb - l_contenu / 2 - marge, cxb + l_contenu / 2 + marge
    y0, y1 = cyb - h_contenu / 2 - marge, cyb + h_contenu / 2 + marge
    pointe = (tete[0] + (R * 0.06 if not fab.vertical else 0), tete[1] - R * 0.02) if not fab.vertical else \
        (tete[0], tete[1] - R * 0.04)
    elements.append(fab.traits(_bulle(cr, x0, y0, x1, y1, pointe, pensee)))
    y = cyb - h_contenu / 2
    for c in contenu:
        elements.append(c.placer(cx=cxb, y=y))
        y += c.hauteur + R * 0.02
    return elements


FONCTIONS = {
    "libre": modele_libre, "titre": modele_titre, "liste": modele_liste, "etapes": modele_etapes,
    "comparaison": modele_comparaison, "chiffre": modele_chiffre, "citation": modele_citation,
    "fin": modele_fin, "graphique": modele_graphique, "proportion": modele_proportion,
    "chronologie": modele_chronologie, "personnage": modele_personnage,
}


def construire(fab, scene: Scene):
    return [e for e in FONCTIONS.get(scene.modele, modele_libre)(fab, scene) if e is not None]


def scene_exemple(code: str) -> Scene:
    info = MODELES.get(code, MODELES["libre"])
    return Scene(modele=code, **info.exemple)
