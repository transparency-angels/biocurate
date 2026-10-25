import { useEffect, useState } from 'react'
import { Dialog } from 'radix-ui'
import { Menu, X } from 'lucide-react'
import { BioCurateWordmark } from '@/components/brand/BioCurateWordmark'
import { Button } from '@/components/ui/button'
import { SidebarNav } from './SidebarNav'

// Matches Tailwind's `md` breakpoint, where the permanent sidebar takes over
const DESKTOP_QUERY = '(min-width: 48rem)'

/** Menu button and slide-in navigation drawer for phones. */
export function MobileNav() {
  const [open, setOpen] = useState(false)

  // Close the drawer if the window grows past the phone layout while it is open,
  // so a hidden dialog never keeps the page scroll-locked
  useEffect(() => {
    if (!open) return
    const query = window.matchMedia(DESKTOP_QUERY)
    const close = () => {
      if (query.matches) setOpen(false)
    }
    query.addEventListener('change', close)
    return () => query.removeEventListener('change', close)
  }, [open])

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button
          variant="ghost"
          size="icon-lg"
          className="-ml-2 size-11 text-muted-foreground hover:text-foreground md:hidden [&_svg:not([class*='size-'])]:size-5"
          aria-label="Open navigation"
        >
          <Menu />
        </Button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70 motion-safe:data-[state=closed]:animate-out motion-safe:data-[state=closed]:fade-out motion-safe:data-[state=open]:animate-in motion-safe:data-[state=open]:fade-in" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 left-0 z-50 flex w-[min(18rem,85vw)] flex-col border-r border-border bg-background outline-none motion-safe:duration-200 motion-safe:data-[state=closed]:animate-out motion-safe:data-[state=closed]:slide-out-to-left motion-safe:data-[state=open]:animate-in motion-safe:data-[state=open]:slide-in-from-left"
        >
          <Dialog.Title className="sr-only">Navigation</Dialog.Title>
          <div className="flex h-14 shrink-0 items-center justify-between pr-2 pl-5">
            <span className="text-[1.0625rem]" aria-hidden="true">
              <BioCurateWordmark />
            </span>
            <Dialog.Close asChild>
              <Button
                variant="ghost"
                size="icon-lg"
                className="size-11 text-muted-foreground hover:text-foreground [&_svg:not([class*='size-'])]:size-5"
                aria-label="Close navigation"
              >
                <X />
              </Button>
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-2">
            <SidebarNav onNavigate={() => setOpen(false)} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
