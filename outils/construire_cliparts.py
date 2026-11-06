"""Construit la bibliothèque de cliparts en couleur de Whiteboard Studio.

Sources (à télécharger avant de lancer ce script) :
  - Fluent Emoji de Microsoft, style « Flat » (licence MIT) :
        git clone --depth 1 --filter=blob:none --sparse https://github.com/microsoft/fluentui-emoji.git
        git -C fluentui-emoji sparse-checkout set --no-cone "/assets/*/Flat/*.svg" "/assets/*/metadata.json" \\
            "/assets/*/Default/Flat/*.svg"
  - noms français (annotations Unicode CLDR) du paquet npm emojibase-data (licence MIT) :
        npm pack emojibase-data  puis décompresser

Usage :
    python outils/construire_cliparts.py chemin/fluentui-emoji chemin/emojibase-data/package
"""
import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

GROUPES_EXCLUS = {"Flags"}
SOUS_GROUPES_EXCLUS = {"alphanum", "keycap", "zodiac", "religion", "av-symbol", "geometric", "gender",
                       "arrow", "transport-sign", "punctuation", "math",
                       "person-fantasy", "person-symbol", "flag", "country-flag", "subdivision-flag"}
# Variantes « homme / femme » d'une même activité : on garde la version neutre
SOUS_GROUPES_NEUTRES = {"person-activity", "person-sport", "person-resting", "person-role", "person-gesture"}


def normaliser_code(h: str) -> str:
    return "-".join(p for p in h.lower().replace(" ", "-").replace("_", "-").split("-") if p and p != "fe0f")


def slug(texte: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if unicodedata.category(c) != "Mn")
    s = s.replace("œ", "oe").replace("æ", "ae").replace("’", "-").replace("'", "-")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def minifier(svg: str) -> str:
    svg = re.sub(r"<\?xml.*?\?>", "", svg, flags=re.S)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r">\s+<", "><", svg)
    return re.sub(r"\s+", " ", svg).strip()


def main(dossier_fluent: Path, dossier_emojibase: Path, sortie: Path) -> None:
    fr = json.loads((dossier_emojibase / "fr" / "data.json").read_text(encoding="utf-8"))
    messages = json.loads((dossier_emojibase / "fr" / "messages.json").read_text(encoding="utf-8"))
    groupes_fr = {g["order"]: g["message"] for g in messages["groups"]}
    sous_groupes = {g["order"]: g["key"] for g in messages["subgroups"]}
    index = {normaliser_code(e["hexcode"]): e for e in fr}

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from whiteboard.vecteur import lire_svg

    resultat, refus = {}, []
    for meta_f in sorted((dossier_fluent / "assets").glob("*/metadata.json")):
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        e = index.get(normaliser_code(meta["unicode"]))
        if e is None or meta.get("group") in GROUPES_EXCLUS:
            continue
        sg = sous_groupes.get(e.get("subgroup"), "")
        label = e["label"]
        if sg in SOUS_GROUPES_EXCLUS:
            continue
        if label in ("doigt d’honneur",):
            continue
        if sg == "time" and re.search(r"\bheures?\b|\bdemie\b|midi|minuit", label):
            continue  # cadrans d'horloge
        if sg in SOUS_GROUPES_NEUTRES and re.match(r"^(homme|femme)\b", label):
            continue
        svgs = sorted(meta_f.parent.glob("Flat/*.svg")) or sorted(meta_f.parent.glob("Default/Flat/*.svg"))
        if not svgs:
            continue
        svg = minifier(svgs[0].read_text(encoding="utf-8"))
        try:
            if not lire_svg(svg):
                raise ValueError("aucune forme")
        except Exception as err:  # noqa: BLE001
            refus.append((label, str(err)))
            continue
        nom = slug(label)
        base, i = nom, 2
        while nom in resultat:
            nom, i = f"{base}-{i}", i + 1
        groupe = groupes_fr.get(e.get("group"), "")
        resultat[nom] = {
            "l": label,
            "c": groupe[:1].upper() + groupe[1:],
            "t": sorted(set(e.get("tags", []) + meta.get("keywords", []) + [meta.get("cldr", "")])),
            "e": e.get("emoji", ""),
            "s": svg,
        }
    # Vignettes précalculées (planche PNG) : le sélecteur s'ouvre instantanément
    from PIL import Image

    from whiteboard.vecteur import rendre_vecteur
    T, COLS = 56, 40
    planche = Image.new("RGB", (T * COLS, T * ((len(resultat) + COLS - 1) // COLS)), "white")
    for i, (nom, info) in enumerate(resultat.items()):
        r = rendre_vecteur(lire_svg(info["s"]), T - 4, T - 4, 0.8, 1.2, (255, 255, 255), (30, 30, 30))
        if r is not None and r.finale is not None:
            planche.paste(Image.fromarray(r.finale), ((i % COLS) * T + (T - r.largeur) // 2,
                                                     (i // COLS) * T + (T - r.hauteur) // 2))
        info["v"] = i
    planche.save(sortie.parent / "vignettes.jpg", quality=88, optimize=True)
    donnees = json.dumps(resultat, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(sortie, "wb", 9) as f:
        f.write(donnees)
    print(f"{len(resultat)} cliparts → {sortie} ({sortie.stat().st_size // 1024} Ko) ; refusés : {len(refus)}")
    for r in refus[:20]:
        print("  refusé :", r)


if __name__ == "__main__":
    racine = Path(__file__).resolve().parents[1]
    main(Path(sys.argv[1]), Path(sys.argv[2]),
         racine / "whiteboard" / "assets" / "cliparts" / "fluent-flat.json.gz")
