"""Génération des voix off avec Qwen3-TTS.

Ce script est exécuté par l'interpréteur Python de l'environnement où
« qwen-tts » et PyTorch sont installés (pas celui de Whiteboard Studio) :

    python tts_worker.py travail.json

Il n'importe rien de Whiteboard Studio. Il charge le modèle une seule fois,
génère chaque phrase et signale son avancement par des lignes JSON sur la
sortie standard.
"""
import json
import os
import sys
import time
import traceback


def signaler(**d):
    sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(chemin_travail):
    with open(chemin_travail, encoding="utf-8") as f:
        t = json.load(f)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    signaler(etat="chargement", message="Chargement de PyTorch et de qwen-tts…")
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    appareil = t.get("appareil") or "cuda:0"
    if appareil.startswith("cuda") and not torch.cuda.is_available():
        signaler(etat="info", message="Carte graphique CUDA indisponible : calcul sur le processeur (lent).")
        appareil = "cpu"
    precision = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}.get(
        t.get("precision") or "bfloat16", torch.bfloat16)
    if appareil == "cpu" and precision != torch.float32:
        precision = torch.float32

    signaler(etat="chargement", message=f"Chargement du modèle {t['modele']} sur {appareil}…")
    debut = time.time()
    tts = Qwen3TTSModel.from_pretrained(t["modele"], device_map=appareil, dtype=precision)
    type_modele = getattr(tts.model, "tts_model_type", "base")
    signaler(etat="pret", message=f"Modèle chargé en {time.time() - debut:.0f} s (type : {type_modele}).")

    langue = t.get("langue") or "Auto"
    reglages_generation = {}
    if t.get("temperature"):
        reglages_generation["temperature"] = float(t["temperature"])

    invite = None
    if type_modele == "base":
        ref = t.get("voix_reference") or ""
        if not ref or not os.path.exists(ref):
            raise SystemExit("Ce modèle clone une voix : indiquez un extrait audio de référence dans les réglages.")
        texte_ref = (t.get("texte_reference") or "").strip()
        invite = tts.create_voice_clone_prompt(ref_audio=ref, ref_text=texte_ref or None,
                                               x_vector_only_mode=not texte_ref)

    for i, item in enumerate(t["phrases"]):
        debut = time.time()
        if type_modele == "base":
            wavs, sr = tts.generate_voice_clone(text=item["texte"], language=langue,
                                                voice_clone_prompt=invite, **reglages_generation)
        elif type_modele == "custom_voice":
            locuteur = t.get("locuteur") or (tts.get_supported_speakers() or [""])[0]
            wavs, sr = tts.generate_custom_voice(text=item["texte"], speaker=locuteur, language=langue,
                                                 instruct=t.get("consigne") or None, **reglages_generation)
        else:  # voice_design
            wavs, sr = tts.generate_voice_design(text=item["texte"], instruct=t.get("consigne") or "",
                                                 language=langue, **reglages_generation)
        audio = np.asarray(wavs[0], dtype=np.float32)
        os.makedirs(os.path.dirname(os.path.abspath(item["sortie"])), exist_ok=True)
        sf.write(item["sortie"], audio, sr)
        signaler(etat="fait", index=i, cle=item.get("cle"), fichier=item["sortie"],
                 duree=round(len(audio) / sr, 2), secondes=round(time.time() - debut, 1))
    signaler(etat="termine")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except SystemExit as e:
        signaler(etat="erreur", message=str(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        signaler(etat="erreur", message=f"{type(e).__name__} : {e}", details=traceback.format_exc())
        sys.exit(1)
