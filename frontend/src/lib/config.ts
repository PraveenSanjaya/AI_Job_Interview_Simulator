/** Base URL of the backend API. Only a public URL belongs here: never put secrets in the frontend. */
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1';
