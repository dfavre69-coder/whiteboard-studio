"""Du texte à la vidéo avec une IA.

1. `construire_prompt()` prépare le prompt à donner à une IA (Claude, ChatGPT,
   un modèle local…) avec le texte source.
2. L'IA répond par un projet JSON ; `projet_depuis_ia()` le lit avec
   tolérance (blocs ```json, virgules en trop, icônes approximatives…).
3. `exporter_narrations()` écrit le texte de chaque voix off (01.txt, 02.txt…)
   pour la synthèse vocale ; `associer_voix()` rattache ensuite les fichiers
   audio (01.wav, 02.mp3…) aux scènes.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .modeles import MODELES
from .projet import Projet, Scene
from .vecteur import (PREFIXE_CLIPART, PREFIXE_ICONE, catalogue_cliparts, catalogue_icones, chercher_cliparts,
                      chercher_icones)

FICHIER_PROMPT = Path(__file__).parent / "assets" / "prompt_video.md"
MOTS_PAR_SECONDE = 2.6        # débit d'une voix off posée (≈ 155 mots par minute)
SECONDES_PAR_SCENE = 9        # pour estimer le nombre de scènes
SECONDES_PAR_SCENE_SHORT = 7  # rythme plus soutenu des Shorts
DUREE_SHORT = 0.75            # durée visée par défaut d'un Short, en minutes (45 s)
FORMAT_SHORT = (1080, 1920)

SECTION_SHORT = """
## Format Short (vidéo verticale, option activée)

