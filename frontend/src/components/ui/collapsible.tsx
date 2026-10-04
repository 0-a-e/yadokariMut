import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible"

import { cn } from "@/lib/utils.ts"

function Collapsible({ ...props }: CollapsiblePrimitive.Root.Props) {
  return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

function CollapsibleTrigger({ ...props }: CollapsiblePrimitive.Trigger.Props) {
  return (
    <CollapsiblePrimitive.Trigger data-slot="collapsible-trigger" {...props} />
  )
}

function CollapsibleContent({ ...props }: CollapsiblePrimitive.Panel.Props) {
  return (
    <CollapsiblePrimitive.Panel
      data-slot="collapsible-content"
      // 開閉アニメ(base-uiの高さ変数。アイドル時は変数が外れて auto 高に戻るため
      // 開いている間の内容量変化にも追従する)。閉じ完了後はアンマウントされる
      className={cn(
        'h-[var(--collapsible-panel-height)] overflow-hidden',
        'transition-[height] duration-300 ease-out',
        'data-[starting-style]:h-0 data-[ending-style]:h-0',
        props.className,
      )}
      {...props}
    />
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
