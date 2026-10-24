export const ACCEPTED_FORMATS = [
  { extension: '.pdf', label: 'PDF' },
  { extension: '.docx', label: 'DOCX' },
  { extension: '.txt', label: 'TXT' },
  { extension: '.csv', label: 'CSV' },
] as const

export const MAX_ATTACHMENTS = 5
export const MAX_FILE_BYTES = 25 * 1024 * 1024

export const ACCEPT_ATTRIBUTE = ACCEPTED_FORMATS.map((format) => format.extension).join(',')

export const ACCEPTED_FORMATS_LABEL = new Intl.ListFormat('en', { type: 'disjunction' }).format(
  ACCEPTED_FORMATS.map((format) => format.label),
)

export interface Attachment {
  id: string
  file: File
}

function attachmentId(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

function hasAcceptedExtension(name: string) {
  const lower = name.toLowerCase()
  return ACCEPTED_FORMATS.some((format) => lower.endsWith(format.extension))
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${Number((bytes / (1024 * 1024)).toFixed(1))} MB`
}

/**
 * Adds files to the current list. The `accept` attribute is only a hint to the
 * file picker, so formats and sizes are checked again here. Duplicates are skipped.
 */
export function addAttachments(current: Attachment[], incoming: File[]) {
  const attachments = [...current]
  const problems: string[] = []

  for (const file of incoming) {
    const id = attachmentId(file)
    if (attachments.some((attachment) => attachment.id === id)) continue

    if (!hasAcceptedExtension(file.name)) {
      problems.push(`${file.name} isn't a supported format. Use ${ACCEPTED_FORMATS_LABEL}.`)
    } else if (file.size > MAX_FILE_BYTES) {
      problems.push(`${file.name} is larger than ${formatBytes(MAX_FILE_BYTES)}.`)
    } else if (attachments.length >= MAX_ATTACHMENTS) {
      problems.push(`You can attach up to ${MAX_ATTACHMENTS} files.`)
      break
    } else {
      attachments.push({ id, file })
    }
  }

  return { attachments, problems }
}
