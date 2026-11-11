"""Rythme Short, sous-titres, bande-son, zone sûre 9:16, modèle accroche, miniature et publication."""
import json
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from whiteboard import audio_sfx, publication as P, sous_titres as ST
from whiteboard.ia import construire_prompt, projet_depuis_ia, regler_short
from whiteboard.modeles import MODELES
from whiteboard.projet import Projet, Scene
from whiteboard.rendu import Animateur, exporter, minutage, preparer_scene, rythme, zone_sure
from whiteboard.video import filtre_mixage

NARRATION = ("Votre cerveau efface soixante-dix pour cent de ce que vous lisez, en moins d'une journée. "
             "Sauf si vous faites une chose.")

REPONSE = json.dumps({
    "titre_video": "Pourquoi on oublie tout",
    "scenes": [
        {"modele": "accroche", "titre": "Votre cerveau efface tout", "texte": "en un jour", "image": "clipart:cerveau",
         "narration": NARRATION},
        {"modele": "liste", "titre": "Trois réflexes", "texte": "Relire\nRaconter\nDormir", "image": "",
         "narration": "Relire le soir, raconter à quelqu'un, dormir assez : trois réflexes simples."},
        {"modele": "fin", "titre": "Vous le saviez ?", "texte": "", "narration": "Dites-le en commentaire."},
    ],
    "publication": {
        "titres_youtube": ["On oublie 70 % en un jour", "Le secret pour retenir", "Trois réflexes mémoire"],
        "description": "Pourquoi la mémoire efface si vite, et comment l'éviter.",
        "hashtags": ["mémoire", "#apprendre", "cerveau !"],
        "texte_miniature": "70 % oubliés",
        "commentaire_epingle": "Vous relisez vos notes le soir ?",
        "variantes_accroche": ["Vous oubliez tout, et c'est normal", "Le cerveau triche"],
    },
}, ensure_ascii=False)


# ---------------------------------------------------------------- rythme
def test_rythme_short_supprime_les_temps_morts():
    normal, short = Projet(), regler_short(Projet())
    assert short.rythme == "short" and short.transition == "coupe" and short.sous_titres == "karaoke"
    assert (short.largeur, short.hauteur) == (1080, 1920)
    rn, rs = rythme(normal), rythme(short)
    assert rs.entree < rn.entree and rs.couleur < rn.couleur and rs.transition < rn.transition
    assert rs.main_reste and not rn.main_reste
    sc = Scene(modele="libre", titre="Un titre", image="clipart:ampoule", texte="Une légende", narration=NARRATION)
    spn, sps = preparer_scene(normal, sc), preparer_scene(short, sc)
    assert sps.pause < spn.pause and sps.entree < spn.entree
    # temps mort d'une scène : entrée + pause ; nettement plus court en Short
    assert sps.entree + sps.pause < 0.6 * (spn.entree + spn.pause)


def test_main_reste_entre_les_scenes():
    p = regler_short(Projet())
    p.largeur, p.hauteur, p.fps = 540, 960, 12
    scenes = [Scene(modele="titre", titre="Un", texte="deux"), Scene(modele="titre", titre="Trois", texte="quatre")]
    anim = Animateur(p)
    sp1, sp2 = (preparer_scene(p, s) for s in scenes)
    for _ in anim.images_scene(sp1, derniere=False):
        pass
    assert anim.main_pos != anim.hors_ecran        # la main reste à l'écran
    for _ in anim.images_scene(sp2, derniere=True):
        pass
    assert anim.main_pos == anim.hors_ecran        # … et sort à la fin de la vidéo
    assert len(anim.vitesses) == sum(minutage(p, [sp1, sp2])[0])
    assert any(v > 0 for v in anim.vitesses)       # journal des vitesses pour le bruit du feutre


# ---------------------------------------------------------------- sous-titres
def test_decoupage_sous_titres():
    groupes = ST.decouper(NARRATION, 0.25, 6.0, "karaoke")
    assert groupes and all(1 <= len(g.mots) <= 4 for g in groupes)
    assert groupes[0].debut == 0.25
    assert 5.8 < groupes[-1].fin <= 6.25          # la voix se tait un peu avant la fin de la scène
    # pas de trou : chaque groupe reste affiché jusqu'au suivant, les mots se suivent
    for a, b in zip(groupes, groupes[1:]):
        assert a.fin == b.debut
    mots = [m for g in groupes for m in g.mots]
    assert " ".join(m.texte for m in mots) == " ".join(NARRATION.split())
    assert all(m.debut < m.fin for m in mots)
    g, i = ST.groupe_courant(groupes, 0.3)
    assert g is groupes[0] and i == 0
    assert ST.groupe_courant(groupes, 99)[0] is None
    simple = ST.decouper(NARRATION, 0, 6.0, "simple")
    assert max(len(g.mots) for g in simple) > max(len(g.mots) for g in groupes)


