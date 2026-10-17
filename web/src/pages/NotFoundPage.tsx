import { Link } from "react-router";

export default function NotFoundPage({ what = "page" }: { what?: string }) {
  return (
    <div className="py-16 text-center">
      <h1 className="text-2xl font-semibold">We couldn't find that {what}</h1>
      <p className="mt-2 text-slate-600">It may have been renamed or removed.</p>
      <Link to="/" className="mt-6 inline-block font-medium text-indigo-700 hover:underline">
        Back to the catalog
      </Link>
    </div>
  );
}
