import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";

import { authProviders, useAuth, type AuthProviders, type CodePurpose } from "../auth";
import { LogoMark } from "../components/Logo";
import { Button, ErrorText, Spinner, usePageMeta } from "../components/ui";

const inputClass =
  "mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

const MIN_PASSWORD = 8;
const RESEND_SECONDS = 60;
const CARRY_KEY = "makemyexe.loginCarry"; // page state kept across the Google round trip

/** Only allow same-site paths as the post-login destination. */
function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/me/jobs";
}

type View =
  | { name: "signin"; tab: "password" | "code" }
  | { name: "signup" }
  | { name: "forgot" }
  | { name: "verify"; email: string; purpose: CodePurpose }
  | { name: "new-password" };

export default function LoginPage() {
  usePageMeta("Sign in");
  const auth = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const [view, setView] = useState<View>(() =>
    params.get("mode") === "signup" ? { name: "signup" } : { name: "signin", tab: "password" },
  );

  const carry = location.state ?? readCarry(); // e.g. a half-written description from /custom
  const done = () => navigate(next, { state: carry, replace: true });

  // Back from Google (?code=...): once the session is in, go where the user was heading.
  const fromRedirect = params.has("code");
  useEffect(() => {
    if (auth.session && fromRedirect && !auth.recovering) {
      clearCarry();
      done();
    }
  }, [auth.session, fromRedirect, auth.recovering]); // done() only reads values fixed for this page

  if (auth.mode === "none") {
    return (
      <AuthShell title="Sign in" subtitle="Accounts open together with custom apps, soon.">
        <p className="text-sm text-slate-600">Ready-made automations need no account.</p>
      </AuthShell>
    );
  }
  if (auth.mode === "dev") return <DevLogin onDone={done} />;
  if (auth.loading) {
    return (
      <AuthShell title="Sign in">
        <Spinner label="Checking your login…" />
      </AuthShell>
    );
  }

  if (auth.recovering || view.name === "new-password") return <NewPassword onDone={done} />;

  if (auth.session) {
    return (
      <AuthShell title="You're signed in" subtitle={`as ${auth.session.label}`}>
        <div className="flex gap-3">
          <Button className="flex-1" onClick={done}>
            Continue
          </Button>
          <Button variant="secondary" onClick={() => void auth.signOut()}>
            Sign out
          </Button>
        </div>
      </AuthShell>
    );
  }

  const google = (
    <GoogleSignIn
      onStart={() => {
        writeCarry(carry);
        return auth.signInWithGoogle(`/login?next=${encodeURIComponent(next)}`);
      }}
    />
  );

  switch (view.name) {
    case "verify":
      return (
        <VerifyCode
          email={view.email}
          purpose={view.purpose}
          onVerified={() => (view.purpose === "recovery" ? setView({ name: "new-password" }) : done())}
          onBack={() =>
            setView(
              view.purpose === "signup"
                ? { name: "signup" }
                : view.purpose === "recovery"
                  ? { name: "forgot" }
                  : { name: "signin", tab: "code" },
            )
          }
        />
      );
    case "forgot":
      return (
        <Forgot
          onSent={(email) => setView({ name: "verify", email, purpose: "recovery" })}
          onBack={() => setView({ name: "signin", tab: "password" })}
        />
      );
    case "signup":
      return (
        <SignUp
          google={google}
          onSignedIn={done}
          onConfirm={(email) => setView({ name: "verify", email, purpose: "signup" })}
          onSignIn={() => setView({ name: "signin", tab: "password" })}
        />
      );
    default:
      return (
        <SignIn
          tab={view.tab}
          google={google}
          onTab={(tab) => setView({ name: "signin", tab })}
          onSignedIn={done}
          onCodeSent={(email) => setView({ name: "verify", email, purpose: "email" })}
          onForgot={() => setView({ name: "forgot" })}
          onSignUp={() => setView({ name: "signup" })}
          redirectError={params.get("error_description")}
        />
      );
  }
}

// --- Views ------------------------------------------------------------------------------

