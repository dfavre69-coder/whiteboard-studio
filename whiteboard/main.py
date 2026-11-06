"""La main qui tient le feutre.

La main par défaut est dessinée par le programme (aucun fichier externe,
aucun droit d'auteur). On peut la remplacer par un PNG transparent
personnalisé, par exemple la photo détourée de sa propre main.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PEAU = (241, 196, 160)
PEAU_OMBRE = (226, 176, 140)
CONTOUR = (120, 72, 48)
MANCHE = (52, 86, 140)
MANCHE_OMBRE = (38, 64, 108)
FEUTRE = (40, 44, 52)
ETIQUETTE = (236, 236, 236)

# Géométrie de référence (pour une vidéo de 1080 pixels de haut).
# Le bras est prolongé jusqu'au bord de l'image : sa longueur dépend de la vidéo,
# pour qu'il sorte toujours de l'écran, où que soit la main.
HAUTEUR_REF = 1240  # hauteur minimale de l'image de la main
POINTE_REF = (30, 470)
HAUTEUR_MAIN_PERSO = 560  # hauteur à laquelle on ramène une main personnalisée
ECHELLE_MAIN = 0.85  # taille de la main par rapport au dessin


def _capsule(a, b, r, n=24):
    """Polygone d'un segment arrondi de a à b, de rayon r."""
    ax, ay = a
    bx, by = b
    ang = math.atan2(by - ay, bx - ax)
    pts = []
    for i in range(n + 1):
        t = ang - math.pi / 2 + math.pi * i / n
        pts.append((bx + r * math.cos(t), by + r * math.sin(t)))
    for i in range(n + 1):
        t = ang + math.pi / 2 + math.pi * i / n
        pts.append((ax + r * math.cos(t), ay + r * math.sin(t)))
    return pts


def _ellipse_pts(cx, cy, rx, ry, angle=0.0, n=72):
    a = math.radians(angle)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)))
    return pts


def _forme(d: ImageDraw.ImageDraw, pts, remplissage, contour, epaisseur):
    d.polygon(pts, fill=remplissage)
    d.line(pts + [pts[0]], fill=contour, width=epaisseur, joint="curve")


