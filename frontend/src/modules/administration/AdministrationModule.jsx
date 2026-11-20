import AdditionalPage from "./AdditionalPage.jsx";
import { useAdminDataController } from "../../hooks/administration/useAdminDataController.js";

export default function AdministrationModule({
  page, auth, profile, request, refresh, notify, setError,
  setSelectedChat, setMessages,
}) {
  const state = useAdminDataController({
    auth, profile, page, request, refresh, notify, setError,
    setSelectedChat, setMessages,
  });
  if (page !== "additional") return null;
  return <AdditionalPage
    dataStats={state.dataStats} dataBusy={state.dataBusy}
    loadDataStats={state.loadDataStats}
    downloadAdminFile={state.downloadAdminFile}
    uploadAdminFile={state.uploadAdminFile}
    retentionDays={state.retentionDays} setRetentionDays={state.setRetentionDays}
    cleanupOldDialogues={state.cleanupOldDialogues}
  />;
}