function SignIn({
  tab,
  google,
  onTab,
  onSignedIn,
  onCodeSent,
  onForgot,
  onSignUp,
  redirectError,
}: {
  redirectError: string | null;
  tab: "password" | "code";
  google: ReactNode;
  onTab: (tab: "password" | "code") => void;
  onSignedIn: () => void;
  onCodeSent: (email: string) => void;
  onForgot: () => void;
  onSignUp: () => void;
}) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const action = useAction();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void action.run(async () => {
      if (tab === "password") {
        await auth.signInWithPassword(email.trim(), password);
        onSignedIn();
      } else {
        await auth.sendEmailCode(email.trim());
        onCodeSent(email.trim());
      }
    });
  };

  return (
    <AuthShell
      title="Sign in to MakeMyEXE"
      subtitle="You need an account only for custom apps. Ready-made ones need no login."
      footer={
        <>
          New here?{" "}
          <LinkButton onClick={onSignUp}>Create an account</LinkButton>
        </>
      }
    >
      {redirectError && (
        <p role="alert" className="mb-5 rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-800">
          Sign-in didn't finish: {redirectError}
        </p>
      )}
      {google}
      <div role="tablist" aria-label="Sign-in method" className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
        {(
          [
            ["password", "Password"],
            ["code", "Email code"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => onTab(value)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              tab === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <form className="mt-5 space-y-4" onSubmit={submit}>
        <EmailField value={email} onChange={setEmail} />
        {tab === "password" ? (
          <PasswordField
            label="Password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            aside={<LinkButton onClick={onForgot}>Forgot password?</LinkButton>}
          />
        ) : (
          <p className="text-sm text-slate-600">We'll email you a 6-digit code. No password needed.</p>
        )}
        <Button
          type="submit"
          className="w-full"
          size="lg"
          disabled={action.busy || !email.trim() || (tab === "password" && !password)}
        >
          {action.busy ? "Please wait…" : tab === "password" ? "Sign in" : "Email me a code"}
        </Button>
        <ErrorText error={action.error} />
      </form>
    </AuthShell>
  );
}

function SignUp({
  google,
  onSignedIn,
  onConfirm,
  onSignIn,
}: {
  google: ReactNode;
  onSignedIn: () => void;
  onConfirm: (email: string) => void;
  onSignIn: () => void;
}) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const action = useAction();
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void action.run(async () => {
      const { signedIn } = await auth.signUp(email.trim(), password);
      if (signedIn) onSignedIn();
      else onConfirm(email.trim());
    });
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Free. Used only to follow your custom apps."
      footer={
        <>
          Already have an account? <LinkButton onClick={onSignIn}>Sign in</LinkButton>
        </>
      }
    >
      {google}
      <form className="space-y-4" onSubmit={submit}>
        <EmailField value={email} onChange={setEmail} />
        <PasswordField
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          hint={tooShort ? `At least ${MIN_PASSWORD} characters` : `${MIN_PASSWORD} or more characters`}
          invalid={tooShort}
        />
        <Button
          type="submit"
          className="w-full"
          size="lg"
          disabled={action.busy || !email.trim() || password.length < MIN_PASSWORD}
        >
          {action.busy ? "Please wait…" : "Create account"}
        </Button>
        <ErrorText error={action.error} />
        <p className="text-center text-xs leading-5 text-slate-500">
          By creating an account you agree to our{" "}
          <Link to="/terms" className="underline hover:text-slate-700">
            Terms
          </Link>{" "}
          and{" "}
          <Link to="/privacy" className="underline hover:text-slate-700">
            Privacy
          </Link>
          .
        </p>
      </form>
    </AuthShell>
  );
}

const VERIFY_TEXT: Record<CodePurpose, { title: string; button: string }> = {
  email: { title: "Check your email", button: "Sign in" },
  signup: { title: "Confirm your email", button: "Confirm and continue" },
  recovery: { title: "Reset your password", button: "Continue" },
};

function VerifyCode({
  email,
  purpose,
  onVerified,
  onBack,
}: {
  email: string;
  purpose: CodePurpose;
  onVerified: () => void;
  onBack: () => void;
}) {
  const auth = useAuth();
  const [code, setCode] = useState("");
  const action = useAction();
  const resend = useAction();
  const cooldown = useCooldown(RESEND_SECONDS);
  const [resent, setResent] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void action.run(async () => {
      await auth.verifyCode(email, code, purpose);
      onVerified();
    });
  };

  const sendAgain = () =>
    void resend.run(async () => {
      if (purpose === "signup") await auth.resendSignupCode(email);
      else if (purpose === "recovery") await auth.sendPasswordReset(email);
      else await auth.sendEmailCode(email);
      setResent(true);
      cooldown.restart();
    });

  return (
    <AuthShell
      title={VERIFY_TEXT[purpose].title}
      subtitle={
        <>
          We sent a 6-digit code to <strong className="text-slate-900">{email}</strong>. You can also
          click the link in that email.
        </>
      }
      footer={<LinkButton onClick={onBack}>Use a different email</LinkButton>}
    >
      <form className="space-y-4" onSubmit={submit}>
        <div>
          <label htmlFor="code" className="block text-sm font-medium text-slate-800">
            Code
          </label>
          <input
            id="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6,10}"
            maxLength={10}
            required
            autoFocus
            className={`${inputClass} text-center font-mono text-2xl tracking-[0.5em]`}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
        </div>
        <Button type="submit" className="w-full" size="lg" disabled={action.busy || code.length < 6}>
          {action.busy ? "Checking…" : VERIFY_TEXT[purpose].button}
        </Button>
        <ErrorText error={action.error} />
        <p className="text-center text-sm text-slate-600">
          {cooldown.left > 0 ? (
            <span role="status">
              {resent ? "Sent again. " : ""}You can ask for a new code in {cooldown.left} s.
            </span>
          ) : (
            <>
              Didn't get it? Check spam, or{" "}
              <LinkButton onClick={sendAgain} disabled={resend.busy}>
                send a new code
              </LinkButton>
              .
            </>
          )}
        </p>
        <ErrorText error={resend.error} />
      </form>
    </AuthShell>
  );
}

