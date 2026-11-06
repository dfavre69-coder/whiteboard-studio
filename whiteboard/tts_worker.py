"""Génération des voix off avec Qwen3-TTS.

Ce script est exécuté par l'interpréteur Python de l'environnement où
« qwen-tts » et PyTorch sont installés (pas celui de Whiteboard Studio).
Il n'importe rien de Whiteboard Studio et signale son avancement par des
lignes JSON sur la sortie standard.

Deux façons de l'utiliser :

    python tts_worker.py travail.json   → un seul travail, puis le processus s'arrête
    python tts_worker.py --serveur      → reste ouvert, garde le modèle en mémoire et lit
                                          les travaux un par un (une ligne JSON chacun)
                                          sur l'entrée standard

Pour aller vite, les phrases sont générées par lots (la carte graphique en traite
plusieurs à la fois), en regroupant les phrases de longueur voisine. Si la
mémoire vidéo manque, la taille des lots est réduite automatiquement.
"""
import json
import os
import sys
import time
import traceback

_MODELE = {"cle": None, "tts": None}
_INVITE = {"cle": None, "invite": None}


def signaler(**d):
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class ErreurTravail(Exception):
    pass


def charger_modele(t):
    import torch
    from qwen_tts import Qwen3TTSModel

    appareil = t.get("appareil") or "cuda:0"
    if appareil.startswith("cuda") and not torch.cuda.is_available():
        signaler(etat="info", message="Carte graphique CUDA indisponible : calcul sur le processeur (lent).")
        appareil = "cpu"
    nom_precision = t.get("precision") or "bfloat16"
    if appareil == "cpu":
        nom_precision = "float32"
    cle = (t["modele"], appareil, nom_precision)
    if _MODELE["cle"] == cle:
        return _MODELE["tts"]
    if _MODELE["tts"] is not None:  # autre modèle demandé : on libère l'ancien
        _MODELE["tts"] = None
        _INVITE["cle"] = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    precision = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[nom_precision]
    signaler(etat="chargement", message=f"Chargement du modèle {t['modele']} sur {appareil}…")
    debut = time.time()
    tts = Qwen3TTSModel.from_pretrained(t["modele"], device_map=appareil, dtype=precision)
    _MODELE.update(cle=cle, tts=tts)
    signaler(etat="pret", message=f"Modèle chargé en {time.time() - debut:.0f} s "
                                  f"(type : {getattr(tts.model, 'tts_model_type', 'base')}).")
    return tts


def invite_clonage(tts, t):
    ref = t.get("voix_reference") or ""
    if not ref or not os.path.exists(ref):
        raise ErreurTravail("Ce modèle clone une voix : indiquez un extrait audio de référence dans les réglages.")
    texte_ref = (t.get("texte_reference") or "").strip()
    cle = (_MODELE["cle"], ref, os.path.getmtime(ref), texte_ref)
    if _INVITE["cle"] != cle:  # l'empreinte de la voix n'est calculée qu'une fois
        _INVITE.update(cle=cle, invite=tts.create_voice_clone_prompt(
            ref_audio=ref, ref_text=texte_ref or None, x_vector_only_mode=not texte_ref))
    return _INVITE["invite"]


def _manque_memoire(e) -> bool:
    import torch
    return isinstance(e, getattr(torch.cuda, "OutOfMemoryError", ())) or "out of memory" in str(e).lower()


def traiter(t, ident=None):
    """Génère toutes les phrases d'un travail."""
    import numpy as np
    import soundfile as sf
    import torch

    debut_travail = time.time()
    tts = charger_modele(t)
    type_modele = getattr(tts.model, "tts_model_type", "base")
    langue = t.get("langue") or "Auto"
    reglages = {}
    if t.get("temperature"):
        reglages["temperature"] = float(t["temperature"])
    invite = invite_clonage(tts, t) if type_modele == "base" else None
    locuteur = t.get("locuteur") or ""
    if type_modele == "custom_voice" and not locuteur:
        locuteur = (tts.get_supported_speakers() or [""])[0]

    phrases = sorted(enumerate(t["phrases"]), key=lambda p: -len(p[1]["texte"]))  # longueurs voisines ensemble
    lot = max(1, int(t.get("lot") or 1))
    i, faites, duree_totale = 0, 0, 0.0
    while i < len(phrases):
        groupe = phrases[i:i + lot]
        textes = [p["texte"] for _, p in groupe]
        debut = time.time()
        try:
            if type_modele == "base":
                wavs, sr = tts.generate_voice_clone(text=textes, language=[langue] * len(textes),
                                                    voice_clone_prompt=invite, **reglages)
            elif type_modele == "custom_voice":
                wavs, sr = tts.generate_custom_voice(text=textes, speaker=[locuteur] * len(textes),
                                                     language=[langue] * len(textes),
                                                     instruct=[t.get("consigne") or ""] * len(textes)
                                                     if t.get("consigne") else None, **reglages)
            else:  # voice_design
                wavs, sr = tts.generate_voice_design(text=textes, instruct=[t.get("consigne") or ""] * len(textes),
                                                     language=[langue] * len(textes), **reglages)
        except Exception as e:  # noqa: BLE001
            if _manque_memoire(e) and lot > 1:
                lot = max(1, lot // 2)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                signaler(etat="info", id=ident, message=f"Mémoire vidéo insuffisante : lots réduits à {lot}.")
                continue
            raise
        secondes = (time.time() - debut) / len(groupe)
        for (index, p), wav in zip(groupe, wavs):
            audio = np.asarray(wav, dtype=np.float32)
            os.makedirs(os.path.dirname(os.path.abspath(p["sortie"])), exist_ok=True)
            sf.write(p["sortie"], audio, sr)
            duree = len(audio) / sr
            duree_totale += duree
            faites += 1
            signaler(etat="fait", id=ident, index=index, cle=p.get("cle"), fichier=p["sortie"],
                     duree=round(duree, 2), secondes=round(secondes, 1), faites=faites, total=len(phrases))
        i += len(groupe)
    signaler(etat="termine", id=ident, duree_audio=round(duree_totale, 1),
             secondes=round(time.time() - debut_travail, 1), lot=lot)


def serveur():
    signaler(etat="serveur", message="Qwen3-TTS prêt à recevoir des travaux.")
    for ligne in sys.stdin:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            t = json.loads(ligne)
        except ValueError:
            continue
        if t.get("commande") == "quitter":
            break
        ident = t.get("id")
        try:
            traiter(t, ident)
        except ErreurTravail as e:
            signaler(etat="erreur", id=ident, message=str(e))
        except Exception as e:  # noqa: BLE001
            signaler(etat="erreur", id=ident, message=f"{type(e).__name__} : {e}", details=traceback.format_exc())


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--serveur":
            serveur()
        else:
            with open(sys.argv[1], encoding="utf-8") as f:
                traiter(json.load(f))
    except (ErreurTravail, SystemExit) as e:
        signaler(etat="erreur", message=str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        signaler(etat="erreur", message=f"{type(e).__name__} : {e}", details=traceback.format_exc())
        sys.exit(1)
