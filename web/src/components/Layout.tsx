import { Link, NavLink, Outlet } from "react-router";

const navClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-md px-2 py-2 text-sm font-medium sm:px-3 ${
    isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:text-slate-900"
  }`;

export default function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link to="/" className="flex shrink-0 items-center gap-2 font-semibold text-slate-900">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            MakeMyEXE
          </Link>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navClass}>
              Catalog
            </NavLink>
            <NavLink to="/custom" className={navClass}>
              Make a custom one
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-4 py-5 text-sm text-slate-500 sm:px-6">
          Every automation runs on your own Windows PC. Your files and data never leave it.
        </div>
      </footer>
    </div>
  );
}
