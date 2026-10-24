import { useEffect } from 'react'

const APP_NAME = 'BioCurate AI'

/** Sets the browser tab title. Pass nothing for the plain app name. */
export function useDocumentTitle(page?: string) {
  useEffect(() => {
    document.title = page ? `${page} · ${APP_NAME}` : APP_NAME
  }, [page])
}
