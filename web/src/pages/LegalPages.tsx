import type { ReactNode } from "react";
import { Link } from "react-router";

import { Eyebrow, usePageMeta } from "../components/ui";
import { contactEmail } from "../env";

const UPDATED = "17 October 2026";

function LegalPage({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl">
      <Eyebrow>Legal</Eyebrow>
      <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-900">{title}</h1>
      <p className="mt-3 text-sm text-slate-500">Last updated {UPDATED}</p>
      <p className="mt-6 text-lg leading-8 text-slate-600">{intro}</p>
      <div className="mt-10 space-y-10 text-[15px] leading-7 text-slate-700 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-slate-900 [&_li]:mt-1.5 [&_p]:mt-3 [&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-6">
        {children}
      </div>
    </article>
  );
}

function Contact() {
  const email = contactEmail();
  return email ? (
    <p>
      Questions? Write to <a className="font-medium text-brand-700 hover:underline" href={`mailto:${email}`}>{email}</a>.
    </p>
  ) : null;
}

export function PrivacyPage() {
  usePageMeta("Privacy", "How MakeMyEXE handles your data: the apps run offline and never send what you type.");
  return (
    <LegalPage
      title="Privacy"
      intro="MakeMyEXE is built so that we never need your data. This page explains the little we do keep, why, and for how long."
    >
      <section>
        <h2>The apps you download</h2>
        <ul>
          <li>Apps run on your own Windows PC. What you type and the files you choose stay there.</li>
          <li>
            Apps don't connect to the internet. The rare app that has to reach a website says so on
            its page and in its window, and names the only sites it connects to.
          </li>
          <li>Apps don't collect usage data and don't update themselves.</li>
          <li>
            Your settings for an app are saved on your PC only, in the folder{" "}
            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-sm">%APPDATA%\MakeMyEXE</code>.
            Deleting that folder removes them.
          </li>
        </ul>
      </section>

      <section>
        <h2>This website</h2>
        <ul>
          <li>Browsing the site and the catalog needs no account. We don't use analytics, advertising or tracking cookies.</li>
          <li>When you sign in, your browser stores a sign-in token so you stay signed in. It is used for nothing else.</li>
        </ul>
      </section>

      <section>
        <h2>Custom apps</h2>
        <p>To build a custom app for you, we keep:</p>
        <ul>
          <li>
            Your account: your email address, used only to sign you in. If you set a password, it
            is stored by Supabase as a one-way hash that nobody can read back. If you continue with
            Google, Google tells us your email address and name, nothing else.
          </li>
          <li>
            Your description of the task. Before it is saved, personal details (phone numbers,
            email addresses, card and bank numbers, Aadhaar, PAN and GSTIN) are masked, first in your browser and again on
            our server. The description is deleted after 30 days.
          </li>
          <li>The app's design (its form and steps), your answers to our questions, and the build status.</li>
        </ul>
        <p>
          Describe the task, not your data: we never need real customer names, amounts or files.
          A design you don't confirm expires after 30 days.
        </p>
        <p>
          Your description is processed by Anthropic's Claude to design and build the app. It is
          not used to identify you.
        </p>
      </section>

      <section>
        <h2>Who runs the services</h2>
        <ul>
          <li>Cloudflare hosts this website and stores finished apps for download.</li>
          <li>Render runs our server, and Supabase stores accounts and custom-app designs.</li>
          <li>GitHub builds and tests the apps.</li>
        </ul>
      </section>

      <section>
        <h2>Your choices</h2>
        <p>
          You can ask us to delete your account and everything linked to it at any time. We don't
          sell or share your information with anyone else.
        </p>
        <Contact />
      </section>
    </LegalPage>
  );
}

export function TermsPage() {
  usePageMeta("Terms", "The terms for using MakeMyEXE and the apps it builds.");
  return (
    <LegalPage
      title="Terms of use"
      intro="These terms apply when you use this website or an app downloaded from it. They are written to be read, not skimmed past."
    >
      <section>
        <h2>Early access</h2>
        <p>
          MakeMyEXE is in early access. Features may change, and some, such as downloads and
          custom apps, may be limited while we grow.
        </p>
      </section>

      <section>
        <h2>Using the apps</h2>
        <ul>
          <li>
            Every app is tested on Windows with example data before it can be downloaded. Your
            own data can still be different, so check important results, such as invoice totals,
            before you rely on them.
          </li>
          <li>
            Apps never change or delete your original files. Apps that rename files show a preview
            first and keep an undo history. Keep backups of important files all the same.
          </li>
          <li>Apps are provided as they are, without a warranty. Use them for lawful purposes only.</li>
        </ul>
      </section>

      <section>
        <h2>Custom apps</h2>
        <ul>
          <li>Describe the task, not your data. Don't include passwords or other people's personal details.</li>
          <li>We may decline a request we can't build safely, for example one that needs to change system settings.</li>
          <li>You may use the app you receive for your own work and your business.</li>
        </ul>
      </section>

      <section>
        <h2>Liability</h2>
        <p>
          To the extent the law allows, we are not liable for indirect losses or lost data arising
          from the use of the apps or this site.
        </p>
      </section>

      <section>
        <h2>Changes</h2>
        <p>
          If these terms change, we'll update this page and the date above. See also our{" "}
          <Link to="/privacy" className="font-medium text-brand-700 hover:underline">
            privacy page
          </Link>
          .
        </p>
        <Contact />
      </section>
    </LegalPage>
  );
}
