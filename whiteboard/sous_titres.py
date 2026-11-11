"""Sous-titres incrustés : la narration s'affiche par petits groupes de mots pendant que la voix la lit.

Beaucoup de Shorts sont regardés sans le son : sans sous-titres, le message est perdu. Deux styles :
- « simple » : le groupe de mots en cours, en couleur d'encre ;
- « karaoke » : le mot en train d'être prononcé passe en couleur d'accent.

Le minutage mot à mot est proportionnel à la longueur des mots (avec un temps de respiration après la
ponctuation) : avec une voix de synthèse au débit régulier, c'est très proche de la réalité.
Un fichier .srt (par groupe) est aussi produit à côté de la vidéo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .projet import Projet

ACCENT = (217, 52, 27)          # couleur du mot en cours (karaoké)
CONTOUR = (255, 255, 255)       # contour clair pour rester lisible sur un dessin
FIN_PHRASE = ".!?;:…"
MOTS_MAX = {"karaoke": 3, "simple": 5}


@dataclass
class Mot:
    texte: str
    debut: float   # secondes, depuis le début de la scène
    fin: float


@dataclass
class Groupe:
    mots: list[Mot] = field(default_factory=list)

    @property
    def debut(self) -> float:
        return self.mots[0].debut

    @property
    def fin(self) -> float:
        return self.mots[-1].fin

    @property
    def texte(self) -> str:
        return " ".join(m.texte for m in self.mots)


def _poids(mot: str) -> tuple[float, float]:
    """(poids de prononciation, poids de pause après) d'un mot."""
    lettres = len(re.sub(r"[^\w]", "", mot))
    pause = 0.0
    if mot.endswith(tuple(FIN_PHRASE)):
        pause = 3.0
    elif mot.endswith(","):
        pause = 1.5
    return max(1.0, lettres + 1.5), pause


def decouper(narration: str, debut: float, duree: float, style: str = "karaoke",
             mots_max: int | None = None) -> list[Groupe]:
    """Répartit la narration en groupes de mots minutés sur [debut, debut + duree]."""
    mots = narration.replace("\n", " ").split()
    if not mots or duree <= 0:
        return []
    mots_max = mots_max or MOTS_MAX.get(style, 3)
    poids = [_poids(m) for m in mots]
    total = sum(p + q for p, q in poids)
    if total <= 0:
        return []
    echelle = duree / total
    # La voix s'arrête un peu avant la fin de la scène : on garde les derniers mots affichés jusque-là.
    t = debut
    minutes: list[Mot] = []
    for mot, (p, q) in zip(mots, poids):
        fin = t + p * echelle
        minutes.append(Mot(mot, t, fin))
        t = fin + q * echelle
    groupes: list[Groupe] = []
    courant = Groupe()
    for m in minutes:
        courant.mots.append(m)
        long = len(courant.mots)
        if long >= mots_max or (long >= 2 and m.texte.endswith(tuple(FIN_PHRASE))):
            groupes.append(courant)
            courant = Groupe()
    if courant.mots:
        if len(courant.mots) == 1 and groupes and len(groupes[-1].mots) < mots_max + 1:
            groupes[-1].mots.extend(courant.mots)   # pas de mot orphelin
        else:
            groupes.append(courant)
    # Chaque groupe reste affiché jusqu'au début du suivant (pas d'écran vide entre deux groupes).
    for g, suivant in zip(groupes, groupes[1:]):
        g.mots[-1].fin = suivant.debut
    return groupes


def groupe_courant(groupes: list[Groupe], t: float) -> tuple[Groupe | None, int]:
    """Le groupe visible à l'instant t et l'indice du mot en cours (-1 si aucun)."""
    for g in groupes:
        if g.debut <= t < g.fin:
            indice = len(g.mots) - 1
            for i, m in enumerate(g.mots):
                if t < m.fin:
                    indice = i
                    break
            return g, indice
    return None, -1


