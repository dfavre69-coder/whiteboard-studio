"""Illustrations sur mesure générées par une IA d'images (ChatGPT, par exemple).

Déroulement :
1. `preparer()` choisit les scènes à illustrer et donne à chacune une clé stable
   (« illus_03 ») : c'est le nom de fichier que l'IA devra utiliser.
2. `prompts()` écrit le prompt des illustrations (distinct de celui du scénario), par
   lots de 10 images au plus : contexte de chaque scène (texte à l'écran, voix off,
   idée imposée facultative), style adapté au tableau blanc, noms de fichiers.
3. L'utilisateur colle chaque prompt dans ChatGPT, qui renvoie un zip par lot.
4. `charger()` lit les zip (ou des images isolées), range les images à côté du
   projet et les rattache aux scènes par leur clé — même si les scènes ont été
   déplacées entre-temps.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .projet import Projet, Scene

TAILLE_LOT = 10
FICHIER_PROMPT = Path(__file__).parent / "assets" / "prompt_illustrations.md"
LIBELLES_MODELES = {"libre": "image et texte", "titre": "titre de chapitre", "liste": "liste à puces",
                    "chiffre": "chiffre clé"}
# Modèles dont le champ « Visuel » est une illustration (pas un personnage ni un logo)
MODELES_ILLUSTRABLES = ("libre", "titre", "liste", "chiffre")
EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
TAILLE_MAX_IMAGE = 40 * 1024 * 1024      # octets, par image décompressée
TAILLE_MAX_TOTALE = 400 * 1024 * 1024    # octets, par zip
PIXELS_MAX = 40_000_000

STYLE_PAR_DEFAUT = ("Illustration au style « vectoriel plat » pour une vidéo explicative de type tableau blanc : "
                    "contours noirs nets et assez épais, couleurs franches en aplats (sans dégradés ni textures), "
                    "formes simples et lisibles, sujet unique centré, fond entièrement blanc, aucune ombre portée, "
                    "aucun texte, aucune lettre ni chiffre dans l'image, format carré 1024 × 1024")


@dataclass
class Demande:
    cle: str            # nom du fichier attendu, sans extension (illus_03)
    index: int          # numéro de la scène dans le projet (0 = première)
    description: str


def illustrable(scene: Scene) -> bool:
    return scene.modele in MODELES_ILLUSTRABLES


def coche_par_defaut(scene: Scene) -> bool:
    """Scènes proposées d'office : une idée illustrée (libre) ou un titre, ou une illustration déjà décrite."""
    return bool(scene.illustration.strip()) or scene.modele in ("libre", "titre")


def sujet_par_defaut(projet: Projet) -> str:
    for sc in projet.scenes:
        if sc.modele == "titre" and sc.titre.strip():
            return sc.titre.strip()
    return next((sc.titre.strip() for sc in projet.scenes if sc.titre.strip()), "")


def _numero(cle: str) -> int | None:
    m = re.search(r"(\d+)", cle or "")
    return int(m.group(1)) if m else None


def preparer(projet: Projet, indices: list[int], descriptions: dict[int, str] | None = None) -> list[Demande]:
    """Attribue une clé aux scènes choisies (en gardant celles déjà attribuées) et note leur description."""
    descriptions = descriptions or {}  # « idée imposée » facultative, par scène
    utilisees = {_numero(s.illustration_cle) for s in projet.scenes if s.illustration_cle}
    suivant = max([n for n in utilisees if n is not None] + [0]) + 1
    demandes = []
    for i in indices:
        sc = projet.scenes[i]
        if i in descriptions:
            sc.illustration = descriptions[i].strip()
        if not sc.illustration_cle:
            sc.illustration_cle = f"illus_{suivant:02d}"
            suivant += 1
        demandes.append(Demande(sc.illustration_cle, i, sc.illustration.strip()))
    return demandes


def _bloc_scene(n: int, d: Demande, scene: Scene) -> str:
    lignes = [f"### Image {n} — fichier « {d.cle}.png »",
              f"Scène : {LIBELLES_MODELES.get(scene.modele, scene.modele)}"
              + (f", titre « {scene.titre.strip()} »" if scene.titre.strip() else "")]
    texte = " / ".join(l.strip() for l in re.sub(r"\[[^\]]*\]", "", scene.texte).split("\n") if l.strip())
    if texte:
        lignes.append(f"Texte écrit à l'écran : {texte}")
    if scene.narration.strip():
        lignes.append(f"Voix off : {scene.narration.strip()}")
    lignes.append(f"Idée imposée : {d.description}" if d.description else
                  "Idée imposée : aucune, choisis toi-même l'image la plus parlante pour cette scène.")
    return "\n".join(lignes)


