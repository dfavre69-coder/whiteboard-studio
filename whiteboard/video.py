"""Accès à ffmpeg : durée des fichiers audio et écriture de la vidéo.

La vidéo est produite en deux temps : les images sont encodées en H.264 dans un fichier temporaire,
puis la bande-son est mixée (voix off, musique atténuée sous la voix, bruitages, normalisation) et
assemblée avec la vidéo sans la réencoder. On peut donc ajouter une piste calculée pendant le rendu
(le bruit du feutre) sans tout refaire.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_CREATION = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # pas de console noire


def chemin_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        trouve = shutil.which("ffmpeg")
        if trouve:
            return trouve
        raise RuntimeError("ffmpeg introuvable : relancez install.bat (paquet imageio-ffmpeg).")


def duree_audio(chemin: str) -> float:
    """Durée d'un fichier audio en secondes (lue par ffmpeg)."""
    res = subprocess.run([chemin_ffmpeg(), "-hide_banner", "-i", chemin],
                         capture_output=True, text=True, errors="replace", **_CREATION)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
    if not m:
        raise ValueError(f"Impossible de lire la durée de « {chemin} ».")
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


@dataclass
class PisteAudio:
    chemin: str
    debut: float  # secondes


def filtre_mixage(n_voix: int, musique: bool, sfx: bool, duree: float, volume_musique: float,
                  ducking: bool = True, normaliser: bool = True, volume_sfx: float = 1.0,
                  voix: list[PisteAudio] | None = None) -> str:
    """Graphe de filtres ffmpeg du mixage. Entrées : 0 = vidéo, 1… = voix, puis musique, puis bruitages."""
    voix = voix or []
    filtres, voies = [], []
    i = 1
    for v in voix:
        ms = max(0, int(round(v.debut * 1000)))
        filtres.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=delays={ms}:all=1[v{i}]")
        i += 1
    if n_voix == 1:
        filtres.append("[v1]acopy[vmix]")
    elif n_voix > 1:
        filtres.append(f"{''.join(f'[v{k}]' for k in range(1, n_voix + 1))}amix=inputs={n_voix}:normalize=0:"
                       f"duration=longest[vmix]")
    if n_voix:
        if musique and ducking:
            filtres.append("[vmix]asplit=2[vmix1][vsc]")
            voies.append("[vmix1]")
        else:
            voies.append("[vmix]")
    if musique:
        fin = max(0.0, duree - 2.0)
        filtres.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume_musique:.3f},"
                       f"afade=t=in:d=1,afade=t=out:st={fin:.2f}:d=2[mus0]")
        if n_voix and ducking:
            # La musique baisse dès que la voix parle (compression pilotée par la voix), puis remonte.
            filtres.append("[mus0][vsc]sidechaincompress=threshold=0.02:ratio=6:attack=12:release=350:"
                           "makeup=1:level_sc=1.5[mus]")
        else:
            filtres.append("[mus0]acopy[mus]")
        voies.append("[mus]")
        i += 1
    if sfx:
        filtres.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={volume_sfx:.3f}[sfx]")
        voies.append("[sfx]")
        i += 1
    if len(voies) == 1:
        filtres.append(f"{voies[0]}apad[mix]")
    else:
        filtres.append(f"{''.join(voies)}amix=inputs={len(voies)}:normalize=0:duration=longest,apad[mix]")
    if normaliser and (n_voix or musique):
        # -14 LUFS : le niveau auquel YouTube ramène les vidéos ; -1.5 dBTP évite toute saturation.
        # (Pas de normalisation quand il n'y a que les bruitages : le crissement du feutre doit rester discret.)
        filtres.append("[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        filtres.append("[mix]alimiter=limit=0.95[a]")
    return ";".join(filtres)


class EcrivainVideo:
    """Reçoit les images une par une et les encode en MP4 (H.264 + AAC)."""

    def __init__(self, sortie: str, largeur: int, hauteur: int, fps: int, duree: float,
                 voix: list[PisteAudio] | None = None, musique: str = "",
                 volume_musique: float = 0.12, qualite: int = 20, ducking: bool = True,
                 normaliser: bool = True):
        self.sortie, self.fps, self.duree = sortie, fps, duree
        self.voix, self.musique, self.volume_musique = voix or [], musique, volume_musique
        self.ducking, self.normaliser = ducking, normaliser
        self.sfx = ""            # piste de bruitages, fournie avant fermer()
        self.volume_sfx = 1.0
        self._temp = str(Path(sortie).with_name(Path(sortie).stem + ".video-temp.mp4"))
        cmd = [chemin_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{largeur}x{hauteur}",
               "-r", str(fps), "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(qualite),
               "-pix_fmt", "yuv420p", "-an", "-t", f"{duree:.3f}", self._temp]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_CREATION)

    def ecrire(self, image) -> None:
        try:
            self._proc.stdin.write(image.tobytes())
        except (BrokenPipeError, OSError):
            self._fin_video()

    def _fin_video(self) -> None:
        if self._proc.stdin and not self._proc.stdin.closed:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        erreur = self._proc.stderr.read().decode("utf-8", "replace") if self._proc.stderr else ""
        code = self._proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg a échoué (code {code}) :\n{erreur.strip()}")

    def fermer(self) -> None:
        self._fin_video()
        voix = [v for v in self.voix if Path(v.chemin).exists()]
        musique = self.musique if self.musique and Path(self.musique).exists() else ""
        sfx = self.sfx if self.sfx and Path(self.sfx).exists() else ""
        try:
            if not voix and not musique and not sfx:
                shutil.move(self._temp, self.sortie)
                return
            cmd = [chemin_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", self._temp]
            for v in voix:
                cmd += ["-i", v.chemin]
            if musique:
                cmd += ["-stream_loop", "-1", "-i", musique]
            if sfx:
                cmd += ["-i", sfx]
            graphe = filtre_mixage(len(voix), bool(musique), bool(sfx), self.duree, self.volume_musique,
                                   self.ducking, self.normaliser, self.volume_sfx, voix)
            cmd += ["-filter_complex", graphe, "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    "-t", f"{self.duree:.3f}", self.sortie]
            res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **_CREATION)
            if res.returncode != 0:
                raise RuntimeError(f"ffmpeg a échoué au mixage (code {res.returncode}) :\n{res.stderr.strip()}")
        finally:
            if os.path.exists(self._temp):
                try:
                    os.remove(self._temp)
                except OSError:
                    pass

    def annuler(self) -> None:
        try:
            self._proc.kill()
        finally:
            self._proc.wait()
            if os.path.exists(self._temp):
                try:
                    os.remove(self._temp)
                except OSError:
                    pass
