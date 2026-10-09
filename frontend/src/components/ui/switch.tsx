import { Switch as SwitchPrimitive } from "@base-ui/react/switch"

import { cn } from "@/lib/utils.ts"

function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors outline-none",
        "focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "data-checked:border-primary data-checked:bg-primary/70 data-unchecked:border-border data-unchecked:bg-white/[0.06]",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="inline-block size-3.5 rounded-full bg-white shadow transition-transform data-checked:translate-x-[18px] data-unchecked:translate-x-[3px]"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
