"""Projet de démonstration : illustrations originales dessinées par le programme."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from .projet import Projet, Scene

NOIR = (30, 30, 30)
E = 9  # épaisseur des traits


def _ampoule(chemin: Path) -> None:
    img = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((250, 170, 650, 570), fill=(255, 214, 70), outline=NOIR, width=E)
    d.polygon([(330, 520), (570, 520), (530, 640), (370, 640)], fill=(255, 214, 70))
    d.line([(330, 520), (370, 640)], fill=NOIR, width=E)
    d.line([(570, 520), (530, 640)], fill=NOIR, width=E)
    d.rectangle((365, 640, 535, 740), fill=(170, 170, 178), outline=NOIR, width=E)
    for y in (673, 706):
        d.line([(365, y), (535, y)], fill=NOIR, width=E - 3)
    d.chord((400, 715, 500, 800), 0, 180, fill=(120, 120, 128), outline=NOIR, width=E)
    d.line([(400, 520), (430, 430), (450, 480), (470, 430), (500, 520)], fill=NOIR, width=E - 2, joint="curve")
    d.arc((310, 230, 470, 390), 190, 260, fill=(255, 250, 225), width=E + 6)
    for k in range(9):
        a = math.radians(-180 + k * 22.5)
        x0, y0 = 450 + 255 * math.cos(a), 370 + 255 * math.sin(a)
        x1, y1 = 450 + 330 * math.cos(a), 370 + 330 * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=(240, 160, 30), width=E + 2)
        d.line([(x0, y0), (x1, y1)], fill=NOIR, width=3)
    img.save(chemin)


def _engrenage(d: ImageDraw.ImageDraw, cx, cy, r, dents, teinte, decal=0.0):
    pts = []
    for i in range(dents * 4):
        a = 2 * math.pi * i / (dents * 4) + decal
        rr = r * (1.0 if (i % 4) in (1, 2) else 0.80)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=teinte)
    d.line(pts + [pts[0]], fill=NOIR, width=E, joint="curve")
    d.ellipse((cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42), fill=(250, 250, 250), outline=NOIR, width=E)
    d.ellipse((cx - r * 0.14, cy - r * 0.14, cx + r * 0.14, cy + r * 0.14), fill=NOIR)


def _engrenages(chemin: Path) -> None:
    img = Image.new("RGBA", (1200, 760), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _engrenage(d, 400, 400, 280, 12, (88, 150, 220))
    _engrenage(d, 800, 260, 190, 9, (240, 120, 90), decal=0.17)
    _engrenage(d, 880, 590, 140, 8, (110, 190, 120), decal=0.35)
    img.save(chemin)


def _graphique(chemin: Path) -> None:
    img = Image.new("RGBA", (1200, 800), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(120, 60), (120, 700), (1120, 700)], fill=NOIR, width=E, joint="curve")
    d.polygon([(105, 70), (120, 40), (135, 70)], fill=NOIR)
    d.polygon([(1110, 685), (1140, 700), (1110, 715)], fill=NOIR)
    teintes = [(170, 205, 240), (120, 175, 230), (80, 145, 215), (45, 110, 190)]
    for i, h in enumerate((160, 280, 400, 540)):
        x = 220 + i * 220
        d.rectangle((x, 700 - h, x + 140, 700), fill=teintes[i], outline=NOIR, width=E)
    pts = [(240, 470), (470, 380), (690, 300), (880, 160), (1000, 110)]
    d.line(pts, fill=(220, 60, 60), width=E + 4, joint="curve")
    d.polygon([(985, 70), (1060, 85), (1015, 145)], fill=(220, 60, 60))
    img.save(chemin)


def _cloche(chemin: Path) -> None:
    img = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bas_droite = (640, 590)
    corps = [(400, 150), (470, 165), (530, 220), (560, 320), (575, 450), (600, 540), bas_droite,
             (160, 590), (200, 540), (225, 450), (240, 320), (270, 220), (330, 165)]
    d.polygon(corps, fill=(255, 196, 60))
    d.line(corps + [corps[0]], fill=NOIR, width=E, joint="curve")
    d.ellipse((365, 110, 435, 160), fill=(255, 196, 60), outline=NOIR, width=E)
    d.chord((340, 560, 460, 680), 0, 180, fill=(255, 196, 60), outline=NOIR, width=E)
    d.line([(160, 590), (640, 590)], fill=NOIR, width=E)
    for s in (-1, 1):
        cx = 400 + s * 300
        d.arc((cx - 60, 220, cx + 60, 460), 300 if s > 0 else 120, 60 if s > 0 else 240, fill=NOIR, width=E)
    img.save(chemin)


FUSEE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">
  <defs>
    <linearGradient id="flamme" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd23f"/><stop offset="1" stop-color="#ff6b35"/>
    </linearGradient>
  </defs>
  <g stroke="#1e1e1e" stroke-width="7" stroke-linejoin="round" stroke-linecap="round">
    <path d="M200 330 C175 360 185 385 200 395 C215 385 225 360 200 330 Z" fill="url(#flamme)"/>
    <path d="M150 250 L105 300 L110 330 L160 300 Z" fill="#e63946"/>
    <path d="M250 250 L295 300 L290 330 L240 300 Z" fill="#e63946"/>
    <path d="M200 30 C260 80 270 190 250 300 L150 300 C130 190 140 80 200 30 Z" fill="#f1faee"/>
    <path d="M168 300 L232 300 L222 330 L178 330 Z" fill="#a8a8b3"/>
    <circle cx="200" cy="150" r="32" fill="#a8dadc"/>
    <circle cx="200" cy="150" r="17" fill="#457b9d"/>
    <path d="M185 75 C192 66 208 66 215 75" fill="none"/>
    <path d="M200 255 L200 300" fill="none"/>
  </g>
  <g fill="#1e1e1e" stroke="none">
    <circle cx="70" cy="80" r="6"/><circle cx="330" cy="60" r="5"/><circle cx="345" cy="190" r="7"/>
    <circle cx="55" cy="210" r="5"/>
  </g>
</svg>
"""


