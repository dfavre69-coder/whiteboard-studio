// Extrait les pièces des personnages Open Peeps (Pablo Stanley, CC0) depuis le paquet npm
// @dicebear/open-peeps, et les enregistre en JSON pour Whiteboard Studio.
//
//   npm pack @dicebear/open-peeps && tar -xzf dicebear-open-peeps-*.tgz
//   node outils/construire_personnages.mjs chemin/package
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const source = path.resolve(process.argv[2] || 'package');
const lib = path.join(source, 'lib');
// @dicebear/core n'est utile que pour escape.xml : on le remplace par une version minimale
const faux = path.join(source, 'node_modules', '@dicebear', 'core');
fs.mkdirSync(faux, { recursive: true });
fs.writeFileSync(path.join(faux, 'package.json'), JSON.stringify({ name: '@dicebear/core', type: 'module', main: 'index.js' }));
fs.writeFileSync(path.join(faux, 'index.js'), "export const escape = { xml: (s) => String(s) };\n");

const couleurs = { skin: '{PEAU}', clothing: '{VETEMENT}', headContrast: '{CHEVEUX}' };
const pieces = {};
for (const nom of ['head', 'face', 'facialHair', 'accessories', 'mask']) {
  const module = await import(pathToFileURL(path.join(lib, 'components', `${nom}.js`)).href);
  const variantes = Object.values(module)[0];
  pieces[nom] = Object.fromEntries(Object.entries(variantes).map(([cle, f]) => [cle, f({}, couleurs)]));
}

// Corps (buste) et position de chaque pièce : lus dans le modèle de index.js
const index = fs.readFileSync(path.join(lib, 'index.js'), 'utf8');
let corps = index.split('body: `')[1].split('`,\n        extra')[0];
corps = corps.replace(/\$\{escape\.xml\(`\$\{colors\.(\w+)\}`\)\}/g, (_, c) => couleurs[c]);
corps = corps.replace(/\$\{\(_\w+ = \(_\w+ = components\.(\w+)\)[^}]*?: ''\}/g, (_, c) => `{${c.toUpperCase()}}`);
const vue = (index.match(/viewBox: '([^']+)'/) || [])[1];

const schema = (await import(pathToFileURL(path.join(lib, 'schema.js')).href)).schema.properties;
const sortie = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'whiteboard', 'assets', 'personnages', 'open-peeps.json');
fs.writeFileSync(sortie, JSON.stringify({
  source: 'Open Peeps, Pablo Stanley (CC0 1.0), via @dicebear/open-peeps',
  viewBox: vue,
  corps,
  pieces,
  couleurs: { peau: schema.skinColor.default, vetement: schema.clothingColor.default, cheveux: schema.headContrastColor.default },
}));
console.log(`OK : ${Object.entries(pieces).map(([k, v]) => `${k} ${Object.keys(v).length}`).join(', ')} → ${sortie}`);
