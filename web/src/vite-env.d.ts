/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  /** Supabase publishable key (sb_publishable_...); the name predates the new key format. */
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_DEV_AUTH?: string;
  /** Public contact address for the footer and legal pages. */
  readonly VITE_CONTACT_EMAIL?: string;
}
