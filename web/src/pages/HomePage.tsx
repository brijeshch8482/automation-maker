import type { ComponentType, ReactNode, SVGProps } from "react";
import { Link } from "react-router";

import { getAutomation, listAutomations } from "../api";
import AutomationCard from "../components/AutomationCard";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Cog,
  Download,
  EyeOff,
  Shield,
  Sparkles,
  Undo,
  WifiOff,
  Windows,
} from "../components/icons";
import SpecPreview from "../components/SpecPreview";
import { ButtonLink, Container, Eyebrow, usePageMeta } from "../components/ui";
import { useAsync } from "../lib/useAsync";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const HERO_APP = "make-pdf";

export default function HomePage() {
  usePageMeta(
    null,
    "Small Windows apps for everyday office work: make PDFs, rename files, create invoices. They run offline on your own PC, so your files never leave it.",
  );
  return (
    <>
      <Hero />
      <TrustStrip />
      <HowItWorks />
      <Featured />
      <Privacy />
      <CustomCta />
      <Faq />
    </>
  );
}

function Hero() {
  const preview = useAsync(() => getAutomation(HERO_APP), []);
  return (
    <section className="relative overflow-hidden border-b border-slate-200 bg-gradient-to-b from-brand-50/70 via-white to-white">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 right-0 h-[32rem] w-[32rem] rounded-full bg-brand-200/40 blur-3xl"
      />
      <Container className="relative grid items-center gap-12 py-16 sm:py-20 lg:grid-cols-2 lg:gap-16 lg:py-24">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white px-3 py-1 text-sm font-medium text-brand-700 shadow-sm">
            <WifiOff className="h-4 w-4" /> Runs offline on your PC
          </p>
          <h1 className="mt-6 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl lg:text-[3.4rem] lg:leading-[1.1]">
            Everyday office work, done by <span className="text-brand-600">your own Windows app</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-slate-600">
            Pick a ready-made automation, or describe your task in plain words. You get a small
            Windows app with a step-by-step guide. It works offline, so your files never leave
            your computer.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ButtonLink to="/automations" size="lg">
              Browse automations <ArrowRight className="h-5 w-5" />
            </ButtonLink>
            <ButtonLink to="/custom" size="lg" variant="secondary">
              Describe your task
            </ButtonLink>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-600">
            {["No installation", "No account for ready-made apps", "Guide included"].map((item) => (
              <li key={item} className="flex items-center gap-1.5">
                <Check className="h-4 w-4 text-emerald-600" /> {item}
              </li>
            ))}
          </ul>
        </div>
        <div className="relative">
          <div aria-hidden className="absolute -inset-4 rounded-3xl bg-gradient-to-tr from-brand-100 to-white blur-sm" />
          <div className="relative">
            {preview.status === "ready" && preview.data && <SpecPreview spec={preview.data} />}
          </div>
        </div>
      </Container>
    </section>
  );
}

const TRUST: [Icon, string, string][] = [
  [WifiOff, "Works offline", "No internet needed to run"],
  [Undo, "Originals stay safe", "Results are saved as new files"],
  [EyeOff, "No tracking", "No telemetry, no auto-updates"],
  [Windows, "Windows 10 & 11", "Unzip and double-click"],
];

function TrustStrip() {
  return (
    <section aria-label="Promises" className="border-b border-slate-200 bg-white">
      <Container className="grid grid-cols-2 gap-6 py-8 lg:grid-cols-4">
        {TRUST.map(([Icon, title, text]) => (
          <div key={title} className="flex items-start gap-3">
            <Icon className="mt-0.5 h-6 w-6 shrink-0 text-brand-600" />
            <div>
              <p className="text-sm font-semibold text-slate-900">{title}</p>
              <p className="text-sm text-slate-500">{text}</p>
            </div>
          </div>
        ))}
      </Container>
    </section>
  );
}

const STEPS: [Icon, string, string][] = [
  [
    Sparkles,
    "Choose or describe",
    "Pick an automation from the catalog, or tell us what you do by hand today. We show you the app's form and steps before anything is built.",
  ],
  [
    Cog,
    "We build and test it",
    "Your app is built on Windows and tested with sample data. It must pass before it can be downloaded.",
  ],
  [
    Download,
    "Download and run",
    "Unzip it, double-click, and fill in the form. A Guide.pdf with screenshots shows every step.",
  ],
];

function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-white py-20 sm:py-24">
      <Container>
        <SectionHeading eyebrow="How it works" title="From task to app in three steps">
          No setup, no installer, nothing to configure on a server.
        </SectionHeading>
        <ol className="mt-14 grid gap-6 md:grid-cols-3">
          {STEPS.map(([Icon, title, text], i) => (
            <li key={title} className="relative rounded-2xl border border-slate-200 bg-slate-50/60 p-7">
              <div className="flex items-center justify-between">
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white shadow-md shadow-brand-600/25">
                  <Icon className="h-6 w-6" />
                </span>
                <span className="text-sm font-semibold text-slate-400">Step {i + 1}</span>
              </div>
              <h3 className="mt-6 text-lg font-semibold text-slate-900">{title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
            </li>
          ))}
        </ol>
      </Container>
    </section>
  );
}

