// Small shared UI pieces.

import { useEffect, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link, type LinkProps } from "react-router";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-600 text-white shadow-sm shadow-brand-600/20 hover:bg-brand-700 disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none",
  secondary:
    "border border-slate-300 bg-white text-slate-800 shadow-sm hover:border-slate-400 hover:bg-slate-50 disabled:text-slate-400",
  danger: "text-rose-700 hover:bg-rose-50",
  ghost: "text-slate-700 hover:bg-slate-100",
};

const SIZES: Record<Size, string> = {
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-3 text-base",
};

export function buttonClass(variant: Variant = "primary", size: Size = "md", className = "") {
  return `inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${SIZES[size]} ${className}`;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return <button type="button" className={buttonClass(variant, size, className)} {...props} />;
}

/** A link styled as a button. */
export function ButtonLink({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: LinkProps & { variant?: Variant; size?: Size }) {
  return <Link className={buttonClass(variant, size, className)} {...props} />;
}

export function Card({ title, children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5 ${className}`}>
      {title && <h2 className="mb-3 text-base font-semibold text-slate-900">{title}</h2>}
      {children}
    </section>
  );
}

/** Page width and side padding, the same on every page. */
export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8 ${className}`}>{children}</div>;
}

/** The small label above a section heading. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">{children}</p>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="mt-2 text-sm text-rose-700">
      {message}
    </p>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-600" role="status">
      <span
        aria-hidden
        className="h-4 w-4 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600"
      />
      {label}
    </span>
  );
}

const SITE = "MakeMyEXE";

/** Title and description of the current page, for the browser tab and link previews. */
export function usePageMeta(title: string | null, description?: string) {
  useEffect(() => {
    document.title = title ? `${title} · ${SITE}` : `${SITE} · Windows automations that run offline`;
    if (description) {
      document.querySelector('meta[name="description"]')?.setAttribute("content", description);
    }
  }, [title, description]);
}
