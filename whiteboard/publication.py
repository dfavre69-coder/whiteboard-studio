"""Tout ce qui accompagne la vidéo sur YouTube : miniature, titres, description, hashtags, chapitres,
commentaire à épingler, fichier de sous-titres.

Les textes viennent de la réponse de l'IA (champ `publication` du projet) ; à défaut, ils sont déduits
des scènes. La fiche est écrite à côté du MP4 à chaque export complet.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .projet import Projet, Scene

CLES_PUBLICATION = ("titres_youtube", "description", "hashtags", "texte_miniature", "commentaire_epingle",
                    "variantes_accroche")
JAUNE = (255, 212, 59)
ENCRE_MINIATURE = (20, 20, 20)


# ---------------------------------------------------------------------------
# Textes
# ---------------------------------------------------------------------------
def _liste(valeur) -> list[str]:
    if isinstance(valeur, str):
        valeur = re.split(r"[\n;]", valeur)
    if not isinstance(valeur, (list, tuple)):
        return []
    return [str(v).strip() for v in valeur if str(v).strip()]


def normaliser_publication(brut: dict | None) -> dict:
    """Ne garde que les champs connus, sous une forme régulière (listes de chaînes ou chaînes)."""
    if not isinstance(brut, dict):
        return {}
    pub: dict = {}
    for cle in CLES_PUBLICATION:
        v = brut.get(cle)
        if v is None:
            continue
        if cle in ("titres_youtube", "hashtags", "variantes_accroche"):
            vals = _liste(v)
            if cle == "hashtags":
                vals = ["#" + re.sub(r"[^\w]", "", h.lstrip("#")) for h in vals if re.sub(r"[^\w]", "", h)]
            if vals:
                pub[cle] = vals
        else:
            s = str(v).strip()
            if s:
                pub[cle] = s
    return pub


def horodatage_chapitre(t: float) -> str:
    t = int(round(t))
    h, reste = divmod(t, 3600)
    m, s = divmod(reste, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapitres(scenes: list[Scene], debuts: list[float]) -> list[tuple[float, str]]:
    """(instant, titre) des chapitres : les scènes « titre » et « accroche », sinon chaque scène titrée."""
    reperes = [(t, s.titre.strip()) for s, t in zip(scenes, debuts)
               if s.modele in ("titre", "accroche") and s.titre.strip()]
    if len(reperes) < 2:
        reperes = [(t, s.titre.strip()) for s, t in zip(scenes, debuts) if s.titre.strip() and s.modele != "fin"]
    if reperes and reperes[0][0] > 0:
        reperes[0] = (0.0, reperes[0][1])
    return reperes


def texte_publication(projet: Projet, debuts: list[float] | None = None, scenes: list[Scene] | None = None) -> str:
    """La fiche à coller dans YouTube Studio."""
    pub = projet.publication or {}
    scenes = scenes if scenes is not None else projet.scenes
    titre_defaut = next((s.titre.strip() for s in scenes if s.titre.strip()), "") or "Ma vidéo"
    titres = pub.get("titres_youtube") or [titre_defaut]
    lignes = ["TITRE (choisir, 60 caractères max.)"]
    lignes += [f"  {i}. {t}" for i, t in enumerate(titres, start=1)]
    if pub.get("variantes_accroche"):
        lignes += ["", "ACCROCHES ALTERNATIVES (pour tester une autre première scène)"]
        lignes += [f"  • {a}" for a in pub["variantes_accroche"]]
    lignes += ["", "DESCRIPTION"]
    desc = pub.get("description") or " ".join(s.narration.strip() for s in scenes[:2] if s.narration.strip())
    lignes.append(desc or "(à compléter)")
    if debuts is not None and len(scenes) == len(debuts):
        chap = chapitres(scenes, debuts)
        if len(chap) >= 2:
            lignes += ["", "CHAPITRES (à coller dans la description)"]
            lignes += [f"{horodatage_chapitre(t)} {titre}" for t, titre in chap]
    if pub.get("hashtags"):
        lignes += ["", "HASHTAGS", " ".join(pub["hashtags"])]
    lignes += ["", "TEXTE DE LA MINIATURE", pub.get("texte_miniature") or titre_defaut]
    if pub.get("commentaire_epingle"):
        lignes += ["", "COMMENTAIRE À ÉPINGLER", pub["commentaire_epingle"]]
    return "\n".join(lignes) + "\n"


# ---------------------------------------------------------------------------
# Miniature
# ---------------------------------------------------------------------------
def _arrondi(d: ImageDraw.ImageDraw, boite, r, fill) -> None:
    d.rounded_rectangle(boite, radius=r, fill=fill)


def miniature(projet: Projet, scene: Scene, texte: str = "", largeur: int | None = None) -> Image.Image:
    """La scène terminée, avec un texte très lisible : 1280 × 720 (ou 1080 × 1920 pour un Short)."""
    from .rendu import image_finale, police

    vertical = projet.hauteur > projet.largeur * 1.15
    if largeur is None:
        largeur = 1080 if vertical else 1280
    img = image_finale(projet, scene, largeur=largeur).convert("RGB")
    W, H = img.size
    R = min(W, H)
    texte = (texte or projet.publication.get("texte_miniature") or scene.titre).strip()
    if not texte:
        return img
    # Zone « choc » : le texte en grand, sur des bandeaux jaunes, en bas
    taille = int(R * (0.17 if vertical else 0.15))
    fnt = police(projet, taille)
    mots, lignes, courante = texte.split(), [], ""
    for m in mots:
        essai = (courante + " " + m).strip()
        if fnt.getlength(essai) <= W * 0.86 or not courante:
            courante = essai
        else:
            lignes.append(courante)
            courante = m
    lignes.append(courante)
    lignes = lignes[:3]
    interligne = int(taille * 1.25)
    d = ImageDraw.Draw(img)
    bloc_h = interligne * len(lignes)
    # En vertical, le dessin occupe le haut (zone sûre des Shorts) : le texte prend la bande libre en dessous.
    y = int(H * 0.88 - bloc_h) if vertical else int(H - bloc_h - R * 0.08)
    # léger voile blanc derrière, pour détacher le texte du dessin
    voile = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dv = ImageDraw.Draw(voile)
    marge = int(R * 0.03)
    for i, l in enumerate(lignes):
        lw = fnt.getlength(l)
        x = (W - lw) / 2
        yy = y + i * interligne
        _arrondi(dv, (x - marge, yy + taille * 0.08, x + lw + marge, yy + taille * 1.12), int(R * 0.015), JAUNE + (255,))
    img = Image.alpha_composite(img.convert("RGBA"), voile)
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lignes):
        lw = fnt.getlength(l)
        x = (W - lw) / 2
        d.text((x, y + i * interligne), l, font=fnt, fill=ENCRE_MINIATURE + (255,),
               stroke_width=max(1, taille // 40), stroke_fill=ENCRE_MINIATURE + (255,))
    return img.convert("RGB")


def exporter_miniature(projet: Projet, scene: Scene, chemin: str | Path, texte: str = "") -> str:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    miniature(projet, scene, texte).save(chemin, quality=92)
    return str(chemin)


def scene_miniature(projet: Projet) -> Scene:
    """La scène la plus parlante pour une miniature : un chiffre, un personnage, sinon la première illustrée."""
    for code in ("chiffre", "personnage", "accroche", "libre", "titre"):
        for s in projet.scenes:
            if s.modele == code and (s.image.strip() or code in ("chiffre", "accroche")):
                return s
    return projet.scenes[0]


# ---------------------------------------------------------------------------
# Fichiers écrits à côté du MP4
# ---------------------------------------------------------------------------
def ecrire_annexes(projet: Projet, sortie: str | Path, preparees, debuts: list[float], groupes) -> list[str]:
    """Écrit le .srt (si sous-titres) et la fiche de publication ; renvoie les chemins créés."""
    from .sous_titres import srt

    sortie = Path(sortie)
    crees = []
    if projet.sous_titres and any(groupes):
        chemin = sortie.with_suffix(".srt")
        chemin.write_text(srt(list(zip(debuts, groupes))), encoding="utf-8")
        crees.append(str(chemin))
    fiche = sortie.with_name(sortie.stem + "_publication.txt")
    fiche.write_text(texte_publication(projet, debuts, [sp.scene for sp in preparees]), encoding="utf-8")
    crees.append(str(fiche))
    return crees
