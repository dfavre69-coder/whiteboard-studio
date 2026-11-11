"""Bruitages synthétisés : le feutre qui crisse quand la main dessine, un « pop » quand les couleurs
apparaissent, un « tampon » quand un texte d'accroche surgit.

Tout est calculé avec numpy à partir du journal de l'animation (vitesse de la pointe à chaque image) :
aucun fichier son à fournir, et le bruit suit exactement le tracé.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

FREQ = 48000
NIVEAU_FEUTRE = 0.16    # amplitude du crissement (≈ -16 dBFS en pointe)
NIVEAU_POP = 0.30


def _bande(signal: np.ndarray, f_bas: float, f_haut: float) -> np.ndarray:
    """Filtre passe-bande par FFT, aux flancs doux."""
    n = len(signal)
    spectre = np.fft.rfft(signal)
    f = np.fft.rfftfreq(n, 1 / FREQ)
    gain = np.clip((f - f_bas * 0.7) / (f_bas * 0.3), 0, 1) * np.clip((f_haut * 1.3 - f) / (f_haut * 0.3), 0, 1)
    return np.fft.irfft(spectre * gain, n)


def bruit_feutre(vitesses: list[float], fps: int, graine: int = 7) -> np.ndarray:
    """Crissement du feutre dont le volume suit la vitesse de la pointe, image par image."""
    n_images = len(vitesses)
    n = int(round(n_images * FREQ / fps))
    if n <= 0:
        return np.zeros(0, np.float32)
    v = np.asarray(vitesses, dtype=np.float64)
    actifs = v[v > 0.5]
    ref = float(np.percentile(actifs, 75)) if len(actifs) else 1.0
    env = np.clip(v / max(ref, 1e-6), 0, 1.3) ** 0.6
    # Un peu de lissage : la main ne freine pas instantanément
    noyau = np.array([0.25, 0.5, 0.25])
    env = np.convolve(np.pad(env, 1, mode="edge"), noyau, mode="valid")
    t_images = np.arange(n_images) / fps
    t = np.arange(n) / FREQ
    enveloppe = np.interp(t, t_images, env)
    rng = np.random.default_rng(graine)
    bruit = rng.standard_normal(n)
    bruit = _bande(bruit, 1500.0, 6500.0)
    bruit /= max(1e-6, float(np.percentile(np.abs(bruit), 99)))
    # Légère modulation : le crissement n'est pas un souffle continu
    grain = 0.75 + 0.25 * np.sin(2 * np.pi * 37 * t + 3 * np.sin(2 * np.pi * 5 * t))
    return (bruit * enveloppe * grain * NIVEAU_FEUTRE).astype(np.float32)


def pop(duree: float = 0.09, f0: float = 900.0, f1: float = 420.0, niveau: float = NIVEAU_POP) -> np.ndarray:
    """Petit « pop » : sinus glissant de f0 à f1 avec décroissance rapide."""
    n = int(duree * FREQ)
    t = np.arange(n) / FREQ
    f = f0 + (f1 - f0) * (t / duree)
    phase = 2 * np.pi * np.cumsum(f) / FREQ
    env = np.exp(-t * 38) * np.minimum(1.0, t * 800)
    return (np.sin(phase) * env * niveau).astype(np.float32)


def tampon(niveau: float = NIVEAU_POP) -> np.ndarray:
    """« Tampon » : un coup sourd bref suivi d'un claquement."""
    n = int(0.12 * FREQ)
    t = np.arange(n) / FREQ
    coup = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 45)
    rng = np.random.default_rng(3)
    clac = _bande(rng.standard_normal(n), 2500, 7000)
    clac = clac / max(1e-6, float(np.abs(clac).max())) * np.exp(-t * 90)
    return ((coup + 0.5 * clac) * niveau).astype(np.float32)


def generer(vitesses: list[float], evenements: list[tuple[int, str]], fps: int, chemin: str | Path,
            feutre: bool = True) -> str:
    """Écrit la piste de bruitages (WAV mono 48 kHz) et renvoie son chemin."""
    n = int(round(len(vitesses) * FREQ / fps))
    piste = np.zeros(max(n, FREQ // 10), np.float32)
    if feutre and vitesses:
        b = bruit_feutre(vitesses, fps)
        piste[:len(b)] += b
    sons = {"couleur": pop(), "tampon": tampon()}
    for image, genre in evenements:
        son = sons.get(genre)
        if son is None:
            continue
        debut = int(image * FREQ / fps)
        fin = min(len(piste), debut + len(son))
        if fin > debut:
            piste[debut:fin] += son[:fin - debut]
    piste = np.clip(piste, -1, 1)
    chemin = Path(chemin)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FREQ)
        w.writeframes((piste * 32767).astype("<i2").tobytes())
    return str(chemin)