def test_srt():
    texte = ST.srt([(0.0, ST.decouper("Bonjour à tous. Voici la suite.", 0.25, 2.0, "simple")),
                    (10.0, ST.decouper("Et la fin.", 0.0, 1.0, "simple"))])
    assert texte.startswith("1\n00:00:00,250 --> ")
    assert "\n3\n00:00:10,000 --> 00:00:10," in texte and texte.rstrip().endswith("Et la fin.")


def test_incrustation_sous_titres():
    p = regler_short(Projet())
    p.largeur, p.hauteur = 540, 960
    rendu = ST.RenduSousTitres(p)
    groupes = ST.decouper(NARRATION, 0.0, 5.0, "karaoke")
    img = np.full((960, 540, 3), 255, np.uint8)
    out = rendu.appliquer(img, groupes, 0.5)
    assert (out != 255).any()
    ys = np.nonzero((out != 255).any(axis=2).any(axis=1))[0]
    # dans la bande réservée : sous la zone de mise en page, au-dessus de l'interface de YouTube
    assert ys.min() > zone_sure(p)[1] and ys.max() < 960 * 0.82
    # le mot en cours est en couleur d'accent
    assert (np.abs(out.astype(int) - np.array(ST.ACCENT)).sum(axis=2) < 40).any()


# ---------------------------------------------------------------- bande-son
def test_bruitages(tmp_path):
    fps = 12
    vitesses = [0.0] * 6 + [8.0] * 24 + [0.0] * 12
    chemin = audio_sfx.generer(vitesses, [(30, "couleur"), (0, "tampon")], fps, tmp_path / "sfx.wav")
    with wave.open(chemin) as w:
        assert w.getframerate() == audio_sfx.FREQ and w.getnchannels() == 1
        data = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float) / 32767
    assert abs(len(data) - len(vitesses) * audio_sfx.FREQ / fps) < 2
    s = audio_sfx.FREQ
    actif = data[int(1.0 * s):int(2.0 * s)]
    assert np.abs(actif).mean() > 5 * max(1e-6, np.abs(data[int(0.2 * s):int(0.45 * s)]).mean())
    assert np.abs(data).max() <= 1.0
    sans = audio_sfx.generer([0.0] * 12, [], fps, tmp_path / "vide.wav", feutre=False)
    with wave.open(sans) as w:
        assert not np.frombuffer(w.readframes(w.getnframes()), "<i2").any()


def test_graphe_de_mixage():
    from whiteboard.video import PisteAudio
    voix = [PisteAudio("a.wav", 0.25), PisteAudio("b.wav", 4.0)]
    g = filtre_mixage(2, True, True, 30.0, 0.2, ducking=True, normaliser=True, voix=voix)
    assert "adelay=delays=250" in g and "adelay=delays=4000" in g
    assert "sidechaincompress" in g and "loudnorm=I=-14" in g and "amix=inputs=3" in g
    assert g.endswith("[a]")
    g2 = filtre_mixage(1, False, True, 30.0, 0.2, ducking=True, normaliser=True, voix=voix[:1])
    assert "sidechaincompress" not in g2 and "loudnorm" in g2
    # seuls les bruitages : pas de normalisation (le crissement doit rester discret)
    g3 = filtre_mixage(0, False, True, 30.0, 0.2, normaliser=True)
    assert "loudnorm" not in g3 and "[sfx]apad[mix]" in g3


# ---------------------------------------------------------------- zone sûre et accroche
def test_zone_sure_verticale():
    p = Projet(largeur=1080, hauteur=1920)
    w, h = zone_sure(p)
    assert w <= 1080 * 0.9 and h <= 1920 * 0.85
    p.sous_titres = "karaoke"
    assert zone_sure(p)[1] < h
    assert zone_sure(Projet()) == (1920, 1080)
    for code in MODELES:
        sp = preparer_scene(p, Scene(modele=code, titre="Titre", texte="a\nb\nc", image="clipart:ampoule"))
        for el in sp.elements:
            assert el.x + el.largeur <= w + 2 and el.y + el.hauteur <= h + 2, code