Cette vidéo est un Short YouTube : écran vertical 9:16, regardé sur téléphone, en moins d'une minute (visée : {SECONDES} secondes). Ces règles remplacent les règles contraires plus haut.
- 5 à 8 scènes, rythme rapide. La narration de chaque scène fait 8 à 25 mots ; le total de la narration ne dépasse pas {MOTS} mots.
- La première scène est une accroche qui retient le pouce dès les deux premières secondes : une question intrigante (modèle "personnage"), un chiffre étonnant tiré du texte (modèle "chiffre") ou un titre choc (modèle "titre"). Sa narration commence directement par l'accroche, sans « Bonjour » ni présentation.
- L'écran est étroit : titres de 25 caractères au plus, 3 lignes au plus dans "liste" et "etapes", 2 colonnes au plus dans "comparaison", 4 barres au plus dans "graphique", 4 dates au plus dans "chronologie".
- Une seule idée forte par scène, dite simplement ; pas de transition du type « voyons maintenant ».
- La dernière scène reste "fin", avec une narration de 10 mots au plus qui invite à s'abonner.
"""
EXTENSIONS_AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus"}

ICONES_PROMPT = {
    "idées et réflexion": "bulb brain puzzle question-mark help-circle info-circle search zoom-in eye sparkles "
                          "wand target focus-2 compass",
    "personnes": "user users users-group user-check user-plus friends heart-handshake man woman school "
                 "mood-smile mood-happy mood-sad mood-angry hand-stop hand-finger thumb-up thumb-down speakerphone",
    "travail et entreprise": "briefcase building building-store building-factory building-bank presentation "
                             "presentation-analytics report report-money file-text file-certificate checklist "
                             "list-check clipboard-list calendar calendar-event clock hourglass alarm stopwatch "
                             "businessplan tie award trophy medal certificate",
    "argent": "cash coin coins currency-euro currency-dollar wallet pig-money receipt shopping-cart shopping-bag "
              "discount credit-card gift tag",
    "données et progrès": "chart-bar chart-line chart-pie chart-arrows-vertical chart-dots trending-up trending-down "
                          "arrow-up-right arrow-down-right percentage math-function scale stairs-up stairs ladder "
                          "flag flag-2",
    "technologie": "device-desktop device-laptop device-mobile device-tablet wifi world-www cloud database server "
                   "code terminal-2 cpu robot rocket api lock lock-open key shield shield-check fingerprint "
                   "password settings adjustments tool tools plug bolt battery-charging",
    "communication": "message message-circle messages mail send phone bell bell-ringing share link microphone "
                     "headphones video camera photo news book book-2 notebook pencil writing",
    "nature et monde": "world map map-pin route road home building-skyscraper tree trees plant plant-2 leaf flower "
                       "sun moon cloud cloud-rain snowflake flame droplet wind mountain beach planet recycle",
    "santé et vie quotidienne": "heart heart-rate-monitor stethoscope pill vaccine first-aid-kit apple coffee "
                                "tools-kitchen-2 bed run bike walk ball-football barbell yoga",
    "transport": "car bus train plane ship truck scooter gas-station parking",
    "symboles": "check x plus minus equal arrow-right arrow-left arrow-up arrow-down arrows-exchange refresh "
                "repeat infinity star alert-triangle ban circle-check circle-x",
    "science et école": "flask atom microscope dna telescope math calculator ruler-2 abacus globe history "
                        "hourglass-high",
    "loisirs": "music movie device-gamepad palette brush ticket confetti balloon cake",
}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def liste_icones_prompt() -> str:
    cat = catalogue_icones()
    lignes = []
    for groupe, noms in ICONES_PROMPT.items():
        valides = [n for n in dict.fromkeys(noms.split()) if n in cat]
        lignes.append(f"- {groupe} : {', '.join(valides)}")
    lignes.append("(La bibliothèque en contient environ 4 800 autres, nommées en anglais comme ci-dessus : "
                  "tu peux en utiliser d'autres si tu es sûr du nom.)")
    return "\n".join(lignes)


CLIPARTS_PROMPT = {
    "personnes et métiers": "bebe enfant garcon fille adulte personne-agee professionnel-de-la-sante-tous-genres "
                            "etudiant-tous-genres informaticien-tous-genres cuisinier-tous-genres fermier-tous-genres "
                            "ouvrier-tous-genres employe-de-bureau-tous-genres mecanicien-tous-genres pompier policier "
                            "astronaute artiste juge detective poignee-de-main applaudissements pouce-vers-le-haut "
                            "pouce-vers-le-bas biceps-contracte cerveau oeil oreille",
    "émotions": "visage-souriant visage-riant-aux-larmes visage-pensif visage-decu visage-en-colere visage-ebahi "
                "visage-qui-hurle-de-peur visage-endormi visage-souriant-avec-yeux-en-forme-de-coeur coeur-rouge "
                "coeur-brise etoile-brillante cent-points bulle-de-pensee explosion",
    "animaux": "abeille chat chien lapin ours panda koala singe tete-de-lion tigre cheval vache cochon mouton poule "
               "oiseau aigle chouette pingouin poisson dauphin baleine requin tortue grenouille serpent papillon "
               "fourmi coccinelle araignee escargot t-rex",
    "nature et météo": "arbre-a-feuilles-caduques conifere palmier cactus fleur-de-cerisier tournesol rose plante-en-pot "
                       "feuille-d-erable champignon soleil nuage soleil-derriere-les-nuages nuage-avec-pluie "
                       "nuage-avec-eclair flocon arc-en-ciel goutte-d-eau feu vague tornade "
                       "globe-tourne-sur-l-afrique-et-l-europe montagne volcan plage-avec-parasol croissant-de-lune etoile",
    "nourriture": "pomme-rouge banane raisin fraise citron pasteque carotte brocoli tomate pain part-de-fromage oeuf "
                  "pizza hamburger frites gateau-d-anniversaire cookie barre-chocolatee pot-de-miel boisson-chaude "
                  "theiere verre-de-lait",
    "objets": "ampoule ordinateur-portable ordinateur-de-bureau telephone-portable telephone clavier livres livre-ouvert "
              "carnet crayon stylo trombone ciseaux calendrier horloge sablier reveil cadenas-ferme cle "
              "loupe-orientee-a-gauche microscope telescope aimant pile cable-avec-fiche-electrique boite-a-outils "
              "marteau cle-a-molette roue-dentee boussole carte-du-monde bagage cartable lunettes appareil-photo camera "
              "micro casque televiseur radio cadeau enveloppe colis graphique-en-hausse graphique-en-baisse piece "
              "sac-plein-d-argent billet-en-euros carte-bancaire balance-a-poids seringue thermometre",
    "lieux et transports": "maison immeuble-de-bureaux ecole hopital usine banque grand-magasin chateau stade tente "
                           "voiture bus velo moto camion-de-livraison train avion fusee navire helicoptere "
                           "feu-tricolore-vertical autoroute",
    "activités": "trophee medaille-d-or ballon-de-football tennis jeu-video piece-de-puzzle palette-de-peinture guitare "
                 "piano dans-le-mille confettis ballon-gonflable",
    "symboles": "coche bouton-coche croix symbole-d-avertissement sens-interdit symbole-recyclage",
}


def liste_cliparts_prompt() -> str:
    cat = catalogue_cliparts()
    lignes = []
    for groupe, noms in CLIPARTS_PROMPT.items():
        valides = [n for n in dict.fromkeys(noms.split()) if n in cat]
        if valides:
            lignes.append(f"- {groupe} : {', '.join(valides)}")
    lignes.append(f"(La bibliothèque contient {len(cat)} cliparts nommés en français comme ci-dessus : "
                  "tu peux en utiliser d'autres, le logiciel trouvera le plus proche.)")
    return "\n".join(lignes)


def construire_prompt(texte: str, duree_minutes: float = 3, ton: str = "", short: bool = False) -> str:
    from . import personnages as P
    modele = FICHIER_PROMPT.read_text(encoding="utf-8")
    if short:
        duree_minutes = min(duree_minutes, 1.0)
        secondes = int(round(duree_minutes * 60))
        section = (SECTION_SHORT.replace("{SECONDES}", str(secondes))
                   .replace("{MOTS}", str(int(secondes * MOTS_PAR_SECONDE * 0.85))))
        modele = modele.replace("## Cliparts en couleur disponibles",
                                section.strip() + "\n\n## Cliparts en couleur disponibles", 1)
        modele = modele.replace("environ {DUREE} minute(s)", f"environ {secondes} secondes (Short vertical)")
        nb = max(5, min(8, round(duree_minutes * 60 / SECONDES_PAR_SCENE_SHORT)))
    else:
        nb = max(3, round(duree_minutes * 60 / SECONDES_PAR_SCENE))
    remplacements = {
        "{DUREE}": f"{duree_minutes:g}".replace(".", ","),
        "{NB_SCENES}": str(nb),
        "{TON}": ton.strip() or "grand public curieux, ton clair, chaleureux et pédagogique",
        "{ICONES}": liste_icones_prompt(),
        "{CLIPARTS}": liste_cliparts_prompt(),
        "{EMOTIONS}": ", ".join(P.CHOIX_EMOTION),
        "{COIFFURES}": ", ".join(P.CHOIX_COIFFURE),
        "{BARBES}": ", ".join(P.CHOIX_PILOSITE),
        "{ACCESSOIRES}": ", ".join(P.CHOIX_ACCESSOIRE),
        "{PEAUX}": ", ".join(P.CHOIX_PEAU),
        "{VETEMENTS}": ", ".join(P.CHOIX_VETEMENT),
        "{TEXTE}": texte.strip() or "(colle ici ton texte)",
    }
    for cle, valeur in remplacements.items():
        modele = modele.replace(cle, valeur)
    return modele


# ---------------------------------------------------------------------------
# Lecture de la réponse
# ---------------------------------------------------------------------------
class ReponseIllisible(ValueError):
    pass


def _sans_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


SYNONYMES = {
    "libre": "libre", "image": "libre", "illustration": "libre", "image-texte": "libre", "imageettexte": "libre",
    "titre": "titre", "title": "titre", "chapitre": "titre", "intro": "titre", "introduction": "titre",
    "liste": "liste", "list": "liste", "puces": "liste", "listeapuces": "liste", "bullets": "liste",
    "etapes": "etapes", "etape": "etapes", "steps": "etapes", "processus": "etapes",
    "etapesreliees": "etapes",
    "graphique": "graphique", "barres": "graphique", "histogramme": "graphique", "diagramme": "graphique",
    "graphiqueenbarres": "graphique", "chart": "graphique", "graph": "graphique",
    "proportion": "proportion", "pictogrammes": "proportion", "pictogramme": "proportion", "ratio": "proportion",
    "pourcentage": "proportion",
    "chronologie": "chronologie", "frise": "chronologie", "frisechronologique": "chronologie",
    "timeline": "chronologie", "dates": "chronologie",
    "personnage": "personnage", "dialogue": "personnage", "bulle": "personnage", "personnagequiparle": "personnage",
    "character": "personnage",
    "comparaison": "comparaison", "comparison": "comparaison", "versus": "comparaison", "vs": "comparaison",
    "chiffre": "chiffre", "chiffrecle": "chiffre", "nombre": "chiffre", "statistique": "chiffre", "stat": "chiffre",
    "number": "chiffre",
    "citation": "citation", "quote": "citation",
    "fin": "fin", "outro": "fin", "conclusion": "fin", "end": "fin", "findevideo": "fin",
}


def extraire_json(reponse: str):
    """Trouve et lit le JSON d'une réponse d'IA, même entouré de texte ou un peu abîmé."""
    texte = reponse.strip().lstrip("﻿")
    bloc = re.search(r"```(?:json)?\s*(.*?)```", texte, re.S | re.I)
    if bloc:
        texte = bloc.group(1).strip()
    debuts = [i for i in (texte.find("{"), texte.find("[")) if i >= 0]
    if not debuts:
        raise ReponseIllisible("Aucun JSON trouvé dans la réponse.")
    debut = min(debuts)
    fin = max(texte.rfind("}"), texte.rfind("]"))
    texte = texte[debut:fin + 1]
    essais = [texte]
    repare = re.sub(r"^\s*//.*$", "", texte, flags=re.M)          # commentaires //
    repare = re.sub(r",(\s*[}\]])", r"\1", repare)                 # virgules finales
    repare = repare.replace("“", '"').replace("”", '"')            # guillemets typographiques
    essais.append(repare)
    erreur = None
    for e in essais:
        try:
            return json.loads(e)
        except json.JSONDecodeError as err:
            erreur = err
        try:  # retours à la ligne bruts dans les chaînes
            return json.loads(e, strict=False)
        except json.JSONDecodeError as err:
            erreur = err
    raise ReponseIllisible(f"JSON invalide : {erreur}")


def resoudre_icone(nom: str) -> str | None:
    """Nom d'icône existant le plus proche, ou None."""
    cat = catalogue_icones()
    n = nom.strip().lower().removeprefix(PREFIXE_ICONE).strip().replace(" ", "-").replace("_", "-")
    n = n.removeprefix("ti-").removeprefix("icon-")
    if n in cat:
        return n
    generiques = {"icon", "icone", "icons", "ti", "outline", "filled", "line", "svg", "logo", "symbol"}
    mots = [m for m in n.split("-") if m and m not in generiques] or ["?"]
    # le nom principal est souvent le dernier mot en anglais (« kitchen-timer » → « timer »)
    for essai in (n, " ".join(mots), mots[-1], mots[0]):
        if len(essai) < 4:
            continue
        trouves = chercher_icones(essai, limite=1)
        if trouves:
            return trouves[0]
    return None


