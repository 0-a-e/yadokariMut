import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * UUID generator that works outside Secure Contexts
 * (e.g. http://192.168.x.x for LAN debugging).
 * crypto.randomUUID() is only available on https / localhost.
 */
let createIdFallbackWarned = false

function warnCreateIdFallback(method: "getRandomValues" | "Math.random"): void {
  if (!import.meta.env.DEV || createIdFallbackWarned) return
  createIdFallbackWarned = true
  console.warn(
    `[createId] crypto.randomUUID() が使えないため ${method} にフォールバックしました。` +
      " Secure Context（https / localhost）以外では randomUUID は利用できません。",
  )
}

export function createId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID()
    } catch {
      /* non-secure context or restricted environment */
    }
  }
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    warnCreateIdFallback("getRandomValues")
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  warnCreateIdFallback("Math.random")
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === "x" ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
