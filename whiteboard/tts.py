"""Pilotage de Qwen3-TTS depuis Whiteboard Studio.

Qwen3-TTS (PyTorch, CUDA…) vit dans son propre environnement Python : Whiteboard
Studio lance `tts_worker.py` avec l'interpréteur de cet environnement.

Pour la vitesse :
- le script génère plusieurs phrases à la fois (lots) ;
- pendant une session, il reste ouvert et garde le modèle chargé : une deuxième
  génération démarre immédiatement. Il s'arrête de lui-même après quelques minutes
  d'inactivité, ce qui libère la mémoire vidéo (pour Ollama, par exemple) ;
- chaque voix générée porte une empreinte (texte + réglages de voix) : seules les
  narrations modifiées sont regénérées.
"""
from __future__ import annotations

import atexit
import hashlib
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


def empreinte(texte: str, r: Reglages) -> str:
    """Identifie une voix off : si le texte ou un réglage de voix change, l'empreinte change."""
    ref = Path(r.tts_voix_reference) if r.tts_voix_reference else None
    infos_ref = (str(ref), ref.stat().st_mtime, ref.stat().st_size) if ref and ref.exists() else None
    contenu = json.dumps([texte.strip(), r.tts_modele, r.tts_langue, infos_ref, r.tts_texte_reference.strip(),
                          r.tts_locuteur, r.tts_consigne, r.tts_temperature], ensure_ascii=False)
    return hashlib.sha1(contenu.encode("utf-8")).hexdigest()[:16]


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


def _travail(phrases: list[Phrase], r: Reglages) -> dict:
    return {
        "modele": r.tts_modele, "appareil": r.tts_appareil, "precision": r.tts_precision,
        "langue": r.tts_langue, "voix_reference": r.tts_voix_reference,
        "texte_reference": r.tts_texte_reference, "locuteur": r.tts_locuteur,
        "consigne": r.tts_consigne, "temperature": r.tts_temperature, "lot": r.tts_lot,
        "phrases": [{"texte": p.texte, "sortie": str(p.sortie), "cle": p.cle} for p in phrases],
    }


def _env() -> dict:
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")


# ---------------------------------------------------------------------------
# Processus persistant : le modèle reste chargé entre deux générations
# ---------------------------------------------------------------------------
class ServeurTTS:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._python = ""
        self._verrou = threading.Lock()
        self._minuteur: threading.Timer | None = None
        self._erreurs: list[str] = []
        self._numero = 0

    @property
    def actif(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _demarrer(self, python: str) -> None:
        self.arreter()
        self._erreurs = []
        self._proc = subprocess.Popen([python, "-u", str(SCRIPT_TRAVAIL), "--serveur"], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8", errors="replace", env=_env(), **_CREATION)
        self._python = python
        proc = self._proc
        threading.Thread(target=lambda: [self._erreurs.append(l) for l in proc.stderr], daemon=True).start()

    def arreter(self) -> None:
        if self._minuteur is not None:
            self._minuteur.cancel()
            self._minuteur = None
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write(json.dumps({"commande": "quitter"}) + "\n")
                proc.stdin.flush()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            if proc.poll() is None:
                proc.kill()

    def _programmer_arret(self, minutes: float) -> None:
        if self._minuteur is not None:
            self._minuteur.cancel()
        if minutes > 0:
            self._minuteur = threading.Timer(minutes * 60, self.arreter)
            self._minuteur.daemon = True
            self._minuteur.start()
        else:
            self.arreter()

    def generer(self, phrases: list[Phrase], r: Reglages, evenement=None, arret=None) -> list[dict]:
        with self._verrou:
            if self._minuteur is not None:
                self._minuteur.cancel()
            if not self.actif or self._python != r.tts_python:
                self._demarrer(r.tts_python)
            self._numero += 1
            ident = self._numero
            travail = dict(_travail(phrases, r), commande="generer", id=ident)
            proc = self._proc
            try:
                proc.stdin.write(json.dumps(travail, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except OSError as e:
                self.arreter()
                raise ErreurTTS(f"Qwen3-TTS ne répond pas : {e}") from e
            faits, erreur, fini = [], None, False
            surveillance = None
            if arret is not None:  # l'annulation arrête le processus (le modèle sera rechargé)
                def guetter():
                    while not fini and proc.poll() is None:
                        if arret.wait(0.2):
                            proc.kill()
                            return
                surveillance = threading.Thread(target=guetter, daemon=True)
                surveillance.start()
            try:
                for ligne in proc.stdout:
                    ligne = ligne.strip()
                    if not ligne.startswith("{"):
                        continue
                    try:
                        msg = json.loads(ligne)
                    except ValueError:
                        continue
                    if msg.get("id") not in (None, ident):
                        continue
                    if evenement:
                        evenement(msg)
                    if msg.get("etat") == "fait":
                        faits.append(msg)
                    elif msg.get("etat") == "erreur":
                        erreur = msg.get("message", "erreur inconnue")
                        if msg.get("id") == ident:
                            break
                    elif msg.get("etat") == "termine" and msg.get("id") == ident:
                        break
            finally:
                fini = True
            if arret is not None and arret.is_set():
                self.arreter()
                raise Annule()
            if erreur is None and not self.actif:
                detail = ("".join(self._erreurs).strip().splitlines() or ["arrêt inattendu"])[-1]
                self.arreter()
                raise ErreurTTS(f"Qwen3-TTS s'est arrêté : {detail}")
            if erreur is not None:
                if not self.actif:
                    self.arreter()
                raise ErreurTTS(f"Qwen3-TTS a échoué : {erreur}")
            self._programmer_arret(r.tts_garder_minutes)
            return faits


_SERVEUR = ServeurTTS()
atexit.register(_SERVEUR.arreter)


def liberer() -> None:
    """Arrête le processus Qwen3-TTS (libère la mémoire vidéo)."""
    _SERVEUR.arreter()


def modele_charge() -> bool:
    return _SERVEUR.actif


def generer(phrases: list[Phrase], r: Reglages,
            evenement: Callable[[dict], None] | None = None,
            arret: threading.Event | None = None, persistant: bool | None = None) -> list[dict]:
    """Génère les fichiers audio. `evenement` reçoit chaque message du script de travail.

    Renvoie la liste des messages « fait ». Par défaut, le modèle reste chargé entre deux
    appels si `r.tts_garder_minutes` > 0 (interface) ; la ligne de commande passe
    persistant=False.
    """
    verifier_reglages(r)
    if not phrases:
        return []
    if persistant is None:
        persistant = r.tts_garder_minutes > 0
    if persistant:
        return _SERVEUR.generer(phrases, r, evenement, arret)
    return _generer_une_fois(phrases, r, evenement, arret)


def _generer_une_fois(phrases, r, evenement, arret) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(_travail(phrases, r), f, ensure_ascii=False)
        chemin = f.name
    proc = subprocess.Popen([r.tts_python, "-u", str(SCRIPT_TRAVAIL), chemin], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=_env(),
                            **_CREATION)
    erreurs: list[str] = []
    threading.Thread(target=lambda: erreurs.extend(proc.stderr), daemon=True).start()
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