def prompts(projet: Projet, demandes: list[Demande], style: str = "", sujet: str = "",
            taille_lot: int = TAILLE_LOT) -> list[str]:
    """Le prompt des illustrations, découpé en lots de `taille_lot` images au plus."""
    modele = FICHIER_PROMPT.read_text(encoding="utf-8")
    style = style.strip().rstrip(".") or STYLE_PAR_DEFAUT
    sujet = sujet.strip() or sujet_par_defaut(projet) or "(non précisé)"
    lots = [demandes[i:i + taille_lot] for i in range(0, len(demandes), taille_lot)]
    resultat = []
    for n, lot in enumerate(lots, start=1):
        blocs = "\n\n".join(_bloc_scene(k, d, projet.scenes[d.index]) for k, d in enumerate(lot, start=1))
        valeurs = {
            "{SUJET}": sujet, "{STYLE}": style, "{NB}": str(len(lot)), "{S}": "s" if len(lot) > 1 else "",
            "{LOT}": f" (lot {n} sur {len(lots)})" if len(lots) > 1 else "",
            "{SCENES}": blocs, "{EXEMPLE}": f"{lot[0].cle}.png",
            "{ZIP}": f"illustrations_lot_{n}.zip" if len(lots) > 1 else "illustrations.zip",
        }
        texte = modele
        for cle, valeur in valeurs.items():
            texte = texte.replace(cle, valeur)
        resultat.append(texte.strip())
    return resultat


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
@dataclass
class Resultat:
    associees: list[tuple[int, str]]    # (index de scène, fichier image)
    remarques: list[str]


def _lire_images(sources: list[str | Path]) -> list[tuple[str, bytes]]:
    """(nom d'origine, contenu) de chaque image des zip ou fichiers donnés, sans rien extraire sur le disque."""
    images: list[tuple[str, bytes]] = []
    for source in sources:
        source = Path(source)
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as z:
                total = 0
                for info in z.infolist():
                    nom = Path(info.filename.replace("\\", "/")).name
                    if info.is_dir() or not nom or nom.startswith((".", "_")) or "__MACOSX" in info.filename:
                        continue
                    if Path(nom).suffix.lower() not in EXTENSIONS:
                        continue
                    if info.file_size > TAILLE_MAX_IMAGE:
                        raise ValueError(f"« {nom} » est trop volumineux.")
                    total += info.file_size
                    if total > TAILLE_MAX_TOTALE:
                        raise ValueError(f"Le zip « {source.name} » est trop volumineux.")
                    images.append((nom, z.read(info)))
        elif source.suffix.lower() in EXTENSIONS:
            images.append((source.name, source.read_bytes()))
    return images


def _ouvrir(contenu: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(contenu))
    if img.width * img.height > PIXELS_MAX:
        raise ValueError("image trop grande")
    img.load()
    return img.convert("RGBA") if "A" in img.getbands() or img.mode == "P" else img.convert("RGB")


def charger(projet: Projet, sources: list[str | Path], dossier: str | Path) -> Resultat:
    """Range les images dans `dossier` et les rattache aux scènes qui les attendent."""
    dossier = Path(dossier)
    attendues = {s.illustration_cle: i for i, s in enumerate(projet.scenes) if s.illustration_cle}
    par_numero = {_numero(c): c for c in attendues}
    remarques: list[str] = []
    associees: list[tuple[int, str]] = []
    sans_cle: list[tuple[str, Image.Image]] = []
    deja: set[str] = set()

    for nom, contenu in sorted(_lire_images(sources), key=lambda x: x[0].lower()):
        try:
            img = _ouvrir(contenu)
        except Exception:  # noqa: BLE001
            remarques.append(f"« {nom} » n'est pas une image lisible, ignorée.")
            continue
        cle = Path(nom).stem.lower()
        if cle not in attendues:
            num = _numero(cle)
            cle = par_numero.get(num) if num is not None else None
        if cle is None or cle in deja:
            sans_cle.append((nom, img))
            continue
        associees.append(_ranger(projet, attendues[cle], cle, img, dossier))
        deja.add(cle)

    # Images aux noms imprévus : rattachées dans l'ordre aux scènes encore sans image
    restantes = [c for c in sorted(attendues, key=lambda c: (_numero(c) or 0)) if c not in deja]
    for (nom, img), cle in zip(sans_cle, restantes):
        associees.append(_ranger(projet, attendues[cle], cle, img, dossier))
        deja.add(cle)
        remarques.append(f"« {nom} » ne portait pas un nom attendu : rattachée à la scène "
                         f"{attendues[cle] + 1} ({cle}), dans l'ordre. Vérifiez qu'elle correspond.")
    for nom, _ in sans_cle[len(restantes):]:
        remarques.append(f"« {nom} » : aucune scène ne l'attend, ignorée.")
    manquantes = [c for c in attendues if c not in deja and not _a_deja_image(projet.scenes[attendues[c]], dossier)]
    if manquantes:
        remarques.append("Encore sans illustration : " + ", ".join(
            f"scène {attendues[c] + 1} ({c})" for c in sorted(manquantes, key=lambda c: _numero(c) or 0)) + ".")
    return Resultat(associees, remarques)


def revenir(projet: Projet) -> int:
    """Remet le visuel d'origine des scènes illustrées ; renvoie le nombre de scènes concernées."""
    n = 0
    for sc in projet.scenes:
        if sc.illustration_cle and sc.image and Path(sc.image).stem == sc.illustration_cle:
            sc.image, sc.image_secours = sc.image_secours, ""
            n += 1
    return n


def _a_deja_image(scene: Scene, dossier: Path) -> bool:
    return bool(scene.image) and Path(scene.image).parent == dossier and Path(scene.image).exists()


def _ranger(projet: Projet, index: int, cle: str, img: Image.Image, dossier: Path) -> tuple[int, str]:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{cle}.png"
    img.save(chemin)
    sc = projet.scenes[index]
    if sc.image and Path(sc.image).stem != cle:
        sc.image_secours = sc.image  # le visuel d'origine, pour pouvoir revenir en arrière
    sc.image = str(chemin)
    return index, str(chemin)
