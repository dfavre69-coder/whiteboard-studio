"""Client minimal pour Ollama (modèles d'IA locaux), sans dépendance externe."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .config import Reglages


class ErreurOllama(RuntimeError):
    pass


class Arrete(Exception):
    pass


def _url(base: str, chemin: str) -> str:
    return base.rstrip("/") + chemin


def lister_modeles(url: str, delai: float = 5) -> list[str]:
    """Noms des modèles installés dans Ollama."""
    try:
        with urllib.request.urlopen(_url(url, "/api/tags"), timeout=delai) as r:
            donnees = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ErreurOllama(f"Ollama ne répond pas à {url} ({e.reason}). Est-il lancé ?") from e
    except (OSError, ValueError) as e:
        raise ErreurOllama(f"Réponse inattendue d'Ollama : {e}") from e
    return sorted(m.get("name", "") for m in donnees.get("models", []) if m.get("name"))


@dataclass
class Statistiques:
    caracteres: int = 0
    jetons: int = 0
    secondes: float = 0.0
    reflexion: bool = False   # le modèle est en train de « réfléchir » (balises <think>)

    @property
    def jetons_par_seconde(self) -> float:
        return self.jetons / self.secondes if self.secondes > 0 else 0.0


def retirer_reflexion(texte: str) -> str:
    texte = re.sub(r"<think>.*?</think>", "", texte, flags=re.S)
    if "<think>" in texte:  # balise non refermée
        texte = texte.split("<think>")[0]
    return texte.strip()


def generer(prompt: str, reglages: Reglages, progression: Callable[[str, Statistiques], None] | None = None,
            arret: threading.Event | None = None, format_json: bool = True) -> str:
    """Envoie le prompt au modèle choisi et renvoie sa réponse complète (en continu via `progression`)."""
    if not reglages.ollama_modele:
        raise ErreurOllama("Aucun modèle Ollama choisi (Réglages IA et voix).")
    contenu = prompt + ("\n\n/no_think" if reglages.ollama_sans_reflexion else "")
    corps = {
        "model": reglages.ollama_modele,
        "messages": [{"role": "user", "content": contenu}],
        "stream": True,
        "options": {"num_ctx": int(reglages.ollama_contexte), "temperature": float(reglages.ollama_temperature)},
    }
    if format_json:
        corps["format"] = "json"
    if reglages.ollama_sans_reflexion:
        corps["think"] = False
    if reglages.ollama_liberer_vram:
        corps["keep_alive"] = 0

    try:
        return _envoyer(corps, reglages.ollama_url, progression, arret)
    except ErreurOllama as e:
        # Anciennes versions d'Ollama ou modèle sans mode « réflexion » : on retente sans ces options
        message = str(e).lower()
        if "think" in message and "think" in corps:
            corps.pop("think")
            return _envoyer(corps, reglages.ollama_url, progression, arret)
        if "format" in message and "format" in corps:
            corps.pop("format")
            return _envoyer(corps, reglages.ollama_url, progression, arret)
        raise


def _envoyer(corps: dict, url: str, progression, arret) -> str:
    requete = urllib.request.Request(_url(url, "/api/chat"), data=json.dumps(corps).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    stats = Statistiques()
    debut = time.time()
    morceaux: list[str] = []
    try:
        reponse = urllib.request.urlopen(requete, timeout=600)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise ErreurOllama(f"Ollama a refusé la requête : {detail}") from e
    except urllib.error.URLError as e:
        raise ErreurOllama(f"Ollama ne répond pas à {url} ({e.reason}). Est-il lancé ?") from e
    with reponse:
        for ligne in reponse:
            if arret is not None and arret.is_set():
                raise Arrete()
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                d = json.loads(ligne.decode("utf-8"))
            except ValueError:
                continue
            if d.get("error"):
                raise ErreurOllama(str(d["error"]))
            message = d.get("message") or {}
            texte = message.get("content") or ""
            stats.reflexion = bool(message.get("thinking"))
            if texte:
                morceaux.append(texte)
                stats.caracteres += len(texte)
            stats.jetons += 1 if (texte or message.get("thinking")) else 0
            if d.get("done"):
                if d.get("eval_count"):
                    stats.jetons = int(d["eval_count"])
                if d.get("eval_duration"):
                    stats.secondes = d["eval_duration"] / 1e9
            else:
                stats.secondes = time.time() - debut
            if progression:
                progression("".join(morceaux), stats)
            if d.get("done"):
                break
    return retirer_reflexion("".join(morceaux))
