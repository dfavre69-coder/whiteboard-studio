"""Réglages de l'utilisateur (Ollama, Qwen3-TTS), communs à tous les projets."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def dossier_config() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "WhiteboardStudio"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "whiteboard-studio"


FICHIER_CONFIG = dossier_config() / "config.json"

MODELES_TTS = [
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
]
LANGUES_TTS = ["French", "Auto", "English", "German", "Spanish", "Italian", "Portuguese",
               "Chinese", "Japanese", "Korean", "Russian"]


@dataclass
class Reglages:
    # --- Ollama -----------------------------------------------------------
    ollama_url: str = "http://localhost:11434"
    ollama_modele: str = ""
    ollama_contexte: int = 32768
    ollama_temperature: float = 0.7
    ollama_sans_reflexion: bool = True     # « /no_think » + think=false : plus rapide, meilleur en rédaction
    ollama_liberer_vram: bool = True       # décharge le modèle après la réponse (place pour la synthèse vocale)
    # --- Qwen3-TTS ----------------------------------------------------------
    tts_python: str = ""                   # python.exe de l'environnement où « qwen-tts » est installé
    tts_modele: str = MODELES_TTS[0]       # identifiant Hugging Face ou dossier local
    tts_appareil: str = "cuda:0"
    tts_precision: str = "bfloat16"
    tts_langue: str = "French"
    tts_voix_reference: str = ""           # extrait audio de la voix à cloner (modèles « Base »)
    tts_texte_reference: str = ""          # ce qui est dit dans l'extrait (vide = mode « timbre seul »)
    tts_locuteur: str = ""                 # voix prédéfinie (modèles « CustomVoice »)
    tts_consigne: str = ""                 # consigne de style (modèles « CustomVoice »), facultative
    tts_temperature: float = 0.9
    tts_lot: int = 4                       # phrases générées ensemble par la carte graphique
    tts_garder_minutes: int = 5            # modèle gardé en mémoire entre deux générations (0 = non)
    # --- Illustrations générées par une IA d'images -----------------------------
    style_illustrations: str = ""          # vide = style par défaut (illustrations.STYLE_PAR_DEFAUT)

    @classmethod
    def charger(cls, chemin: Path | None = None) -> "Reglages":
        chemin = chemin or FICHIER_CONFIG
        try:
            d = json.loads(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        noms = {f.name for f in fields(cls)}
        r = cls(**{k: v for k, v in d.items() if k in noms})
        return r

    def enregistrer(self, chemin: Path | None = None) -> None:
        chemin = Path(chemin or FICHIER_CONFIG)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
