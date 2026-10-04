"use client"

import { Menu as MenuPrimitive } from "@base-ui/react/menu"

import { cn } from "@/lib/utils.ts"

function Menu({ ...props }: MenuPrimitive.Root.Props) {
  return <MenuPrimitive.Root data-slot="menu" {...props} />
}

function MenuTrigger({ ...props }: MenuPrimitive.Trigger.Props) {
  return <MenuPrimitive.Trigger data-slot="menu-trigger" {...props} />
}

function MenuContent({
  className,
  side = "bottom",
  sideOffset = 6,
  align = "end",
  alignOffset = 0,
  children,
  ...props
}: MenuPrimitive.Popup.Props &
  Pick<
    MenuPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset"
  >) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        className="isolate z-[10000]"
      >
        <MenuPrimitive.Popup
          data-slot="menu-content"
          className={cn(
            "z-50 flex w-44 origin-(--transform-origin) flex-col gap-0.5 rounded-lg border border-border bg-panel p-1.5 text-xs text-text shadow-lg backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-in-95",
            className
          )}
          {...props}
        >
          {children}
        </MenuPrimitive.Popup>
      </MenuPrimitive.Positioner>
    </MenuPrimitive.Portal>
  )
}

function MenuItem({ className, ...props }: MenuPrimitive.Item.Props) {
  return (
    <MenuPrimitive.Item
      data-slot="menu-item"
      className={cn(
        "flex cursor-pointer list-none items-center gap-2.5 rounded-md px-2.5 py-2 text-xs text-text outline-none select-none data-highlighted:bg-white/[0.06] data-highlighted:text-text",
        className
      )}
      {...props}
    />
  )
}

export { Menu, MenuTrigger, MenuContent, MenuItem }