def creer_demo(dossier: str | Path) -> Path:
    """Crée images + projet de démonstration ; renvoie le chemin du projet."""
    dossier = Path(dossier)
    images = dossier / "images"
    images.mkdir(parents=True, exist_ok=True)
    _ampoule(images / "ampoule.png")
    (images / "fusee.svg").write_text(FUSEE_SVG, encoding="utf-8")
    p = Projet(scenes=[
        Scene(modele="titre", titre="Une idée en 3 étapes", texte="La méthode expliquée simplement",
              image="clipart:ampoule", duree_dessin=4.0, pause=1.5),
        Scene(modele="personnage", image="personne:femme,pensive,lunettes,bleu",
              texte="[clipart:ampoule] Et si je lançais mon projet ?", duree_dessin=6.0, pause=2.0),
        Scene(titre="1. Avoir l'idée", image=str(images / "ampoule.png"),
              texte="Tout commence par une étincelle", duree_dessin=5.0, pause=1.5),
        Scene(modele="etapes", titre="2. Construire",
              texte="[clipart:crayon] Dessiner\n[clipart:boite-a-outils] Assembler\n[clipart:coche] Tester",
              duree_dessin=6.0, pause=2.0),
        Scene(titre="3. Lancer", image=str(images / "fusee.svg"), texte="Et le projet décolle !",
              duree_dessin=4.5, pause=1.5),
        Scene(modele="comparaison", titre="Seule ou en équipe ?",
              texte="[personne:femme,lunettes,bleu,débordée] Seule\n[personne:femme,lunettes,bleu,heureuse] En équipe",
              duree_dessin=6.5, pause=2.0),
        Scene(modele="graphique", titre="Utilisateurs (exemple)",
              texte="Mois 1 : 120\nMois 2 : 450\nMois 3 : 1 300", duree_dessin=5.0, pause=2.0),
        Scene(modele="chronologie", titre="Le calendrier",
              texte="[clipart:ampoule] Janvier : l'idée\n[clipart:boite-a-outils] Mars : le prototype\n"
                    "[clipart:fusee] Juin : le lancement", duree_dessin=6.0, pause=2.0),
        Scene(modele="liste", titre="À retenir",
              texte="[clipart:dans-le-mille+ok] Partir d'un vrai problème\n"
                    "[clipart:telephone-portable+non] Éviter les distractions\n"
                    "[clipart:coeur-rouge] Garder le plaisir", duree_dessin=5.5, pause=2.0),
        Scene(modele="fin", titre="Merci d'avoir regardé !", duree_dessin=4.0, pause=2.0),
    ])
    chemin = dossier / "demo.json"
    p.enregistrer(chemin)
    return chemin
