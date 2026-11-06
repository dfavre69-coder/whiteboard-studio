"""Extraction de l'encre d'une image et calcul de l'ordre de tracé.

Principe : l'image est découpée en petites cellules. Les cellules qui
contiennent de l'encre sont parcourues en suivant les traits (parcours en
profondeur qui préfère continuer tout droit), bloc par bloc, en allant
chaque fois au bloc le plus proche de la main. On obtient ainsi un ordre
qui ressemble à celui d'une personne qui dessine.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

VOISINS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def masque_encre(rgb: np.ndarray, sensibilite: int = 50) -> np.ndarray:
    """Pixels à « dessiner » dans une image RGB (tableau booléen).

    sensibilite : 0 = seulement les traits marqués, 100 = un maximum de détails.
    """
    s = max(0, min(100, int(sensibilite))) / 100
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)
    h, w = gris.shape
    bloc = max(11, (min(h, w) // 40) | 1)
    c = 26 - 22 * s
    contours = cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                     cv2.THRESH_BINARY_INV, bloc, c) > 0
    sombres = gris < (60 + 70 * s)
    encre = contours | sombres
    # Suppression des petites taches
    n, etiquettes, stats, _ = cv2.connectedComponentsWithStats(encre.astype(np.uint8), connectivity=8)
    aire_min = int(round(4 + 26 * (1 - s)))
    garder = np.zeros(n, dtype=bool)
    garder[1:] = stats[1:, cv2.CC_STAT_AREA] >= aire_min
    return garder[etiquettes]


def ordre_cellules(encre: np.ndarray, taille: int, depart=(0.0, 0.0),
                   lecture: bool = False) -> list[tuple[int, int]]:
    """Ordre de tracé : liste de cellules (ligne, colonne) de la grille.

    lecture=True : les blocs sont pris de gauche à droite (pour l'écriture).
    """
    h, w = encre.shape
    gh, gw = math.ceil(h / taille), math.ceil(w / taille)
    pad = np.zeros((gh * taille, gw * taille), dtype=bool)
    pad[:h, :w] = encre
    actives = pad.reshape(gh, taille, gw, taille).any(axis=(1, 3))
    if not actives.any():
        return []

    nb, etiquettes = cv2.connectedComponents(actives.astype(np.uint8), connectivity=8)
    blocs: list[np.ndarray] = []
    for i in range(1, nb):
        ys, xs = np.nonzero(etiquettes == i)
        blocs.append(np.stack([ys, xs], axis=1))

    visite = np.zeros_like(actives)
    ordre: list[tuple[int, int]] = []
    pos = np.array([depart[1] / taille, depart[0] / taille])  # (ligne, colonne) en cellules

    if lecture:
        blocs.sort(key=lambda b: (b[:, 1].min(), b[:, 0].min()))
        file_blocs = blocs
    else:
        file_blocs = None

    restants = list(range(len(blocs)))
    while restants:
        if lecture:
            idx = restants.pop(0)
            b = file_blocs[idx]
            # on commence par la cellule la plus à gauche (puis la plus haute)
            j = int(np.lexsort((b[:, 0], b[:, 1]))[0])
        else:
            # bloc dont une cellule est la plus proche de la main
            meilleur, meilleure_d, meilleur_j = 0, float("inf"), 0
            for k, idx in enumerate(restants):
                d2 = ((blocs[idx] - pos) ** 2).sum(axis=1)
                j = int(np.argmin(d2))
                if d2[j] < meilleure_d:
                    meilleur, meilleure_d, meilleur_j = k, float(d2[j]), j
            idx = restants.pop(meilleur)
            b, j = blocs[idx], meilleur_j
        debut = (int(b[j, 0]), int(b[j, 1]))
        _parcours(actives, visite, debut, ordre)
        pos = np.array(ordre[-1], dtype=float)
    return ordre


def _parcours(actives, visite, debut, ordre):
    """Parcours en profondeur qui privilégie la direction courante."""
    gh, gw = actives.shape
    pile = [(debut, (0, 1))]
    while pile:
        (y, x), direction = pile.pop()
        if visite[y, x]:
            continue
        visite[y, x] = True
        ordre.append((y, x))
        candidats = []
        for dy, dx in VOISINS:
            ny, nx = y + dy, x + dx
            if 0 <= ny < gh and 0 <= nx < gw and actives[ny, nx] and not visite[ny, nx]:
                # produit scalaire : plus il est grand, plus on va tout droit
                score = dy * direction[0] + dx * direction[1]
                candidats.append((score, (ny, nx), (dy, dx)))
        # le meilleur candidat doit sortir de la pile en premier → placé en dernier
        candidats.sort(key=lambda c: c[0])
        for _, cell, dirn in candidats:
            pile.append((cell, dirn))