function Forgot({ onSent, onBack }: { onSent: (email: string) => void; onBack: () => void }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const action = useAction();
  return (
    <AuthShell
      title="Forgot your password?"
      subtitle="Enter your email and we'll send you a code to set a new one."
      footer={<LinkButton onClick={onBack}>Back to sign in</LinkButton>}
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            await auth.sendPasswordReset(email.trim());
            onSent(email.trim());
          });
        }}
      >
        <EmailField value={email} onChange={setEmail} />
        <Button type="submit" className="w-full" size="lg" disabled={action.busy || !email.trim()}>
          {action.busy ? "Please wait…" : "Send reset code"}
        </Button>
        <ErrorText error={action.error} />
      </form>
    </AuthShell>
  );
}

function NewPassword({ onDone }: { onDone: () => void }) {
  const auth = useAuth();
  const [password, setPassword] = useState("");
  const action = useAction();
  return (
    <AuthShell title="Choose a new password" subtitle={auth.session ? `for ${auth.session.label}` : undefined}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            await auth.setNewPassword(password);
            onDone();
          });
        }}
      >
        <PasswordField
          label="New password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          hint={`${MIN_PASSWORD} or more characters`}
        />
        <Button type="submit" className="w-full" size="lg" disabled={action.busy || password.length < MIN_PASSWORD}>
          {action.busy ? "Saving…" : "Save password and continue"}
        </Button>
        <ErrorText error={action.error} />
      </form>
    </AuthShell>
  );
}

function DevLogin({ onDone }: { onDone: () => void }) {
  const { session, devSignIn, signOut } = useAuth();
  const [name, setName] = useState("");
  if (session) {
    return (
      <AuthShell title="You're signed in" subtitle={`as ${session.label}`}>
        <div className="flex gap-3">
          <Button className="flex-1" onClick={onDone}>
            Continue
          </Button>
          <Button variant="secondary" onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
      </AuthShell>
    );
  }
  return (
    <AuthShell title="Sign in" subtitle="You need an account only for custom apps. Ready-made ones need no login.">
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          devSignIn(name.trim());
          onDone();
        }}
      >
        <div>
          <label htmlFor="login" className="block text-sm font-medium text-slate-800">
            Dev user name
          </label>
          <input id="login" autoComplete="off" required className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          <p className="mt-1.5 text-xs text-amber-700">Development login. Not for real accounts.</p>
        </div>
        <Button type="submit" className="w-full" disabled={!name.trim()}>
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}

