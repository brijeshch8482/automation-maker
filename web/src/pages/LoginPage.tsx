import { useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../auth";
import { Button, Card, ErrorText } from "../components/ui";

const inputClass =
  "mt-1.5 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";

/** Only allow same-site paths as the post-login destination. */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/me/jobs";
}

export default function LoginPage() {
  const { mode, session, signInWithEmail, devSignIn, signOut } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const carry = location.state; // e.g. a half-written description from /custom

  const [value, setValue] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (session) {
    return (
      <div className="max-w-md">
        <h1 className="text-2xl font-bold tracking-tight">You're signed in</h1>
        <p className="mt-2 text-slate-600">as {session.label}</p>
        <div className="mt-4 flex gap-2">
          <Button onClick={() => navigate(next, { state: carry })}>Continue</Button>
          <Button variant="secondary" onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
      </div>
    );
  }

  if (mode === "none") {
    return (
      <div className="max-w-md">
        <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
        <p className="mt-2 text-slate-600">Accounts open together with custom builds, soon.</p>
      </div>
    );
  }

  const submit = async () => {
    setError(null);
    if (mode === "dev") {
      devSignIn(value.trim());
      navigate(next, { state: carry });
      return;
    }
    try {
      await signInWithEmail(value.trim());
      setSent(true);
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div className="max-w-md">
      <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
      <p className="mt-2 text-slate-600">
        You need an account only for custom automations. Ready-made ones need no login.
      </p>
      <Card className="mt-6">
        {sent ? (
          <p role="status" className="text-slate-700">
            Check your email: we sent a sign-in link to <strong>{value}</strong>.
          </p>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label htmlFor="login" className="block text-sm font-medium text-slate-800">
              {mode === "dev" ? "Dev user name" : "Email"}
            </label>
            <input
              id="login"
              type={mode === "dev" ? "text" : "email"}
              autoComplete={mode === "dev" ? "off" : "email"}
              required
              className={inputClass}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            {mode === "dev" && (
              <p className="mt-1.5 text-xs text-amber-700">Development login. Not for real accounts.</p>
            )}
            <Button type="submit" className="mt-4" disabled={!value.trim()}>
              {mode === "dev" ? "Sign in" : "Email me a sign-in link"}
            </Button>
            <ErrorText error={error} />
          </form>
        )}
      </Card>
    </div>
  );
}
