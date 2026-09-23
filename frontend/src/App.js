import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import AuditHub from "@/pages/AuditHub";
import MappingWizard from "@/pages/MappingWizard";
import Dashboard from "@/pages/Dashboard";
import Diagnostics from "@/pages/Diagnostics";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AuditHub />} />
          <Route path="/audit/:id/mapping" element={<MappingWizard />} />
          <Route path="/audit/:id/dashboard" element={<Dashboard />} />
          <Route path="/audit/:id/diagnostics" element={<Diagnostics />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" theme="dark" />
    </div>
  );
}

export default App;
