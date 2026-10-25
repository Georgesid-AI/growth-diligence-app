import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import AuditHub from "@/pages/AuditHub";
import MappingWizard from "@/pages/MappingWizard";
import Dashboard from "@/pages/Dashboard";
import Diagnostics from "@/pages/Diagnostics";
import AccessLink, { FullLinkNeeded } from "@/pages/AccessLink";
import OwnerPage from "@/pages/OwnerPage";

// The Run audit page moved onto Upload & Mapping (docs/specs/chat-upload.md section 24): an old link lands there.
export function RunToMapping() {
  const { id } = useParams();
  return <Navigate to={`/audit/${id}/mapping`} replace />;
}

// The Review page is gone (docs/design/simplified-flow.md): its open questions are cards on the Audit page, an old link lands there.
export function ReviewToAudit() {
  const { id } = useParams();
  return <Navigate to={`/audit/${id}/dashboard`} replace />;
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/t" element={<FullLinkNeeded />} />
          <Route path="/t/:token" element={<AccessLink />} />
          <Route path="/owner" element={<OwnerPage />} />
          <Route path="/" element={<AuditHub />} />
          <Route path="/audit/:id/run" element={<RunToMapping />} />
          <Route path="/audit/:id/review" element={<ReviewToAudit />} />
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
