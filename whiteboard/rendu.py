"""Mise en page des scènes et fabrication des images de la vidéo."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .main import charger_main
from .projet import Projet, Scene
from .traits import masque_encre, ordre_cellules
from .vecteur import (_ligne, _reechantillonner, charger_vecteur, est_clipart, est_icone, est_vectoriel,
                      rendre_vecteur)
from .video import EcrivainVideo, PisteAudio, duree_audio

DOSSIER_ASSETS = Path(__file__).parent / "assets"
POLICE_FOURNIE = DOSSIER_ASSETS / "polices" / "PatrickHand-Regular.ttf"

DUREE_ENTREE = 0.35      # la main entre dans l'écran
DUREE_SORTIE = 0.45      # la main sort
DUREE_COULEUR = 0.8      # apparition des couleurs
DUREE_TRANSITION = 0.6
DECALAGE_VOIX = 0.25     # la voix démarre peu après le début de la scène


class Annule(Exception):
    pass


def couleur(hexa: str) -> tuple[int, int, int]:
    hexa = hexa.lstrip("#")
    return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def police(projet: Projet, taille: int) -> ImageFont.FreeTypeFont:
    for chemin in (projet.police, str(POLICE_FOURNIE)):
        if chemin and Path(chemin).exists():
            return ImageFont.truetype(chemin, taille)
    return ImageFont.load_default(size=taille)


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------
@dataclass
class Element:
    """Une zone à dessiner : un texte, une image, un dessin vectoriel ou un trait."""
    x: int
    y: int
    croquis: np.ndarray            # RGB : l'élément dessiné au trait
    couverture: np.ndarray         # bool : pixels recouverts par le trait
    finale: np.ndarray | None      # RGB : version en couleur, ou None
    cellules: list[tuple[int, int]] = field(default_factory=list)
    taille_cellule: int = 8
    points: np.ndarray | None = None   # dessin vectoriel : parcours (x, y, rayon) de la main
    lecture: bool = False              # texte : tracé de gauche à droite

    @property
    def largeur(self) -> int:
        return self.croquis.shape[1]

    @property
    def hauteur(self) -> int:
        return self.croquis.shape[0]

    def placer(self, x: float | None = None, y: float | None = None,
               cx: float | None = None, cy: float | None = None) -> "Element":
        """Positionne l'élément par son coin (x, y) ou par son centre (cx, cy)."""
        if cx is not None:
            self.x = int(round(cx - self.largeur / 2))
        if x is not None:
            self.x = int(round(x))
        if cy is not None:
            self.y = int(round(cy - self.hauteur / 2))
        if y is not None:
            self.y = int(round(y))
        return self


@dataclass
class ScenePreparee:
    scene: Scene
    elements: list[Element]
    duree_dessin: float
    pause: float
    duree_voix: float = 0.0
    etapes: list[tuple[int, int, int]] = field(default_factory=list)   # (élément, a, b) ou (-1, x, y) déplacement

    @property
    def duree(self) -> float:
        return DUREE_ENTREE + self.duree_dessin + self.pause


def _couper_lignes(texte: str, fnt: ImageFont.FreeTypeFont, largeur_max: int) -> list[str]:
    lignes: list[str] = []
    for paragraphe in texte.split("\n"):
        mots, courante = paragraphe.split(), ""
        if not mots:
            lignes.append("")
            continue
        for mot in mots:
            essai = (courante + " " + mot).strip()
            if fnt.getlength(essai) <= largeur_max or not courante:
                courante = essai
            else:
                lignes.append(courante)
                courante = mot
        lignes.append(courante)
    return lignes


def _composer(alpha: np.ndarray, fond, encre) -> np.ndarray:
    f = np.array(fond, dtype=np.float32)
    e = np.array(encre, dtype=np.float32)
    a = alpha[..., None]
    return (f * (1 - a) + e * a).astype(np.uint8)