function Featured() {
  const state = useAsync(listAutomations, []);
  return (
    <section className="border-y border-slate-200 bg-slate-50 py-20 sm:py-24">
      <Container>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <SectionHeading eyebrow="Ready-made" title="Automations you can use today" align="left">
            Each one is a complete app, tested on Windows.
          </SectionHeading>
          <Link
            to="/automations"
            className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-brand-700 hover:text-brand-600"
          >
            See all automations <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        {state.status === "ready" && (
          <ul className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {state.data.slice(0, 6).map((spec) => (
              <li key={spec.id}>
                <AutomationCard spec={spec} />
              </li>
            ))}
          </ul>
        )}
      </Container>
    </section>
  );
}

const PRIVACY: [Icon, string, string][] = [
  [
    Shield,
    "We never need your data",
    "To build an app we only need to know the shape of your task: which fields, which steps. Your real names, numbers and files are typed in only inside the app on your PC.",
  ],
  [
    WifiOff,
    "Offline by default",
    "Apps don't connect to the internet unless the task needs it, and then only to the sites listed on the app's page.",
  ],
  [
    Undo,
    "Your originals are never changed",
    "Results are saved as new files. Apps that rename files show a preview first, and one click undoes it.",
  ],
  [
    EyeOff,
    "No tracking, no auto-updates",
    "Apps don't send usage data and don't update themselves. What you download is what runs.",
  ],
];

function Privacy() {
  return (
    <section className="bg-brand-900 py-20 text-white sm:py-24">
      <Container>
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-brand-200">Privacy by design</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Your data stays on your PC</h2>
          <p className="mt-4 text-lg leading-8 text-brand-100/80">
            Most online tools ask you to upload your files. Ours come to you instead.
          </p>
        </div>
        <div className="mt-14 grid gap-x-10 gap-y-10 sm:grid-cols-2">
          {PRIVACY.map(([Icon, title, text]) => (
            <div key={title} className="flex gap-4">
              <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15">
                <Icon className="h-6 w-6 text-brand-200" />
              </span>
              <div>
                <h3 className="font-semibold">{title}</h3>
                <p className="mt-1.5 text-sm leading-6 text-brand-100/75">{text}</p>
              </div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

function CustomCta() {
  return (
    <section className="bg-white py-20 sm:py-24">
      <Container>
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-600 to-brand-700 px-6 py-14 text-center shadow-xl shadow-brand-900/10 sm:px-12">
          <div aria-hidden className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/10 blur-2xl" />
          <h2 className="relative text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Don't see your task?
          </h2>
          <p className="relative mx-auto mt-4 max-w-xl text-lg leading-8 text-brand-100">
            Describe what you do by hand today. We design the app with you, build it, and test it on
            Windows.
          </p>
          <div className="relative mt-8 flex justify-center">
            <ButtonLink to="/custom" size="lg" variant="secondary" className="border-transparent">
              Describe your task <ArrowRight className="h-5 w-5" />
            </ButtonLink>
          </div>
        </div>
      </Container>
    </section>
  );
}

const FAQ: [string, string][] = [
  [
    "Do I need to install anything?",
    "No. Unzip the download into a folder and double-click the app. It doesn't need administrator rights and doesn't change your system.",
  ],
  [
    "Why does Windows say “Windows protected your PC”?",
    "During early access our apps are not yet signed with a code-signing certificate, so Windows doesn't recognise them. Click “More info”, then “Run anyway”. Signed apps are on our roadmap.",
  ],
  [
    "Does the app need the internet?",
    "No. Apps run fully offline. The rare app that has to reach a website says so on its page and in its window, and names the only sites it connects to.",
  ],
  [
    "Do you see my files or the data I type in?",
    "No. Everything you type and every file you choose stays on your PC. The app doesn't send anything to us or anyone else.",
  ],
  [
    "Which Windows versions are supported?",
    "Windows 10 and Windows 11, 64-bit.",
  ],
  [
    "How does a custom app work?",
    "Sign in and describe your task. We turn it into a design you can check and change: the form you'll fill in and the steps the app takes. When you confirm it, we build and test the app, and it appears under My apps.",
  ],
];

function Faq() {
  return (
    <section className="border-t border-slate-200 bg-slate-50 py-20 sm:py-24">
      <Container className="max-w-3xl">
        <SectionHeading eyebrow="FAQ" title="Questions, answered" />
        <div className="mt-12 divide-y divide-slate-200 rounded-2xl border border-slate-200 bg-white shadow-sm">
          {FAQ.map(([question, answer]) => (
            <details key={question} className="group px-6 py-5 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-slate-900">
                {question}
                <ChevronDown className="h-5 w-5 shrink-0 text-slate-400 transition-transform group-open:rotate-180" />
              </summary>
              <p className="mt-3 text-sm leading-6 text-slate-600">{answer}</p>
            </details>
          ))}
        </div>
      </Container>
    </section>
  );
}

function SectionHeading({
  eyebrow,
  title,
  children,
  align = "center",
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  align?: "center" | "left";
}) {
  return (
    <div className={align === "center" ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{title}</h2>
      {children && <p className="mt-4 text-lg leading-8 text-slate-600">{children}</p>}
    </div>
  );
}