def test_modele_accroche():
    assert "accroche" in MODELES
    p = regler_short(Projet())
    p.largeur, p.hauteur, p.fps = 540, 960, 12
    sc = Scene(modele="accroche", titre="Personne ne vous dit ça", texte="et pourtant", image="clipart:ampoule")
    sp = preparer_scene(p, sc)
    instants = [el for el in sp.elements if el.instant]
    assert len(instants) == 1                         # le titre surgit d'un coup
    assert all(e[0] < 0 or not sp.elements[e[0]].instant for e in sp.etapes)   # la main ne le trace pas
    anim = Animateur(p)
    images = list(anim.images_scene(sp))
    el = instants[0]
    zone = images[2][el.y:el.y + el.hauteur, el.x:el.x + el.largeur]
    assert (zone != 255).any()                        # visible dès les premières images
    assert any(g == "tampon" for _, g in anim.evenements)
    # un trait de surligneur jaune est dessiné par la main
    assert any((np.abs(e.croquis.reshape(-1, 3).astype(int) - np.array([255, 212, 59])).sum(axis=1) < 30).any()
               for e in sp.elements if not e.instant)


# ---------------------------------------------------------------- publication et miniature
def test_import_publication_et_accroche():
    p, remarques = projet_depuis_ia(REPONSE, Projet(), short=True)
    assert [s.modele for s in p.scenes] == ["accroche", "liste", "fin"]
    pub = p.publication
    assert pub["titres_youtube"][0] == "On oublie 70 % en un jour"
    assert pub["hashtags"] == ["#mémoire", "#apprendre", "#cerveau"]
    assert pub["texte_miniature"] == "70 % oubliés" and len(pub["variantes_accroche"]) == 2
    # le projet se sauve et se recharge avec sa fiche
    d = p.vers_dict()
    q = Projet.depuis_dict(json.loads(json.dumps(d)))
    assert q.publication == pub and q.rythme == "short" and q.sous_titres == "karaoke"
    prompt = construire_prompt("x", 0.75, short=True)
    assert '"accroche"' in prompt and '"publication"' in prompt and "variantes_accroche" in prompt
    fiche = P.texte_publication(p, [0.0, 5.0, 12.0])
    assert "On oublie 70 % en un jour" in fiche and "#apprendre" in fiche and "Vous relisez" in fiche
    assert "0:00 Votre cerveau efface tout" in fiche


def test_miniature(tmp_path):
    p, _ = projet_depuis_ia(REPONSE, Projet(), short=True)
    scene = P.scene_miniature(p)
    assert scene.modele == "accroche"
    chemin = P.exporter_miniature(p, scene, tmp_path / "mini.png")
    img = Image.open(chemin)
    assert img.size == (1080, 1920)
    a = np.asarray(img)
    assert (np.abs(a.astype(int) - np.array(P.JAUNE)).sum(axis=2) < 30).sum() > 5000   # bandeaux jaunes
    horizontal = P.miniature(Projet(scenes=p.scenes), p.scenes[1], "Trois réflexes")
    assert horizontal.size == (1280, 720)


def test_export_short_complet(tmp_path):
    p, _ = projet_depuis_ia(REPONSE, Projet(), short=True)
    p.largeur, p.hauteur, p.fps = 270, 480, 12
    sortie = tmp_path / "short.mp4"
    exporter(p, str(sortie), fichiers_annexes=True)
    assert sortie.exists() and sortie.stat().st_size > 10_000
    assert not list(tmp_path.glob("*temp*"))                      # fichiers temporaires nettoyés
    srt = (tmp_path / "short.srt").read_text(encoding="utf-8")
    assert "-->" in srt and "Votre cerveau" in srt
    fiche = (tmp_path / "short_publication.txt").read_text(encoding="utf-8")
    assert "TITRE" in fiche and "COMMENTAIRE À ÉPINGLER" in fiche
    from whiteboard.video import chemin_ffmpeg
    import subprocess
    info = subprocess.run([chemin_ffmpeg(), "-hide_banner", "-i", str(sortie)], capture_output=True, text=True).stderr
    assert "Audio: aac" in info   # la piste de bruitages est mixée même sans voix off
