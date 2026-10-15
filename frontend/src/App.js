import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import AuditHub from "@/pages/AuditHub";
import MappingWizard from "@/pages/MappingWizard";
import Dashboard from "@/pages/Dashboard";
import Diagnostics from "@/pages/Diagnostics";
import RunAudit from "@/pages/RunAudit";
import Review from "@/pages/Review";
import AccessLink from "@/pages/AccessLink";
import OwnerPage from "@/pages/OwnerPage";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/t/:token" element={<AccessLink />} />
          <Route path="/owner" element={<OwnerPage />} />
          <Route path="/" element={<AuditHub />} />
          <Route path="/audit/:id/run" element={<RunAudit />} />
          <Route path="/audit/:id/review" element={<Review />} />
          <Route path="/audit/:id/mapping" element={<MappingWizard />} />
          <Route path="/audit/:id/dashboard" element={<Dashboard />} />
          <Route path="/audit/:id/diagnostics" element={<Diagnostics />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" theme="light" />
    </div>
  );
}

export default App;