// --- Pieces -----------------------------------------------------------------------------

function AuthShell({
  title,
  subtitle,
  footer,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-md">
      <div className="text-center">
        <LogoMark className="mx-auto h-11 w-11" />
        <h1 className="mt-5 text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-2 text-sm leading-6 text-slate-600">{subtitle}</p>}
      </div>
      <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">{children}</div>
      {footer && <p className="mt-6 text-center text-sm text-slate-600">{footer}</p>}
    </div>
  );
}

function GoogleSignIn({ onStart }: { onStart: () => Promise<void> }) {
  const [settings, setSettings] = useState<AuthProviders | null>(null);
  const action = useAction();
  useEffect(() => {
    let live = true;
    void authProviders().then((p) => live && setSettings(p));
    return () => {
      live = false;
    };
  }, []);
  if (!settings?.google) return null;
  return (
    <div className="mb-5">
      <button
        type="button"
        onClick={() => void action.run(onStart)}
        disabled={action.busy}
        className="flex w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-slate-50 disabled:opacity-60"
      >
        <GoogleLogo />
        {action.busy ? "Opening Google…" : "Continue with Google"}
      </button>
      <ErrorText error={action.error} />
      <div className="mt-5 flex items-center gap-3 text-xs font-medium uppercase tracking-wider text-slate-400">
        <span className="h-px flex-1 bg-slate-200" />
        or
        <span className="h-px flex-1 bg-slate-200" />
      </div>
    </div>
  );
}

function GoogleLogo() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.44.34-2.1V7.06H2.18A11 11 0 0 0 1 12c0 1.77.43 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.3 9.14 5.38 12 5.38z" />
    </svg>
  );
}

function EmailField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div>
      <label htmlFor="email" className="block text-sm font-medium text-slate-800">
        Email
      </label>
      <input
        id="email"
        type="email"
        autoComplete="email"
        required
        placeholder="you@example.com"
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  autoComplete,
  aside,
  hint,
  invalid = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  aside?: ReactNode;
  hint?: string;
  invalid?: boolean;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div>
      <div className="flex items-center justify-between">
        <label htmlFor="password" className="block text-sm font-medium text-slate-800">
          {label}
        </label>
        {aside}
      </div>
      <div className="relative">
        <input
          id="password"
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          required
          className={`${inputClass} pr-16 ${invalid ? "border-rose-400" : ""}`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={hint ? "password-hint" : undefined}
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          className="absolute inset-y-0 right-0 mt-1.5 px-3.5 text-xs font-semibold text-slate-500 hover:text-slate-800"
          aria-label={shown ? "Hide password" : "Show password"}
        >
          {shown ? "Hide" : "Show"}
        </button>
      </div>
      {hint && (
        <p id="password-hint" className={`mt-1.5 text-xs ${invalid ? "text-rose-700" : "text-slate-500"}`}>
          {hint}
        </p>
      )}
    </div>
  );
}

function LinkButton({ onClick, children, disabled }: { onClick: () => void; children: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="text-sm font-semibold text-brand-700 hover:text-brand-600 disabled:opacity-60"
    >
      {children}
    </button>
  );
}

// --- Hooks ------------------------------------------------------------------------------

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return {
    busy,
    error,
    async run(action: () => Promise<void>) {
      setBusy(true);
      setError(null);
      try {
        await action();
      } catch (err) {
        setError(err);
      } finally {
        setBusy(false);
      }
    },
  };
}

function useCooldown(seconds: number) {
  const [until, setUntil] = useState(() => Date.now() + seconds * 1000);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (now >= until) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [now, until]);
  return {
    left: Math.max(0, Math.ceil((until - now) / 1000)),
    restart() {
      const t = Date.now();
      setUntil(t + seconds * 1000);
      setNow(t);
    },
  };
}

function readCarry(): unknown {
  try {
    const raw = sessionStorage.getItem(CARRY_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeCarry(value: unknown): void {
  try {
    if (value) sessionStorage.setItem(CARRY_KEY, JSON.stringify(value));
  } catch {
    // Storage blocked: the user re-types the description after Google, nothing worse.
  }
}

function clearCarry(): void {
  try {
    sessionStorage.removeItem(CARRY_KEY);
  } catch {
    // ignore
  }
}
