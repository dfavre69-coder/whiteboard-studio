"""Ligne de commande.

    python -m whiteboard                       → ouvre l'interface
    python -m whiteboard rendu projet.json     → fabrique la vidéo
    python -m whiteboard demo [dossier]        → crée le projet de démonstration
    python -m whiteboard plan plan.txt         → crée un projet à partir d'un plan texte
    python -m whiteboard prompt texte.txt      → prépare le prompt pour une IA
    python -m whiteboard ia reponse.txt        → crée le projet à partir de la réponse de l'IA
    python -m whiteboard narrations projet.json dossier   → 01.txt, 02.txt… pour la synthèse vocale
    python -m whiteboard voix projet.json dossier         → rattache 01.wav, 02.wav… aux scènes
    python -m whiteboard ollama texte.txt      → texte → projet, rédigé par le modèle local Ollama
    python -m whiteboard tts projet.json       → génère les voix off avec Qwen3-TTS
(Ollama et Qwen3-TTS utilisent les réglages enregistrés depuis l'interface.)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _barre(f: float, msg: str) -> None:
    n = int(f * 30)
    sys.stdout.write(f"\r[{'#' * n}{'.' * (30 - n)}] {f * 100:5.1f} %  {msg[:60]:<60}")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="whiteboard", description="Vidéos « main qui dessine ».")
    sous = ap.add_subparsers(dest="commande")

    r = sous.add_parser("rendu", help="fabriquer la vidéo d'un projet")
    r.add_argument("projet")
    r.add_argument("-o", "--sortie", help="fichier MP4 (par défaut : à côté du projet)")
    r.add_argument("--apercu", action="store_true", help="rendu rapide en basse définition")
    r.add_argument("--scenes", help="numéros des scènes à rendre, ex. 1,3")

    dm = sous.add_parser("demo", help="créer le projet de démonstration")
    dm.add_argument("dossier", nargs="?", default="demo")

    pl = sous.add_parser("plan", help="créer un projet depuis un plan texte (# Titre / texte)")
    pl.add_argument("fichier")
    pl.add_argument("-o", "--sortie", help="projet JSON à créer")

    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0].lower().endswith(".json"):  # double-clic sur un projet
        from .gui import lancer
        lancer(argv[0])
        return 0
    pr = sous.add_parser("prompt", help="préparer le prompt « texte → vidéo » pour une IA")
    pr.add_argument("texte", help="fichier texte source")
    pr.add_argument("--duree", type=float, default=3, help="durée visée en minutes (défaut 3)")
    pr.add_argument("--ton", default="", help="public et ton souhaités")
    pr.add_argument("-o", "--sortie", help="fichier où écrire le prompt (sinon : affiché)")

    ia = sous.add_parser("ia", help="créer un projet à partir de la réponse d'une IA")
    ia.add_argument("reponse", help="fichier contenant la réponse de l'IA")
    ia.add_argument("-o", "--sortie", help="projet JSON à créer")
    ia.add_argument("--base", help="projet dont on reprend les réglages (format, main, musique…)")

    na = sous.add_parser("narrations", help="exporter les textes de voix off (01.txt, 02.txt…)")
    na.add_argument("projet")
    na.add_argument("dossier")

    vo = sous.add_parser("voix", help="rattacher les fichiers audio d'un dossier aux scènes")
    vo.add_argument("projet")
    vo.add_argument("dossier")

    ol = sous.add_parser("ollama", help="faire rédiger le projet par un modèle Ollama local")
    ol.add_argument("texte", help="fichier texte source")
    ol.add_argument("-o", "--sortie", help="projet JSON à créer")
    ol.add_argument("--duree", type=float, default=3)
    ol.add_argument("--ton", default="")
    ol.add_argument("--modele", help="modèle Ollama (sinon : celui des réglages)")

    tt = sous.add_parser("tts", help="générer les voix off des narrations avec Qwen3-TTS")
    tt.add_argument("projet")
    tt.add_argument("--toutes", action="store_true", help="regénérer aussi les voix à jour")

    args = ap.parse_args(argv)

    if args.commande is None:
        from .gui import lancer
        lancer()
        return 0

    from .projet import Projet, depuis_plan_texte

    if args.commande == "demo":
        from .demo import creer_demo
        chemin = creer_demo(args.dossier)
        print(f"Projet de démonstration créé : {chemin}")
        print(f"Pour fabriquer la vidéo : python -m whiteboard rendu \"{chemin}\"")
        return 0

    if args.commande == "plan":
        source = Path(args.fichier)
        p = Projet(scenes=depuis_plan_texte(source.read_text(encoding="utf-8")))
        sortie = Path(args.sortie) if args.sortie else source.with_suffix(".json")
        p.enregistrer(sortie)
        print(f"{len(p.scenes)} scène(s) → {sortie}")
        return 0

    if args.commande == "prompt":
        from .ia import construire_prompt
        texte = Path(args.texte).read_text(encoding="utf-8", errors="replace")
        prompt = construire_prompt(texte, args.duree, args.ton)
        if args.sortie:
            Path(args.sortie).write_text(prompt, encoding="utf-8")
            print(f"Prompt écrit dans {args.sortie} ({len(prompt)} caractères).")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            print(prompt)
        return 0

    if args.commande == "ia":
        from .ia import projet_depuis_ia
        reponse = Path(args.reponse).read_text(encoding="utf-8", errors="replace")
        base = Projet.charger(args.base) if args.base else None
        p, remarques = projet_depuis_ia(reponse, base)
        sortie = Path(args.sortie) if args.sortie else Path(args.reponse).with_suffix(".json")
        p.enregistrer(sortie)
        for r in remarques:
            print("  •", r)
        print(f"{len(p.scenes)} scène(s) → {sortie}")
        return 0

    if args.commande in ("narrations", "voix"):
        from .ia import associer_voix, exporter_narrations
        p = Projet.charger(args.projet)
        if args.commande == "narrations":
            n = exporter_narrations(p, args.dossier)
            print(f"{n} narration(s) écrite(s) dans {args.dossier}")
        else:
            trouves = associer_voix(p, args.dossier)
            p.enregistrer(args.projet)
            for num, nom in trouves:
                print(f"  scène {num} ← {nom}")
            print(f"{len(trouves)} voix off rattachée(s) ; projet enregistré.")
        return 0

    if args.commande == "ollama":
        from .config import Reglages
        from .ia import construire_prompt, projet_depuis_ia
        from .ollama import generer
        r = Reglages.charger()
        if args.modele:
            r.ollama_modele = args.modele
        texte = Path(args.texte).read_text(encoding="utf-8", errors="replace")
        reponse = generer(construire_prompt(texte, args.duree, args.ton), r,
                          lambda t, st: _barre(min(0.99, len(t) / 6000), f"{st.caracteres} caractères"))
        p, remarques = projet_depuis_ia(reponse)
        sortie = Path(args.sortie) if args.sortie else Path(args.texte).with_suffix(".json")
        p.enregistrer(sortie)
        print()
        for rq in remarques:
            print("  •", rq)
        print(f"{len(p.scenes)} scène(s) → {sortie}")
        return 0

    if args.commande == "tts":
        from . import tts
        from .config import Reglages
        chemin = Path(args.projet)
        p = Projet.charger(chemin)
        dossier = chemin.parent / f"{chemin.stem}_voix"
        largeur = max(2, len(str(len(p.scenes))))
        r = Reglages.charger()
        empreintes = {i: tts.empreinte(s.narration, r) for i, s in enumerate(p.scenes) if s.narration.strip()}
        phrases = [tts.Phrase(p.scenes[i].narration.strip(), str(dossier / f"{i + 1:0{largeur}d}.wav"), i)
                   for i in empreintes
                   if args.toutes or not (p.scenes[i].audio and Path(p.scenes[i].audio).exists()
                                          and p.scenes[i].audio_empreinte == empreintes[i])]

        def afficher(msg):
            if msg.get("etat") == "fait":
                print(f"  scène {msg['cle'] + 1} : {msg['duree']} s")
            elif msg.get("message"):
                print(msg["message"])

        for f in tts.generer(phrases, r, afficher, persistant=False):
            sc = p.scenes[f["cle"]]
            sc.audio, sc.caler_sur_audio, sc.audio_empreinte = f["fichier"], True, empreintes[f["cle"]]
        p.enregistrer(chemin)
        print(f"{len(phrases)} voix off générée(s) dans {dossier} ; projet enregistré.")
        return 0

    from .rendu import exporter
    chemin = Path(args.projet)
    p = Projet.charger(chemin)
    indices = None
    if args.scenes:
        indices = [int(x) - 1 for x in args.scenes.split(",") if x.strip()]
    sortie = args.sortie or str(chemin.with_name(chemin.stem + ("_apercu" if args.apercu else "") + ".mp4"))
    debut = time.time()
    exporter(p, sortie, _barre, echelle=0.5 if args.apercu else 1.0, indices=indices)
    print(f"\nVidéo créée : {sortie}  ({time.time() - debut:.0f} s)")
    return 0