def _visuel(valeur: str, remarques: list[str], ou: str) -> str:
    valeur = (valeur or "").strip()
    if not valeur:
        return ""
    if valeur.lower().startswith("personne:"):
        return "personne:" + valeur[len("personne:"):].strip()
    if "+" in valeur and not Path(valeur).exists():
        # composition : premier visuel + autres visuels ou pastilles
        from .vecteur import PASTILLES, _sans_accents
        parties = [p.strip() for p in valeur.split("+") if p.strip()]
        base = _visuel(parties[0], remarques, ou)
        if not base:
            return ""
        ajouts = []
        for p in parties[1:]:
            cle = _sans_accents(p)
            if cle in PASTILLES:
                ajouts.append(cle)
                continue
            v = _visuel(p if p.startswith(("icone:", "clipart:", "personne:")) else PREFIXE_CLIPART + p,
                        remarques, ou)
            if v:
                ajouts.append(v)
        return "+".join([base] + ajouts)
    if re.search(r"[\\/]|\.(svg|png|jpe?g|webp|bmp|gif)$", valeur, re.I):
        if Path(valeur).exists():
            return valeur
        remarques.append(f"{ou} : fichier « {valeur} » introuvable, visuel retiré.")
        return ""
    if valeur.lower().startswith(PREFIXE_CLIPART):
        brut = valeur[len(PREFIXE_CLIPART):].strip()
        nom = resoudre_clipart(brut)
        if nom is None:
            # pas de clipart approchant : une icône au trait fera l'affaire
            icone = resoudre_icone(brut)
            if icone is None:
                remarques.append(f"{ou} : clipart « {brut} » inconnu, retiré.")
                return ""
            remarques.append(f"{ou} : clipart « {brut} » inconnu, remplacé par l'icône « {icone} ».")
            return PREFIXE_ICONE + icone
        if nom != brut:
            remarques.append(f"{ou} : clipart « {brut} » remplacé par « {nom} ».")
        return PREFIXE_CLIPART + nom
    nom = resoudre_icone(valeur)
    if nom is None:
        clip = resoudre_clipart(valeur.lower().removeprefix(PREFIXE_ICONE))
        if clip is not None:
            remarques.append(f"{ou} : « {valeur} » remplacé par le clipart « {clip} ».")
            return PREFIXE_CLIPART + clip
        remarques.append(f"{ou} : icône « {valeur} » inconnue, retirée.")
        return ""
    brut = valeur.lower().removeprefix(PREFIXE_ICONE).strip()
    if nom != brut:
        remarques.append(f"{ou} : icône « {brut} » remplacée par « {nom} ».")
    return PREFIXE_ICONE + nom


