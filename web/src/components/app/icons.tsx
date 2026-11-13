import { AudioLinesIcon, CodeXmlIcon, FileTextIcon, ImageIcon, Table2Icon, type LucideProps } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Modality } from "@/lib/types"

const ICONS = {
  text: FileTextIcon,
  code: CodeXmlIcon,
  table: Table2Icon,
  image: ImageIcon,
  audio: AudioLinesIcon,
} as const

/** Small colour-coded icon for a content type. */
export function ModalityIcon({ modality, className, ...props }: { modality: Modality | string } & LucideProps) {
  const Icon = ICONS[(modality in ICONS ? modality : "text") as Modality]
  return (
    <Icon
      aria-hidden="true"
      data-modality={modality}
      className={cn(
        "size-3.5 shrink-0",
        {
          text: "text-sky-600 dark:text-sky-400",
          code: "text-violet-600 dark:text-violet-400",
          table: "text-emerald-600 dark:text-emerald-400",
          image: "text-amber-600 dark:text-amber-400",
          audio: "text-rose-600 dark:text-rose-400",
        }[modality as Modality] ?? "text-muted-foreground",
        className,
      )}
      {...props}
    />
  )
}

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-6 shrink-0", className)}>
      <rect width="32" height="32" rx="8" className="fill-brand" />
      <circle cx="16" cy="16" r="7.2" fill="none" className="stroke-brand-foreground" strokeWidth="2.6" />
      <circle cx="16" cy="16" r="2.4" className="fill-brand-foreground" />
      <circle cx="24.6" cy="7.4" r="2" className="fill-brand-foreground/60" />
    </svg>
  )
}
