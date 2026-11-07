import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from whiteboard.projet import Projet, Scene, depuis_plan_texte
from whiteboard.rendu import exporter, image_finale, preparer_scene
from whiteboard.traits import masque_encre, ordre_cellules
from whiteboard.video import chemin_ffmpeg, duree_audio


def _dessin(chemin: Path) -> Path:
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 180, 180), outline="black", width=6)
    d.rectangle((220, 60, 360, 240), fill=(200, 60, 60), outline="black", width=6)
    img.save(chemin)
    return chemin


def test_masque_et_ordre_couvrent_tout(tmp_path):
    rgb = np.asarray(Image.open(_dessin(tmp_path / "d.png")))
    encre = masque_encre(rgb, 50)
    assert encre.any() and encre.mean() < 0.5
    ordre = ordre_cellules(encre, 8)
    assert len(ordre) == len(set(ordre))
    # chaque cellule contenant de l'encre est visitée
    h, w = encre.shape
    attendues = {(y // 8, x // 8) for y, x in zip(*np.nonzero(encre))}
    assert set(ordre) == attendues


def test_ordre_de_lecture_gauche_droite():
    encre = np.zeros((40, 200), dtype=bool)
    encre[10:30, 150:160] = True   # bloc de droite
    encre[10:30, 20:30] = True     # bloc de gauche
    ordre = ordre_cellules(encre, 5, depart=(300, 300), lecture=True)
    assert ordre[0][1] < 10  # on commence à gauche


def test_plan_texte():
    scenes = depuis_plan_texte("# Intro\nBonjour\n\n# Suite\nLigne 1\nLigne 2")
    assert [s.titre for s in scenes] == ["Intro", "Suite"]
    assert scenes[1].texte == "Ligne 1\nLigne 2"
    assert len(depuis_plan_texte("Un.\n\nDeux.")) == 2


def test_projet_chemins_relatifs(tmp_path):
    img = _dessin(tmp_path / "d.png")
    p = Projet(scenes=[Scene(titre="A", image=str(img))])
    p.enregistrer(tmp_path / "p.json")
    assert '"image": "d.png"' in (tmp_path / "p.json").read_text(encoding="utf-8")
    q = Projet.charger(tmp_path / "p.json")
    assert Path(q.scenes[0].image) == img.resolve()


def test_apercu_fixe(tmp_path):
    p = Projet(scenes=[Scene(titre="Titre", image=str(_dessin(tmp_path / "d.png")), texte="Légende")])
    img = image_finale(p, p.scenes[0], largeur=480)
    assert img.size == (480, 270)


def test_export_avec_voix(tmp_path):
    voix = tmp_path / "voix.wav"
    subprocess.run([chemin_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", str(voix)], check=True)
    p = Projet(largeur=320, hauteur=180, fps=12, scenes=[
        Scene(titre="Bonjour", duree_dessin=1.0, pause=1.0),
        Scene(image=str(_dessin(tmp_path / "d.png")), texte="Test", audio=str(voix)),
    ])
    sp = preparer_scene(p, p.scenes[1])
    assert sp.duree >= 3.0  # calée sur la voix off
    sortie = tmp_path / "out.mp4"
    etapes = []
    exporter(p, str(sortie), lambda f, m: etapes.append(f))
    assert sortie.stat().st_size > 1000
    assert etapes[-1] == 1.0
    assert abs(duree_audio(str(sortie)) - (2.35 + 0.6 + sp.duree)) < 0.3


# --- Images vectorielles et modèles -----------------------------------------
from whiteboard.modeles import MODELES, analyser_items, scene_exemple  # noqa: E402
from whiteboard.vecteur import charger_vecteur, chercher_icones, lire_svg, rendre_vecteur  # noqa: E402

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<defs><linearGradient id="g"><stop offset="0" stop-color="#ff0000"/><stop offset="1" stop-color="#0000ff"/></linearGradient></defs>
<g transform="translate(10 10)"><rect width="40" height="30" fill="#ffcc00" stroke="#000" stroke-width="3"/></g>
<circle cx="70" cy="70" r="20" fill="url(#g)"/>
<path d="M10 90 C30 70 50 110 90 90" stroke="currentColor" fill="none" stroke-width="2"/>
</svg>"""


def test_lecture_svg():
    chemins = lire_svg(SVG)
    assert len(chemins) == 3
    assert chemins[0].remplissage == (255, 204, 0) and chemins[0].trait_encre
    assert chemins[1].remplissage == (127, 0, 127)  # couleur médiane du dégradé
    assert chemins[2].remplissage is None and len(chemins[2].sous_chemins[0]) > 10


def test_rendu_svg_et_parcours(tmp_path):
    rendu = rendre_vecteur(lire_svg(SVG), 400, 300, 3, 8, (255, 255, 255), (30, 30, 30))
    assert rendu.largeur <= 400 and rendu.hauteur <= 300
    assert rendu.finale is not None  # dessin en couleur
    assert len(rendu.points) > 50
    assert (rendu.points[:, 0] >= 0).all() and (rendu.points[:, 0] < rendu.largeur).all()
    # chaque point du parcours est sur le trait
    xs, ys = rendu.points[:, 0].astype(int), rendu.points[:, 1].astype(int)
    assert (rendu.croquis_alpha[ys, xs] > 0.2).mean() > 0.9


def test_icones():
    assert chercher_icones("fusée")[0] == "rocket"
    assert chercher_icones("ampoule")[0] == "bulb"
    assert not any(n.startswith("brand-") for n in chercher_icones("", limite=10000))
    assert len(charger_vecteur("icone:bulb")) >= 1


def test_items():
    assert analyser_items("[rocket] Lancer\n- Simple\n[img/a.png] Image") == [
        ("icone:rocket", "Lancer"), (None, "Simple"), ("img/a.png", "Image")]


def test_tous_les_modeles(tmp_path):
    for W, H in ((640, 360), (360, 640)):
        p = Projet(largeur=W, hauteur=H)
        for code in MODELES:
            sp = preparer_scene(p, scene_exemple(code))
            assert sp.elements and sp.etapes, code
            for el in sp.elements:  # tout tient dans l'écran
                assert el.x >= 0 and el.y >= 0 and el.x + el.largeur <= W and el.y + el.hauteur <= H


def test_export_svg_et_icone(tmp_path):
    (tmp_path / "d.svg").write_text(SVG, encoding="utf-8")
    p = Projet(largeur=320, hauteur=180, fps=12, scenes=[
        Scene(titre="SVG", image=str(tmp_path / "d.svg"), duree_dessin=1.0, pause=1.0),
        Scene(modele="etapes", titre="Étapes", texte="[bulb] A\n[rocket] B", duree_dessin=1.0, pause=1.0),
    ])
    sortie = tmp_path / "v.mp4"
    exporter(p, str(sortie))
    assert sortie.stat().st_size > 1000
    p.enregistrer(tmp_path / "p.json")
    q = Projet.charger(tmp_path / "p.json")
    assert q.scenes[1].modele == "etapes" and q.scenes[0].image.endswith("d.svg")


# --- Assistant IA --------------------------------------------------------------
from whiteboard.ia import (associer_voix, construire_prompt, exporter_narrations,  # noqa: E402
                           projet_depuis_ia, resoudre_icone)

REPONSE_IA = """Voici le projet :
```json
{"scenes": [
  {"modèle": "Titre", "titre": "Pomodoro", "texte": "Sous-titre", "image": "icone:clock",
   "narration": "Une méthode simple pour rester concentré pendant le travail."},
  {"modele": "étapes", "titre": "Le cycle", "texte": "[target] Tâche\\n[kitchen-timer] 25 min\\n[icone-inexistante-xyz] Pause",
   "narration": "On choisit une tâche, on travaille vingt-cinq minutes, puis on fait une pause."},
  {"modele": "graphique-bizarre", "titre": "Autre", "image": "C:/nexiste/pas.png"},
]}
```
Bonne vidéo !"""


def test_prompt():
    p = construire_prompt("Mon texte source.", 2, "enfants")
    assert "Mon texte source." in p and "enfants" in p and "rocket" in p and "{" in p
    assert "{TEXTE}" not in p and "{ICONES}" not in p


def test_import_reponse_ia(tmp_path):
    base = Projet(largeur=1080, hauteur=1920, main="gauche")
    p, remarques = projet_depuis_ia(REPONSE_IA, base)
    assert (p.largeur, p.hauteur, p.main) == (1080, 1920, "gauche")  # réglages conservés
    assert [s.modele for s in p.scenes] == ["titre", "etapes", "libre"]
    assert p.scenes[0].image == "icone:clock"
    lignes = p.scenes[1].texte.split("\n")
    assert lignes[0] == "[target] Tâche" and lignes[1] == "[alarm] 25 min" and lignes[2] == "Pause"
    assert p.scenes[2].image == ""
    assert len(remarques) >= 3
    assert p.scenes[0].duree_dessin >= 2.5 and p.scenes[2].duree_dessin == 6.0
    # chaque scène importée se prépare sans erreur
    for s in p.scenes:
        preparer_scene(Projet(largeur=320, hauteur=180), s)


def test_resoudre_icone():
    assert resoudre_icone("light-bulb") == "bulb"
    assert resoudre_icone("ti-rocket") == "rocket"
    assert resoudre_icone("zzzz-qqqq") is None


def test_narrations_et_voix(tmp_path):
    p, _ = projet_depuis_ia(REPONSE_IA)
    assert exporter_narrations(p, tmp_path / "v") == 2
    assert (tmp_path / "v" / "02.txt").read_text(encoding="utf-8").startswith("On choisit")
    for nom in ("01.wav", "scene_03.mp3", "notes.txt"):
        (tmp_path / "v" / nom).write_bytes(b"")
    trouves = associer_voix(p, tmp_path / "v")
    assert sorted(trouves) == [(1, "01.wav"), (3, "scene_03.mp3")]
    assert p.scenes[0].audio.endswith("01.wav") and p.scenes[1].audio == ""


# --- Ollama et Qwen3-TTS (avec de faux serveurs) -----------------------------------
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

from whiteboard import tts  # noqa: E402
from whiteboard.config import Reglages  # noqa: E402
from whiteboard.ollama import ErreurOllama, generer, lister_modeles  # noqa: E402


def _faux_ollama(reponse: str, refuser_think: bool = False):
    requetes = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = json.dumps({"models": [{"name": "qwen3.8:27b"}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            corps = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requetes.append(corps)
            if refuser_think and "think" in corps:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "model does not support thinking"}).encode())
                return
            self.send_response(200)
            self.end_headers()
            for morceau in ["<think>hmm</think>"] + [reponse[i:i + 25] for i in range(0, len(reponse), 25)]:
                self.wfile.write((json.dumps({"message": {"content": morceau}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"done": True, "eval_count": 9, "eval_duration": 10 ** 9}) + "\n").encode())

    serveur = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur, f"http://127.0.0.1:{serveur.server_port}", requetes


def test_ollama():
    json_ia = REPONSE_IA.split("```json")[1].split("```")[0]
    serveur, url, requetes = _faux_ollama(json_ia, refuser_think=True)
    try:
        assert lister_modeles(url) == ["qwen3.8:27b"]
        r = Reglages(ollama_url=url, ollama_modele="qwen3.8:27b")
        texte = generer("Prompt", r)
        assert "<think>" not in texte
        p, _ = projet_depuis_ia(texte)
        assert len(p.scenes) == 3
        assert "think" in requetes[0] and "think" not in requetes[1]  # nouvel essai sans « think »
        assert requetes[1]["keep_alive"] == 0 and requetes[1]["format"] == "json"
        assert requetes[1]["messages"][0]["content"].endswith("/no_think")
    finally:
        serveur.shutdown()
    try:
        lister_modeles("http://127.0.0.1:9")
        assert False
    except ErreurOllama:
        pass


FAUX_QWEN = '''
import json, os
import numpy as np

def _noter(evt):
    with open(os.environ["FAUX_JOURNAL"], "a", encoding="utf-8") as f:
        f.write(json.dumps(evt) + "\\n")

class _M: tts_model_type = "base"
class Qwen3TTSModel:
    model = _M()
    @classmethod
    def from_pretrained(cls, nom, **kw):
        _noter({"chargement": nom})
        return cls()
    def create_voice_clone_prompt(self, **kw): return ["invite"]
    def generate_voice_clone(self, text, language=None, voice_clone_prompt=None, **kw):
        textes = text if isinstance(text, list) else [text]
        if len(textes) > int(os.environ.get("FAUX_MAX_LOT", "99")):
            import torch
            raise torch.cuda.OutOfMemoryError("CUDA out of memory (faux)")
        _noter({"lot": len(textes)})
        return [np.zeros(24000 * len(t.split()) // 3, dtype=np.float32) for t in textes], 24000
'''
FAUX_TORCH = '''
__version__ = "faux"
bfloat16 = float16 = float32 = "f"
class cuda:
    class OutOfMemoryError(RuntimeError):
        pass
    @staticmethod
    def is_available(): return False
    @staticmethod
    def empty_cache(): pass
'''
FAUX_SF = '''
import wave, numpy as np
def write(chemin, audio, sr):
    with wave.open(chemin, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.asarray(audio) * 32767).astype("<i2").tobytes())
'''


def _faux_qwen(tmp_path, monkeypatch):
    for nom, code in (("qwen_tts", FAUX_QWEN), ("torch", FAUX_TORCH), ("soundfile", FAUX_SF)):
        (tmp_path / "site" / nom).mkdir(parents=True, exist_ok=True)
        (tmp_path / "site" / nom / "__init__.py").write_text(code, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))
    journal = tmp_path / "journal.jsonl"
    monkeypatch.setenv("FAUX_JOURNAL", str(journal))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"")
    r = Reglages(tts_python=sys.executable, tts_voix_reference=str(ref), tts_texte_reference="Essai.")
    return r, journal


def _journal(journal):
    return [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines()] if journal.exists() else []


def test_tts_qwen(tmp_path, monkeypatch):
    r, journal = _faux_qwen(tmp_path, monkeypatch)
    assert "faux" in tts.diagnostiquer(r)
    p, _ = projet_depuis_ia(REPONSE_IA)
    phrases = [tts.Phrase(s.narration, str(tmp_path / "voix" / f"{i + 1:02d}.wav"), i)
               for i, s in enumerate(p.scenes) if s.narration]
    evenements = []
    faits = tts.generer(phrases, r, evenements.append, persistant=False)
    assert sorted(f["cle"] for f in faits) == [0, 1]
    assert evenements[-1]["etat"] == "termine"
    assert abs(duree_audio(str(tmp_path / "voix" / "02.wav")) - 13 / 3) < 0.1  # 13 mots / 3
    r.tts_voix_reference = ""
    try:
        tts.generer(phrases, r)
        assert False
    except tts.ErreurTTS:
        pass


def _phrases(tmp_path, n):
    return [tts.Phrase(" ".join(["mot"] * (3 + i)), str(tmp_path / "v" / f"{i:02d}.wav"), i) for i in range(n)]


def test_tts_par_lots_et_memoire(tmp_path, monkeypatch):
    r, journal = _faux_qwen(tmp_path, monkeypatch)
    r.tts_lot = 4
    faits = tts.generer(_phrases(tmp_path, 6), r, persistant=False)
    assert sorted(f["cle"] for f in faits) == list(range(6))
    assert [e["lot"] for e in _journal(journal) if "lot" in e] == [4, 2]
    # mémoire vidéo insuffisante : les lots se réduisent tout seuls
    journal.unlink()
    monkeypatch.setenv("FAUX_MAX_LOT", "2")
    infos = []
    faits = tts.generer(_phrases(tmp_path, 5), r, infos.append, persistant=False)
    assert len(faits) == 5
    assert [e["lot"] for e in _journal(journal) if "lot" in e] == [2, 2, 1]
    assert any("réduits" in i.get("message", "") for i in infos)


def test_tts_modele_garde_en_memoire(tmp_path, monkeypatch):
    r, journal = _faux_qwen(tmp_path, monkeypatch)
    r.tts_garder_minutes = 5
    try:
        tts.generer(_phrases(tmp_path, 2), r)
        assert tts.modele_charge()
        tts.generer(_phrases(tmp_path, 3), r)  # deuxième génération : pas de rechargement
        assert len([e for e in _journal(journal) if "chargement" in e]) == 1
    finally:
        tts.liberer()
    assert not tts.modele_charge()


def test_tts_empreinte(tmp_path):
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    r = Reglages(tts_voix_reference=str(ref), tts_texte_reference="Essai.")
    e = tts.empreinte("Bonjour.", r)
    assert e == tts.empreinte("  Bonjour. ", r)
    assert e != tts.empreinte("Bonsoir.", r)
    r.tts_langue = "English"
    assert e != tts.empreinte("Bonjour.", r)


# --- Cliparts en couleur -------------------------------------------------------------
from whiteboard.vecteur import catalogue_cliparts, chercher_cliparts, vignette_clipart  # noqa: E402


def test_cliparts():
    cat = catalogue_cliparts()
    assert len(cat) >= 1000
    assert chercher_cliparts("abeille")[0] == "abeille"
    assert chercher_cliparts("miel")[0] == "pot-de-miel"
    assert vignette_clipart("abeille", 56).size == (56, 56)
    rendu = rendre_vecteur(charger_vecteur("clipart:abeille"), 300, 300, 3, 8, (255, 255, 255), (30, 30, 30))
    assert rendu.finale is not None and len(rendu.points) > 50


def test_clipart_dans_projet_et_modeles(tmp_path):
    p = Projet(largeur=640, hauteur=360, scenes=[
        Scene(modele="titre", titre="T", image="clipart:abeille"),
        Scene(modele="etapes", titre="E", texte="[clipart:soleil] A\n[bulb] B"),
    ])
    p.enregistrer(tmp_path / "p.json")
    q = Projet.charger(tmp_path / "p.json")
    assert q.scenes[0].image == "clipart:abeille"   # pas transformé en chemin de fichier
    for s in q.scenes:
        sp = preparer_scene(q, s)
        assert sum(e.finale is not None for e in sp.elements) >= 1  # le clipart est bien là, en couleur


def test_ia_cliparts():
    p, remarques = projet_depuis_ia('{"scenes": [{"modele": "libre", "titre": "x", "image": "clipart:pot de miel",'
                                    ' "texte": "[clipart:abeille] a\\n[clipart:zzzz-inconnu] b"}]}')
    assert p.scenes[0].image == "clipart:pot-de-miel"
    assert p.scenes[0].texte.split("\n") == ["[clipart:abeille] a", "b"]
    assert "clipart:soleil" in construire_prompt("x")


# --- Personnages, compositions, modèles de données ----------------------------------------
from whiteboard.personnages import analyser  # noqa: E402


def test_personnages():
    a = analyser("personne:femme,surprise,lunettes,peau foncée,vert")
    assert a["face"] == "awe" and a["accessories"] == "glasses" and a["peau"] == "#694d3d" and a["vetement"] == "#78e185"
    # même apparence quand seule l'expression change, quel que soit l'ordre des mots
    b = analyser("personne:vert, peau foncée, lunettes, femme, triste")
    assert {k: v for k, v in a.items() if k != "face"} == {k: v for k, v in b.items() if k != "face"}
    rendu = rendre_vecteur(charger_vecteur("personne:homme,barbe,pensif"), 300, 300, 3, 8,
                           (255, 255, 255), (30, 30, 30))
    assert rendu.finale is not None and len(rendu.points) > 200
    assert rendu.largeur <= 300 and rendu.hauteur <= 300  # buste recadré dans sa vue


def test_compositions():
    base = charger_vecteur("clipart:maison")
    avec = charger_vecteur("clipart:maison+ok")
    assert len(avec) > len(base)
    assert len(charger_vecteur("clipart:ordinateur-portable+cadenas-ferme")) > len(charger_vecteur("clipart:ordinateur-portable"))
    assert len(charger_vecteur("clipart:maison+pastille-inconnue-zz")) == len(base)  # ignoré sans planter


def test_modeles_de_donnees():
    for W, H in ((640, 360), (360, 640)):
        p = Projet(largeur=W, hauteur=H)
        for sc in [scene_exemple(c) for c in ("graphique", "proportion", "chronologie", "personnage")] + [
                Scene(modele="liste", titre="L", texte="[personne:femme,content] A\n[clipart:maison+ok] B"),
                Scene(modele="graphique", titre="G", texte="pas de chiffres ici")]:
            sp = preparer_scene(p, sc)
            assert sp.elements and sp.etapes, sc.modele
            for el in sp.elements:
                assert el.x >= 0 and el.y >= 0 and el.x + el.largeur <= W and el.y + el.hauteur <= H
    # le graphique dessine une barre par valeur, colorée
    sp = preparer_scene(Projet(largeur=640, hauteur=360), scene_exemple("graphique"))
    assert sum(e.finale is not None for e in sp.elements) == 3


def test_ia_metteur_en_scene():
    rep = ('{"scenes": [{"modele": "dialogue", "image": "personne:femme,pensive", "texte": "[clipart:goutte-d-eau] Pourquoi ?"},'
           '{"modele": "frise", "titre": "Dates", "texte": "1957 : A\\n1969 : B"},'
           '{"modele": "histogramme", "titre": "G", "texte": "A : 1\\nB : 2"},'
           '{"modele": "comparaison", "titre": "C", "texte": "[clipart:telephone-portable+non] X\\n[clipart:livres+ok] Y"}]}')
    p, remarques = projet_depuis_ia(rep)
    assert [s.modele for s in p.scenes] == ["personnage", "chronologie", "graphique", "comparaison"]
    assert p.scenes[0].image == "personne:femme,pensive"
    assert p.scenes[3].texte.startswith("[clipart:telephone-portable+non]")
    prompt = construire_prompt("x")
    for mot in ("personne:", "graphique", "proportion", "chronologie", "+ok", "pensive"):
        assert mot in prompt


def test_references_non_fichiers_conservees(tmp_path):
    p = Projet(scenes=[Scene(image="personne:femme,pensive"), Scene(image="clipart:maison+ok"),
                       Scene(image="icone:bulb+question")])
    p.enregistrer(tmp_path / "p.json")
    q = Projet.charger(tmp_path / "p.json")
    assert [s.image for s in q.scenes] == ["personne:femme,pensive", "clipart:maison+ok", "icone:bulb+question"]


# --- Illustrations générées par une IA d'images ---------------------------------------------
import io  # noqa: E402
import zipfile  # noqa: E402

from whiteboard import illustrations as I  # noqa: E402


def _png(couleur="orange"):
    img = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(img).ellipse((40, 40, 160, 160), fill=couleur, outline="black", width=8)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def test_illustrations_prompts_et_zip(tmp_path):
    scenes = [Scene(modele="libre", titre=f"S{k}", image="clipart:abeille", illustration=f"Image {k}")
              for k in range(12)]
    scenes.insert(3, Scene(modele="etapes", titre="E"))
    p = Projet(scenes=scenes)
    indices = [i for i, s in enumerate(p.scenes) if I.illustrable(s)]
    assert 3 not in indices
    demandes = I.preparer(p, indices, {0: "Une ruche dans un pré"})
    textes = I.prompts(p, demandes, sujet="Les abeilles")
    assert len(textes) == 2 and "illus_01.png" in textes[0] and "illus_12.png" in textes[1]
    assert "aucun texte" in textes[0].lower() and "zip" in textes[0] and "Les abeilles" in textes[0]
    assert "Idée imposée : Une ruche dans un pré" in textes[0]
    assert "choisis toi-même" in textes[0]           # scènes sans idée imposée
    assert "{" not in textes[0]                       # aucun champ oublié
    # les clés survivent à l'enregistrement et à un déplacement de scène
    p.scenes.insert(0, p.scenes.pop(5))
    p.enregistrer(tmp_path / "p.json")
    p = Projet.charger(tmp_path / "p.json")
    zip_ = tmp_path / "lot.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        z.writestr("dossier/illus_01.png", _png())
        z.writestr("Illus-2.png", _png())                 # nom approché
        z.writestr("../../hors.png", _png())              # tentative de sortie du dossier
        z.writestr("abime.png", b"pas une image")
    res = I.charger(p, [zip_], tmp_path / "illus")
    cle_vers_scene = {s.illustration_cle: i for i, s in enumerate(p.scenes) if s.illustration_cle}
    rattachees = dict(res.associees)
    assert rattachees[cle_vers_scene["illus_01"]].endswith("illus_01.png")
    assert rattachees[cle_vers_scene["illus_02"]].endswith("illus_02.png")
    assert len(res.associees) == 3                        # « hors.png » rattachée par ordre, signalée
    assert not (tmp_path.parent / "hors.png").exists()
    assert any("abime.png" in r for r in res.remarques)
    assert all(Path(f).parent == tmp_path / "illus" for f in rattachees.values())
    # retour aux visuels d'origine
    i0 = cle_vers_scene["illus_01"]
    assert p.scenes[i0].image_secours == "clipart:abeille"
    assert I.revenir(p) == 3 and p.scenes[i0].image == "clipart:abeille"


def test_prompts_distincts():
    assert "## Illustrations sur mesure" not in construire_prompt("x") and "illus_" not in construire_prompt("x")
    p = Projet(scenes=[Scene(modele="titre", titre="Lascaux", narration="Une grotte."),
                       Scene(modele="libre", titre="Les peintures", texte="[clipart:cheval] Chevaux",
                             narration="Des chevaux sur la paroi.")])
    texte = I.prompts(p, I.preparer(p, [0, 1]))[0]
    assert "Sujet de la vidéo : Lascaux" in texte and "Voix off : Des chevaux sur la paroi." in texte
    assert "Texte écrit à l'écran : Chevaux" in texte and "[clipart" not in texte
    p, _ = projet_depuis_ia('{"scenes": [{"modele": "libre", "titre": "R", "image": "clipart:abeille",'
                            ' "illustration": "Une ruche dans un pré"}]}')
    assert p.scenes[0].illustration == "Une ruche dans un pré" and p.scenes[0].image == "clipart:abeille"


# --- Shorts ------------------------------------------------------------------------------
def test_short():
    normal = construire_prompt("x", 3)
    short = construire_prompt("x", 0.75, short=True)
    assert "## Format Short" not in normal and "## Format Short" in short
    assert "45 secondes" in short and "{" not in short.split("## Texte source")[0].split("## Cliparts")[0][-2000:]
    p, _ = projet_depuis_ia(REPONSE_IA, Projet(), short=True)
    assert (p.largeur, p.hauteur) == (1080, 1920)
    q, _ = projet_depuis_ia(REPONSE_IA, Projet())
    assert p.scenes[0].pause < q.scenes[0].pause
    assert p.scenes[0].duree_dessin + p.scenes[0].pause < q.scenes[0].duree_dessin + q.scenes[0].pause
    # chaque scène du Short tient dans l'écran vertical
    for s in p.scenes:
        sp = preparer_scene(Projet(largeur=540, hauteur=960), s)
        for el in sp.elements:
            assert el.x >= 0 and el.y >= 0 and el.x + el.largeur <= 540 and el.y + el.hauteur <= 960
