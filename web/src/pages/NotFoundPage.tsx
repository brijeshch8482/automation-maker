import { ArrowRight } from "../components/icons";
import { ButtonLink, usePageMeta } from "../components/ui";

export default function NotFoundPage({ what = "page" }: { what?: string }) {
  usePageMeta("Not found");
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="text-sm font-semibold uppercase tracking-wider text-brand-600">404</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight">We couldn't find that {what}</h1>
      <p className="mt-3 text-slate-600">It may have been renamed or removed.</p>
      <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
        <ButtonLink to="/automations">
          Browse automations <ArrowRight className="h-4 w-4" />
        </ButtonLink>
        <ButtonLink to="/" variant="secondary">
          Go to the home page
        </ButtonLink>
      </div>
    </div>
  );
}