@lru_cache(maxsize=4)
def main_par_defaut(gauche: bool = False, hauteur: int = HAUTEUR_REF) -> tuple[Image.Image, tuple[int, int]]:
    """Renvoie (image RGBA, position de la pointe du feutre) à la taille de référence.

    `hauteur` : hauteur de l'image ; le bras descend jusqu'en bas.
    """
    hauteur = max(HAUTEUR_REF, int(hauteur))
    k = 2  # sur-échantillonnage pour des bords lisses
    larg_ref = _largeur_pour(hauteur)
    W, H = larg_ref * k, hauteur * k
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    e = 5 * k

    def S(pts):
        return [(x * k, y * k) for x, y in pts]

    px, py = POINTE_REF
    ang = math.radians(-50)
    deg = math.degrees(ang)
    dx, dy = math.cos(ang), math.sin(ang)   # le long du feutre, vers l'arrière
    nx, ny = -dy, dx                        # perpendiculaire, côté de la main

    def P(t, o=0.0):
        """Point à la distance t de la pointe, décalé de o vers la main."""
        return (px + dx * t + nx * o, py + dy * t + ny * o)

    def rect(origine, ux, uy, longueur, demi):
        vx, vy = -uy, ux
        ox, oy = origine
        return [(ox + vx * demi, oy + vy * demi),
                (ox + ux * longueur + vx * demi, oy + uy * longueur + vy * demi),
                (ox + ux * longueur - vx * demi, oy + uy * longueur - vy * demi),
                (ox - vx * demi, oy - vy * demi)]

    # --- bras et manche ---------------------------------------------------
    poignet = P(222, 80)
    bx, by = 0.50, 0.866  # direction du bras : vers le bas à droite
    _forme(d, S(rect(poignet, bx, by, hauteur * 2, 80)), MANCHE, MANCHE_OMBRE, e)
    c0 = (poignet[0] + bx * 45, poignet[1] + by * 45)
    _forme(d, S(rect(c0, bx, by, 70, 86)), (70, 108, 166), MANCHE_OMBRE, e)
    d.line(S([(c0[0] + bx * 170 - by * 25, c0[1] + by * 170 + bx * 25),
              (c0[0] + bx * 320 - by * 8, c0[1] + by * 320 + bx * 8)]), fill=MANCHE_OMBRE, width=4 * k)

    # --- poing (dos de la main) -------------------------------------------
    cx, cy = P(210, 62)
    _forme(d, S(_ellipse_pts(cx, cy, 100, 82, angle=deg)), PEAU, CONTOUR, e)

    # --- doigts repliés (majeur, annulaire, auriculaire) ------------------
    for t0, t1, o, r in [(190, 118, 44, 23), (195, 132, 82, 22), (190, 148, 114, 20)]:
        _forme(d, S(_capsule(P(t0, o), P(t1, o), r)), PEAU_OMBRE, CONTOUR, e)

    # --- pouce, de l'autre côté du feutre ---------------------------------
    _forme(d, S(_capsule(P(210, -28), P(108, -26), 21)), PEAU, CONTOUR, e)
    _forme(d, S(_ellipse_pts(*P(100, -25), 11, 9, angle=deg)), (250, 224, 208), (200, 150, 120), 2 * k)

    # --- feutre -----------------------------------------------------------
    def bande(t0, t1, w):
        return [P(t0, w / 2), P(t1, w / 2), P(t1, -w / 2), P(t0, -w / 2)]

    _forme(d, S([P(0), P(26, 12), P(26, -12)]), (25, 25, 25), (10, 10, 10), 2 * k)
    _forme(d, S(bande(26, 62, 30)), (205, 205, 210), (90, 90, 95), 3 * k)
    _forme(d, S(bande(62, 380, 38)), FEUTRE, (15, 15, 20), 3 * k)
    _forme(d, S(bande(255, 330, 34)), ETIQUETTE, (150, 150, 150), 2 * k)
    _forme(d, S(bande(352, 384, 42)), (30, 30, 34), (10, 10, 12), 3 * k)
    d.line(S([P(70, -10), P(240, -10)]), fill=(95, 100, 112), width=4 * k)  # reflet

    # --- index posé sur le feutre -----------------------------------------
    _forme(d, S(_capsule(P(225, 16), P(80, 6), 23)), PEAU, CONTOUR, e)
    _forme(d, S(_ellipse_pts(*P(70, 6), 12, 10, angle=deg)), (250, 224, 208), (200, 150, 120), 2 * k)
    for t in (128, 175):  # plis des phalanges
        d.line(S([P(t, -4), P(t + 4, 20)]), fill=CONTOUR, width=3 * k)

    # --- réduction puis ombre portée douce -------------------------------
    img = img.resize((larg_ref, hauteur), Image.LANCZOS)
    ombre = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ombre.putalpha(img.split()[3].point(lambda a: int(a * 0.20)))
    ombre = ombre.filter(ImageFilter.GaussianBlur(9))
    fond = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fond.alpha_composite(ombre, (16, 20))
    fond.alpha_composite(img)
    img = fond

    tip = POINTE_REF
    if gauche:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
        tip = (larg_ref - 1 - tip[0], tip[1])
    return img, tip


def _largeur_pour(hauteur: int) -> int:
    """Largeur nécessaire pour que le bras (incliné) tienne dans l'image."""
    poignet_x, poignet_y = 330, 380  # position approximative du poignet
    return int(poignet_x + (hauteur - poignet_y) * 0.5 / 0.866 + 80 / 0.866 + 60)


def charger_main(reglage: str, pointe: tuple[int, int] | None, cote_video: int,
                 grand_cote: int | None = None):
    """Prépare la main à l'échelle de la vidéo.

    Renvoie (tableau RGBA numpy, pointe (x, y)).
    """
    echelle = cote_video / 1080 * ECHELLE_MAIN  # cote_video : plus petit côté de la vidéo
    if reglage in ("droite", "gauche", ""):
        # assez long pour que le bras sorte de l'écran même quand la main est tout en haut
        hauteur = POINTE_REF[1] + (grand_cote or cote_video) / echelle + 60
        img, tip = main_par_defaut(reglage == "gauche", int(math.ceil(hauteur / 20) * 20))
    else:
        img = Image.open(reglage).convert("RGBA")
        # Sans indication, la pointe d'une main personnalisée est le point opaque
        # le plus en bas à gauche.
        tip = pointe if pointe else _pointe_auto(img)
        f = HAUTEUR_MAIN_PERSO / img.height
        img = img.resize((max(1, round(img.width * f)), HAUTEUR_MAIN_PERSO), Image.LANCZOS)
        tip = (round(tip[0] * f), round(tip[1] * f))
    if echelle != 1:
        img = img.resize((max(1, round(img.width * echelle)), max(1, round(img.height * echelle))),
                         Image.LANCZOS)
        tip = (round(tip[0] * echelle), round(tip[1] * echelle))
    return np.asarray(img).copy(), tip


def _pointe_auto(img: Image.Image) -> tuple[int, int]:
    a = np.asarray(img.split()[3]) > 128
    ys, xs = np.nonzero(a)
    if len(xs) == 0:
        return (0, img.height - 1)
    i = int(np.argmax(ys.astype(np.int64) - xs))
    return int(xs[i]), int(ys[i])
