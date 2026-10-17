import { Link } from "react-router";

export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return <img src="/favicon.svg" alt="" className={className} />;
}

export default function Logo() {
  return (
    <Link to="/" className="flex shrink-0 items-center gap-2.5 rounded-md" aria-label="MakeMyEXE home">
      <LogoMark />
      <span className="text-lg font-bold tracking-tight text-slate-900">
        MakeMy<span className="text-brand-600">EXE</span>
      </span>
    </Link>
  );
}
