/**
 * Small molecule drawings used as tsParticles image shapes. Each molecule is one
 * image, so its atoms and bonds drift and rotate together as a single body.
 * Drawn on a 120 × 120 canvas centred on (60, 60); the glow is a soft radial halo
 * baked into each atom because tsParticles v4 has no particle shadow.
 */

type Tone = 'blue' | 'cyan' | 'white'

interface Atom {
  x: number
  y: number
  r: number
  tone: Tone
}

interface Molecule {
  name: string
  atoms: Atom[]
  /** Pairs of atom indexes; a third value of 2 draws a double bond */
  bonds: [number, number, (1 | 2)?][]
}

const TONES: Record<Tone, { core: string; light: string }> = {
  blue: { core: '#5aa2ff', light: '#b9d8ff' },
  cyan: { core: '#5fd8ee', light: '#c4f3fb' },
  white: { core: '#dfe9f7', light: '#ffffff' },
}

const BOND_COLOUR = 'rgba(214, 230, 255, 0.55)'

const polar = (angleDeg: number, distance: number, cx = 60, cy = 60) => {
  const a = (angleDeg * Math.PI) / 180
  return { x: cx + Math.cos(a) * distance, y: cy + Math.sin(a) * distance }
}

const ring = (count: number, radius: number, r: number, tones: Tone[], startDeg = -90): Atom[] =>
  Array.from({ length: count }, (_, i) => ({
    ...polar(startDeg + (360 / count) * i, radius),
    r,
    tone: tones[i % tones.length],
  }))

const MOLECULES: Molecule[] = [
  {
    // Benzene-like ring with alternating double bonds
    name: 'ring6',
    atoms: ring(6, 26, 4.2, ['cyan']),
    bonds: [[0, 1, 2], [1, 2], [2, 3, 2], [3, 4], [4, 5, 2], [5, 0]],
  },
  {
    // Bent three-atom molecule, water-like
    name: 'bent',
    atoms: [
      { x: 60, y: 54, r: 6.5, tone: 'blue' },
      { ...polar(142, 24, 60, 54), r: 4, tone: 'white' },
      { ...polar(38, 24, 60, 54), r: 4, tone: 'white' },
    ],
    bonds: [[0, 1], [0, 2]],
  },
  {
    // Tetrahedral centre seen in projection; the fourth arm sits further back
    name: 'tetra',
    atoms: [
      { x: 60, y: 60, r: 6, tone: 'blue' },
      { ...polar(-90, 26), r: 3.8, tone: 'white' },
      { ...polar(30, 26), r: 3.8, tone: 'white' },
      { ...polar(150, 26), r: 3.8, tone: 'white' },
      { ...polar(95, 14), r: 3, tone: 'cyan' },
    ],
    bonds: [[0, 1], [0, 2], [0, 3], [0, 4]],
  },
  {
    // Zigzag chain
    name: 'chain',
    atoms: [
      { x: 18, y: 68, r: 4, tone: 'cyan' },
      { x: 39, y: 52, r: 4.6, tone: 'blue' },
      { x: 60, y: 68, r: 4.6, tone: 'blue' },
      { x: 81, y: 52, r: 4.6, tone: 'blue' },
      { x: 102, y: 68, r: 4, tone: 'cyan' },
    ],
    bonds: [[0, 1], [1, 2], [2, 3, 2], [3, 4]],
  },
  {
    // Linear, CO2-like
    name: 'linear',
    atoms: [
      { x: 30, y: 60, r: 5, tone: 'blue' },
      { x: 60, y: 60, r: 4.4, tone: 'white' },
      { x: 90, y: 60, r: 5, tone: 'blue' },
    ],
    bonds: [[0, 1, 2], [1, 2, 2]],
  },
  {
    // Five-membered ring with one side group
    name: 'ring5',
    atoms: [
      ...ring(5, 20, 4, ['blue', 'cyan', 'cyan', 'cyan', 'cyan'], -90),
      { ...polar(-90, 42), r: 3.6, tone: 'white' },
    ],
    bonds: [[0, 1], [1, 2, 2], [2, 3], [3, 4, 2], [4, 0], [0, 5]],
  },
  {
    // Diatomic
    name: 'pair',
    atoms: [
      { x: 47, y: 60, r: 5.2, tone: 'cyan' },
      { x: 73, y: 60, r: 5.2, tone: 'cyan' },
    ],
    bonds: [[0, 1, 2]],
  },
]

function bondLines(a: Atom, b: Atom, order: 1 | 2) {
  const line = (dx: number, dy: number) =>
    `<line x1="${(a.x + dx).toFixed(2)}" y1="${(a.y + dy).toFixed(2)}" x2="${(b.x + dx).toFixed(2)}" y2="${(b.y + dy).toFixed(2)}"/>`
  if (order === 1) return line(0, 0)
  // Offset the two strokes perpendicular to the bond
  const len = Math.hypot(b.x - a.x, b.y - a.y)
  const nx = (-(b.y - a.y) / len) * 1.7
  const ny = ((b.x - a.x) / len) * 1.7
  return line(nx, ny) + line(-nx, -ny)
}

function toSvg({ atoms, bonds }: Molecule) {
  const gradients = (Object.keys(TONES) as Tone[])
    .map((tone) => {
      const { core, light } = TONES[tone]
      return (
        `<radialGradient id="h-${tone}"><stop offset="0" stop-color="${core}" stop-opacity="0.45"/><stop offset="1" stop-color="${core}" stop-opacity="0"/></radialGradient>` +
        `<radialGradient id="c-${tone}" cx="0.38" cy="0.35" r="0.7"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${core}"/></radialGradient>`
      )
    })
    .join('')

  const bondMarkup = bonds.map(([i, j, order = 1]) => bondLines(atoms[i], atoms[j], order)).join('')
  const halos = atoms.map((a) => `<circle cx="${a.x.toFixed(2)}" cy="${a.y.toFixed(2)}" r="${(a.r * 2.8).toFixed(2)}" fill="url(#h-${a.tone})"/>`).join('')
  const cores = atoms.map((a) => `<circle cx="${a.x.toFixed(2)}" cy="${a.y.toFixed(2)}" r="${a.r}" fill="url(#c-${a.tone})"/>`).join('')

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">` +
    `<defs>${gradients}</defs>${halos}` +
    `<g stroke="${BOND_COLOUR}" stroke-width="1.4" stroke-linecap="round">${bondMarkup}</g>${cores}</svg>`
  )
}

export const MOLECULE_IMAGES = MOLECULES.map((molecule) => ({
  name: molecule.name,
  src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(toSvg(molecule))}`,
  width: 120,
  height: 120,
}))
