"""Pilotage de Qwen3-TTS depuis Whiteboard Studio.

Qwen3-TTS (PyTorch, CUDA…) vit dans son propre environnement Python. Whiteboard
Studio lui confie un fichier de travail et lance `tts_worker.py` avec
l'interpréteur de cet environnement : rien de lourd n'est installé ici, et
le modèle tourne dans un processus séparé (fil principal, mémoire libérée à
la fin).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Reglages

SCRIPT_TRAVAIL = Path(__file__).parent / "tts_worker.py"
_CREATION = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


class ErreurTTS(RuntimeError):
    pass


class Annule(Exception):
    pass


@dataclass
class Phrase:
    texte: str
    sortie: str
    cle: object = None   # identifiant libre (ex. index de la scène)


def verifier_reglages(r: Reglages) -> None:
    if not r.tts_python or not Path(r.tts_python).exists():
        raise ErreurTTS("Indiquez dans « Réglages IA et voix » le python.exe de l'environnement où "
                        "Qwen3-TTS est installé (par exemple …\\qwen_env\\Scripts\\python.exe).")
    if "base" in r.tts_modele.lower() and not (r.tts_voix_reference and Path(r.tts_voix_reference).exists()):
        raise ErreurTTS("Le modèle « Base » clone une voix : choisissez un extrait audio de référence "
                        "(10 à 20 secondes de parole claire) dans « Réglages IA et voix ».")


def diagnostiquer(r: Reglages) -> str:
    """Vérifie l'environnement Qwen3-TTS : versions, carte graphique."""
    if not r.tts_python or not Path(r.tts_python).exists():
        raise ErreurTTS("Interpréteur Python introuvable.")
    code = ("import json, torch, qwen_tts, soundfile; "
            "print(json.dumps({'torch': torch.__version__, 'cuda': torch.cuda.is_available(), "
            "'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '', "
            "'qwen_tts': getattr(qwen_tts, '__version__', 'installé')}))")
    res = subprocess.run([r.tts_python, "-c", code], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=180, **_CREATION)
    if res.returncode != 0:
        derniere = (res.stderr.strip().splitlines() or ["erreur inconnue"])[-1]
        raise ErreurTTS(f"Cet environnement ne peut pas lancer Qwen3-TTS : {derniere}")
    infos = json.loads(res.stdout.strip().splitlines()[-1])
    carte = f"carte graphique : {infos['gpu']}" if infos["cuda"] else "pas de carte graphique CUDA (calcul lent)"
    return f"OK — PyTorch {infos['torch']}, qwen-tts {infos['qwen_tts']}, {carte}."


def generer(phrases: list[Phrase], r: Reglages,
            evenement: Callable[[dict], None] | None = None,
            arret: threading.Event | None = None) -> list[dict]:
    """Génère les fichiers audio. `evenement` reçoit chaque message du script de travail.

    Renvoie la liste des messages « fait ».
    """
    verifier_reglages(r)
    if not phrases:
        return []
    travail = {
        "modele": r.tts_modele, "appareil": r.tts_appareil, "precision": r.tts_precision,
        "langue": r.tts_langue, "voix_reference": r.tts_voix_reference,
        "texte_reference": r.tts_texte_reference, "locuteur": r.tts_locuteur,
        "consigne": r.tts_consigne, "temperature": r.tts_temperature,
        "phrases": [{"texte": p.texte, "sortie": str(p.sortie), "cle": p.cle} for p in phrases],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(travail, f, ensure_ascii=False)
        chemin = f.name
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([r.tts_python, "-u", str(SCRIPT_TRAVAIL), chemin], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env,
                            **_CREATION)
    erreurs: list[str] = []
    lecteur = threading.Thread(target=lambda: erreurs.extend(proc.stderr), daemon=True)
    lecteur.start()
    faits, erreur = [], None
    try:
        for ligne in proc.stdout:
            if arret is not None and arret.is_set():
                proc.kill()
                raise Annule()
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                msg = json.loads(ligne)
            except ValueError:
                continue
            if msg.get("etat") == "fait":
                faits.append(msg)
            elif msg.get("etat") == "erreur":
                erreur = msg.get("message", "erreur inconnue")
            if evenement:
                evenement(msg)
        code = proc.wait()
        if arret is not None and arret.is_set():
            raise Annule()
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.unlink(chemin)
        except OSError:
            pass
    if erreur or code != 0:
        detail = erreur or ("".join(erreurs).strip().splitlines() or [f"code de sortie {code}"])[-1]
        raise ErreurTTS(f"Qwen3-TTS a échoué : {detail}")
    return faits
