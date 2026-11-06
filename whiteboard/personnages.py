"""Personnages modulaires (Open Peeps de Pablo Stanley, CC0).

Un personnage se décrit par des mots-clés français :

    personne:femme,surprise,lunettes,cheveux roux
    personne:homme,barbe,pensif,peau foncée,pull vert

Les éléments non précisés sont tirés au hasard, mais toujours de la même
façon pour une même description (le personnage ne change pas d'une
prévisualisation à l'autre).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

FICHIER = Path(__file__).parent / "assets" / "personnages" / "open-peeps.json"
PREFIXE_PERSONNE = "personne:"


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.replace("-", " ").replace("_", " ")).strip()


# --- Vocabulaire ------------------------------------------------------------------
EMOTIONS = {
    "content": "smile", "souriant": "smile", "heureux": "smileBig", "heureuse": "smileBig", "joyeux": "smileBig",
    "joyeuse": "smileBig", "ravi": "smileBig", "ravie": "smileBig", "rieur": "smileLOL", "rit": "smileLOL",
    "eclate de rire": "smileLOL", "calme": "calm", "serein": "calm", "sereine": "calm", "neutre": "blank",
    "triste": "concerned", "decu": "concerned", "decue": "concerned", "inquiet": "concerned",
    "inquiete": "concerned", "soucieux": "concerned", "effraye": "fear", "effrayee": "fear", "peur": "fear",
    "angoisse": "concernedFear", "angoissee": "concernedFear", "surpris": "awe", "surprise": "awe",
    "emerveille": "awe", "emerveillee": "awe", "etonne": "awe", "etonnee": "awe", "en colere": "rage",
    "fache": "rage", "fachee": "rage", "furieux": "veryAngry", "furieuse": "veryAngry", "agace": "angryWithFang",
    "pensif": "serious", "pensive": "serious", "serieux": "serious", "serieuse": "serious",
    "concentre": "driven", "concentree": "driven", "determine": "driven", "determinee": "driven",
    "explique": "explaining", "parle": "explaining", "enseigne": "explaining", "fatigue": "tired",
    "fatiguee": "tired", "epuise": "tired", "epuisee": "tired", "mefiant": "suspicious", "mefiante": "suspicious",
    "sceptique": "suspicious", "amoureux": "lovingGrin1", "amoureuse": "lovingGrin1", "gourmand": "eatingHappy",
    "gourmande": "eatingHappy", "mange": "eatingHappy", "debordee": "hectic", "deborde": "hectic",
    "stresse": "hectic", "stressee": "hectic", "panique": "hectic", "malicieux": "cheeky", "malicieuse": "cheeky",
    "espiegle": "cheeky", "mignon": "cute", "mignonne": "cute", "solennel": "solemn", "solennelle": "solemn",
    "yeux fermes": "eyesClosed", "dort": "eyesClosed", "medite": "eyesClosed", "meprisant": "contempt",
    "dedaigneux": "contempt", "age": "old", "agee": "old", "vieux": "old", "vieille": "old",
}
COIFFURES = {
    "afro": "afro", "frange": "bangs", "chignon": "bun", "chignons": "buns", "nattes": "cornrows",
    "tresses": "cornrows2", "dreadlocks": "dreads1", "dreads": "dreads2", "brosse": "flatTop",
    "cheveux gris": "grayShort", "cheveux blancs": "grayMedium", "chignon gris": "grayBun",
    "bonnet": "hatBeanie", "chapeau": "hatHip", "hijab": "hijab", "voile": "hijab", "turban": "turban",
    "cheveux longs": "long", "long": "long", "longs": "long", "boucles": "longCurly", "boucle": "longCurly",
    "cheveux boucles": "longCurly", "mi longs": "medium1", "mi long": "medium1", "carre": "mediumStraight",
    "iroquoise": "mohawk", "chauve": "noHair1", "crane rase": "shaved1", "rase": "shaved2",
    "banane": "pomp", "cheveux courts": "short1", "court": "short2", "courts": "short2", "vanilles": "twists",
}
BARBES = {"barbe": "full", "grande barbe": "full2", "barbe courte": "chin", "bouc": "goatee1",
          "moustache": "moustache1", "barbu": "full3"}
ACCESSOIRES = {"lunettes": "glasses", "lunettes rondes": "glasses2", "lunettes de soleil": "sunglasses",
               "cache oeil": "eyepatch", "pirate": "eyepatch"}
MASQUES = {"masque": "medicalMask", "masque chirurgical": "medicalMask", "respirateur": "respirator"}
PEAUX = {"peau claire": 0, "peau rosee": 0, "peau doree": 1, "peau mate": 2, "peau brune": 3, "peau foncee": 4,
         "peau noire": 4}
COULEURS_CHEVEUX = {"cheveux noirs": "2c1b18", "brun": "4a312c", "brune": "4a312c", "chatain": "724133",
                    "blond": "d6b370", "blonde": "d6b370", "roux": "c93305", "rousse": "c93305",
                    "cheveux roses": "f59797", "platine": "ecdcbf"}
COULEURS_VETEMENT = {"rouge": "e78276", "orange": "ffcf77", "jaune": "fdea6b", "vert": "78e185", "verte": "78e185",
                     "turquoise": "9ddadb", "bleu": "8fa7df", "bleue": "8fa7df", "rose": "e279c7",
                     "violet": "b39ddb", "gris": "c9c9c9", "blanc": "f4f4f4", "noir": "5a5a5a"}
FEMININ = ["long", "longCurly", "bun", "medium1", "mediumStraight", "longBangs", "mediumBangs", "bangs",
           "buns", "longAfro", "bun2"]
MASCULIN = ["short1", "short2", "short3", "short4", "short5", "flatTop", "pomp", "shaved1", "noHair2", "afro",
            "mediumBangs3", "dreads1"]

# Mots-clés proposés dans l'interface et dans le prompt de l'IA
CHOIX_EMOTION = ["content", "heureux", "rieur", "calme", "pensif", "explique", "concentré", "surpris", "inquiet",
                 "triste", "effrayé", "en colère", "fatigué", "méfiant", "amoureux", "débordé", "malicieux"]
CHOIX_COIFFURE = ["cheveux courts", "cheveux longs", "mi-longs", "carré", "bouclés", "afro", "chignon", "frange",
                  "tresses", "dreadlocks", "chauve", "crâne rasé", "cheveux gris", "cheveux blancs", "bonnet",
                  "chapeau", "hijab", "turban", "iroquoise"]
CHOIX_PILOSITE = ["barbe", "barbe courte", "bouc", "moustache"]
CHOIX_ACCESSOIRE = ["lunettes", "lunettes rondes", "lunettes de soleil", "masque"]
CHOIX_PEAU = ["peau claire", "peau dorée", "peau mate", "peau brune", "peau foncée"]
CHOIX_VETEMENT = ["rouge", "orange", "jaune", "vert", "turquoise", "bleu", "rose", "violet", "gris", "noir"]


@lru_cache(maxsize=1)
def donnees() -> dict:
    return json.loads(FICHIER.read_text(encoding="utf-8"))


def est_personne(source: str) -> bool:
    return source.startswith(PREFIXE_PERSONNE)


def analyser(description: str) -> dict:
    """Mots-clés → choix des pièces et des couleurs (le reste est tiré au sort, de façon stable)."""
    texte = _norm(description.removeprefix(PREFIXE_PERSONNE))
    d = donnees()
    mots = [m.strip() for m in re.split(r"[,;/]+", texte) if m.strip()]
    # La graine ne dépend ni de l'ordre des mots ni de l'expression : le même personnage
    # garde la même apparence quand seule son expression change d'une scène à l'autre.
    emotions = {_norm(k) for k in EMOTIONS}
    stables = sorted(m for m in mots if m not in emotions)
    graine = int(hashlib.md5("|".join(stables).encode()).hexdigest()[:8], 16)
    rng = random.Random(graine)
    # On cherche aussi les expressions à plusieurs mots dans chaque élément (« femme surprise »)
    elements: list[str] = []
    for m in mots:
        elements.append(m)
        elements.extend(m.split())

    def trouver(table):
        for cle in sorted(table, key=len, reverse=True):  # le plus précis d'abord
            k = _norm(cle)
            if any(e == k for e in elements) or any(re.search(rf"\b{re.escape(k)}\b", m) for m in mots):
                return table[cle]
        return None

    genre = "femme" if any(e in ("femme", "fille", "elle") for e in elements) else \
            "homme" if any(e in ("homme", "garcon", "lui") for e in elements) else None
    choix = {
        "face": trouver(EMOTIONS) or "smile",
        "head": trouver(COIFFURES),
        "facialHair": trouver(BARBES),
        "accessories": trouver(ACCESSOIRES),
        "mask": trouver(MASQUES),
    }
    tetes = list(d["pieces"]["head"])
    if choix["head"] is None:
        liste = FEMININ if genre == "femme" else MASCULIN if genre == "homme" else tetes
        choix["head"] = rng.choice([t for t in liste if t in d["pieces"]["head"]] or tetes)
    age = any(e in ("age", "agee", "vieux", "vieille", "senior", "grand pere", "grand mere") for e in elements)
    if (age or choix["face"] == "old") and choix["head"] not in ("grayShort", "grayMedium", "grayBun", "noHair1") \
            and trouver(COIFFURES) is None:
        choix["head"] = rng.choice(["grayShort", "grayMedium", "grayBun"])
    if "sans barbe" in texte or genre == "femme":
        choix["facialHair"] = choix["facialHair"] if "barbe" in texte or "moustache" in texte else None
    peau_i = trouver(PEAUX)
    couleurs = d["couleurs"]
    choix["peau"] = "#" + couleurs["peau"][peau_i if peau_i is not None else rng.randrange(len(couleurs["peau"]))]
    choix["cheveux"] = "#" + (trouver(COULEURS_CHEVEUX) or
                              ("e8e1e1" if choix["head"].startswith("gray") else rng.choice(
                                  ["2c1b18", "4a312c", "724133", "b58143", "d6b370", "a55728"])))
    vet = None
    for m in elements:
        if m in COULEURS_VETEMENT:
            vet = COULEURS_VETEMENT[m]
    choix["vetement"] = "#" + (vet or rng.choice(couleurs["vetement"]))
    return choix


def svg_personne(description: str) -> str:
    d = donnees()
    c = analyser(description)
    corps = d["corps"]

    def piece(nom, cle):
        return d["pieces"][nom].get(cle, "") if cle else ""

    svg = (corps.replace("{HEAD}", piece("head", c["head"])).replace("{FACE}", piece("face", c["face"]))
           .replace("{FACIALHAIR}", piece("facialHair", c["facialHair"]))
           .replace("{MASK}", piece("mask", c["mask"])).replace("{ACCESSORIES}", piece("accessories", c["accessories"])))
    svg = svg.replace("{PEAU}", c["peau"]).replace("{VETEMENT}", c["vetement"]).replace("{CHEVEUX}", c["cheveux"])
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{d["viewBox"]}" fill="none">{svg}</svg>'


def description_lisible(description: str) -> str:
    """Résumé en français de ce qui a été compris (pour l'interface)."""
    c = analyser(description)
    emotion = next((m for m in CHOIX_EMOTION if EMOTIONS.get(_norm(m)) == c["face"]), None) or \
        next((k for k, v in EMOTIONS.items() if v == c["face"]), c["face"])
    coiffure = next((m for m in CHOIX_COIFFURE if COIFFURES.get(_norm(m)) == c["head"]), None)
    texte = f"expression « {emotion} », " + (f"coiffure « {coiffure} »" if coiffure else "coiffure tirée au sort")
    return texte + (", barbe" if c["facialHair"] else "") + (", lunettes" if c["accessories"] else "") + \
        (", masque" if c["mask"] else "")