def resoudre_clipart(nom: str) -> str | None:
    """Nom de clipart existant le plus proche, ou None."""
    cat = catalogue_cliparts()
    n = nom.strip().lower().removeprefix(PREFIXE_CLIPART).strip().replace(" ", "-").replace("_", "-")
    if n in cat:
        return n
    generiques = {"icon", "icone", "icons", "clipart", "image", "emoji", "svg", "logo"}
    mots = [m for m in n.split("-") if m and m not in generiques] or ["?"]
    singulier = " ".join(re.sub(r"(?<=\w{3})[sx]$", "", m) for m in mots)  # « abeilles » → « abeille »
    for essai in (singulier, singulier.split()[0]):
        if essai.replace(" ", "-") in cat:
            return essai.replace(" ", "-")
    for essai in (" ".join(mots), singulier, mots[0], singulier.split()[0]):
        if len(essai) < 4:
            continue
        trouves = chercher_cliparts(essai, limite=1)
        if trouves:
            return trouves[0]
    return None


def _texte(valeur, remarques: list[str], ou: str) -> str:
    if isinstance(valeur, list):
        valeur = "\n".join(str(v) for v in valeur)
    lignes = []
    for ligne in str(valeur or "").replace("\\n", "\n").split("\n"):
        m = re.match(r"^(\s*)\[([^\]]+)\](.*)$", ligne)
        if m:
            vis = _visuel(m.group(2), remarques, ou)
            if vis.startswith(PREFIXE_ICONE):
                ligne = f"{m.group(1)}[{vis[len(PREFIXE_ICONE):]}]{m.group(3)}"
            elif vis:
                ligne = f"{m.group(1)}[{vis}]{m.group(3)}"
            else:
                ligne = f"{m.group(1)}{m.group(3).strip()}"
        lignes.append(ligne.rstrip())
    return "\n".join(lignes).strip()