def _recadrer(img: Image.Image, fond: tuple[int, int, int]) -> Image.Image:
    """Retire les marges vides (transparentes ou couleur du fond) autour d'une image."""
    a = np.asarray(img)
    plein = a[..., 3] > 10
    diff = np.abs(a[..., :3].astype(np.int16) - np.array(fond, dtype=np.int16)).max(axis=2) > 18
    utile = plein & diff
    ys, xs = np.nonzero(utile)
    if len(xs) == 0:
        return img
    m = max(4, int(0.02 * max(img.size)))
    return img.crop((max(0, xs.min() - m), max(0, ys.min() - m),
                     min(img.width, xs.max() + m + 1), min(img.height, ys.max() + m + 1)))


class Fabrique:
    """Fabrique les éléments d'une scène (textes, visuels, traits) à la bonne échelle."""

    def __init__(self, projet: Projet, scene: Scene):
        self.p, self.scene = projet, scene
        self.W, self.H = projet.largeur, projet.hauteur
        self.R = min(self.W, self.H)            # référence des tailles (marche aussi en vertical)
        self.mx, self.my = int(self.W * 0.06), int(self.H * 0.06)
        self.fond, self.encre = couleur(projet.fond), couleur(projet.encre)
        self.trait = max(2.0, self.R * 0.0045)  # épaisseur du feutre
        self.vertical = self.H > self.W * 1.15

    # --- textes ------------------------------------------------------------
    def texte(self, texte: str, taille: float, largeur_max: float, lignes_max: int | None = None,
              aligne: str = "centre", couleur_texte=None) -> Element | None:
        texte = texte.strip()
        if not texte:
            return None
        taille = int(taille)
        fnt = police(self.p, taille)
        lignes = _couper_lignes(texte, fnt, int(largeur_max))
        while lignes_max and len(lignes) > lignes_max and taille > 14:
            taille = int(taille * 0.9)
            fnt = police(self.p, taille)
            lignes = _couper_lignes(texte, fnt, int(largeur_max))
        interligne = int(taille * 1.2)
        largeur = max(1, int(max(fnt.getlength(l) for l in lignes)) + 8)
        hauteur = interligne * len(lignes) + int(taille * 0.35)
        alpha = Image.new("L", (largeur, hauteur), 0)
        d = ImageDraw.Draw(alpha)
        for i, l in enumerate(lignes):
            x = 4 if aligne == "gauche" else (largeur - fnt.getlength(l)) / 2
            d.text((x, i * interligne), l, font=fnt, fill=255)
        a = np.asarray(alpha).astype(np.float32) / 255
        return Element(0, 0, _composer(a, self.fond, couleur_texte or self.encre), a > 0.08, None,
                       taille_cellule=max(3, round(taille / 7)), lecture=True)

    # --- images et dessins vectoriels -------------------------------------
    def visuel(self, source: str, largeur_max: float, hauteur_max: float) -> Element | None:
        """Image (PNG, JPG…), fichier SVG ou icône de la bibliothèque (« icone:nom »)."""
        source = (source or "").strip()
        if not source or largeur_max < 8 or hauteur_max < 8:
            return None
        if est_vectoriel(source):
            if not (est_icone(source) or est_clipart(source)) and not Path(source).exists():
                return None
            try:
                chemins = charger_vecteur(source)
            except Exception:  # noqa: BLE001  (icône inconnue, SVG illisible)
                return None
            r = rendre_vecteur(chemins, int(largeur_max), int(hauteur_max), self.trait * 0.8,
                               self.trait * 2.2, self.fond, self.encre,
                               couleur=self.scene.mode == "couleur")
            if r is None:
                return None
            return Element(0, 0, _composer(r.croquis_alpha, self.fond, self.encre),
                           r.croquis_alpha > 0.03, r.finale, points=r.points)
        if not Path(source).exists():
            return None
        img = _recadrer(Image.open(source).convert("RGBA"), self.fond)
        f = min(largeur_max / img.width, hauteur_max / img.height)
        w, h = max(1, int(img.width * f)), max(1, int(img.height * f))
        img = img.resize((w, h), Image.LANCZOS)
        fond = Image.new("RGBA", (w, h), self.fond + (255,))
        fond.alpha_composite(img)
        rgb = np.asarray(fond.convert("RGB"))
        encre = masque_encre(rgb, self.scene.sensibilite)
        a = cv2.GaussianBlur(encre.astype(np.float32), (0, 0), 0.7)
        finale = rgb.copy() if self.scene.mode == "couleur" else None
        return Element(0, 0, _composer(a, self.fond, self.encre), a > 0.03, finale,
                       taille_cellule=max(5, round(self.R / 90)))

    # --- traits à main levée ----------------------------------------------
    def traits(self, polylignes: list, epaisseur: float | None = None) -> Element | None:
        """Traits en coordonnées écran (flèches, soulignés, cercles…)."""
        polys = [np.asarray(p, dtype=np.float64) for p in polylignes if len(p) >= 2]
        if not polys:
            return None
        ep = epaisseur or self.trait
        marge = ep + 2
        tous = np.concatenate(polys)
        ox, oy = math.floor(tous[:, 0].min() - marge), math.floor(tous[:, 1].min() - marge)
        w = int(math.ceil(tous[:, 0].max() + marge)) - ox + 1
        h = int(math.ceil(tous[:, 1].max() + marge)) - oy + 1
        k = 2
        alpha = Image.new("L", (w * k, h * k), 0)
        d = ImageDraw.Draw(alpha)
        points = []
        r = ep / 2 + 1.5
        for p in polys:
            loc = p - (ox, oy)
            _ligne(d, loc * k, ep * k, 255)
            for q in _reechantillonner(loc, max(1.2, r * 0.7)):
                points.append((q[0], q[1], r))
        a = np.asarray(alpha.resize((w, h), Image.LANCZOS)).astype(np.float32) / 255
        return Element(ox, oy, _composer(a, self.fond, self.encre), a > 0.03, None,
                       points=np.array(points, dtype=np.float32).reshape(-1, 3))


