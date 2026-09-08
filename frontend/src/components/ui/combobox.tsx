import * as React from "react"
import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox"

import { cn } from "@/lib/utils"
import { LuCheck, LuX } from "react-icons/lu"

export interface MultiComboboxItem {
  value: string
  label: string
}

export interface MultiComboboxProps {
  items: MultiComboboxItem[]
  value: string[]
  onValueChange: (value: string[]) => void
  /** 入力テキストの変更通知(部分一致フィルタ等の外部利用向け) */
  onInputValueChange?: (inputValue: string) => void
  placeholder?: string
  className?: string
  ariaLabel?: string
}

/**
 * 複数選択コンボボックス(@base-ui/react v1.5 の Combobox 部品のラッパー)。
 * 選択値はx付きピル(Chips/Chip/ChipRemove)で表示し、入力欄はピルと同じ行に置く。
 * ポップアップの項目は items を label 部分一致で絞り込む。
 * 候補が0件のときは Popup(とEmpty表示)を render しない(設計doc §6)。
 */
function MultiCombobox({
  items,
  value,
  onValueChange,
  onInputValueChange,
  placeholder,
  className,
  ariaLabel,
}: MultiComboboxProps) {
  const [inputValue, setInputValue] = React.useState("")
  const itemByValue = React.useMemo(
    () => new Map(items.map((item) => [item.value, item])),
    [items],
  )
  const valueIds = React.useMemo(() => items.map((item) => item.value), [items])

  const labelOf = (v: string) => itemByValue.get(v)?.label ?? v

  const matches = (label: string, query: string) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return label.toLowerCase().includes(q)
  }
  const hasCandidates = React.useMemo(
    () => items.some((item) => matches(item.label, inputValue)),
    [items, inputValue],
  )

  return (
    <div className={cn("w-full", className)}>
      <ComboboxPrimitive.Root<string, true>
        multiple
        items={valueIds}
        value={value}
        onValueChange={(next) => {
          onValueChange(next ?? [])
        }}
        onInputValueChange={(inputValue) => {
          setInputValue(inputValue)
          onInputValueChange?.(inputValue)
        }}
        filter={(v, query) => {
          const q = query.trim().toLowerCase()
          if (!q) return true
          return labelOf(v).toLowerCase().includes(q)
        }}
      >
        <ComboboxPrimitive.Chips
          aria-label={ariaLabel}
          className={cn(
            "flex min-h-9 w-full flex-wrap items-center gap-1 rounded-lg border border-border",
            "bg-white/[0.04] px-2 py-1 text-sm text-text outline-none",
            "focus-within:border-primary",
          )}
        >
          {value.map((v) => (
            <ComboboxPrimitive.Chip
              key={v}
              aria-label={labelOf(v)}
              aria-description="Backspaceまたはxで削除"
              className={cn(
                "inline-flex h-5 max-w-full items-center gap-0.5 rounded-full bg-primary/25 pl-2 pr-1",
                "text-[10px] font-medium text-text select-none",
              )}
            >
              <span className="truncate">{labelOf(v)}</span>
              <ComboboxPrimitive.ChipRemove
                aria-label={`${labelOf(v)}を削除`}
                className="flex size-3.5 shrink-0 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-white/10 hover:text-text"
              >
                <LuX className="size-2.5" />
              </ComboboxPrimitive.ChipRemove>
            </ComboboxPrimitive.Chip>
          ))}
          <ComboboxPrimitive.Input
            placeholder={placeholder}
            className="min-w-16 flex-1 bg-transparent text-xs text-text outline-none placeholder:text-text-muted"
          />
        </ComboboxPrimitive.Chips>

        {/* 候補0件のときはポップアップ自体を表示しない(§6) */}
        {hasCandidates && (
          <ComboboxPrimitive.Portal>
            <ComboboxPrimitive.Positioner
              sideOffset={6}
              align="start"
              className="z-[9999] isolate"
            >
              <ComboboxPrimitive.Popup
                className={cn(
                  "max-h-64 min-w-44 overflow-y-auto rounded-lg border border-border bg-panel",
                  "p-1 text-sm shadow-lg backdrop-blur-glass",
                )}
              >
                <ComboboxPrimitive.List className="flex flex-col gap-0.5 outline-none">
                  {(v: string) => (
                    <ComboboxPrimitive.Item
                      key={v}
                      value={v}
                      className={cn(
                        "flex cursor-default items-center gap-1.5 rounded-md px-2 py-1 text-xs",
                        "text-text-muted outline-none select-none data-highlighted:bg-white/[0.06] data-highlighted:text-text",
                      )}
                    >
                      <span className="flex-1 truncate">{labelOf(v)}</span>
                      <ComboboxPrimitive.ItemIndicator
                        render={
                          <span className="flex size-3.5 shrink-0 items-center justify-center" />
                        }
                      >
                        <LuCheck className="size-3 text-primary" />
                      </ComboboxPrimitive.ItemIndicator>
                    </ComboboxPrimitive.Item>
                  )}
                </ComboboxPrimitive.List>
              </ComboboxPrimitive.Popup>
            </ComboboxPrimitive.Positioner>
          </ComboboxPrimitive.Portal>
        )}
      </ComboboxPrimitive.Root>
    </div>
  )
}

export { MultiCombobox }