def duree_estimee(narration: str, short: bool = False) -> tuple[float, float]:
    """(durée du dessin, pause) estimées d'après la longueur de la narration."""
    mots = len(narration.split())
    total = mots / MOTS_PAR_SECONDE + (0.5 if short else 0.8)
    pause = 1.0 if short else 1.5
    return max(2.0 if short else 2.5, round(total - pause - 0.35, 1)), pause


def duree_totale(projet: Projet) -> float:
    """Durée approximative de la vidéo, en secondes (voix off non mesurées : estimation par la narration)."""
    from .rendu import DUREE_ENTREE, DUREE_TRANSITION
    total = sum(DUREE_ENTREE + s.duree_dessin + s.pause for s in projet.scenes)
    if projet.transition != "coupe":
        total += DUREE_TRANSITION * max(0, len(projet.scenes) - 1)
    return total


def projet_depuis_ia(reponse: str, base: Projet | None = None, short: bool = False) -> tuple[Projet, list[str]]:
    """Construit un projet (réglages de `base` conservés) à partir de la réponse d'une IA.

    Renvoie (projet, remarques sur les corrections effectuées).
    """
    donnees = extraire_json(reponse)
    if isinstance(donnees, dict):
        brutes = donnees.get("scenes") or donnees.get("scènes") or donnees.get("Scenes")
        if brutes is None and ("modele" in donnees or "titre" in donnees):
            brutes = [donnees]
    else:
        brutes = donnees
    if not isinstance(brutes, list) or not brutes:
        raise ReponseIllisible("La réponse ne contient pas de liste « scenes ».")

    projet = Projet.depuis_dict(base.vers_dict()) if base is not None else Projet()
    projet.scenes = []
    remarques: list[str] = []
    for i, brute in enumerate(brutes, start=1):
        if not isinstance(brute, dict):
            remarques.append(f"Scène {i} ignorée (format inattendu).")
            continue
        d = {_sans_accents(str(k)).lower().strip(): v for k, v in brute.items()}
        ou = f"Scène {i}"
        code_brut = _sans_accents(str(d.get("modele") or d.get("model") or d.get("type") or "libre"))
        code = SYNONYMES.get(re.sub(r"[^a-z]", "", code_brut.lower()), None)
        if code is None:
            remarques.append(f"{ou} : modèle « {code_brut} » inconnu, remplacé par « libre ».")
            code = "libre"
        narration = str(d.get("narration") or d.get("voix") or d.get("voixoff") or d.get("voice") or "").strip()
        scene = Scene(
            modele=code,
            titre=str(d.get("titre") or d.get("title") or "").strip(),
            texte=_texte(d.get("texte") or d.get("text") or d.get("items") or "", remarques, ou),
            image=_visuel(str(d.get("image") or d.get("icone") or d.get("visuel") or d.get("icon") or ""),
                          remarques, ou),
            narration=narration,
            illustration=str(d.get("illustration") or d.get("image_ia") or d.get("prompt_image")
                             or d.get("illustration_ia") or "").strip(),
        )
        if narration:
            scene.duree_dessin, scene.pause = duree_estimee(narration, short)
        elif short:
            scene.duree_dessin, scene.pause = 3.0, 1.0
        projet.scenes.append(scene)
    if not projet.scenes:
        raise ReponseIllisible("Aucune scène exploitable dans la réponse.")
    if short:
        projet.largeur, projet.hauteur = FORMAT_SHORT
        if projet.transition == "glisser":
            projet.transition = "fondu"  # plus court à l'œil sur un écran étroit
    return projet, remarques


