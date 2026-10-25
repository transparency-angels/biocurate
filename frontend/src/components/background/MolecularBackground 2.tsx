import { useMemo } from 'react'
import { Particles, ParticlesProvider } from '@tsparticles/react'
import type { Engine, ISourceOptions } from '@tsparticles/engine'
import { loadSlim } from '@tsparticles/slim'
import { MOLECULE_IMAGES } from './molecules'

const loadEngine = (engine: Engine) => loadSlim(engine)

// The centre column stays nearly clear so the wordmark and composer read first
const MASK =
  'radial-gradient(ellipse 58% 50% at 50% 45%, transparent 25%, #000 92%), linear-gradient(to bottom, #000 65%, transparent)'

// Kept sparse on purpose: the field is a texture at the edges, not a decoration
function moleculeCount(width: number) {
  if (width < 640) return 4
  if (width < 1024) return 6
  return 9
}

function buildOptions(count: number, reduceMotion: boolean): ISourceOptions {
  return {
    fullScreen: { enable: false },
    background: { color: 'transparent' },
    fpsLimit: 60,
    detectRetina: true,
    pauseOnBlur: true,
    pauseOnOutsideViewport: true,
    particles: {
      number: { value: count },
      shape: { type: 'image', options: { image: MOLECULE_IMAGES } },
      // Radius in px; the drawing is twice this. Mostly small, a few larger
      size: { value: { min: 20, max: 44 } },
      opacity: {
        value: { min: 0.28, max: 0.5 },
        animation: { enable: !reduceMotion, speed: 0.08, sync: false, startValue: 'random' },
      },
      rotate: {
        value: { min: 0, max: 360 },
        direction: 'random',
        animation: { enable: !reduceMotion, speed: { min: 0.15, max: 0.6 }, sync: false },
      },
      move: {
        enable: !reduceMotion,
        speed: { min: 0.06, max: 0.18 },
        direction: 'none',
        random: true,
        straight: false,
        outModes: { default: 'out' },
      },
    },
    interactivity: {
      detectsOn: 'window',
      events: {
        onHover: { enable: !reduceMotion, mode: ['parallax', 'repulse'] },
        onClick: { enable: false },
        resize: { enable: true },
      },
      modes: {
        parallax: { force: 40, smooth: 60 },
        repulse: { distance: 110, duration: 1.2, speed: 0.25, factor: 3, maxSpeed: 2, easing: 'ease-out-quad' },
      },
    },
  }
}

/**
 * Decorative molecular field behind the homepage. It never takes pointer events,
 * is hidden from assistive technology, and holds still for reduced motion.
 */
export default function MolecularBackground() {
  const options = useMemo(() => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    return buildOptions(moleculeCount(window.innerWidth), reduceMotion)
  }, [])

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-1000"
      style={{
        // Quieter behind the title and composer, full strength towards the edges,
        // and faded out at the foot so the field never ends on a hard line
        maskImage: MASK,
        WebkitMaskImage: MASK,
        maskComposite: 'intersect',
        WebkitMaskComposite: 'source-in',
      }}
    >
      <ParticlesProvider init={loadEngine}>
        <Particles id="biocurate-molecules" options={options} className="absolute inset-0 size-full" />
      </ParticlesProvider>
    </div>
  )
}
