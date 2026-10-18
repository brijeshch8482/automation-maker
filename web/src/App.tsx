import { Route, Routes } from "react-router";

import Layout, { PageShell } from "./components/Layout";
import AutomationPage from "./pages/AutomationPage";
import CatalogPage from "./pages/CatalogPage";
import CustomPage from "./pages/CustomPage";
import DownloadPage from "./pages/DownloadPage";
import HomePage from "./pages/HomePage";
import JobPage from "./pages/JobPage";
import { PrivacyPage, TermsPage } from "./pages/LegalPages";
import LoginPage from "./pages/LoginPage";
import MyJobsPage from "./pages/MyJobsPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route element={<PageShell />}>
          <Route path="automations" element={<CatalogPage />} />
          <Route path="automations/:id" element={<AutomationPage />} />
          <Route path="custom" element={<CustomPage />} />
          <Route path="download" element={<DownloadPage />} />
          <Route path="jobs/:id" element={<JobPage />} />
          <Route path="me/jobs" element={<MyJobsPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="privacy" element={<PrivacyPage />} />
          <Route path="terms" element={<TermsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
