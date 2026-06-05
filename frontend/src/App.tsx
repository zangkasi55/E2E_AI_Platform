// =============================================================================
// App.tsx — route table. 4 routes only (POC_SPEC §1): Demo Hub, Credit Memo
// (UC1), Banking (UC2), Token Monitor. Each page renders inside <AppShell>.
// =============================================================================
import { Navigate, Route, Routes } from "react-router-dom";
import { DemoHub } from "./pages/DemoHub";
import { CreditMemoPage } from "./pages/CreditMemoPage";
import { BankingPage } from "./pages/BankingPage";
import { TokenMonitorDashboard } from "./pages/TokenMonitorDashboard";
import { GovernancePage } from "./pages/GovernancePage";
import { TestExpectationsDashboard } from "./pages/TestExpectationsDashboard";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DemoHub />} />
      <Route path="/credit-memo" element={<CreditMemoPage />} />
      <Route path="/banking" element={<BankingPage />} />
      <Route path="/tokens" element={<TokenMonitorDashboard />} />
      <Route path="/governance" element={<GovernancePage />} />
      <Route path="/test-expectations" element={<TestExpectationsDashboard />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
