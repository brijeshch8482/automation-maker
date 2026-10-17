import { Route, Routes } from "react-router";

import Layout from "./components/Layout";
import AutomationPage from "./pages/AutomationPage";
import CatalogPage from "./pages/CatalogPage";
import CustomPage from "./pages/CustomPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CatalogPage />} />
        <Route path="automations/:id" element={<AutomationPage />} />
        <Route path="custom" element={<CustomPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
