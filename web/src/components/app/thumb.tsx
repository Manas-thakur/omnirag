import * as React from "react"
import { ImageOffIcon } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { rawUrl } from "@/lib/store"
import { cn } from "@/lib/utils"

/** An image document's original file, fetched with the API key and shown inline. */
export function Thumb({ kb, docId, alt = "", className }: { kb: string; docId: string; alt?: string; className?: string }) {
  const [state, setState] = React.useState<{ key: string; url: string | null; failed: boolean }>({
    key: "",
    url: null,
    failed: false,
  })
  const key = `${kb}/${docId}`
  React.useEffect(() => {
    let live = true
    rawUrl(kb, docId).then(
      (url) => live && setState({ key, url, failed: false }),
      () => live && setState({ key, url: null, failed: true }),
    )
    return () => {
      live = false
    }
  }, [kb, docId, key])
  const current = state.key === key ? state : { url: null, failed: false }
  if (current.failed)
    return (
      <span className={cn("flex items-center justify-center bg-muted text-muted-foreground", className)}>
        <ImageOffIcon className="size-4" aria-hidden="true" />
        <span className="sr-only">Image unavailable</span>
      </span>
    )
  if (!current.url) return <Skeleton className={className} />
  // Diagrams usually assume a white page, so images sit on white in both themes.
  return <img src={current.url} alt={alt} decoding="async" className={cn("object-contain", className, "bg-white")} />
}