# ---------------------------------------------------------------------------
# Voix off
# ---------------------------------------------------------------------------
def exporter_narrations(projet: Projet, dossier: str | Path) -> int:
    """Écrit 01.txt, 02.txt… (une narration par scène) et script_complet.txt. Renvoie le nombre de fichiers."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    largeur = max(2, len(str(len(projet.scenes))))
    n, complet = 0, []
    for i, s in enumerate(projet.scenes, start=1):
        if not s.narration.strip():
            continue
        nom = f"{i:0{largeur}d}"
        (dossier / f"{nom}.txt").write_text(s.narration.strip() + "\n", encoding="utf-8")
        complet.append(f"[{nom}] {s.narration.strip()}")
        n += 1
    if complet:
        (dossier / "script_complet.txt").write_text("\n\n".join(complet) + "\n", encoding="utf-8")
    return n


def associer_voix(projet: Projet, dossier: str | Path) -> list[tuple[int, str]]:
    """Rattache 01.wav (ou scene_01.mp3, 1-intro.wav…) à la scène 1, etc.

    Le premier nombre du nom de fichier donne le numéro de scène.
    Renvoie [(numéro de scène, fichier)].
    """
    trouves = []
    for f in sorted(Path(dossier).iterdir()):
        if f.suffix.lower() not in EXTENSIONS_AUDIO:
            continue
        m = re.search(r"\d+", f.stem)
        if not m:
            continue
        num = int(m.group())
        if 1 <= num <= len(projet.scenes) and all(n != num for n, _ in trouves):
            s = projet.scenes[num - 1]
            s.audio = str(f.resolve())
            s.caler_sur_audio = True
            trouves.append((num, f.name))
    return trouves


__all__ = ["construire_prompt", "projet_depuis_ia", "exporter_narrations", "associer_voix",
           "resoudre_icone", "extraire_json", "ReponseIllisible", "MODELES"]
