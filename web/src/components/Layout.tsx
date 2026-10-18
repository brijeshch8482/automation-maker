import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { useAuth } from "../auth";
import { contactEmail } from "../env";
import { Close, Menu } from "./icons";
import Logo, { LogoMark } from "./Logo";
import { ButtonLink, Container } from "./ui";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "text-brand-700" : "text-slate-600 hover:text-slate-900"
  }`;

const mobileNavClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded-lg px-3 py-2.5 text-base font-medium ${
    isActive ? "bg-brand-50 text-brand-700" : "text-slate-700 hover:bg-slate-50"
  }`;

const NAV = [
  { to: "/automations", label: "Automations" },
  { to: "/#how-it-works", label: "How it works" },
  { to: "/custom", label: "Custom app" },
  { to: "/download", label: "Get the app" },
];

export default function Layout() {
  const { mode, session, signOut } = useAuth();
  const { pathname, hash } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  // A new page starts at the top (or at its #section) and closes the mobile menu.
  useEffect(() => {
    setMenuOpen(false);
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
    else window.scrollTo(0, 0);
  }, [pathname, hash]);

  const account =
    mode === "none" ? null : session ? (
      { to: "/me/jobs", label: "My apps" }
    ) : (
      { to: "/login", label: "Sign in" }
    );

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-4 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>

      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
        <Container className="flex h-16 items-center justify-between gap-4">
          <Logo />
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            {NAV.map((item) => (
              <NavItem key={item.to} {...item} className={navClass} />
            ))}
          </nav>
          <div className="hidden items-center gap-2 md:flex">
            {session ? (
              <AccountMenu label={session.label} onSignOut={() => void signOut()} />
            ) : (
              account && (
                <NavLink to={account.to} className={navClass}>
                  {account.label}
                </NavLink>
              )
            )}
            <ButtonLink to="/automations">Browse automations</ButtonLink>
          </div>
          <button
            type="button"
            className="-mr-2 rounded-md p-2 text-slate-700 hover:bg-slate-100 md:hidden"
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <Close className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </Container>
        {menuOpen && (
          <nav id="mobile-menu" aria-label="Main" className="border-t border-slate-200 bg-white md:hidden">
            <Container className="space-y-1 py-3">
              {[...NAV, ...(account ? [account] : [])].map((item) => (
                <NavItem key={item.to} {...item} className={mobileNavClass} />
              ))}
              {session && (
                <button type="button" className={`${mobileNavClass({ isActive: false })} w-full text-left`} onClick={() => void signOut()}>
                  Sign out <span className="text-sm font-normal text-slate-500">({session.label})</span>
                </button>
              )}
              <ButtonLink to="/automations" className="mt-2 w-full">
                Browse automations
              </ButtonLink>
            </Container>
          </nav>
        )}
      </header>

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <Footer />
    </div>
  );
}

function AccountMenu({ label, onSignOut }: { label: string; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account"
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold uppercase text-brand-700 ring-1 ring-brand-200 hover:bg-brand-200"
      >
        {label.trim().charAt(0) || "?"}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
        >
          <p className="truncate border-b border-slate-100 px-4 py-3 text-sm text-slate-600">
            Signed in as
            <span className="block truncate font-semibold text-slate-900">{label}</span>
          </p>
          <Link role="menuitem" to="/me/jobs" className="block px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50">
            My apps
          </Link>
          <Link role="menuitem" to="/custom" className="block px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50">
            New custom app
          </Link>
          <button
            role="menuitem"
            type="button"
            onClick={onSignOut}
            className="block w-full border-t border-slate-100 px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/** Section links (/#...) are never "active"; page links are. */
function NavItem({
  to,
  label,
  className,
}: {
  to: string;
  label: string;
  className: (state: { isActive: boolean }) => string;
}) {
  if (to.includes("#")) {
    return (
      <Link to={to} className={className({ isActive: false })}>
        {label}
      </Link>
    );
  }
  return (
    <NavLink to={to} className={className}>
      {label}
    </NavLink>
  );
}

/** Width and padding for ordinary pages; the home page lays out its own full-width sections. */
export function PageShell() {
  return (
    <Container className="py-10 sm:py-14">
      <Outlet />
    </Container>
  );
}

function Footer() {
  const email = contactEmail();
  return (
    <footer className="border-t border-slate-200 bg-slate-50">
      <Container className="grid gap-10 py-12 sm:grid-cols-2 lg:grid-cols-4">
        <div className="lg:col-span-2">
          <div className="flex items-center gap-2.5">
            <LogoMark className="h-7 w-7" />
            <span className="font-bold tracking-tight">
              MakeMy<span className="text-brand-600">EXE</span>
            </span>
          </div>
          <p className="mt-3 max-w-sm text-sm leading-6 text-slate-600">
            Small Windows apps for everyday work. They run offline on your own PC, so your files
            and data never leave it.
          </p>
        </div>
        <FooterColumn
          title="Product"
          links={[
            { to: "/automations", label: "Automations" },
            { to: "/#how-it-works", label: "How it works" },
            { to: "/custom", label: "Request a custom app" },
            { to: "/download", label: "Download MakeMyEXE" },
          ]}
        />
        <div>
          <FooterColumn
            title="Company"
            links={[
              { to: "/privacy", label: "Privacy" },
              { to: "/terms", label: "Terms" },
            ]}
          />
          {email && (
            <a href={`mailto:${email}`} className="mt-2.5 block text-sm text-slate-600 hover:text-slate-900">
              {email}
            </a>
          )}
        </div>
      </Container>
      <div className="border-t border-slate-200">
        <Container className="flex flex-col gap-2 py-5 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
          <p>© {new Date().getFullYear()} MakeMyEXE. All rights reserved.</p>
          <p>Works on Windows 10 and 11. No tracking on this site.</p>
        </Container>
      </div>
    </footer>
  );
}

function FooterColumn({ title, links }: { title: string; links: { to: string; label: string }[] }) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      <ul className="mt-3 space-y-2.5">
        {links.map((link) => (
          <li key={link.to}>
            <Link to={link.to} className="text-sm text-slate-600 hover:text-slate-900">
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
