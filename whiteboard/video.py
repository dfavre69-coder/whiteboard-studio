"""Accès à ffmpeg : durée des fichiers audio et écriture de la vidéo."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

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


class EcrivainVideo:
    """Reçoit les images une par une et les encode en MP4 (H.264 + AAC)."""

    def __init__(self, sortie: str, largeur: int, hauteur: int, fps: int, duree: float,
                 voix: list[PisteAudio] | None = None, musique: str = "",
                 volume_musique: float = 0.12, qualite: int = 20):
        cmd = [chemin_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{largeur}x{hauteur}",
               "-r", str(fps), "-i", "-"]
        voix = voix or []
        for v in voix:
            cmd += ["-i", v.chemin]
        if musique:
            cmd += ["-stream_loop", "-1", "-i", musique]

        filtres, sorties = [], []
        for i, v in enumerate(voix, start=1):
            ms = max(0, int(round(v.debut * 1000)))
            filtres.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                           f"adelay=delays={ms}:all=1[v{i}]")
            sorties.append(f"[v{i}]")
        if musique:
            m = len(voix) + 1
            fin = max(0.0, duree - 2.0)
            filtres.append(f"[{m}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                           f"volume={volume_musique:.3f},afade=t=in:d=1,"
                           f"afade=t=out:st={fin:.2f}:d=2[mus]")
            sorties.append("[mus]")
        if sorties:
            if len(sorties) == 1:
                filtres.append(f"{sorties[0]}apad[a]")
            else:
                filtres.append(f"{''.join(sorties)}amix=inputs={len(sorties)}:normalize=0:"
                               f"duration=longest,apad[a]")
            cmd += ["-filter_complex", ";".join(filtres), "-map", "0:v", "-map", "[a]",
                    "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(qualite),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-t", f"{duree:.3f}", sortie]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_CREATION)

    def ecrire(self, image) -> None:
        try:
            self._proc.stdin.write(image.tobytes())
        except (BrokenPipeError, OSError):
            self.fermer()

    def fermer(self) -> None:
        if self._proc.stdin and not self._proc.stdin.closed:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        erreur = self._proc.stderr.read().decode("utf-8", "replace") if self._proc.stderr else ""
        code = self._proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg a échoué (code {code}) :\n{erreur.strip()}")

    def annuler(self) -> None:
        try:
            self._proc.kill()
        finally:
            self._proc.wait()
