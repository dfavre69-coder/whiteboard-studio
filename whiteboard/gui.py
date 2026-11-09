"""Interface graphique (Tkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import ImageTk

from . import __version__
from .config import LANGUES_TTS, MODELES_TTS, Reglages
from .modeles import MODELES, scene_exemple
from .projet import Projet, Scene, depuis_plan_texte
from .vecteur import (PREFIXE_CLIPART, PREFIXE_ICONE, categories_cliparts, categories_icones, chercher_cliparts,
                      chercher_icones, vignette_clipart, vignette_icone)

TITRE_APP = "Whiteboard Studio"
TYPES_IMAGE = [("Images et dessins vectoriels", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg"),
               ("Dessins vectoriels (SVG)", "*.svg"), ("Tous les fichiers", "*.*")]
TYPES_AUDIO = [("Audio", "*.wav *.mp3 *.m4a *.ogg *.flac *.aac"), ("Tous les fichiers", "*.*")]
TYPES_PROJET = [("Projet Whiteboard", "*.json")]
MODES = {"Dessin puis couleurs": "couleur", "Dessin au trait seulement": "trait"}
TRANSITIONS = {"Glisser vers la gauche": "glisser", "Fondu": "fondu", "Coupe franche": "coupe"}
FORMATS = {"1920 × 1080 (YouTube, Full HD)": (1920, 1080), "1280 × 720 (HD)": (1280, 720),
           "3840 × 2160 (4K)": (3840, 2160), "1080 × 1920 (Shorts, vertical)": (1080, 1920),
           "1080 × 1080 (carré)": (1080, 1080)}


def ouvrir_fichier(chemin: str) -> None:
    if sys.platform == "win32":
        os.startfile(chemin)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


def _cle(dico: dict, valeur):
    for k, v in dico.items():
        if v == valeur:
            return k
    return next(iter(dico))


class Application(tk.Tk):
    def __init__(self, chemin_projet: str | None = None):
        super().__init__()
        self.title(TITRE_APP)
        self.geometry("1320x900")
        self.minsize(1100, 780)
        self.style = ttk.Style(self)
        if "vista" in self.style.theme_names():
            self.style.theme_use("vista")
        elif "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.style.configure("Titre.TLabel", font=("Segoe UI", 11, "bold"))
        self.style.configure("Grand.TButton", padding=(14, 6))

        self.projet = Projet(scenes=[Scene(titre="Ma première scène")])
        self.reglages = Reglages.charger()
        self.chemin: Path | None = None
        self.modifie = False
        self.index = 0
        self._chargement = False
        self._apercu_img = None
        self._apercu_job = None
        self._apercu_gen = 0
        self._file: queue.Queue = queue.Queue()
        self._arret: threading.Event | None = None

        self._construire()
        try:
            from PIL import Image
            icone = Path(__file__).parent / "assets" / "icone.png"
            self._icone = ImageTk.PhotoImage(Image.open(icone))
            self.iconphoto(True, self._icone)
        except Exception:  # noqa: BLE001
            pass
        self.protocol("WM_DELETE_WINDOW", self._quitter)
        self.bind_all("<Control-s>", lambda e: self.enregistrer())
        self.bind_all("<Control-o>", lambda e: self.ouvrir())
        self.bind_all("<Control-n>", lambda e: self.nouveau())
        if chemin_projet:
            self._charger(Path(chemin_projet))
        else:
            self._rafraichir_tout()
        self.after(100, self._lire_file)

    # ------------------------------------------------------------------ UI
    def _construire(self) -> None:
        barre = ttk.Frame(self, padding=(8, 6))
        barre.pack(fill="x")
        for texte, cmd in [("Nouveau", self.nouveau), ("Ouvrir…", self.ouvrir),
                           ("Enregistrer", self.enregistrer), ("Enregistrer sous…", self.enregistrer_sous),
                           ("Plan texte…", self.importer_plan),
                           ("Assistant IA…", self.assistant_ia),
                           ("Réglages IA et voix…", self.ouvrir_reglages),
                           ("Démo", self.demo)]:
            ttk.Button(barre, text=texte, command=cmd).pack(side="left", padx=2)
        self.bouton_export = ttk.Button(barre, text="Exporter la vidéo…", style="Grand.TButton",
                                        command=self.exporter)
        self.bouton_export.pack(side="right", padx=2)
        self.bouton_apercu = ttk.Button(barre, text="Aperçu animé", command=self.apercu_anime)
        self.bouton_apercu.pack(side="right", padx=6)

        corps = ttk.PanedWindow(self, orient="horizontal")
        corps.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # --- liste des scènes ------------------------------------------
        gauche = ttk.Frame(corps, padding=4)
        corps.add(gauche, weight=0)
        ttk.Label(gauche, text="Scènes", style="Titre.TLabel").pack(anchor="w")
        cadre_liste = ttk.Frame(gauche)
        cadre_liste.pack(fill="both", expand=True, pady=4)
        self.liste = tk.Listbox(cadre_liste, width=30, activestyle="none", exportselection=False,
                                font=("Segoe UI", 10))
        defil = ttk.Scrollbar(cadre_liste, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=defil.set)
        self.liste.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.liste.bind("<<ListboxSelect>>", self._choix_scene)
        boutons = ttk.Frame(gauche)
        boutons.pack(fill="x")
        self.menu_modeles = tk.Menu(self, tearoff=0)
        for code, info in MODELES.items():
            self.menu_modeles.add_command(label=f"{info.libelle} — {info.description}",
                                          command=lambda c=code: self.ajouter(c))
        self.menu_modeles.add_separator()
        self.menu_modeles.add_command(label="Scène vide", command=lambda: self.ajouter(None))
        for i, (texte, cmd) in enumerate([("+ Ajouter ▾", self._menu_ajouter), ("Dupliquer", self.dupliquer),
                                          ("Supprimer", self.supprimer), ("▲ Monter", lambda: self.deplacer(-1)),
                                          ("▼ Descendre", lambda: self.deplacer(1))]):
            ttk.Button(boutons, text=texte, command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        boutons.columnconfigure((0, 1), weight=1)
        ttk.Separator(gauche).pack(fill="x", pady=6)
        ttk.Label(gauche, text="Voix off du projet", style="Titre.TLabel").pack(anchor="w")
        self.bouton_tts = ttk.Button(gauche, text="Générer les voix off (Qwen3-TTS)", command=lambda: self.generer_voix())
        self.bouton_tts.pack(fill="x", pady=1)
        ttk.Button(gauche, text="Exporter les narrations (01.txt…)", command=self.exporter_narrations).pack(fill="x", pady=1)
        ttk.Button(gauche, text="Associer un dossier de voix off…", command=self.associer_voix).pack(fill="x", pady=1)
        ttk.Label(gauche, text="Illustrations", style="Titre.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Button(gauche, text="Prompt des illustrations (ChatGPT)…", command=self.illustrations_ia).pack(fill="x", pady=1)
        self.label_duree = ttk.Label(gauche, text="", foreground="#555")
        self.label_duree.pack(anchor="w", pady=(6, 0))

        # --- éditeur de scène ------------------------------------------
        milieu = ttk.Frame(corps, padding=(10, 4))
        corps.add(milieu, weight=1)
        ttk.Label(milieu, text="Scène sélectionnée", style="Titre.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        self.v_modele = tk.StringVar()
        self.v_titre = tk.StringVar()
        self.v_image = tk.StringVar()
        self.v_mode = tk.StringVar()
        self.v_dessin = tk.DoubleVar()
        self.v_pause = tk.DoubleVar()
        self.v_audio = tk.StringVar()
        self.v_caler = tk.BooleanVar()
        self.v_defil = tk.BooleanVar()
        self.v_sensibilite = tk.IntVar()

        r = 1
        ttk.Label(milieu, text="Modèle").grid(row=r, column=0, sticky="w", pady=3)
        cadre_mod = ttk.Frame(milieu)
        cadre_mod.grid(row=r, column=1, columnspan=3, sticky="ew")
        ttk.Combobox(cadre_mod, textvariable=self.v_modele, state="readonly", width=22,
                     values=[i.libelle for i in MODELES.values()]).pack(side="left")
        self.lbl_modele = ttk.Label(cadre_mod, text="", foreground="#555", wraplength=250, justify="left")
        self.lbl_modele.pack(side="left", padx=8)
        r += 1
        self.lbl_titre = ttk.Label(milieu, text="Titre", wraplength=95, justify="left")
        self.lbl_titre.grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(milieu, textvariable=self.v_titre).grid(row=r, column=1, columnspan=3, sticky="ew")
        r += 1
        ttk.Label(milieu, text="Visuel").grid(row=r, column=0, sticky="w", pady=3)
        cadre_vis = ttk.Frame(milieu)
        cadre_vis.grid(row=r, column=1, columnspan=3, sticky="ew")
        ttk.Button(cadre_vis, text="Retirer", command=lambda: self.v_image.set("")).pack(side="right", padx=(2, 0))
        ttk.Button(cadre_vis, text="Bibliothèque…", command=self._choisir_icone_visuel).pack(side="right", padx=2)
        ttk.Button(cadre_vis, text="Fichier…", command=self._choisir_image).pack(side="right", padx=2)
        ttk.Entry(cadre_vis, textvariable=self.v_image).pack(side="left", fill="x", expand=True)
        r += 1
        self.lbl_texte = ttk.Label(milieu, text="Texte", wraplength=95, justify="left")
        self.lbl_texte.grid(row=r, column=0, sticky="nw", pady=3)
        self.t_texte = tk.Text(milieu, height=4, wrap="word", font=("Segoe UI", 10), undo=True)
        self.t_texte.grid(row=r, column=1, columnspan=3, sticky="ew", pady=3)
        self.t_texte.bind("<<Modified>>", self._texte_modifie)
        r += 1
        cadre_aide = ttk.Frame(milieu)
        cadre_aide.grid(row=r, column=1, columnspan=3, sticky="ew")
        self.lbl_aide = ttk.Label(cadre_aide, text="", foreground="#555")
        self.lbl_aide.pack(side="left")
        ttk.Button(cadre_aide, text="Insérer un visuel…", command=self._inserer_icone).pack(side="right")
        r += 1
        ttk.Label(milieu, text="Narration", wraplength=95).grid(row=r, column=0, sticky="nw", pady=3)
        self.t_narration = tk.Text(milieu, height=2, wrap="word", font=("Segoe UI", 10), undo=True,
                                   foreground="#334")
        self.t_narration.grid(row=r, column=1, columnspan=3, sticky="ew", pady=3)
        self.t_narration.bind("<<Modified>>", self._narration_modifiee)
        r += 1
        ttk.Label(milieu, text="Rendu").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(milieu, textvariable=self.v_mode, values=list(MODES), state="readonly",
                     width=28).grid(row=r, column=1, sticky="w")
        r += 1
        ligne = ttk.Frame(milieu)
        ligne.grid(row=r, column=0, columnspan=4, sticky="w", pady=3)
        ttk.Label(ligne, text="Durée du dessin (s)").pack(side="left")
        self.spin_dessin = ttk.Spinbox(ligne, from_=0.5, to=120, increment=0.5, width=6, textvariable=self.v_dessin)
        self.spin_dessin.pack(side="left", padx=(6, 18))
        ttk.Label(ligne, text="Pause à la fin (s)").pack(side="left")
        ttk.Spinbox(ligne, from_=0.5, to=60, increment=0.5, width=6, textvariable=self.v_pause).pack(side="left", padx=6)
        r += 1
        ttk.Label(milieu, text="Voix off").grid(row=r, column=0, sticky="w", pady=3)
        cadre_voix = ttk.Frame(milieu)
        cadre_voix.grid(row=r, column=1, columnspan=3, sticky="ew")
        ttk.Button(cadre_voix, text="Retirer", command=lambda: self.v_audio.set("")).pack(side="right", padx=(2, 0))
        ttk.Button(cadre_voix, text="Fichier…", command=self._choisir_audio).pack(side="right", padx=2)
        ttk.Button(cadre_voix, text="▶", width=3, command=self._ecouter_voix).pack(side="right", padx=2)
        ttk.Button(cadre_voix, text="Générer", command=lambda: self.generer_voix([self.index])).pack(side="right", padx=2)
        ttk.Entry(cadre_voix, textvariable=self.v_audio).pack(side="left", fill="x", expand=True)
        r += 1
        ttk.Checkbutton(milieu, text="Caler la durée de la scène sur la voix off",
                        variable=self.v_caler).grid(row=r, column=1, columnspan=3, sticky="w")
        r += 1
        ttk.Checkbutton(milieu, text="Texte défilant : le champ Texte s'affiche en grand et défile pendant la lecture",
                        variable=self.v_defil).grid(row=r, column=1, columnspan=3, sticky="w")
        r += 1
        ttk.Label(milieu, text="Détails extraits").grid(row=r, column=0, sticky="w", pady=3)
        cadre_s = ttk.Frame(milieu)
        cadre_s.grid(row=r, column=1, columnspan=3, sticky="ew")
        ttk.Label(cadre_s, text="peu").pack(side="left", padx=(4, 0))
        ttk.Scale(cadre_s, from_=0, to=100, variable=self.v_sensibilite,
                  command=lambda v: self.v_sensibilite.set(int(float(v)))).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(cadre_s, text="beaucoup").pack(side="left")
        r += 1
        ttk.Label(milieu, text="Aperçu de la scène terminée", style="Titre.TLabel").grid(
            row=r, column=0, columnspan=4, sticky="w", pady=(10, 2))
        r += 1
        self.canvas = tk.Canvas(milieu, background="#d9d9d9", highlightthickness=0)
        self.canvas.grid(row=r, column=0, columnspan=4, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self._planifier_apercu(50))
        milieu.columnconfigure(1, weight=1)
        milieu.rowconfigure(r, weight=1)

        for v in (self.v_modele, self.v_titre, self.v_image, self.v_mode, self.v_dessin, self.v_pause,
                  self.v_audio, self.v_caler, self.v_defil, self.v_sensibilite):
            v.trace_add("write", lambda *a: self._formulaire_modifie())

        # --- réglages du projet ----------------------------------------
        droite = ttk.Frame(corps, padding=(10, 4))
        corps.add(droite, weight=0)
        ttk.Label(droite, text="Réglages de la vidéo", style="Titre.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self.v_format = tk.StringVar()
        self.v_fps = tk.StringVar()
        self.v_main = tk.StringVar()
        self.v_transition = tk.StringVar()
        self.v_musique = tk.StringVar()
        self.v_volume = tk.IntVar()
        self.v_police = tk.StringVar()

        r = 1
        ttk.Label(droite, text="Format").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(droite, textvariable=self.v_format, values=list(FORMATS), state="readonly",
                     width=30).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1
        ttk.Label(droite, text="Images/s").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(droite, textvariable=self.v_fps, values=["24", "25", "30", "50", "60"], state="readonly",
                     width=6).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(droite, text="Main").grid(row=r, column=0, sticky="w", pady=3)
        self.combo_main = ttk.Combobox(droite, textvariable=self.v_main, state="readonly",
                                       values=["Main droite", "Main gauche", "Image personnalisée…"], width=22)
        self.combo_main.grid(row=r, column=1, columnspan=2, sticky="ew")
        self.combo_main.bind("<<ComboboxSelected>>", self._choix_main)
        r += 1
        ttk.Label(droite, text="Transition").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(droite, textvariable=self.v_transition, values=list(TRANSITIONS), state="readonly",
                     width=22).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1
        ttk.Label(droite, text="Couleurs").grid(row=r, column=0, sticky="w", pady=3)
        cadre_c = ttk.Frame(droite)
        cadre_c.grid(row=r, column=1, columnspan=2, sticky="w")
        self.b_fond = tk.Button(cadre_c, text="Fond", width=8, relief="groove", command=lambda: self._couleur("fond"))
        self.b_fond.pack(side="left", padx=(0, 4))
        self.b_encre = tk.Button(cadre_c, text="Encre", width=8, relief="groove", command=lambda: self._couleur("encre"))
        self.b_encre.pack(side="left")
        r += 1
        ttk.Label(droite, text="Police").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(droite, textvariable=self.v_police, state="readonly").grid(row=r, column=1, sticky="ew")
        cadre_p = ttk.Frame(droite)
        cadre_p.grid(row=r + 1, column=1, columnspan=2, sticky="w")
        ttk.Button(cadre_p, text="Choisir…", command=self._choisir_police).pack(side="left")
        ttk.Button(cadre_p, text="Par défaut", command=lambda: self._regler("police", "")).pack(side="left", padx=4)
        r += 2
        ttk.Separator(droite).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(droite, text="Musique de fond").grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Entry(droite, textvariable=self.v_musique, state="readonly").grid(row=r, column=0, columnspan=3, sticky="ew")
        r += 1
        cadre_m = ttk.Frame(droite)
        cadre_m.grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Button(cadre_m, text="Choisir…", command=self._choisir_musique).pack(side="left")
        ttk.Button(cadre_m, text="Retirer", command=lambda: self._regler("musique", "")).pack(side="left", padx=4)
        r += 1
        ttk.Label(droite, text="Volume").grid(row=r, column=0, sticky="w")
        ttk.Scale(droite, from_=0, to=60, variable=self.v_volume,
                  command=lambda v: self.v_volume.set(int(float(v)))).grid(row=r, column=1, columnspan=2, sticky="ew")
        r += 1
        ttk.Separator(droite).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        r += 1
        aide = ("Astuces\n"
                "• « + Ajouter ▾ » propose des scènes toutes prêtes (liste, étapes, chiffre clé…).\n"
                "• « Icône… » ouvre 4 800 icônes libres ; les fichiers SVG sont dessinés trait par trait.\n"
                "• Les dessins au trait sur fond blanc (PNG) donnent le plus bel effet.\n"
                "• Ajoutez une voix off par scène : la durée du dessin s'y cale.\n"
                "• « Assistant IA… » : une IA transforme votre texte en scènes et en narrations.\n"
                "• Un plan texte « # Titre » puis le texte crée toutes les scènes d'un coup.\n"
                "• Ctrl+S : enregistrer.")
        ttk.Label(droite, text=aide, foreground="#555", wraplength=300, justify="left").grid(
            row=r, column=0, columnspan=3, sticky="w")
        droite.columnconfigure(1, weight=1)

        for v in (self.v_format, self.v_fps, self.v_transition):
            v.trace_add("write", lambda *a: self._reglages_modifies())
        self.v_volume.trace_add("write", lambda *a: self._reglages_modifies(apercu=False))

        # --- barre d'état ------------------------------------------------
        etat = ttk.Frame(self, padding=(8, 4))
        etat.pack(fill="x", side="bottom")
        self.label_etat = ttk.Label(etat, text="Prêt.")
        self.label_etat.pack(side="left")
        self.bouton_annuler = ttk.Button(etat, text="Annuler", command=self._annuler, state="disabled")
        self.bouton_annuler.pack(side="right")
        self.barre = ttk.Progressbar(etat, length=320, maximum=1.0)
        self.barre.pack(side="right", padx=8)
        ttk.Label(etat, text=f"v{__version__}", foreground="#888").pack(side="right", padx=8)

    # ------------------------------------------------------------ données
    @property
    def scene(self) -> Scene:
        return self.projet.scenes[self.index]

    def _rafraichir_tout(self) -> None:
        self._chargement = True
        p = self.projet
        self.v_format.set(_cle(FORMATS, (p.largeur, p.hauteur)) if (p.largeur, p.hauteur) in FORMATS.values()
                          else f"{p.largeur} × {p.hauteur}")
        self.v_fps.set(str(p.fps))
        self.v_main.set({"droite": "Main droite", "gauche": "Main gauche"}.get(p.main, "Image personnalisée…"))
        self.v_transition.set(_cle(TRANSITIONS, p.transition))
        self.v_musique.set(Path(p.musique).name if p.musique else "")
        self.v_volume.set(int(round(p.volume_musique * 100)))
        self.v_police.set(Path(p.police).name if p.police else "Manuscrite (fournie)")
        self.b_fond.configure(background=p.fond)
        self.b_encre.configure(background=p.encre, foreground="white")
        self._chargement = False
        self._rafraichir_liste()
        self._charger_scene()
        self._maj_titre()

    def _rafraichir_liste(self) -> None:
        self.liste.delete(0, "end")
        for i, s in enumerate(self.projet.scenes, start=1):
            nom = s.titre or (s.texte.split("\n")[0][:30] if s.texte else "") or \
                  (Path(s.image).name if s.image else "(vide)")
            marque = " ♪" if s.audio else ""
            genre = "" if s.modele == "libre" else f"  [{MODELES.get(s.modele, MODELES['libre']).libelle}]"
            if s.defilement:
                genre = "  [Texte défilant]"
            self.liste.insert("end", f"{i:>2}. {nom}{marque}{genre}")
        self.index = min(self.index, len(self.projet.scenes) - 1)
        self.liste.selection_clear(0, "end")
        self.liste.selection_set(self.index)
        self.liste.see(self.index)
        total = sum(s.duree_dessin + s.pause + 0.35 for s in self.projet.scenes)
        self.label_duree.configure(text=f"{len(self.projet.scenes)} scène(s) · ≈ {int(total // 60)} min {int(total % 60):02d} s"
                                        "\n(hors calage sur les voix off)")

    def _charger_scene(self) -> None:
        self._chargement = True
        s = self.scene
        self.v_modele.set(MODELES.get(s.modele, MODELES["libre"]).libelle)
        self._maj_aides()
        self.v_titre.set(s.titre)
        self.v_image.set(s.image)
        self.t_texte.delete("1.0", "end")
        self.t_texte.insert("1.0", s.texte)
        self.t_narration.delete("1.0", "end")
        self.t_narration.insert("1.0", s.narration)
        self.t_narration.edit_modified(False)
        self.t_texte.edit_modified(False)
        self.v_mode.set(_cle(MODES, s.mode))
        self.v_dessin.set(s.duree_dessin)
        self.v_pause.set(s.pause)
        self.v_audio.set(s.audio)
        self.v_caler.set(s.caler_sur_audio)
        self.v_defil.set(s.defilement)
        self.v_sensibilite.set(s.sensibilite)
        self._chargement = False
        self._maj_etat_duree()
        self._planifier_apercu(10)

    def _formulaire_modifie(self) -> None:
        if self._chargement:
            return
        s = self.scene
        for code, info in MODELES.items():
            if info.libelle == self.v_modele.get() and code != s.modele:
                s.modele = code
                self._maj_aides()
        s.titre = self.v_titre.get()
        s.image = self.v_image.get().strip().strip('"')
        s.mode = MODES.get(self.v_mode.get(), "couleur")
        for attr, var in (("duree_dessin", self.v_dessin), ("pause", self.v_pause)):
            try:
                setattr(s, attr, max(0.5, float(var.get())))
            except (tk.TclError, ValueError):
                pass
        s.audio = self.v_audio.get().strip().strip('"')
        s.caler_sur_audio = bool(self.v_caler.get())
        s.defilement = bool(self.v_defil.get())
        s.sensibilite = int(self.v_sensibilite.get())
        self._marquer_modifie()
        self._maj_etat_duree()
        sel = self.index
        self._rafraichir_liste()
        self.index = sel
        self._planifier_apercu()

    def _narration_modifiee(self, _event=None) -> None:
        if not self.t_narration.edit_modified():
            return
        self.t_narration.edit_modified(False)
        if self._chargement:
            return
        self.scene.narration = self.t_narration.get("1.0", "end-1c")
        self._marquer_modifie()

    def _texte_modifie(self, _event=None) -> None:
        if not self.t_texte.edit_modified():
            return
        self.t_texte.edit_modified(False)
        if self._chargement:
            return
        self.scene.texte = self.t_texte.get("1.0", "end-1c")
        self._formulaire_modifie()

    def _maj_aides(self) -> None:
        info = MODELES.get(self.scene.modele, MODELES["libre"])
        self.lbl_modele.configure(text=info.description)
        self.lbl_titre.configure(text=info.aide_titre)
        self.lbl_texte.configure(text="Texte")
        self.lbl_aide.configure(text=info.aide_texte)

    def _maj_etat_duree(self) -> None:
        cale = bool(self.scene.audio) and self.scene.caler_sur_audio
        self.spin_dessin.configure(state="disabled" if cale else "normal")

    def _reglages_modifies(self, apercu: bool = True) -> None:
        if self._chargement:
            return
        p = self.projet
        if self.v_format.get() in FORMATS:
            p.largeur, p.hauteur = FORMATS[self.v_format.get()]
        try:
            p.fps = int(self.v_fps.get())
        except ValueError:
            pass
        p.transition = TRANSITIONS.get(self.v_transition.get(), "glisser")
        try:
            p.volume_musique = int(self.v_volume.get()) / 100
        except tk.TclError:
            pass
        self._marquer_modifie()
        if apercu:
            self._planifier_apercu()

    def _regler(self, attr: str, valeur) -> None:
        setattr(self.projet, attr, valeur)
        self._marquer_modifie()
        self._rafraichir_tout()

    def _marquer_modifie(self) -> None:
        if not self.modifie:
            self.modifie = True
            self._maj_titre()

    def _maj_titre(self) -> None:
        nom = self.chemin.name if self.chemin else "Sans titre"
        self.title(f"{'● ' if self.modifie else ''}{nom} — {TITRE_APP}")

    # ----------------------------------------------------------- scènes
    def _choix_scene(self, _event=None) -> None:
        sel = self.liste.curselection()
        if sel and sel[0] != self.index:
            self.index = sel[0]
            self._charger_scene()

    def _menu_ajouter(self) -> None:
        x, y = self.winfo_pointerxy()
        try:
            self.menu_modeles.tk_popup(x, y)
        finally:
            self.menu_modeles.grab_release()

    def ajouter(self, modele: str | None = None) -> None:
        self.projet.scenes.insert(self.index + 1, scene_exemple(modele) if modele else Scene())
        self.index += 1
        self._marquer_modifie()
        self._rafraichir_liste()
        self._charger_scene()

    def dupliquer(self) -> None:
        self.projet.scenes.insert(self.index + 1, deepcopy(self.scene))
        self.index += 1
        self._marquer_modifie()
        self._rafraichir_liste()
        self._charger_scene()

    def supprimer(self) -> None:
        if len(self.projet.scenes) == 1:
            self.projet.scenes[0] = Scene()
        else:
            del self.projet.scenes[self.index]
            self.index = max(0, self.index - 1)
        self._marquer_modifie()
        self._rafraichir_liste()
        self._charger_scene()

    def deplacer(self, sens: int) -> None:
        j = self.index + sens
        if 0 <= j < len(self.projet.scenes):
            sc = self.projet.scenes
            sc[self.index], sc[j] = sc[j], sc[self.index]
            self.index = j
            self._marquer_modifie()
            self._rafraichir_liste()

    # ----------------------------------------------------------- fichiers
    def _choisir_image(self) -> None:
        f = filedialog.askopenfilename(title="Choisir une image", filetypes=TYPES_IMAGE)
        if f:
            self.v_image.set(f)

    def _choisir_icone_visuel(self) -> None:
        SelecteurIcones(self, self.v_image.set)

    def _inserer_icone(self) -> None:
        def inserer(source):
            nom = source[len(PREFIXE_ICONE):] if source.startswith(PREFIXE_ICONE) else source
            debut = self.t_texte.index("insert linestart")
            ligne = self.t_texte.get(debut, f"{debut} lineend")
            import re
            m = re.match(r"^\s*\[[^\]]*\]\s*", ligne)
            if m:  # remplace l'icône existante de la ligne
                self.t_texte.delete(debut, f"{debut}+{len(m.group(0))}c")
            self.t_texte.insert(debut, f"[{nom}] ")
            self.t_texte.focus_set()
        SelecteurIcones(self, inserer)

    def _choisir_audio(self) -> None:
        f = filedialog.askopenfilename(title="Choisir la voix off", filetypes=TYPES_AUDIO)
        if f:
            self.v_audio.set(f)

    def _choisir_musique(self) -> None:
        f = filedialog.askopenfilename(title="Choisir la musique de fond", filetypes=TYPES_AUDIO)
        if f:
            self._regler("musique", f)

    def _choisir_police(self) -> None:
        f = filedialog.askopenfilename(title="Choisir une police", filetypes=[("Polices", "*.ttf *.otf")])
        if f:
            self._regler("police", f)

    def _choix_main(self, _event=None) -> None:
        choix = self.v_main.get()
        if choix == "Main droite":
            self._regler("main", "droite")
        elif choix == "Main gauche":
            self._regler("main", "gauche")
        else:
            f = filedialog.askopenfilename(
                title="PNG transparent d'une main (pointe du stylo en bas à gauche)",
                filetypes=[("PNG transparent", "*.png")])
            if f:
                self.projet.pointe_main = None
                self._regler("main", f)
            else:
                self._rafraichir_tout()

    def _couleur(self, attr: str) -> None:
        actuelle = getattr(self.projet, attr)
        res = colorchooser.askcolor(color=actuelle, title="Choisir une couleur")
        if res and res[1]:
            self._regler(attr, res[1])
            self._planifier_apercu()

    def _confirmer_abandon(self) -> bool:
        if not self.modifie:
            return True
        rep = messagebox.askyesnocancel(TITRE_APP, "Enregistrer les modifications du projet ?")
        if rep is None:
            return False
        if rep:
            return self.enregistrer()
        return True

    def nouveau(self) -> None:
        if self._confirmer_abandon():
            self.projet, self.chemin, self.modifie, self.index = Projet(scenes=[Scene()]), None, False, 0
            self._rafraichir_tout()

    def ouvrir(self) -> None:
        if not self._confirmer_abandon():
            return
        f = filedialog.askopenfilename(title="Ouvrir un projet", filetypes=TYPES_PROJET)
        if f:
            self._charger(Path(f))

    def _charger(self, chemin: Path) -> None:
        try:
            self.projet = Projet.charger(chemin)
            if not self.projet.scenes:
                self.projet.scenes.append(Scene())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(TITRE_APP, f"Impossible d'ouvrir le projet :\n{e}")
            return
        self.chemin, self.modifie, self.index = chemin, False, 0
        self._rafraichir_tout()

    def enregistrer(self) -> bool:
        if self.chemin is None:
            return self.enregistrer_sous()
        try:
            self.projet.enregistrer(self.chemin)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(TITRE_APP, f"Échec de l'enregistrement :\n{e}")
            return False
        self.modifie = False
        self._maj_titre()
        self.label_etat.configure(text=f"Projet enregistré : {self.chemin}")
        return True

    def enregistrer_sous(self) -> bool:
        f = filedialog.asksaveasfilename(title="Enregistrer le projet", defaultextension=".json",
                                         filetypes=TYPES_PROJET)
        if not f:
            return False
        self.chemin = Path(f)
        return self.enregistrer()

    def importer_plan(self) -> None:
        f = filedialog.askopenfilename(title="Plan texte (# Titre puis texte)",
                                       filetypes=[("Texte", "*.txt *.md"), ("Tous les fichiers", "*.*")])
        if not f:
            return
        scenes = depuis_plan_texte(Path(f).read_text(encoding="utf-8", errors="replace"))
        if not scenes:
            messagebox.showinfo(TITRE_APP, "Aucune scène trouvée dans ce fichier.")
            return
        vide = len(self.projet.scenes) == 1 and not (self.scene.titre or self.scene.texte or self.scene.image)
        if vide:
            self.projet.scenes = scenes
        else:
            self.projet.scenes.extend(scenes)
        self._marquer_modifie()
        self._rafraichir_tout()
        self.label_etat.configure(text=f"{len(scenes)} scène(s) importée(s). Ajoutez-y images et voix off.")

    # ----------------------------------------------------------- IA et voix off
    def assistant_ia(self) -> None:
        AssistantIA(self)

    def appliquer_ia(self, reponse: str, remplacer: bool, short: bool = False) -> bool:
        from .ia import ReponseIllisible, projet_depuis_ia
        try:
            nouveau, remarques = projet_depuis_ia(reponse, self.projet, short=short)
        except ReponseIllisible as e:
            messagebox.showerror(TITRE_APP, f"Impossible de lire la réponse de l'IA :\n\n{e}\n\n"
                                 "Vérifiez que vous avez copié toute la réponse (elle doit contenir le JSON).")
            return False
        vide = len(self.projet.scenes) == 1 and not (self.scene.titre or self.scene.texte or self.scene.image)
        if short:  # format vertical pour tout le projet
            self.projet.largeur, self.projet.hauteur = nouveau.largeur, nouveau.hauteur
            self.projet.transition = nouveau.transition
        if remplacer or vide:
            self.projet.scenes = nouveau.scenes
            self.index = 0
        else:
            self.index = len(self.projet.scenes)
            self.projet.scenes.extend(nouveau.scenes)
        self._marquer_modifie()
        self._rafraichir_tout()
        from .ia import duree_totale
        duree = duree_totale(self.projet)
        msg = (f"{len(nouveau.scenes)} scène(s) créée(s){' au format Short (1080 × 1920)' if short else ''}. "
               f"Durée estimée : {int(duree // 60)} min {int(duree % 60):02d} s.")
        if short and duree > 60:
            msg += ("\n\nAttention : c'est plus d'une minute. YouTube accepte les Shorts jusqu'à 3 minutes, "
                    "mais moins d'une minute reste le plus efficace : raccourcissez quelques narrations "
                    "ou supprimez une scène.")
        if remarques:
            msg += "\n\nCorrections automatiques :\n• " + "\n• ".join(remarques[:15])
            if len(remarques) > 15:
                msg += f"\n… et {len(remarques) - 15} autre(s)."
        msg += ("\n\nÉtape suivante : « Générer les voix off (Qwen3-TTS) », ou « Exporter les "
                "narrations » pour un autre outil de synthèse vocale.")
        msg += ("\n\nFacultatif : « Prompt des illustrations » prépare un second prompt, pour faire dessiner "
                "par ChatGPT des images sur mesure.")
        messagebox.showinfo(TITRE_APP, msg)
        return True

    def illustrations_ia(self) -> None:
        from .illustrations import illustrable
        if not any(illustrable(s) for s in self.projet.scenes):
            messagebox.showinfo(TITRE_APP, "Aucune scène ne peut recevoir d'illustration : il faut des scènes "
                                "de modèle « Image et texte », « Titre de chapitre », « Liste » ou « Chiffre clé ».")
            return
        FenetreIllustrations(self)

    def preparer_illustrations(self, indices: list[int] | None = None, descriptions: dict | None = None,
                               style: str | None = None, sujet: str = "") -> list[str]:
        """Prompt des illustrations (par lots). Sans `indices` : scènes proposées par défaut."""
        from . import illustrations as I
        if indices is None:
            indices = [i for i, s in enumerate(self.projet.scenes) if I.illustrable(s) and I.coche_par_defaut(s)]
        if not indices:
            return []
        if style is not None:
            style = style.strip()
            if style != (self.reglages.style_illustrations or I.STYLE_PAR_DEFAUT):
                self.reglages.style_illustrations = "" if style == I.STYLE_PAR_DEFAUT else style
                self.reglages.enregistrer()
        demandes = I.preparer(self.projet, indices, descriptions or {})
        self._marquer_modifie()
        if self.chemin is not None:
            self.enregistrer()  # les noms de fichiers attendus doivent être conservés
        return I.prompts(self.projet, demandes, style or self.reglages.style_illustrations, sujet)

    def charger_illustrations(self, parent) -> str | None:
        """Demande les zip (ou images) et les rattache aux scènes ; renvoie le compte rendu."""
        from . import illustrations as I
        if self.chemin is None:
            messagebox.showinfo(TITRE_APP, "Enregistrez d'abord le projet : les images seront rangées à côté.",
                                parent=parent)
            if not self.enregistrer_sous():
                return None
        if not any(s.illustration_cle for s in self.projet.scenes):
            messagebox.showinfo(TITRE_APP, "Préparez d'abord le prompt des illustrations : il indique à l'IA "
                                "le nom de chaque image.", parent=parent)
            return None
        fichiers = filedialog.askopenfilenames(parent=parent, title="Zip ou images renvoyés par l'IA",
                                               filetypes=[("Zip ou images", "*.zip *.png *.jpg *.jpeg *.webp")])
        if not fichiers:
            return None
        dossier = self.chemin.parent / f"{self.chemin.stem}_illustrations"
        try:
            res = I.charger(self.projet, list(fichiers), dossier)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(TITRE_APP, f"Impossible de lire ces fichiers :\n\n{e}", parent=parent)
            return None
        if res.associees:
            self._marquer_modifie()
            self.enregistrer()
            self._rafraichir_tout()
        texte = (f"{len(res.associees)} illustration(s) rattachée(s) : scène(s) "
                 + ", ".join(str(i + 1) for i, _ in sorted(res.associees))) if res.associees else \
            "Aucune image rattachée."
        if res.remarques:
            texte += "\n• " + "\n• ".join(res.remarques)
        return texte

    def ouvrir_reglages(self, onglet: int = 0) -> None:
        FenetreReglages(self, onglet)

    def _ecouter_voix(self) -> None:
        if self.scene.audio and Path(self.scene.audio).exists():
            ouvrir_fichier(self.scene.audio)
        else:
            messagebox.showinfo(TITRE_APP, "Cette scène n'a pas encore de voix off.")

    def _occupe(self, oui: bool) -> None:
        etat = "disabled" if oui else "normal"
        for b in (self.bouton_export, self.bouton_apercu, self.bouton_tts):
            b.configure(state=etat)
        self.bouton_annuler.configure(state="normal" if oui else "disabled")
        if not oui:
            self._arret = None

    def generer_voix(self, indices: list[int] | None = None) -> None:
        """Synthèse des narrations avec Qwen3-TTS, puis rattachement aux scènes.

        Sans `indices` : seules les voix manquantes ou dont la narration (ou la voix) a changé
        sont générées. Avec `indices` (bouton « Générer » d'une scène) : toujours regénérée.
        """
        from . import tts
        if self._arret is not None:
            return
        try:
            tts.verifier_reglages(self.reglages)
        except tts.ErreurTTS as e:
            if messagebox.askyesno(TITRE_APP, f"{e}\n\nOuvrir les réglages maintenant ?"):
                self.ouvrir_reglages(1)
            return
        tout = indices is None
        indices = list(range(len(self.projet.scenes))) if tout else indices
        avec_texte = [i for i in indices if self.projet.scenes[i].narration.strip()]
        if not avec_texte:
            messagebox.showinfo(TITRE_APP, "Aucune narration à lire. Remplissez le champ « Narration » "
                                "(ou utilisez l'Assistant IA).")
            return
        empreintes = {i: tts.empreinte(self.projet.scenes[i].narration, self.reglages) for i in avec_texte}
        if tout:
            def a_jour(i):
                sc = self.projet.scenes[i]
                return bool(sc.audio) and Path(sc.audio).exists() and sc.audio_empreinte == empreintes[i]
            a_faire = [i for i in avec_texte if not a_jour(i)]
            if not a_faire:
                if not messagebox.askyesno(TITRE_APP, "Toutes les voix off sont à jour (aucune narration ni "
                                           "réglage de voix n'a changé).\n\nLes regénérer quand même ?"):
                    return
                a_faire = avec_texte
            avec_texte = a_faire
        if self.chemin is None:
            messagebox.showinfo(TITRE_APP, "Enregistrez d'abord le projet : les voix off seront rangées "
                                "dans un dossier à côté de lui.")
            if not self.enregistrer_sous():
                return
        dossier = self.chemin.parent / f"{self.chemin.stem}_voix"
        largeur = max(2, len(str(len(self.projet.scenes))))
        phrases = [tts.Phrase(self.projet.scenes[i].narration.strip(), str(dossier / f"{i + 1:0{largeur}d}.wav"), i)
                   for i in avec_texte]
        arret, reglages, total = threading.Event(), deepcopy(self.reglages), len(phrases)
        self._occupe(True)
        self._arret = arret
        self._tts_empreintes = empreintes
        self.barre.configure(value=0)
        self.label_etat.configure(text="Qwen3-TTS : modèle déjà chargé, génération…" if tts.modele_charge()
                                  else "Démarrage de Qwen3-TTS…")

        def evenement(msg):
            if msg.get("etat") == "fait":
                self._file.put(("tts_fait", msg.get("cle"), msg.get("fichier"), msg.get("duree"), total))
            elif msg.get("etat") in ("chargement", "pret", "info"):
                self._file.put(("tts_info", msg.get("message", "")))
            elif msg.get("etat") == "termine":
                self._file.put(("tts_bilan", msg.get("duree_audio", 0), msg.get("secondes", 0)))

        def travail():
            try:
                faits = tts.generer(phrases, reglages, evenement, arret)
                self._file.put(("tts_fin", len(faits), str(dossier)))
            except tts.Annule:
                self._file.put(("tts_annule",))
            except Exception as e:  # noqa: BLE001
                self._file.put(("tts_erreur", str(e)))

        self._tts_faits = 0
        self._tts_bilan = ""
        threading.Thread(target=travail, daemon=True).start()

    def exporter_narrations(self) -> None:
        from .ia import exporter_narrations
        if not any(s.narration.strip() for s in self.projet.scenes):
            messagebox.showinfo(TITRE_APP, "Aucune scène n'a de narration. Remplissez le champ « Narration » "
                                "ou utilisez l'Assistant IA.")
            return
        dossier = filedialog.askdirectory(title="Dossier où écrire les narrations (01.txt, 02.txt…)")
        if dossier:
            n = exporter_narrations(self.projet, dossier)
            self.label_etat.configure(text=f"{n} narration(s) écrite(s) dans {dossier}")
            if messagebox.askyesno(TITRE_APP, f"{n} fichier(s) texte écrit(s), plus script_complet.txt.\n\n"
                                   "Générez les voix (01.wav, 02.wav…) puis utilisez « Associer un dossier "
                                   "de voix off ».\n\nOuvrir le dossier ?"):
                ouvrir_fichier(dossier)

    def associer_voix(self) -> None:
        from .ia import associer_voix
        dossier = filedialog.askdirectory(title="Dossier contenant 01.wav, 02.wav…")
        if not dossier:
            return
        trouves = associer_voix(self.projet, dossier)
        if not trouves:
            messagebox.showinfo(TITRE_APP, "Aucun fichier audio numéroté trouvé (ex. 01.wav, 02.mp3…).")
            return
        self._marquer_modifie()
        self._rafraichir_tout()
        manquantes = [str(i) for i in range(1, len(self.projet.scenes) + 1) if not self.projet.scenes[i - 1].audio]
        msg = f"{len(trouves)} voix off rattachée(s) ; la durée de ces scènes suit maintenant la voix."
        if manquantes:
            msg += f"\n\nScènes sans voix off : {', '.join(manquantes)}"
        messagebox.showinfo(TITRE_APP, msg)

    def demo(self) -> None:
        if not self._confirmer_abandon():
            return
        dossier = filedialog.askdirectory(title="Dossier où créer la démonstration")
        if not dossier:
            return
        from .demo import creer_demo
        self._charger(creer_demo(Path(dossier) / "demo-whiteboard"))

    def _quitter(self) -> None:
        if self._arret is not None:
            if not messagebox.askyesno(TITRE_APP, "Un export est en cours. Quitter quand même ?"):
                return
            self._arret.set()
        if self._confirmer_abandon():
            self.destroy()

    # ----------------------------------------------------------- aperçu
    def _planifier_apercu(self, delai: int = 450) -> None:
        if self._apercu_job is not None:
            self.after_cancel(self._apercu_job)
        self._apercu_job = self.after(delai, self._lancer_apercu)

    def _lancer_apercu(self) -> None:
        self._apercu_job = None
        largeur = max(200, self.canvas.winfo_width() - 20)
        hauteur = max(120, self.canvas.winfo_height() - 20)
        ratio = self.projet.largeur / self.projet.hauteur
        largeur = int(min(largeur, hauteur * ratio))
        self._apercu_gen += 1
        gen, projet, scene = self._apercu_gen, deepcopy(self.projet), deepcopy(self.scene)

        def travail():
            from .rendu import image_finale
            try:
                img = image_finale(projet, scene, largeur=max(160, largeur))
                self._file.put(("apercu", gen, img))
            except Exception as e:  # noqa: BLE001
                self._file.put(("apercu_erreur", gen, str(e)))

        threading.Thread(target=travail, daemon=True).start()

    def _afficher_apercu(self, img) -> None:
        self._apercu_img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.create_image(cw // 2, ch // 2, image=self._apercu_img, anchor="center")

    # ----------------------------------------------------------- rendu vidéo
    def apercu_anime(self) -> None:
        sortie = str(Path(tempfile.gettempdir()) / f"whiteboard_apercu_scene{self.index + 1}.mp4")
        self._demarrer_rendu(sortie, echelle=0.5, indices=[self.index], ouvrir=True)

    def exporter(self) -> None:
        initial = (self.chemin.stem if self.chemin else "ma-video") + ".mp4"
        f = filedialog.asksaveasfilename(title="Exporter la vidéo", defaultextension=".mp4",
                                         initialfile=initial, filetypes=[("Vidéo MP4", "*.mp4")])
        if f:
            self._demarrer_rendu(f, echelle=1.0, indices=None, ouvrir=False)

    def _demarrer_rendu(self, sortie: str, echelle: float, indices, ouvrir: bool) -> None:
        if self._arret is not None:
            return
        manquants = [s.image for s in self.projet.scenes if s.image and not Path(s.image).exists()]
        manquants += [s.audio for s in self.projet.scenes if s.audio and not Path(s.audio).exists()]
        if manquants:
            if not messagebox.askyesno(TITRE_APP, "Fichiers introuvables (ils seront ignorés) :\n\n"
                                       + "\n".join(manquants[:8]) + "\n\nContinuer ?"):
                return
        arret, projet = threading.Event(), deepcopy(self.projet)
        self._occupe(True)
        self._arret = arret
        self.barre.configure(value=0)

        def progression(f, msg):
            self._file.put(("progression", f, msg))

        def travail():
            from .rendu import Annule, exporter
            try:
                exporter(projet, sortie, progression, arret, echelle=echelle, indices=indices)
                self._file.put(("fini", sortie, ouvrir))
            except Annule:
                self._file.put(("annule", sortie, None))
            except Exception as e:  # noqa: BLE001
                self._file.put(("erreur", str(e), None))

        threading.Thread(target=travail, daemon=True).start()

    def _annuler(self) -> None:
        if self._arret is not None:
            self._arret.set()
            self.label_etat.configure(text="Annulation…")

    def _fin_rendu(self) -> None:
        self._occupe(False)

    def _lire_file(self) -> None:
        try:
            while True:
                msg = self._file.get_nowait()
                genre = msg[0]
                if genre == "apercu" and msg[1] == self._apercu_gen:
                    self._afficher_apercu(msg[2])
                elif genre == "apercu_erreur" and msg[1] == self._apercu_gen:
                    self.canvas.delete("all")
                    self.canvas.create_text(20, 20, anchor="nw", text=f"Aperçu impossible :\n{msg[2]}",
                                            fill="#a00", width=max(200, self.canvas.winfo_width() - 40))
                elif genre == "progression":
                    self.barre.configure(value=msg[1])
                    self.label_etat.configure(text=msg[2])
                elif genre == "fini":
                    self._fin_rendu()
                    self.barre.configure(value=1.0)
                    self.label_etat.configure(text=f"Vidéo prête : {msg[1]}")
                    if msg[2]:
                        ouvrir_fichier(msg[1])
                    elif messagebox.askyesno(TITRE_APP, f"Vidéo créée :\n{msg[1]}\n\nL'ouvrir maintenant ?"):
                        ouvrir_fichier(msg[1])
                elif genre == "annule":
                    self._fin_rendu()
                    self.barre.configure(value=0)
                    self.label_etat.configure(text="Export annulé.")
                    try:
                        Path(msg[1]).unlink(missing_ok=True)
                    except OSError:
                        pass
                elif genre == "tts_info":
                    self.label_etat.configure(text=msg[1])
                elif genre == "tts_fait":
                    _, i, fichier, duree, total = msg
                    self._tts_faits += 1
                    if i is not None and 0 <= i < len(self.projet.scenes):
                        sc = self.projet.scenes[i]
                        sc.audio, sc.caler_sur_audio = fichier, True
                        sc.audio_empreinte = getattr(self, "_tts_empreintes", {}).get(i, "")
                        self._marquer_modifie()
                        if i == self.index:
                            self._charger_scene()
                        sel = self.index
                        self._rafraichir_liste()
                        self.index = sel
                    self.barre.configure(value=self._tts_faits / max(1, total))
                    self.label_etat.configure(text=f"Voix off {self._tts_faits}/{total} générée "
                                                   f"(scène {(i or 0) + 1}, {duree} s)")
                elif genre == "tts_bilan":
                    duree_audio, secondes = msg[1], msg[2]
                    if secondes:
                        self._tts_bilan = (f" ({duree_audio:.0f} s de voix en {secondes:.0f} s, "
                                           f"×{duree_audio / secondes:.1f} le temps réel)")
                elif genre == "tts_fin":
                    self._occupe(False)
                    self.barre.configure(value=1.0)
                    if self.chemin is not None:
                        self.enregistrer()
                    self.label_etat.configure(text=f"{msg[1]} voix off générée(s){self._tts_bilan} — "
                                                   "projet enregistré.")
                elif genre == "tts_annule":
                    self._occupe(False)
                    self.label_etat.configure(text=f"Synthèse vocale arrêtée ({self._tts_faits} voix générée(s)).")
                elif genre == "tts_erreur":
                    self._occupe(False)
                    self.label_etat.configure(text="Erreur de synthèse vocale.")
                    messagebox.showerror(TITRE_APP, msg[1])
                elif genre == "erreur":
                    self._fin_rendu()
                    self.label_etat.configure(text="Erreur pendant l'export.")
                    messagebox.showerror(TITRE_APP, f"L'export a échoué :\n\n{msg[1]}")
        except queue.Empty:
            pass
        self.after(100, self._lire_file)


class AssistantIA(tk.Toplevel):
    """Texte → prompt pour une IA → réponse collée → scènes."""

    def __init__(self, app: Application):
        super().__init__(app)
        self.app = app
        self.title("Assistant IA : du texte à la vidéo")
        self.transient(app)
        self.geometry("880x900")
        self.minsize(700, 600)
        cadre = ttk.Frame(self, padding=12)
        cadre.pack(fill="both", expand=True)
        cadre.columnconfigure(0, weight=1)

        ttk.Label(cadre, text="1. Votre texte (article, script, notes…)", style="Titre.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Button(cadre, text="Ouvrir un fichier texte…", command=self._ouvrir).grid(row=0, column=1, sticky="e")
        self.t_source = tk.Text(cadre, height=10, wrap="word", font=("Segoe UI", 10), undo=True)
        self.t_source.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=4)
        opts = ttk.Frame(cadre)
        opts.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(opts, text="Durée visée (min)").pack(side="left")
        self.v_duree = tk.DoubleVar(value=3)
        self.spin_duree = ttk.Spinbox(opts, from_=0.25, to=30, increment=0.25, width=5, textvariable=self.v_duree)
        self.spin_duree.pack(side="left", padx=6)
        self.v_short = tk.BooleanVar(value=app.projet.hauteur > app.projet.largeur)
        ttk.Checkbutton(opts, text="Short (vertical, < 1 min)", variable=self.v_short,
                        command=self._basculer_short).pack(side="left", padx=(6, 0))
        self._duree_normale = 3.0
        if self.v_short.get():
            self.v_duree.set(0.75)
        ttk.Label(opts, text="Public et ton").pack(side="left", padx=(12, 0))
        self.v_ton = tk.StringVar(value="grand public curieux, ton clair et chaleureux")
        ttk.Entry(opts, textvariable=self.v_ton).pack(side="left", fill="x", expand=True, padx=6)

        ttk.Label(cadre, text="2. Donnez le prompt à une IA", style="Titre.TLabel").grid(
            row=3, column=0, sticky="w", pady=(14, 0))
        etape2 = ttk.Frame(cadre)
        etape2.grid(row=4, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(etape2, text="Copier le prompt", command=self._copier).pack(side="left")
        ttk.Button(etape2, text="Enregistrer le prompt…", command=self._enregistrer).pack(side="left", padx=6)
        self.lbl_copie = ttk.Label(etape2, text="Collez-le dans Claude, ChatGPT, Mistral ou votre modèle local.",
                                   foreground="#555")
        self.lbl_copie.pack(side="left", padx=6)

        ollama = ttk.Frame(cadre)
        ollama.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        ttk.Label(ollama, text="… ou directement avec Ollama :").pack(side="left")
        self.v_modele = tk.StringVar(value=app.reglages.ollama_modele)
        self.combo_modele = ttk.Combobox(ollama, textvariable=self.v_modele, width=26)
        self.combo_modele.pack(side="left", padx=6)
        self.b_ollama = ttk.Button(ollama, text="Générer avec Ollama", command=self._ollama)
        self.b_ollama.pack(side="left")
        self.b_stop = ttk.Button(ollama, text="Arrêter", command=self._arreter, state="disabled")
        self.b_stop.pack(side="left", padx=4)
        self.lbl_ollama = ttk.Label(cadre, text="Une IA externe (Claude, ChatGPT…) donne en général un meilleur "
                                    "découpage ; Ollama évite le copier-coller.", foreground="#555")
        self.lbl_ollama.grid(row=6, column=0, columnspan=2, sticky="w")
        self._arret_ollama: threading.Event | None = None
        self._file_ollama: queue.Queue = queue.Queue()
        threading.Thread(target=self._charger_modeles, daemon=True).start()
        self.after(150, self._lire_ollama)

        ttk.Label(cadre, text="3. Collez ici la réponse de l'IA", style="Titre.TLabel").grid(
            row=7, column=0, sticky="w", pady=(14, 0))
        ttk.Button(cadre, text="Coller", command=self._coller).grid(row=7, column=1, sticky="e", pady=(14, 0))
        self.t_reponse = tk.Text(cadre, height=10, wrap="word", font=("Consolas", 9), undo=True)
        self.t_reponse.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=4)
        cadre.rowconfigure(1, weight=1)
        cadre.rowconfigure(8, weight=1)

        bas = ttk.Frame(cadre)
        bas.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.v_remplacer = tk.BooleanVar(value=True)
        ttk.Radiobutton(bas, text="Remplacer les scènes actuelles", variable=self.v_remplacer, value=True).pack(side="left")
        ttk.Radiobutton(bas, text="Ajouter à la suite", variable=self.v_remplacer, value=False).pack(side="left", padx=10)
        ttk.Button(bas, text="Créer les scènes", style="Grand.TButton", command=self._creer).pack(side="right", padx=6)

        # --- 4. Illustrations sur mesure (facultatif) ---------------------------
        ttk.Label(cadre, text="4. Illustrations sur mesure (facultatif) : second prompt, pour une IA d'images",
                  style="Titre.TLabel").grid(row=10, column=0, columnspan=2, sticky="w", pady=(14, 0))
        illus = ttk.Frame(cadre)
        illus.grid(row=11, column=0, columnspan=2, sticky="ew", pady=4)
        self.b_illus = ttk.Button(illus, text="Copier le prompt des illustrations", command=self._copier_illus,
                                  state="disabled")
        self.b_illus.pack(side="left")
        self.v_lot_illus = tk.StringVar()
        self.combo_illus = ttk.Combobox(illus, textvariable=self.v_lot_illus, state="disabled", width=22)
        self.combo_illus.pack(side="left", padx=6)
        self.combo_illus.bind("<<ComboboxSelected>>", lambda e: self._copier_illus(nouveau=False))
        self.b_zip = ttk.Button(illus, text="Charger les zip…", command=self._charger_illus, state="disabled")
        self.b_zip.pack(side="left")
        self.b_choisir = ttk.Button(illus, text="Choisir les scènes…", command=self.app.illustrations_ia,
                                    state="disabled")
        self.b_choisir.pack(side="left", padx=6)
        ttk.Button(illus, text="Fermer", command=self._fermer).pack(side="right")
        self.lbl_illus = ttk.Label(cadre, foreground="#555", wraplength=820, justify="left",
                                   text="Disponible une fois les scènes créées. Le prompt est copié lot par lot "
                                        "(10 images au plus) ; collez-le dans ChatGPT, puis chargez le zip renvoyé.")
        self.lbl_illus.grid(row=12, column=0, columnspan=2, sticky="w")
        self._prompts_illus: list[str] = []
        if any(s.titre or s.texte or s.image for s in app.projet.scenes):
            self._activer_illus()
        self.bind("<Escape>", lambda e: self._fermer())
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.t_source.focus_set()

    # --- Ollama ---------------------------------------------------------------
    def _charger_modeles(self):
        from .ollama import ErreurOllama, lister_modeles
        try:
            self._file_ollama.put(("modeles", lister_modeles(self.app.reglages.ollama_url)))
        except ErreurOllama as e:
            self._file_ollama.put(("indisponible", str(e)))

    def _ollama(self):
        from .ollama import Arrete, ErreurOllama, generer
        prompt = self._prompt()
        if not prompt or self._arret_ollama is not None:
            return
        modele = self.v_modele.get().strip()
        if not modele:
            messagebox.showinfo(TITRE_APP, "Choisissez un modèle Ollama dans la liste.", parent=self)
            return
        if modele != self.app.reglages.ollama_modele:
            self.app.reglages.ollama_modele = modele
            self.app.reglages.enregistrer()
        reglages = deepcopy(self.app.reglages)
        from . import tts
        if tts.modele_charge():  # la mémoire vidéo va au modèle de rédaction
            tts.liberer()
        self._arret_ollama = arret = threading.Event()
        self.b_ollama.configure(state="disabled")
        self.b_stop.configure(state="normal")
        self.t_reponse.delete("1.0", "end")
        self.lbl_ollama.configure(text=f"Envoi du prompt à {modele}… (le chargement du modèle peut prendre "
                                       "un moment)")

        def progression(texte, stats):
            self._file_ollama.put(("partiel", texte, stats))

        def travail():
            try:
                self._file_ollama.put(("fini", generer(prompt, reglages, progression, arret)))
            except Arrete:
                self._file_ollama.put(("arrete",))
            except ErreurOllama as e:
                self._file_ollama.put(("erreur", str(e)))
            except Exception as e:  # noqa: BLE001
                self._file_ollama.put(("erreur", f"{type(e).__name__} : {e}"))

        threading.Thread(target=travail, daemon=True).start()

    def _arreter(self):
        if self._arret_ollama is not None:
            self._arret_ollama.set()

    def _fermer(self):
        self._arreter()
        self.destroy()

    def _lire_ollama(self):
        if not self.winfo_exists():
            return
        dernier = None
        try:
            while True:
                msg = self._file_ollama.get_nowait()
                if msg[0] == "partiel":
                    dernier = msg  # on n'affiche que le plus récent
                    continue
                if msg[0] == "modeles":
                    self.combo_modele.configure(values=msg[1])
                    if not self.v_modele.get() and msg[1]:
                        self.v_modele.set(msg[1][0])
                elif msg[0] == "indisponible":
                    self.lbl_ollama.configure(text=f"Ollama indisponible : {msg[1]}")
                elif msg[0] in ("fini", "arrete", "erreur"):
                    self._arret_ollama = None
                    self.b_ollama.configure(state="normal")
                    self.b_stop.configure(state="disabled")
                    if msg[0] == "fini":
                        self.t_reponse.delete("1.0", "end")
                        self.t_reponse.insert("1.0", msg[1])
                        self.lbl_ollama.configure(text="Réponse reçue : vérifiez-la si besoin, puis « Créer les scènes ».")
                    elif msg[0] == "arrete":
                        self.lbl_ollama.configure(text="Génération arrêtée.")
                    else:
                        self.lbl_ollama.configure(text="Erreur Ollama.")
                        messagebox.showerror(TITRE_APP, msg[1], parent=self)
        except queue.Empty:
            pass
        if dernier is not None and self._arret_ollama is not None:
            _, texte, stats = dernier
            self.t_reponse.delete("1.0", "end")
            self.t_reponse.insert("1.0", texte)
            self.t_reponse.see("end")
            if stats.reflexion and not texte:
                etat = "le modèle réfléchit…"
            else:
                etat = f"{stats.caracteres} caractères reçus"
            vitesse = f" · {stats.jetons_par_seconde:.1f} jetons/s" if stats.secondes > 1 else ""
            self.lbl_ollama.configure(text=f"Génération en cours : {etat}{vitesse}")
        self.after(200, self._lire_ollama)

    def _prompt(self) -> str | None:
        from .ia import construire_prompt
        texte = self.t_source.get("1.0", "end-1c").strip()
        if not texte:
            messagebox.showinfo(TITRE_APP, "Collez d'abord votre texte dans la zone 1.", parent=self)
            return None
        try:
            duree = float(self.v_duree.get())
        except (tk.TclError, ValueError):
            duree = 3
        return construire_prompt(texte, duree, self.v_ton.get(), short=bool(self.v_short.get()))

    def _basculer_short(self):
        try:
            duree = float(self.v_duree.get())
        except (tk.TclError, ValueError):
            duree = 3.0
        if self.v_short.get():
            self._duree_normale = duree
            self.v_duree.set(0.75)
        else:
            self.v_duree.set(self._duree_normale if self._duree_normale > 1 else 3.0)

    def _ouvrir(self):
        f = filedialog.askopenfilename(parent=self, title="Texte source",
                                       filetypes=[("Texte", "*.txt *.md"), ("Tous les fichiers", "*.*")])
        if f:
            self.t_source.delete("1.0", "end")
            self.t_source.insert("1.0", Path(f).read_text(encoding="utf-8", errors="replace"))

    def _copier(self):
        prompt = self._prompt()
        if prompt:
            self.clipboard_clear()
            self.clipboard_append(prompt)
            self.lbl_copie.configure(text=f"Prompt copié ({len(prompt):,} caractères). Collez-le dans l'IA.".replace(",", " "))

    def _enregistrer(self):
        prompt = self._prompt()
        if not prompt:
            return
        f = filedialog.asksaveasfilename(parent=self, title="Enregistrer le prompt", defaultextension=".txt",
                                         initialfile="prompt_video.txt", filetypes=[("Texte", "*.txt *.md")])
        if f:
            Path(f).write_text(prompt, encoding="utf-8")
            self.lbl_copie.configure(text=f"Prompt enregistré : {Path(f).name}")

    def _coller(self):
        try:
            contenu = self.clipboard_get()
        except tk.TclError:
            return
        self.t_reponse.delete("1.0", "end")
        self.t_reponse.insert("1.0", contenu)

    def _creer(self):
        reponse = self.t_reponse.get("1.0", "end-1c").strip()
        if not reponse:
            messagebox.showinfo(TITRE_APP, "Collez la réponse de l'IA dans la zone 3.", parent=self)
            return
        if self.app.appliquer_ia(reponse, bool(self.v_remplacer.get()), short=bool(self.v_short.get())):
            self._prompts_illus = []
            self._activer_illus()
            self.lbl_illus.configure(text="Scènes créées. Pour des images sur mesure : « Copier le prompt des "
                                          "illustrations », collez-le dans ChatGPT, puis « Charger les zip ». "
                                          "Sinon, fermez simplement cette fenêtre.")
            self.lift()

    # --- illustrations ------------------------------------------------------
    def _activer_illus(self):
        for b in (self.b_illus, self.b_zip, self.b_choisir):
            b.configure(state="normal")

    def _copier_illus(self, nouveau: bool = True):
        from .illustrations import illustrable
        if nouveau or not self._prompts_illus:
            if not any(illustrable(s) for s in self.app.projet.scenes):
                messagebox.showinfo(TITRE_APP, "Aucune scène ne peut recevoir d'illustration (il faut des scènes "
                                    "« Image et texte », « Titre », « Liste » ou « Chiffre clé »).", parent=self)
                return
            self._prompts_illus = self.app.preparer_illustrations()
            if not self._prompts_illus:
                self.lbl_illus.configure(text="Aucune scène proposée d'office : utilisez « Choisir les scènes… ».")
                return
            n = len(self._prompts_illus)
            self.combo_illus.configure(values=[f"Lot {k + 1} sur {n}" for k in range(n)], state="readonly")
            self.combo_illus.current(0)
        k = max(0, self.combo_illus.current())
        self.clipboard_clear()
        self.clipboard_append(self._prompts_illus[k])
        nb = sum(1 for s in self.app.projet.scenes if s.illustration_cle)
        suite = f" Choisissez ensuite le lot suivant dans la liste." if len(self._prompts_illus) > 1 else ""
        self.lbl_illus.configure(text=f"Prompt des illustrations copié (lot {k + 1} sur {len(self._prompts_illus)}, "
                                      f"{nb} image(s) au total) : collez-le dans ChatGPT.{suite} "
                                      "« Choisir les scènes… » permet d'en ajouter ou d'en retirer.")

    def _charger_illus(self):
        texte = self.app.charger_illustrations(self)
        if texte is not None:
            self.lbl_illus.configure(text=texte)


class FenetreIllustrations(tk.Toplevel):
    """Prompt des illustrations (distinct du prompt de scénario) puis chargement des zip obtenus."""

    def __init__(self, app: Application):
        from . import illustrations as I
        super().__init__(app)
        self.app, self.I = app, I
        self.title("Prompt des illustrations (ChatGPT…)")
        self.transient(app)
        self.geometry("940x860")
        self.minsize(780, 680)
        cadre = ttk.Frame(self, padding=12)
        cadre.pack(fill="both", expand=True)
        cadre.columnconfigure(0, weight=1)

        ttk.Label(cadre, text="1. Scènes à illustrer", style="Titre.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(cadre, foreground="#555", wraplength=900, justify="left",
                  text="Cochez les scènes qui méritent une image sur mesure. L'idée est facultative : vide, "
                       "l'IA d'images imagine elle-même l'illustration à partir du texte et de la voix off "
                       "de la scène, qui figurent dans le prompt.").grid(row=1, column=0, sticky="w")
        zone = ttk.Frame(cadre)
        zone.grid(row=2, column=0, sticky="nsew", pady=4)
        cadre.rowconfigure(2, weight=1)
        canvas = tk.Canvas(zone, highlightthickness=0, height=200)
        defil = ttk.Scrollbar(zone, orient="vertical", command=canvas.yview)
        self.liste = ttk.Frame(canvas)
        self.liste.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        fen = canvas.create_window((0, 0), window=self.liste, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(fen, width=e.width))
        canvas.configure(yscrollcommand=defil.set)
        canvas.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.liste.columnconfigure(3, weight=1)
        ttk.Label(self.liste, text="Scène", foreground="#555").grid(row=0, column=1, sticky="w")
        ttk.Label(self.liste, text="Idée imposée (facultatif)", foreground="#555").grid(row=0, column=3, sticky="w",
                                                                                         padx=4)
        self.lignes: dict[int, tuple[tk.BooleanVar, tk.StringVar]] = {}
        r = 1
        for i, sc in enumerate(app.projet.scenes):
            if not I.illustrable(sc):
                continue
            v_coche = tk.BooleanVar(value=I.coche_par_defaut(sc))
            v_desc = tk.StringVar(value=sc.illustration)
            nom = sc.titre or sc.texte.split("\n")[0] or "(sans titre)"
            ttk.Checkbutton(self.liste, variable=v_coche).grid(row=r, column=0, sticky="nw", pady=2)
            ttk.Label(self.liste, text=f"{i + 1}. {nom[:26]}").grid(row=r, column=1, sticky="nw", pady=2)
            ttk.Label(self.liste, text=I.LIBELLES_MODELES.get(sc.modele, ""), foreground="#888").grid(
                row=r, column=2, sticky="nw", padx=6, pady=2)
            ttk.Entry(self.liste, textvariable=v_desc).grid(row=r, column=3, sticky="ew", pady=2, padx=(4, 6))
            charge = sc.illustration_cle and Path(sc.image).stem == sc.illustration_cle
            ttk.Label(self.liste, text="✓ image chargée" if charge else "", foreground="#2e7d32").grid(
                row=r, column=4, sticky="nw")
            self.lignes[i] = (v_coche, v_desc)
            r += 1
        boutons = ttk.Frame(cadre)
        boutons.grid(row=3, column=0, sticky="w")
        ttk.Button(boutons, text="Tout cocher", command=lambda: self._cocher(True)).pack(side="left")
        ttk.Button(boutons, text="Tout décocher", command=lambda: self._cocher(False)).pack(side="left", padx=4)

        reglages = ttk.Frame(cadre)
        reglages.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        reglages.columnconfigure(1, weight=1)
        ttk.Label(reglages, text="Sujet de la vidéo").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.v_sujet = tk.StringVar(value=I.sujet_par_defaut(app.projet))
        ttk.Entry(reglages, textvariable=self.v_sujet).grid(row=0, column=1, sticky="ew")
        ttk.Label(reglages, text="Style commun").grid(row=1, column=0, sticky="nw", padx=(0, 8), pady=(6, 0))
        self.t_style = tk.Text(reglages, height=3, wrap="word", font=("Segoe UI", 9))
        self.t_style.insert("1.0", app.reglages.style_illustrations or I.STYLE_PAR_DEFAUT)
        self.t_style.grid(row=1, column=1, sticky="ew", pady=(6, 0))

        ttk.Label(cadre, text="2. Le prompt des illustrations (un lot de 10 images au plus)",
                  style="Titre.TLabel").grid(row=5, column=0, sticky="w", pady=(10, 0))
        etape2 = ttk.Frame(cadre)
        etape2.grid(row=6, column=0, sticky="ew", pady=4)
        ttk.Button(etape2, text="Préparer le prompt", command=self._preparer).pack(side="left")
        self.v_lot = tk.StringVar()
        self.combo_lot = ttk.Combobox(etape2, textvariable=self.v_lot, state="readonly", width=24)
        self.combo_lot.pack(side="left", padx=6)
        self.combo_lot.bind("<<ComboboxSelected>>", lambda e: self._afficher_lot())
        self.b_copier = ttk.Button(etape2, text="Copier ce lot", command=self._copier, state="disabled")
        self.b_copier.pack(side="left")
        self.b_enreg = ttk.Button(etape2, text="Enregistrer…", command=self._enregistrer, state="disabled")
        self.b_enreg.pack(side="left", padx=6)
        self.t_apercu = tk.Text(cadre, height=9, wrap="word", font=("Consolas", 9), state="disabled",
                                background="#f7f7f7")
        self.t_apercu.grid(row=7, column=0, sticky="nsew", pady=4)
        cadre.rowconfigure(7, weight=1)
        self.lbl2 = ttk.Label(cadre, text="Collez chaque lot dans une conversation ChatGPT qui génère des images, "
                                          "puis téléchargez le zip qu'il propose.", foreground="#555")
        self.lbl2.grid(row=8, column=0, sticky="w")

        ttk.Label(cadre, text="3. Chargez le ou les zip renvoyés", style="Titre.TLabel").grid(
            row=9, column=0, sticky="w", pady=(10, 0))
        etape3 = ttk.Frame(cadre)
        etape3.grid(row=10, column=0, sticky="ew", pady=4)
        ttk.Button(etape3, text="Charger les zip (ou des images)…", style="Grand.TButton",
                   command=self._charger).pack(side="left")
        ttk.Button(etape3, text="Revenir aux visuels d'origine", command=self._revenir).pack(side="left", padx=8)
        ttk.Button(etape3, text="Fermer", command=self.destroy).pack(side="right")
        self.lbl3 = ttk.Label(cadre, text="", foreground="#555", wraplength=900, justify="left")
        self.lbl3.grid(row=11, column=0, sticky="w")
        self._prompts: list[str] = []
        self.bind("<Escape>", lambda e: self.destroy())

    def _cocher(self, oui: bool):
        for v_coche, _ in self.lignes.values():
            v_coche.set(oui)

    def _style(self) -> str:
        return self.t_style.get("1.0", "end").strip()

    def _preparer(self):
        choisies = [i for i, (c, _) in self.lignes.items() if c.get()]
        if not choisies:
            messagebox.showinfo(TITRE_APP, "Cochez au moins une scène.", parent=self)
            return
        self._prompts = self.app.preparer_illustrations(choisies, {i: self.lignes[i][1].get() for i in choisies},
                                                        self._style(), self.v_sujet.get())
        n = len(self._prompts)
        self.combo_lot.configure(values=[
            f"Lot {k + 1} : images {k * 10 + 1} à {min((k + 1) * 10, len(choisies))}" for k in range(n)])
        self.combo_lot.current(0)
        self.b_copier.configure(state="normal")
        self.b_enreg.configure(state="normal")
        self._afficher_lot()
        self.lbl2.configure(text=f"{len(choisies)} image(s) en {n} lot(s). Collez chaque lot dans une conversation "
                                 "ChatGPT qui génère des images, puis téléchargez le zip qu'il propose.")

    def _afficher_lot(self):
        k = max(0, self.combo_lot.current())
        self.t_apercu.configure(state="normal")
        self.t_apercu.delete("1.0", "end")
        self.t_apercu.insert("1.0", self._prompts[k] if self._prompts else "")
        self.t_apercu.configure(state="disabled")

    def _copier(self):
        if not self._prompts:
            return
        k = max(0, self.combo_lot.current())
        self.clipboard_clear()
        self.clipboard_append(self._prompts[k])
        self.lbl2.configure(text=f"Lot {k + 1} copié : collez-le dans ChatGPT.")

    def _enregistrer(self):
        f = filedialog.asksaveasfilename(parent=self, title="Enregistrer le prompt des illustrations",
                                         defaultextension=".txt", initialfile="prompt_illustrations.txt",
                                         filetypes=[("Texte", "*.txt")])
        if f:
            separateur = "\n\n" + "=" * 60 + "\n\n"
            Path(f).write_text(separateur.join(f"LOT {k + 1}\n\n{p}" for k, p in enumerate(self._prompts)),
                               encoding="utf-8")
            self.lbl2.configure(text=f"Prompt enregistré : {Path(f).name}")

    def _charger(self):
        texte = self.app.charger_illustrations(self)
        if texte is not None:
            self.lbl3.configure(text=texte)

    def _revenir(self):
        n = self.I.revenir(self.app.projet)
        if n:
            self.app._marquer_modifie()
            self.app._rafraichir_tout()
        self.lbl3.configure(text=f"{n} scène(s) revenue(s) à leur visuel d'origine.")


class FenetreReglages(tk.Toplevel):
    """Réglages d'Ollama et de Qwen3-TTS (enregistrés pour tous les projets)."""

    def __init__(self, app: Application, onglet: int = 0):
        super().__init__(app)
        self.app = app
        self.title("Réglages IA et voix")
        self.transient(app)
        self.geometry("720x560")
        r = app.reglages
        self.v = {nom: (tk.BooleanVar(value=val) if isinstance(val, bool) else tk.StringVar(value=str(val)))
                  for nom, val in vars(r).items()}
        carnet = ttk.Notebook(self)
        carnet.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Ollama ---------------------------------------------------------
        o = ttk.Frame(carnet, padding=12)
        carnet.add(o, text="Ollama (rédaction des scènes)")
        o.columnconfigure(1, weight=1)
        lignes = 0

        def ligne(parent, texte, widget, aide=""):
            nonlocal lignes
            ttk.Label(parent, text=texte).grid(row=lignes, column=0, sticky="w", pady=4, padx=(0, 8))
            widget.grid(row=lignes, column=1, sticky="ew")
            lignes += 1
            if aide:
                ttk.Label(parent, text=aide, foreground="#666", wraplength=470, justify="left").grid(
                    row=lignes, column=1, sticky="w")
                lignes += 1

        ligne(o, "Adresse", ttk.Entry(o, textvariable=self.v["ollama_url"]))
        cadre_m = ttk.Frame(o)
        self.combo_ollama = ttk.Combobox(cadre_m, textvariable=self.v["ollama_modele"])
        self.combo_ollama.pack(side="left", fill="x", expand=True)
        ttk.Button(cadre_m, text="Tester la connexion", command=self._tester_ollama).pack(side="left", padx=6)
        ligne(o, "Modèle", cadre_m)
        ligne(o, "Contexte (jetons)", ttk.Combobox(o, textvariable=self.v["ollama_contexte"], width=10,
                                                   values=["8192", "16384", "32768", "65536"]),
              "Le prompt et la réponse doivent y tenir : 32768 convient pour un texte de quelques pages.")
        ligne(o, "Température", ttk.Spinbox(o, from_=0, to=1.5, increment=0.1, width=6,
                                            textvariable=self.v["ollama_temperature"]))
        ligne(o, "", ttk.Checkbutton(o, text="Sans phase de réflexion (/no_think)",
                                     variable=self.v["ollama_sans_reflexion"]),
              "Plus rapide, et souvent meilleur pour la rédaction en français avec les modèles Qwen3.")
        ligne(o, "", ttk.Checkbutton(o, text="Libérer la mémoire vidéo après la réponse",
                                     variable=self.v["ollama_liberer_vram"]),
              "Décharge le modèle aussitôt la réponse reçue, pour laisser la carte graphique à Qwen3-TTS.")
        self.lbl_ollama = ttk.Label(o, text="", foreground="#555", wraplength=560)
        self.lbl_ollama.grid(row=lignes, column=0, columnspan=2, sticky="w", pady=8)

        # --- Qwen3-TTS ------------------------------------------------------
        t = ttk.Frame(carnet, padding=12)
        carnet.add(t, text="Qwen3-TTS (voix off)")
        t.columnconfigure(1, weight=1)
        lignes = 0
        cadre_py = ttk.Frame(t)
        ttk.Entry(cadre_py, textvariable=self.v["tts_python"]).pack(side="left", fill="x", expand=True)
        ttk.Button(cadre_py, text="Parcourir…", command=self._choisir_python).pack(side="left", padx=4)
        ttk.Button(cadre_py, text="Vérifier", command=self._verifier_tts).pack(side="left")
        ligne(t, "Python de Qwen3-TTS", cadre_py,
              "Le python.exe de l'environnement où « qwen-tts » est installé, ex. …\\qwen_env\\Scripts\\python.exe")
        ligne(t, "Modèle", ttk.Combobox(t, textvariable=self.v["tts_modele"], values=MODELES_TTS),
              "« Base » : clone la voix de l'extrait ci-dessous. « CustomVoice » : voix prédéfinies.")
        cadre_ap = ttk.Frame(t)
        ttk.Combobox(cadre_ap, textvariable=self.v["tts_appareil"], width=8, values=["cuda:0", "cuda:1", "cpu"]).pack(side="left")
        ttk.Label(cadre_ap, text="  Précision").pack(side="left")
        ttk.Combobox(cadre_ap, textvariable=self.v["tts_precision"], width=9, state="readonly",
                     values=["bfloat16", "float16", "float32"]).pack(side="left", padx=4)
        ttk.Label(cadre_ap, text="  Langue").pack(side="left")
        ttk.Combobox(cadre_ap, textvariable=self.v["tts_langue"], width=10, values=LANGUES_TTS).pack(side="left", padx=4)
        ligne(t, "Calcul", cadre_ap)
        cadre_ref = ttk.Frame(t)
        ttk.Entry(cadre_ref, textvariable=self.v["tts_voix_reference"]).pack(side="left", fill="x", expand=True)
        ttk.Button(cadre_ref, text="Parcourir…", command=self._choisir_reference).pack(side="left", padx=4)
        ligne(t, "Voix à cloner", cadre_ref, "Extrait de 10 à 20 secondes, parole claire, sans musique.")
        ligne(t, "Ce qui y est dit", ttk.Entry(t, textvariable=self.v["tts_texte_reference"]),
              "Transcription exacte de l'extrait : meilleure ressemblance. Vide : seul le timbre est copié.")
        ligne(t, "Locuteur", ttk.Entry(t, textvariable=self.v["tts_locuteur"]),
              "Modèles CustomVoice seulement (vide = premier locuteur disponible).")
        ligne(t, "Consigne de style", ttk.Entry(t, textvariable=self.v["tts_consigne"]),
              "Modèles CustomVoice : ex. « Ton posé et chaleureux, débit modéré ».")
        cadre_vit = ttk.Frame(t)
        ttk.Spinbox(cadre_vit, from_=1, to=16, width=4, textvariable=self.v["tts_lot"]).pack(side="left")
        ttk.Label(cadre_vit, text=" phrases à la fois     garder le modèle chargé").pack(side="left")
        ttk.Spinbox(cadre_vit, from_=0, to=60, width=4, textvariable=self.v["tts_garder_minutes"]).pack(side="left", padx=4)
        ttk.Label(cadre_vit, text="min").pack(side="left")
        ttk.Button(cadre_vit, text="Libérer maintenant", command=self._liberer_tts).pack(side="left", padx=8)
        ligne(t, "Vitesse", cadre_vit,
              "Plus de phrases à la fois = plus rapide, tant que la mémoire vidéo suffit (réduit tout seul sinon). "
              "Garder le modèle chargé évite de le recharger à chaque génération.")
        cadre_essai = ttk.Frame(t)
        ttk.Button(cadre_essai, text="Essayer la voix", command=self._essai_voix).pack(side="left")
        self.lbl_tts = ttk.Label(cadre_essai, text="", foreground="#555", wraplength=360)
        self.lbl_tts.pack(side="left", padx=8)
        ligne(t, "", cadre_essai)

        bas = ttk.Frame(self, padding=(10, 0, 10, 10))
        bas.pack(fill="x")
        ttk.Button(bas, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(bas, text="Enregistrer", command=self._enregistrer).pack(side="right", padx=6)
        carnet.select(onglet)
        self._file: queue.Queue = queue.Queue()
        self.after(150, self._lire)

    def _lire_valeurs(self) -> Reglages:
        r = Reglages()
        for nom, var in self.v.items():
            defaut = getattr(r, nom)
            try:
                brut = var.get()
                if isinstance(defaut, bool):
                    val = bool(brut)
                elif isinstance(defaut, int):
                    val = int(float(brut))
                elif isinstance(defaut, float):
                    val = float(str(brut).replace(",", "."))
                else:
                    val = str(brut).strip().strip('"')
            except (ValueError, tk.TclError):
                val = defaut
            setattr(r, nom, val)
        return r

    def _enregistrer(self):
        self.app.reglages = self._lire_valeurs()
        self.app.reglages.enregistrer()
        self.destroy()

    def _choisir_python(self):
        f = filedialog.askopenfilename(parent=self, title="python.exe de l'environnement Qwen3-TTS",
                                       filetypes=[("Python", "python.exe python3 python"), ("Tous", "*.*")])
        if f:
            self.v["tts_python"].set(f)

    def _choisir_reference(self):
        f = filedialog.askopenfilename(parent=self, title="Extrait de la voix à cloner", filetypes=TYPES_AUDIO)
        if f:
            self.v["tts_voix_reference"].set(f)

    def _en_tache(self, fonction, cle):
        def travail():
            try:
                self._file.put((cle, True, fonction()))
            except Exception as e:  # noqa: BLE001
                self._file.put((cle, False, str(e)))
        threading.Thread(target=travail, daemon=True).start()

    def _tester_ollama(self):
        from .ollama import lister_modeles
        url = self.v["ollama_url"].get()
        self.lbl_ollama.configure(text="Connexion…")
        self._en_tache(lambda: lister_modeles(url), "ollama")

    def _verifier_tts(self):
        from .tts import diagnostiquer
        r = self._lire_valeurs()
        self.lbl_tts.configure(text="Vérification (lancement de PyTorch, quelques secondes)…")
        self._en_tache(lambda: diagnostiquer(r), "tts")

    def _liberer_tts(self):
        from . import tts
        tts.liberer()
        self.lbl_tts.configure(text="Qwen3-TTS arrêté : mémoire vidéo libérée.")

    def _essai_voix(self):
        from . import tts
        r = self._lire_valeurs()
        sortie = str(Path(tempfile.gettempdir()) / "whiteboard_essai_voix.wav")
        phrase = tts.Phrase("Bonjour ! Voici un essai de voix off pour Whiteboard Studio.", sortie)
        self.lbl_tts.configure(text="Génération de l'essai (chargement du modèle : patience)…")

        def faire():
            tts.generer([phrase], r)
            return sortie
        self._en_tache(faire, "essai")

    def _lire(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                cle, ok, res = self._file.get_nowait()
                if cle == "ollama":
                    if ok:
                        self.combo_ollama.configure(values=res)
                        if res and not self.v["ollama_modele"].get():
                            self.v["ollama_modele"].set(res[0])
                        self.lbl_ollama.configure(text=f"Connecté : {len(res)} modèle(s) installé(s).")
                    else:
                        self.lbl_ollama.configure(text=res)
                elif cle == "tts":
                    self.lbl_tts.configure(text=res)
                elif cle == "essai":
                    if ok:
                        self.lbl_tts.configure(text="Essai prêt : lecture.")
                        ouvrir_fichier(res)
                    else:
                        self.lbl_tts.configure(text=res)
        except queue.Empty:
            pass
        self.after(150, self._lire)


class SelecteurIcones(tk.Toplevel):
    """Bibliothèque de visuels : cliparts en couleur, icônes au trait, personnages modulaires.

    `rappel` reçoit la source choisie : « clipart:nom », « icone:nom » ou « personne:… »,
    éventuellement suivie d'une pastille (« +ok », « +non »…).
    """

    TAILLE = 56
    PAR_LIGNE = 9
    MAX = 270
    GENRES = {"clipart": ("Cliparts en couleur", PREFIXE_CLIPART, chercher_cliparts, categories_cliparts,
                          vignette_clipart),
              "icone": ("Icônes au trait", PREFIXE_ICONE, chercher_icones, categories_icones, vignette_icone),
              "personne": ("Personnages", "personne:", None, None, None)}
    _dernier_genre = "clipart"

    def __init__(self, parent, rappel, genre: str | None = None):
        from . import personnages as P
        from .vecteur import PASTILLES
        super().__init__(parent)
        self.P = P
        self.title("Bibliothèque de visuels")
        self.transient(parent)
        self.geometry("740x620")
        self.rappel = rappel
        self._images: dict[str, ImageTk.PhotoImage] = {}
        self._noms: list[str] = []
        self._choix: str | None = None
        self._job = None
        self._gen = 0

        onglets = ttk.Frame(self, padding=(8, 8, 8, 0))
        onglets.pack(fill="x")
        self.v_genre = tk.StringVar(value=genre or SelecteurIcones._dernier_genre)
        for code, (libelle, *_r) in self.GENRES.items():
            ttk.Radiobutton(onglets, text=libelle, value=code, variable=self.v_genre,
                            command=self._changer_genre).pack(side="left", padx=(0, 14))
        self.lbl_nb = ttk.Label(onglets, text="", foreground="#666")
        self.lbl_nb.pack(side="right")

        # --- recherche (cliparts, icônes) -------------------------------------
        self.cadre_recherche = ttk.Frame(self)
        haut = ttk.Frame(self.cadre_recherche, padding=8)
        haut.pack(fill="x")
        ttk.Label(haut, text="Rechercher").pack(side="left")
        self.v_req = tk.StringVar()
        self.champ = ttk.Entry(haut, textvariable=self.v_req, width=24)
        self.champ.pack(side="left", padx=6)
        self.v_cat = tk.StringVar(value="Toutes les catégories")
        self.combo_cat = ttk.Combobox(haut, textvariable=self.v_cat, state="readonly", width=24)
        self.combo_cat.pack(side="left", padx=6)
        self.v_req.trace_add("write", lambda *a: self._planifier())
        self.v_cat.trace_add("write", lambda *a: self._planifier())
        cadre = ttk.Frame(self.cadre_recherche)
        cadre.pack(fill="both", expand=True, padx=8)
        self.canvas = tk.Canvas(cadre, background="white", highlightthickness=0)
        defil = ttk.Scrollbar(cadre, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=defil.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        defil.pack(side="right", fill="y")
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

        # --- composition d'un personnage --------------------------------------
        self.cadre_perso = ttk.Frame(self, padding=10)
        form = ttk.Frame(self.cadre_perso)
        form.pack(side="left", fill="y")
        self.v_p = {}
        champs = [("Genre", ["au hasard", "femme", "homme"]), ("Expression", P.CHOIX_EMOTION),
                  ("Coiffure", ["au hasard"] + P.CHOIX_COIFFURE), ("Barbe", ["aucune"] + P.CHOIX_PILOSITE),
                  ("Accessoire", ["aucun"] + P.CHOIX_ACCESSOIRE), ("Peau", ["au hasard"] + P.CHOIX_PEAU),
                  ("Vêtement", ["au hasard"] + P.CHOIX_VETEMENT)]
        for i, (nom, valeurs) in enumerate(champs):
            ttk.Label(form, text=nom).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 8))
            v = tk.StringVar(value=valeurs[0])
            ttk.Combobox(form, textvariable=v, values=valeurs, state="readonly", width=20).grid(row=i, column=1)
            v.trace_add("write", lambda *a: self._apercu_perso())
            self.v_p[nom] = v
        ttk.Button(form, text="Autre tirage", command=self._autre_tirage).grid(row=len(champs), column=1,
                                                                              sticky="w", pady=8)
        self._tirage = 0
        self.lbl_perso = ttk.Label(form, text="", foreground="#555", wraplength=260, justify="left")
        self.lbl_perso.grid(row=len(champs) + 1, column=0, columnspan=2, sticky="w")
        self.canvas_perso = tk.Canvas(self.cadre_perso, width=320, height=320, background="white",
                                      highlightthickness=0)
        self.canvas_perso.pack(side="right", padx=10)

        # --- bas : pastille et validation -------------------------------------
        bas = ttk.Frame(self, padding=8)
        bas.pack(fill="x", side="bottom")
        self.lbl = ttk.Label(bas, text="Cliquez sur un visuel, puis « Choisir » (ou double-clic).")
        self.lbl.pack(side="left")
        ttk.Button(bas, text="Annuler", command=self.destroy).pack(side="right")
        self.b_ok = ttk.Button(bas, text="Choisir", command=self._valider, state="disabled")
        self.b_ok.pack(side="right", padx=6)
        self.v_pastille = tk.StringVar(value="sans pastille")
        noms_p = ["sans pastille", "ok", "non", "attention", "question", "plus", "moins", "etoile", "coeur",
                  "hausse", "baisse"]
        ttk.Combobox(bas, textvariable=self.v_pastille, values=[n for n in noms_p if n == noms_p[0] or n in PASTILLES],
                     state="readonly", width=13).pack(side="right", padx=6)
        ttk.Label(bas, text="Pastille").pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._valider())
        self._changer_genre()

    @property
    def _g(self):
        return self.GENRES[self.v_genre.get()]

    def _changer_genre(self):
        SelecteurIcones._dernier_genre = self.v_genre.get()
        self._choix = None
        if self.v_genre.get() == "personne":
            self.cadre_recherche.pack_forget()
            self.cadre_perso.pack(fill="both", expand=True)
            self.lbl_nb.configure(text="584 000 combinaisons")
            self._apercu_perso()
            return
        self.cadre_perso.pack_forget()
        self.cadre_recherche.pack(fill="both", expand=True)
        self.champ.focus_set()
        self.combo_cat.configure(values=["Toutes les catégories"] + self._g[3]())
        self.v_cat.set("Toutes les catégories")
        self.b_ok.configure(state="disabled")
        self._planifier(10)

    # --- personnages -----------------------------------------------------------
    def _description_perso(self) -> str:
        mots = []
        for nom, v in self.v_p.items():
            val = v.get()
            if val and not val.startswith(("au hasard", "aucun")):
                mots.append(val)
        if self._tirage:
            mots.append(f"tirage {self._tirage}")
        return "personne:" + ",".join(mots)

    def _autre_tirage(self):
        self._tirage += 1
        self._apercu_perso()

    def _apercu_perso(self):
        from .vecteur import charger_vecteur, rendre_vecteur
        desc = self._description_perso()
        try:
            r = rendre_vecteur(charger_vecteur(desc), 300, 300, 2, 4, (255, 255, 255), (30, 30, 30))
        except Exception as e:  # noqa: BLE001
            self.lbl_perso.configure(text=f"Erreur : {e}")
            return
        from PIL import Image
        img = Image.fromarray(r.finale) if r.finale is not None else Image.new("RGB", (300, 300), "white")
        self._img_perso = ImageTk.PhotoImage(img)
        self.canvas_perso.delete("all")
        self.canvas_perso.create_image(160, 160, image=self._img_perso)
        self._choix = desc
        self.b_ok.configure(state="normal")
        self.lbl.configure(text=desc)
        self.lbl_perso.configure(text="Compris : " + self.P.description_lisible(desc))

    # --- cliparts et icônes ---------------------------------------------------
    def _planifier(self, delai: int = 250):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(delai, self._rechercher)

    def _rechercher(self):
        self._job = None
        if self.v_genre.get() == "personne":
            return
        cat = self.v_cat.get()
        cat = "" if cat.startswith("Toutes") else cat
        self._noms = self._g[2](self.v_req.get(), cat, limite=self.MAX)
        self.lbl_nb.configure(text=f"{len(self._noms)}{'+' if len(self._noms) == self.MAX else ''} résultat(s)")
        self._gen += 1
        self.canvas.delete("all")
        self.canvas.yview_moveto(0)
        pas = self.TAILLE + 22
        lignes = (len(self._noms) + self.PAR_LIGNE - 1) // self.PAR_LIGNE
        self.canvas.configure(scrollregion=(0, 0, pas * self.PAR_LIGNE, lignes * (pas + 8) + 10))
        if not self._noms:
            self.canvas.create_text(20, 20, anchor="nw", text="Aucun résultat.", fill="#666")
        self._afficher(0, self._gen)

    def _afficher(self, debut, gen):
        if gen != self._gen or not self.winfo_exists() or self.v_genre.get() == "personne":
            return
        pas = self.TAILLE + 22
        genre, vignette = self.v_genre.get(), self._g[4]
        for i in range(debut, min(debut + 30, len(self._noms))):
            nom = self._noms[i]
            cle = f"{genre}:{nom}"
            if cle not in self._images:
                self._images[cle] = ImageTk.PhotoImage(vignette(nom, self.TAILLE))
            x = (i % self.PAR_LIGNE) * pas + pas / 2 + 4
            y = (i // self.PAR_LIGNE) * (pas + 8) + self.TAILLE / 2 + 10
            tag = f"i{i}"
            self.canvas.create_rectangle(x - pas / 2 + 2, y - self.TAILLE / 2 - 6, x + pas / 2 - 2,
                                         y + self.TAILLE / 2 + 22, outline="", fill="white", tags=(tag, "fond"))
            self.canvas.create_image(x, y, image=self._images[cle], tags=(tag,))
            court = nom if len(nom) <= 12 else nom[:11] + "…"
            self.canvas.create_text(x, y + self.TAILLE / 2 + 10, text=court, font=("Segoe UI", 8),
                                    fill="#555", tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda e, n=nom, t=tag: self._selectionner(n, t))
            self.canvas.tag_bind(tag, "<Double-Button-1>", lambda e, n=nom: (self._selectionner(n, None), self._valider()))
        if debut + 30 < len(self._noms):
            self.after(1, self._afficher, debut + 30, gen)

    def _selectionner(self, nom, tag):
        self._choix = self._g[1] + nom
        self.canvas.itemconfigure("fond", fill="white")
        if tag:
            for item in self.canvas.find_withtag(tag):
                if "fond" in self.canvas.gettags(item):
                    self.canvas.itemconfigure(item, fill="#dbe8fb")
        self.lbl.configure(text=f"Choix : {nom}")
        self.b_ok.configure(state="normal")

    def _valider(self):
        if self._choix:
            source = self._choix
            if self.v_pastille.get() != "sans pastille":
                source += "+" + self.v_pastille.get()
            self.destroy()
            self.rappel(source)


def lancer(chemin_projet: str | None = None) -> None:
    if chemin_projet is None and len(sys.argv) > 1 and sys.argv[1].lower().endswith(".json"):
        chemin_projet = sys.argv[1]
    if sys.platform == "win32":
        try:  # textes nets sur les écrans haute résolution
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    Application(chemin_projet).mainloop()
