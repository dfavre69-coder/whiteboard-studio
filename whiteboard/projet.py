"""Modèle de projet : scènes et réglages, enregistrés en JSON."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

MODES = ("trait", "couleur")
TRANSITIONS = ("glisser", "fondu", "coupe")


@dataclass
class Scene:
    modele: str = "libre"       # mise en page : voir modeles.py
    titre: str = ""
    image: str = ""             # image (PNG/JPG), fichier SVG ou icône « icone:nom », facultatif
    texte: str = ""             # texte écrit à la main (sous l'image, ou centré s'il n'y a pas d'image)
    narration: str = ""         # texte de la voix off (pour la synthèse vocale), non affiché
    mode: str = "couleur"       # "trait" : dessin seul ; "couleur" : dessin puis couleurs
    duree_dessin: float = 6.0   # secondes pour tout dessiner
    pause: float = 2.0          # secondes d'arrêt sur le dessin terminé
    audio: str = ""             # voix off de la scène (wav, mp3…), facultatif
    caler_sur_audio: bool = True  # si audio : la durée de la scène suit la voix off
    sensibilite: int = 50       # 0-100 : quantité de détails extraits de l'image


@dataclass
class Projet:
    largeur: int = 1920
    hauteur: int = 1080
    fps: int = 30
    fond: str = "#ffffff"
    encre: str = "#1e1e1e"
    main: str = "droite"        # "droite", "gauche" ou chemin d'un PNG personnalisé
    pointe_main: tuple[int, int] | None = None  # position de la pointe du stylo dans le PNG personnalisé
    police: str = ""            # vide = police manuscrite fournie
    transition: str = "glisser"
    musique: str = ""
    volume_musique: float = 0.12
    scenes: list[Scene] = field(default_factory=list)

    # --- persistance ---------------------------------------------------
    def vers_dict(self, dossier: Path | None = None) -> dict:
        d = asdict(self)
        if dossier is not None:
            d["musique"] = _relatif(d["musique"], dossier)
            if d["main"] not in ("droite", "gauche"):
                d["main"] = _relatif(d["main"], dossier)
            d["police"] = _relatif(d["police"], dossier)
            for s in d["scenes"]:
                s["image"] = _relatif(s["image"], dossier)
                s["audio"] = _relatif(s["audio"], dossier)
        return d

    def enregistrer(self, chemin: str | Path) -> None:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        data = self.vers_dict(chemin.parent.resolve())
        chemin.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def depuis_dict(cls, d: dict, dossier: Path | None = None) -> "Projet":
        scenes = [Scene(**{k: v for k, v in s.items() if k in Scene.__dataclass_fields__})
                  for s in d.get("scenes", [])]
        champs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "scenes"}
        p = cls(**champs, scenes=scenes)
        if p.pointe_main is not None:
            p.pointe_main = tuple(p.pointe_main)
        if dossier is not None:
            p.musique = _absolu(p.musique, dossier)
            p.police = _absolu(p.police, dossier)
            if p.main not in ("droite", "gauche"):
                p.main = _absolu(p.main, dossier)
            for s in p.scenes:
                s.image = _absolu(s.image, dossier)
                s.audio = _absolu(s.audio, dossier)
        return p

    @classmethod
    def charger(cls, chemin: str | Path) -> "Projet":
        chemin = Path(chemin)
        d = json.loads(chemin.read_text(encoding="utf-8"))
        return cls.depuis_dict(d, chemin.parent.resolve())


def _relatif(chemin: str, dossier: Path) -> str:
    if not chemin or chemin.startswith(("icone:", "clipart:")):
        return chemin or ""
    try:
        return Path(os.path.relpath(Path(chemin).resolve(), dossier)).as_posix()
    except ValueError:  # autre lecteur sous Windows
        return chemin


def _absolu(chemin: str, dossier: Path) -> str:
    if not chemin or chemin.startswith(("icone:", "clipart:")):
        return chemin or ""
    p = Path(chemin)
    return str(p if p.is_absolute() else (dossier / p).resolve())


def depuis_plan_texte(texte: str) -> list[Scene]:
    """Transforme un plan texte en scènes.

    Une ligne commençant par « # » ouvre une nouvelle scène (son titre) ;
    les lignes suivantes forment le texte écrit à la main.
    Sans aucun « # », chaque paragraphe devient une scène.
    """
    lignes = texte.replace("\r\n", "\n").split("\n")
    scenes: list[Scene] = []
    if any(l.strip().startswith("#") for l in lignes):
        courant: Scene | None = None
        corps: list[str] = []
        for l in lignes:
            if l.strip().startswith("#"):
                if courant is not None:
                    courant.texte = "\n".join(corps).strip()
                    scenes.append(courant)
                courant, corps = Scene(titre=l.strip().lstrip("#").strip()), []
            elif courant is not None:
                corps.append(l.strip())
        if courant is not None:
            courant.texte = "\n".join(corps).strip()
            scenes.append(courant)
    else:
        for para in texte.replace("\r\n", "\n").split("\n\n"):
            para = para.strip()
            if para:
                scenes.append(Scene(texte=para))
    return scenes