def _horodatage(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(entrees: list[tuple[float, list[Groupe]]]) -> str:
    """Texte d'un fichier SRT à partir de (début absolu de la scène, groupes de la scène)."""
    lignes, n = [], 0
    for t0, groupes in entrees:
        for g in groupes:
            n += 1
            lignes += [str(n), f"{_horodatage(t0 + g.debut)} --> {_horodatage(t0 + g.fin)}", g.texte, ""]
    return "\n".join(lignes)


class RenduSousTitres:
    """Dessine le groupe de mots en cours sur une image de la vidéo (rendus mis en cache)."""

    def __init__(self, projet: Projet):
        from .rendu import couleur, police

        self.p = projet
        W, H = projet.largeur, projet.hauteur
        R = min(W, H)
        vertical = H > W * 1.15
        self.style = projet.sous_titres
        self.taille = int(R * (0.075 if vertical else 0.058))
        self.police = police(projet, self.taille)
        self.encre = couleur(projet.encre)
        self.contour = max(2, int(self.taille / 9))
        self.largeur_max = int(W * (0.86 if vertical else 0.8))
        # Bande réservée par rendu.zone_sure : sous le contenu, au-dessus de l'interface de YouTube.
        self.cy = int(H * (0.775 if vertical else 0.94))
        self.cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    def _rendre(self, groupe: Groupe, actif: int) -> tuple[np.ndarray, np.ndarray]:
        fnt, sw = self.police, self.contour
        mots = [m.texte for m in groupe.mots]
        espace = fnt.getlength(" ")
        largeurs = [fnt.getlength(m) for m in mots]
        # Retour à la ligne si le groupe est trop large pour l'écran
        lignes: list[list[int]] = [[]]
        larg = 0.0
        for i, lw in enumerate(largeurs):
            ajout = lw + (espace if lignes[-1] else 0)
            if lignes[-1] and larg + ajout > self.largeur_max:
                lignes.append([i])
                larg = lw
            else:
                lignes[-1].append(i)
                larg += ajout
        interligne = int(self.taille * 1.25)
        w = int(max(sum(largeurs[i] for i in l) + espace * (len(l) - 1) for l in lignes)) + 4 * sw + 8
        h = interligne * len(lignes) + 4 * sw + int(self.taille * 0.3)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, l in enumerate(lignes):
            lw = sum(largeurs[i] for i in l) + espace * (len(l) - 1)
            x = (w - lw) / 2
            y = 2 * sw + li * interligne
            for i in l:
                couleur = ACCENT if (self.style == "karaoke" and i == actif) else self.encre
                d.text((x, y), mots[i], font=fnt, fill=couleur + (255,), stroke_width=sw, stroke_fill=CONTOUR + (255,))
                x += largeurs[i] + espace
        a = np.asarray(img)
        return a[..., :3].copy(), a[..., 3].astype(np.float32) / 255

    def appliquer(self, image: np.ndarray, groupes: list[Groupe], t: float, indice_scene: int = 0) -> np.ndarray:
        """Incruste le groupe de mots en cours (modifie et renvoie l'image)."""
        g, actif = groupe_courant(groupes, t)
        if g is None:
            return image
        cle = (indice_scene, id(g), actif if self.style == "karaoke" else -1)
        if cle not in self.cache:
            self.cache[cle] = self._rendre(g, actif)
        rgb, alpha = self.cache[cle]
        h, w = alpha.shape
        H, W = image.shape[:2]
        x0, y0 = (W - w) // 2, self.cy - h // 2
        ax0, ay0, ax1, ay1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
        if ax1 <= ax0 or ay1 <= ay0:
            return image
        sx, sy = ax0 - x0, ay0 - y0
        a = alpha[sy:sy + (ay1 - ay0), sx:sx + (ax1 - ax0)][..., None]
        zone = image[ay0:ay1, ax0:ax1].astype(np.float32)
        image[ay0:ay1, ax0:ax1] = (rgb[sy:sy + (ay1 - ay0), sx:sx + (ax1 - ax0)] * a + zone * (1 - a)).astype(np.uint8)
        return image