def _rogner(el: Element, W: int, H: int) -> Element | None:
    """Garde seulement la partie d'un élément qui tient dans l'écran."""
    x0, y0 = max(0, -el.x), max(0, -el.y)
    x1 = min(el.largeur, W - el.x)
    y1 = min(el.hauteur, H - el.y)
    if x1 <= x0 or y1 <= y0:
        return None
    if (x0, y0, x1, y1) == (0, 0, el.largeur, el.hauteur):
        return el
    pts = None
    if el.points is not None:
        pts = el.points.copy()
        pts[:, 0] -= x0
        pts[:, 1] -= y0
        garde = (pts[:, 0] >= 0) & (pts[:, 1] >= 0) & (pts[:, 0] < x1 - x0) & (pts[:, 1] < y1 - y0)
        pts = pts[garde]
    return Element(el.x + x0, el.y + y0, el.croquis[y0:y1, x0:x1], el.couverture[y0:y1, x0:x1],
                   None if el.finale is None else el.finale[y0:y1, x0:x1], [], el.taille_cellule,
                   pts, el.lecture)


def preparer_scene(projet: Projet, scene: Scene) -> ScenePreparee:
    from .modeles import construire

    W, H = projet.largeur, projet.hauteur
    fab = Fabrique(projet, scene)
    elements = [e for e in construire(fab, scene) if e is not None]
    elements = [e for e in (_rogner(e, W, H) for e in elements) if e is not None]

    # Ordre de tracé, élément par élément, en partant de la position de la main
    pas_saut = max(8.0, fab.R / 45)  # longueur d'un pas quand la main se déplace sans dessiner
    main_pos = (W * 0.75, H * 1.0)
    etapes: list[tuple[int, int, int]] = []
    precedent = None

    def deplacer_vers(cx, cy, seuil):
        if precedent is None:
            return
        dist = math.hypot(cx - precedent[0], cy - precedent[1])
        if dist > seuil:
            n = int(dist / pas_saut)
            for k in range(1, n + 1):
                f = k / (n + 1)
                etapes.append((-1, int(precedent[0] + (cx - precedent[0]) * f),
                               int(precedent[1] + (cy - precedent[1]) * f)))

    for i, el in enumerate(elements):
        if el.points is not None:
            for k, (px, py, r) in enumerate(el.points):
                cx, cy = el.x + float(px), el.y + float(py)
                deplacer_vers(cx, cy, max(4 * r, pas_saut))
                etapes.append((i, k, 0))
                precedent = (cx, cy)
        else:
            depart = (main_pos[0] - el.x, main_pos[1] - el.y)
            el.cellules = ordre_cellules(el.couverture, el.taille_cellule, depart, lecture=el.lecture)
            for (r, c) in el.cellules:
                cx = el.x + (c + 0.5) * el.taille_cellule
                cy = el.y + (r + 0.5) * el.taille_cellule
                deplacer_vers(cx, cy, el.taille_cellule * 6)
                etapes.append((i, r, c))
                precedent = (cx, cy)
        if precedent is not None:
            main_pos = precedent

    # Durées
    duree_dessin, pause, d_voix = scene.duree_dessin, scene.pause, 0.0
    a_couleur = any(e.finale is not None for e in elements)
    pause_min = DUREE_SORTIE + (DUREE_COULEUR if a_couleur else 0) + 0.3
    if scene.audio and Path(scene.audio).exists():
        d_voix = duree_audio(scene.audio)
        if scene.caler_sur_audio:
            total = DECALAGE_VOIX + d_voix + 0.5
            pause = max(pause_min, min(scene.pause, total * 0.4))
            duree_dessin = max(1.5, total - DUREE_ENTREE - pause)
    pause = max(pause, pause_min)
    if not etapes:
        duree_dessin = 0.0
    return ScenePreparee(scene, elements, max(0.0, duree_dessin), pause, d_voix, etapes)


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------
class Animateur:
    def __init__(self, projet: Projet):
        self.p = projet
        self.fond = np.empty((projet.hauteur, projet.largeur, 3), dtype=np.uint8)
        self.fond[:] = couleur(projet.fond)
        main, pointe = charger_main(projet.main, projet.pointe_main, min(projet.largeur, projet.hauteur),
                                    max(projet.largeur, projet.hauteur))
        self.main_rgb = main[..., :3].astype(np.float32)
        self.main_a = main[..., 3:].astype(np.float32) / 255
        self.pointe = pointe

    def poser_main(self, image: np.ndarray, x: float, y: float) -> None:
        """Dessine la main avec la pointe du feutre en (x, y)."""
        H, W = image.shape[:2]
        mh, mw = self.main_a.shape[:2]
        ox, oy = int(round(x - self.pointe[0])), int(round(y - self.pointe[1]))
        x0, y0, x1, y1 = max(0, ox), max(0, oy), min(W, ox + mw), min(H, oy + mh)
        if x0 >= x1 or y0 >= y1:
            return
        sx0, sy0 = x0 - ox, y0 - oy
        a = self.main_a[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
        m = self.main_rgb[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
        zone = image[y0:y1, x0:x1].astype(np.float32)
        image[y0:y1, x0:x1] = (m * a + zone * (1 - a)).astype(np.uint8)

    def images_scene(self, sp: ScenePreparee) -> Iterator[np.ndarray]:
        p, fps = self.p, self.p.fps
        W, H = p.largeur, p.hauteur
        toile = self.fond.copy()
        hors_ecran = (W * 0.85, H * 1.35)
        n_entree = int(round(DUREE_ENTREE * fps))
        n_dessin = int(round(sp.duree_dessin * fps))
        n_pause = int(round(sp.pause * fps))
        n_sortie = int(round(DUREE_SORTIE * fps))
        n_couleur = int(round(DUREE_COULEUR * fps))
        etapes = sp.etapes

        def centre(etape):
            i, a, b = etape
            if i < 0:
                return float(a), float(b)
            el = sp.elements[i]
            if el.points is not None:
                return el.x + float(el.points[a, 0]), el.y + float(el.points[a, 1])
            return el.x + (b + 0.5) * el.taille_cellule, el.y + (a + 0.5) * el.taille_cellule

        def reveler(etape):
            i, r, c = etape
            if i < 0:
                return
            el = sp.elements[i]
            if el.points is not None:
                # dessin vectoriel : on révèle un petit disque autour de la pointe
                px, py, rayon = (float(v) for v in el.points[r])
                ri = int(math.ceil(rayon)) + 1
                xs0, ys0 = max(0, int(px) - ri), max(0, int(py) - ri)
                xs1, ys1 = min(el.largeur, int(px) + ri + 1), min(el.hauteur, int(py) + ri + 1)
                if xs1 <= xs0 or ys1 <= ys0:
                    return
                yy, xx = np.ogrid[ys0:ys1, xs0:xs1]
                m = ((xx - px) ** 2 + (yy - py) ** 2 <= rayon * rayon) & el.couverture[ys0:ys1, xs0:xs1]
                cible = toile[el.y + ys0:el.y + ys1, el.x + xs0:el.x + xs1]
                cible[m] = el.croquis[ys0:ys1, xs0:xs1][m]
                return
            t = el.taille_cellule
            ys, xs = r * t, c * t
            ye, xe = min(ys + t, el.croquis.shape[0]), min(xs + t, el.croquis.shape[1])
            cov = el.couverture[ys:ye, xs:xe]
            cible = toile[el.y + ys:el.y + ye, el.x + xs:el.x + xe]
            cible[cov] = el.croquis[ys:ye, xs:xe][cov]

        premier = centre(etapes[0]) if etapes else hors_ecran

        # 1. la main entre
        for f in range(n_entree):
            k = _lisse((f + 1) / max(1, n_entree))
            img = toile.copy()
            self.poser_main(img, hors_ecran[0] + (premier[0] - hors_ecran[0]) * k,
                            hors_ecran[1] + (premier[1] - hors_ecran[1]) * k)
            yield img

        # 2. le dessin
        fait = 0
        mx, my = premier
        for f in range(n_dessin):
            cible_n = len(etapes) if f == n_dessin - 1 else int(len(etapes) * (f + 1) / n_dessin)
            while fait < cible_n:
                reveler(etapes[fait])
                fait += 1
            if fait:
                tx, ty = centre(etapes[fait - 1])
                mx, my = mx + (tx - mx) * 0.6, my + (ty - my) * 0.6
            temps = f / fps
            img = toile.copy()
            self.poser_main(img, mx + 1.5 * math.sin(temps * 17), my + 1.5 * math.cos(temps * 13))
            yield img
        while fait < len(etapes):  # sécurité (durée nulle)
            reveler(etapes[fait])
            fait += 1
        # Les aplats foncés des dessins vectoriels ne sont révélés qu'autour de leur contour :
        # on complète le croquis à la fin du tracé.
        for el in sp.elements:
            if el.points is not None:
                zone = toile[el.y:el.y + el.hauteur, el.x:el.x + el.largeur]
                zone[el.couverture] = el.croquis[el.couverture]

        # 3. la main sort, les couleurs apparaissent, pause
        trait = toile.copy()
        couleur_finale = trait.copy()
        for el in sp.elements:
            _coller_finale(couleur_finale, el, self.fond[0, 0])
        a_couleur = any(el.finale is not None for el in sp.elements)
        for f in range(n_pause):
            if a_couleur and f < n_couleur:
                k = _lisse((f + 1) / n_couleur)
                img = (trait.astype(np.float32) * (1 - k) + couleur_finale.astype(np.float32) * k).astype(np.uint8)
            else:
                img = (couleur_finale if a_couleur else trait).copy()
            if f < n_sortie:
                k = _lisse((f + 1) / max(1, n_sortie))
                self.poser_main(img, mx + (hors_ecran[0] - mx) * k, my + (hors_ecran[1] - my) * k)
            yield img

    def transition(self, avant: np.ndarray, apres: np.ndarray) -> Iterator[np.ndarray]:
        n = int(round(DUREE_TRANSITION * self.p.fps))
        mode = self.p.transition
        if mode == "coupe" or n == 0:
            return
        W = self.p.largeur
        for f in range(n):
            k = _lisse((f + 1) / n)
            if mode == "glisser":
                dx = int(round(W * k))
                img = np.empty_like(avant)
                img[:, :W - dx] = avant[:, dx:]
                img[:, W - dx:] = apres[:, :dx]
            else:  # fondu
                img = (avant.astype(np.float32) * (1 - k) + apres.astype(np.float32) * k).astype(np.uint8)
            yield img


def _lisse(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def exporter(projet: Projet, sortie: str, progression: Callable[[float, str], None] | None = None,
             arret: threading.Event | None = None, echelle: float = 1.0,
             indices: list[int] | None = None) -> str:
    """Fabrique la vidéo. `echelle` < 1 donne un aperçu rapide en basse définition."""
    from copy import deepcopy

    p = deepcopy(projet)
    if echelle != 1.0:
        p.largeur = int(p.largeur * echelle) // 2 * 2
        p.hauteur = int(p.hauteur * echelle) // 2 * 2
        p.fps = max(12, int(p.fps * min(1.0, echelle * 1.3)))
    scenes = [p.scenes[i] for i in indices] if indices is not None else p.scenes
    if not scenes:
        raise ValueError("Le projet ne contient aucune scène.")

    def signaler(f, msg):
        if progression:
            progression(f, msg)
        if arret is not None and arret.is_set():
            raise Annule()

    preparees = []
    for i, sc in enumerate(scenes):
        signaler(0.0, f"Préparation de la scène {i + 1}/{len(scenes)}…")
        preparees.append(preparer_scene(p, sc))

    anim = Animateur(p)
    trans = 0 if p.transition == "coupe" else int(round(DUREE_TRANSITION * p.fps))
    n_scenes = [int(round(DUREE_ENTREE * p.fps)) + int(round(sp.duree_dessin * p.fps))
                + int(round(sp.pause * p.fps)) for sp in preparees]
    total = sum(n_scenes) + trans * (len(preparees) - 1)
    duree = total / p.fps

    voix, t = [], 0.0
    for sp, n in zip(preparees, n_scenes):
        if sp.scene.audio and Path(sp.scene.audio).exists():
            voix.append(PisteAudio(sp.scene.audio, t + DECALAGE_VOIX))
        t += (n + trans) / p.fps
    musique = p.musique if p.musique and Path(p.musique).exists() else ""

    Path(sortie).parent.mkdir(parents=True, exist_ok=True)
    ecrivain = EcrivainVideo(sortie, p.largeur, p.hauteur, p.fps, duree, voix, musique, p.volume_musique)
    fait, derniere = 0, None
    try:
        for i, sp in enumerate(preparees):
            if derniere is not None:
                for img in anim.transition(derniere, anim.fond):
                    ecrivain.ecrire(img)
                    fait += 1
            for img in anim.images_scene(sp):
                ecrivain.ecrire(img)
                derniere = img
                fait += 1
                if fait % 5 == 0:
                    signaler(fait / total, f"Scène {i + 1}/{len(preparees)} — image {fait}/{total}")
        while fait < total:  # arrondis : on complète avec la dernière image
            ecrivain.ecrire(derniere)
            fait += 1
    except BaseException:
        ecrivain.annuler()
        raise
    signaler(1.0, "Finalisation de la vidéo…")
    ecrivain.fermer()
    if progression:
        progression(1.0, "Terminé")
    return sortie


def image_finale(projet: Projet, scene: Scene, largeur: int = 960) -> Image.Image:
    """Aperçu fixe : la scène une fois terminée."""
    from copy import deepcopy

    p = deepcopy(projet)
    f = largeur / p.largeur
    p.largeur, p.hauteur = largeur, int(p.hauteur * f)
    sp = preparer_scene(p, scene)
    toile = np.empty((p.hauteur, p.largeur, 3), dtype=np.uint8)
    toile[:] = couleur(p.fond)
    for el in sp.elements:
        if el.finale is not None:
            _coller_finale(toile, el, toile[0, 0].copy())
        else:
            zone = toile[el.y:el.y + el.hauteur, el.x:el.x + el.largeur]
            zone[el.couverture] = el.croquis[el.couverture]
    return Image.fromarray(toile)


def _coller_finale(toile: np.ndarray, el: Element, fond) -> None:
    """Pose la version en couleur d'un élément sans effacer ses voisins."""
    if el.finale is None:
        return
    zone = toile[el.y:el.y + el.hauteur, el.x:el.x + el.largeur]
    utile = (np.abs(el.finale.astype(np.int16) - np.asarray(fond, dtype=np.int16)).max(axis=2) > 6) | el.couverture
    zone[utile] = el.finale[utile]
